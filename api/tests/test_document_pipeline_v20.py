"""Current endpoints, candidate isolation and role-scoped public provenance."""
import io
import zipfile

import httpx
import pytest

from app.extract import pipeline

PAGE = 'https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2026000523&pblancNo=2026000523'
PDF = 'https://www.applyhome.co.kr/current.pdf'


def local_document(url=PDF, digest='current', *, role='primary'):
    rules = [{'id': 'adult', 'kind': 'age_min', 'value': 19, 'verification': 'official',
              'source': 'official_document_parser', 'effect': 'admission',
              'document_hash': digest, 'evidence_url': url}]
    if role == 'price_table':
        rules = [{'kind': 'price_details', 'effect': 'metadata', 'verification': 'official',
                  'source': 'official_document_parser', 'document_hash': digest, 'evidence_url': url}]
    return {'document_hash': digest, 'document_url': url, 'status': 'complete', 'rules': rules,
            'price_identity_confirmed': role == 'price_table',
            'prices': [{'unit_type': '84A', 'price_kind': 'sale_total', 'amount_krw': 100,
                        'verification': 'official', 'document_hash': digest}] if role == 'price_table' else [],
            'diagnostics': [pipeline.document_diagnostic('decode', 'document_read', url, status='ok')]}


def entries(result):
    return next(r for r in result['rules'] if r['kind'] == 'document_diagnostics')['diagnostics']


def test_published_type_specific_endpoint_is_first_and_identifiers_never_change():
    assert pipeline.announcement_page_url(PAGE) == PAGE
    assert pipeline.announcement_page_candidates(PAGE) == [PAGE, PAGE.replace('Detail.do', 'DetailView.do')]
    prmo = PAGE.replace('selectAPT', 'selectPRMO').replace('Detail.do', 'DetailView.do')
    assert pipeline.announcement_page_candidates(prmo)[0] == prmo
    assert pipeline.announcement_page_candidates('https://apply.lh.or.kr/notice') == ['https://apply.lh.or.kr/notice']
    assert pipeline.announcement_page_candidates(PAGE.replace('2026000523', 'bad')) == [PAGE.replace('2026000523', 'bad')]


@pytest.mark.asyncio
@pytest.mark.parametrize('original_status', [200, 404])
async def test_original_endpoint_precedes_alias_and_success_resolves_discovery(monkeypatch, original_status):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == PAGE and original_status != 200:
            return httpx.Response(original_status)
        return httpx.Response(200, text=f'<a href="{PDF}">모집공고문.pdf</a>')
    async def extract(url, client, **kwargs):
        return local_document(url)
    monkeypatch.setattr(pipeline, 'extract_local_document', extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await pipeline.enrich_notice({'official_url': PAGE}, client, allow_gemini=False)
    assert calls[0] == PAGE
    assert len(calls) == (1 if original_status == 200 else 2)
    assert result['document_hash'] == 'current'
    assert all(e['status'] in {'ok', 'resolved'} for e in entries(result))


@pytest.mark.asyncio
async def test_transient_network_failure_is_retried_without_raw_exception(monkeypatch):
    monkeypatch.setattr(pipeline, 'DOWNLOAD_RETRY_DELAY_SECONDS', 0)
    attempts = []
    def handler(request):
        attempts.append(str(request.url))
        if len(attempts) == 1:
            raise httpx.ConnectError('private transport exception', request=request)
        return httpx.Response(200, content=b'%PDF-current')
    diagnostics = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        data, _ = await pipeline._download(PDF, client, diagnostics=diagnostics)
    assert data == b'%PDF-current' and len(attempts) == 2
    assert diagnostics[0]['code'] == 'download_retry_succeeded'
    assert diagnostics[0]['previous_exception_types'] == ['OSError']
    assert 'private' not in str(diagnostics)


@pytest.mark.asyncio
async def test_rejected_candidate_never_reaches_model_and_foreign_hash_is_dropped(monkeypatch):
    wrong = 'https://www.applyhome.co.kr/wrong.pdf'
    model_urls = []
    async def extract(url, client, **kwargs):
        if url == wrong:
            return {**local_document(url), 'document_hash': None, 'identity_status': 'mismatch', 'rules': [],
                    'diagnostics': [pipeline.document_diagnostic('identity', 'current_document_mismatch', url)]}
        return local_document(url)
    async def model(url, client, **kwargs):
        model_urls.append(url)
        return {'document_hash': 'other-file', 'prices': [{'unit_type': 'wrong', 'amount_krw': 900}], 'rules': []}
    monkeypatch.setattr(pipeline, 'extract_local_document', extract)
    monkeypatch.setattr(pipeline, 'extract_document', model)
    monkeypatch.setattr(pipeline, 'extraction_configured', lambda: True)
    html = f'<a href="{wrong}">모집공고문.pdf</a><a href="{PDF}">모집공고문.pdf</a>'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=html))) as client:
        result = await pipeline.enrich_notice({'official_url': PAGE}, client)
    assert model_urls == [PDF]
    assert result['prices'] == []
    assert next(e for e in entries(result) if e['code'] == 'current_document_mismatch')['status'] == 'resolved'


