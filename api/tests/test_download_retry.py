"""Recover temporary public-source failures and retain exact exhausted paths."""
import hashlib
import io
import zipfile

import httpx
import pytest

from app.extract import pipeline

STATIC = ("https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do"
          "?houseManageNo=2026000498&pblancNo=2026000498&atchmnflSeqNo=1991055&atchmnflSn=1")
WWW = STATIC.replace("static.applyhome.co.kr", "www.applyhome.co.kr")


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(pipeline, "DOWNLOAD_RETRY_DELAY_SECONDS", 0)


def public_document():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Contents/section0.xml", '<root><p>민영주택으로 공급하는 입주자모집공고</p><p>본 주택의 최초 입주자모집공고일은 2026.10.02입니다.</p><p>5 일반공급 (「주택공급에 관한 규칙」 제28조)</p><p>대상자 청약예금에 가입하여 6개월이 경과하고 지역별 예치금액 이상인 분</p></root>')
    return buffer.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_temporary_provider_error_retries_same_source_and_records_recovery(status):
    calls, diagnostics = [], []
    data = b"%PDF-current-public-source"
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(status) if len(calls) == 1 else httpx.Response(200, content=data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        downloaded, _ = await pipeline._download(STATIC, client, diagnostics=diagnostics)
    assert downloaded == data and calls == [STATIC, STATIC]
    assert diagnostics == [{**pipeline.document_diagnostic("download", "download_retry_succeeded", STATIC, status="ok"),
                            "attempt_count": 2, "previous_http_statuses": [status]}]
    assert not any(entry.get("missing_items") for entry in diagnostics)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 403, 404, 429])
async def test_permanent_response_and_rate_limit_are_not_retried(status):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(status)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(pipeline.DocumentDownloadFailed) as error:
            await pipeline._download(STATIC, client)
    assert calls == [STATIC]
    assert error.value.diagnostics[0]["http_status"] == status


@pytest.mark.asyncio
async def test_exhausted_static_and_www_attempts_keep_each_actual_failure_url():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(500 if str(request.url) == STATIC else 503)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(pipeline.DocumentDownloadFailed) as error:
            await pipeline.extract_local_document(STATIC, client)
    assert calls == [*([STATIC] * pipeline.MAX_DOWNLOAD_ATTEMPTS), *([WWW] * pipeline.MAX_DOWNLOAD_ATTEMPTS)]
    entries = error.value.diagnostics
    assert len(entries) == 2 * pipeline.MAX_DOWNLOAD_ATTEMPTS
    assert {entry["evidence_url"] for entry in entries} == {STATIC, WWW}
    assert {entry["http_status"] for entry in entries if entry["evidence_url"] == STATIC} == {500}
    assert {entry["http_status"] for entry in entries if entry["evidence_url"] == WWW} == {503}
    assert all(entry["status"] == "error" and entry["missing_items"] for entry in entries)


@pytest.mark.asyncio
async def test_failed_static_then_www_html_remains_download_and_decode_failure():
    def handler(request):
        return httpx.Response(500) if str(request.url) == STATIC else httpx.Response(200, text="Not an official PDF")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(pipeline.DocumentDownloadFailed) as error:
            await pipeline.extract_local_document(STATIC, client)
    entries = error.value.diagnostics
    assert any(entry["http_status"] == 500 for entry in entries if entry["stage"] == "download")
    assert entries[-1]["code"] == "unexpected_response" and entries[-1]["evidence_url"] == WWW


@pytest.mark.asyncio
async def test_enrichment_exhausted_fallback_exposes_actual_host_statuses_without_new_hash():
    page = ("https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do"
            "?houseManageNo=2026000498&pblancNo=2026000498")
    requested = []
    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(500 if str(request.url) == STATIC else 503 if str(request.url) == WWW else 404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await pipeline.enrich_notice({"official_url": page, "announcement_date": "2026-10-02"}, client, allow_gemini=False)
    assert not result.get("document_hash")
    rule = next(rule for rule in result["rules"] if rule["kind"] == "document_diagnostics")
    assert rule["status"] == "unreadable"
    entries = rule["diagnostics"]
    assert next(entry for entry in entries if entry["stage"] == "discovery" and entry["status"] == "error")["evidence_url"] == requested[0]
    failures = [entry for entry in entries if entry["stage"] == "download" and entry["status"] == "error"]
    assert len(failures) == 2 * pipeline.MAX_DOWNLOAD_ATTEMPTS
    assert {(entry["evidence_url"], entry["http_status"]) for entry in failures} == {(STATIC, 500), (WWW, 503)}
    assert not any(entry["code"] == "document_read" for entry in entries)


@pytest.mark.asyncio
async def test_recovered_fallback_records_true_failed_redirect_target_and_original_source():
    redirected = "https://static.applyhome.co.kr/current-file.pdf"
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == STATIC:
            return httpx.Response(302, headers={"Location": redirected})
        if str(request.url) == redirected:
            return httpx.Response(500)
        assert str(request.url) == WWW
        return httpx.Response(200, content=public_document())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await pipeline.extract_local_document(STATIC, client)
    assert calls == [STATIC, *([redirected] * pipeline.MAX_DOWNLOAD_ATTEMPTS), WWW]
    recovered = next(entry for entry in result["diagnostics"] if entry["code"] == "attachment_fallback_succeeded")
    assert recovered["previous_url"] == redirected and recovered["original_url"] == STATIC
    assert recovered["previous_http_status"] == 500 and recovered["previous_attempt_count"] == pipeline.MAX_DOWNLOAD_ATTEMPTS
    assert recovered["status"] == "ok" and "missing_items" not in recovered
    assert not any(entry["status"] == "error" for entry in result["diagnostics"])


@pytest.mark.asyncio
async def test_retry_cannot_follow_untrusted_redirect_or_skip_document_size_limit(monkeypatch):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(500) if len(calls) == 1 else httpx.Response(302, headers={"Location": "https://private.example/file.pdf"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="Only HTTPS"):
            await pipeline._download(STATIC, client)
    assert calls == [STATIC, STATIC]
    monkeypatch.setattr(pipeline, "MAX_DOCUMENT_BYTES", 5)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"123456"))) as client:
        with pytest.raises(ValueError, match="10 MB"):
            await pipeline._download(STATIC, client)


@pytest.mark.asyncio
async def test_real_local_parser_after_transient_failure_has_actual_hash_and_no_blocking_failure():
    data, calls = public_document(), []
    url = "https://apply.lh.or.kr/notice.hwpx"
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(500) if len(calls) == 1 else httpx.Response(200, content=data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await pipeline.enrich_notice({"official_url": url}, client, allow_gemini=False)
    assert result["document_hash"] == hashlib.sha256(data).hexdigest()
    assert any(rule["kind"] == "private_rank_months" for rule in result["rules"])
    diagnostics = next(rule for rule in result["rules"] if rule["kind"] == "document_diagnostics")
    assert any(entry["code"] == "download_retry_succeeded" and entry["status"] == "ok" for entry in diagnostics["diagnostics"])
    assert not any(entry["status"] == "error" for entry in diagnostics["diagnostics"])