@pytest.mark.asyncio
async def test_unreadable_document_cannot_be_sent_to_model(monkeypatch):
    async def extract(url, client, **kwargs):
        return {'document_hash': 'broken', 'status': 'unreadable', 'rules': [],
                'diagnostics': [pipeline.document_diagnostic('decode', 'document_decode_failed', url)]}
    async def forbidden(*args, **kwargs):
        raise AssertionError('unreadable source must not reach model')
    monkeypatch.setattr(pipeline, 'extract_local_document', extract)
    monkeypatch.setattr(pipeline, 'extract_document', forbidden)
    monkeypatch.setattr(pipeline, 'extraction_configured', lambda: True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=f'<a href="{PDF}">공고.pdf</a>'))) as client:
        await pipeline.enrich_notice({'official_url': PAGE}, client)


@pytest.mark.asyncio
@pytest.mark.parametrize('available', [True, False])
async def test_price_appendix_is_processed_after_primary_and_does_not_replace_admission(monkeypatch, available):
    appendix = 'https://www.applyhome.co.kr/prices.pdf'
    visited, model_urls = [], []
    async def extract(url, client, **kwargs):
        visited.append(url)
        if url == appendix:
            if not available:
                raise httpx.ConnectError('temporary', request=httpx.Request('GET', url))
            return local_document(url, 'appendix', role='price_table')
        return local_document(url)
    async def model(url, client, **kwargs):
        model_urls.append(url)
        return {'document_hash': 'current', 'prices': [], 'rules': []}
    monkeypatch.setattr(pipeline, 'extract_local_document', extract)
    monkeypatch.setattr(pipeline, 'extract_document', model)
    monkeypatch.setattr(pipeline, 'extraction_configured', lambda: True)
    html = f'<a href="{PDF}">모집공고문.pdf</a><a href="{appendix}">동호별 공급가격표.pdf</a>'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=html))) as client:
        result = await pipeline.enrich_notice({'official_url': PAGE}, client)
    assert visited == [PDF, appendix]
    assert model_urls == [PDF] and result['document_hash'] == 'current'
    assert result['local_extraction_status'] == 'complete'
    if available:
        assert result['prices'][0]['document_hash'] == 'appendix'
        detail = next(r for r in result['rules'] if r['kind'] == 'price_details')
        assert detail['selected_document_hash'] == 'current'
        assert next(r for r in result['rules'] if r['kind'] == 'document_bundle')['documents'][-1]['role'] == 'price_table'
    else:
        failure = next(e for e in entries(result) if e['code'] == 'document_download_failed')
        assert failure['document_role'] == 'price_table' and failure['status'] == 'error'


def test_extensionless_hwpx_signature_and_source_roles_are_kept():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('Contents/section0.xml', '<root><p>신청자격 원문</p></root>')
    pages = pipeline.document_pages('https://apply.lh.or.kr/lhFile.do?fileid=1', data.getvalue(), 'application/octet-stream')
    assert pages[0]['text'] == '신청자격 원문'
    html = '<a href="javascript:fileDownLoad(&quot;123&quot;)">모집공고문.pdf</a><a href="/form.pdf">개인정보동의서.pdf</a><a href="/prices.pdf">공급가격표.pdf</a>'
    found = pipeline.find_document_candidates(html, 'https://apply.lh.or.kr/notice')
    assert [r['role'] for r in found] == ['primary', 'price_table']
    assert 'fileid=123' in found[0]['url']
