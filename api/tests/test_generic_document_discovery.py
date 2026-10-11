"""Attachment discovery uses current links and stored facts, never a project list."""
import copy

import httpx
import pytest

from app.extract import pipeline

PAGE = "https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2027999123&pblancNo=2027999123"
PDF = "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2027999123&pblancNo=2027999123&atchmnflSeqNo=999901&atchmnflSn=4"


def payload():
    return {"source": "cheongyak_home", "external_id": "2027999123", "title": "새로운 단지 2블록",
            "announcement_date": "2027-04-03", "category": "apt", "official_url": PAGE,
            "document_hash": "current-document", "rules": [{"kind": "age_min", "value": 19,
                "verification": "official", "source": "official_document_parser", "document_hash": "current-document",
                "evidence_url": PDF, "criterion_date": "2027-04-03"}]}


def test_unseen_notice_reuses_only_its_retained_attachment_provenance():
    row = payload()
    assert pipeline._persisted_document_urls(row) == [PDF]
    for change in ({"document_hash": "different"}, {"rules": []}, {"official_url": PAGE.replace("2027999123", "2027999124")}):
        assert pipeline._persisted_document_urls({**row, **change}) == []


def test_correction_link_is_discovered_before_original_without_page_or_notice_catalog():
    html = '<a href="original.pdf">모집공고문 PDF</a><a href="new.pdf">정정 모집공고문 PDF</a>'
    assert pipeline.find_document_links(html, PAGE) == ["https://www.applyhome.co.kr/ai/aia/new.pdf", "https://www.applyhome.co.kr/ai/aia/original.pdf"]


@pytest.mark.parametrize("reversed_order", [False, True])
def test_latest_dated_correction_precedes_older_correction_in_either_page_order(reversed_order):
    anchors = ['<a href="old.pdf">2027.04.04 정정 모집공고문 PDF</a>', '<a href="new.pdf">2027.04.06 정정 모집공고문 PDF</a>']
    if reversed_order:
        anchors.reverse()
    assert pipeline.find_document_links(''.join(anchors), PAGE)[0].endswith('/new.pdf')


def test_new_project_pdf_requires_a_link_on_the_official_page():
    document = "https://new-project.example/announcements/current.pdf"
    assert not pipeline._trusted_url(document)
    assert pipeline.find_document_links(f'<a href="{document}">모집공고문 PDF</a>', PAGE) == [document]
    assert pipeline.find_document_links(f'<a href="{document}">모집공고문 PDF</a>', "https://unrelated.example/") == []


@pytest.mark.parametrize("url", ["http://new-project.example/current.pdf", "https://127.0.0.1/current.pdf",
    "https://10.0.0.1/current.pdf", "https://localhost/current.pdf", "https://docs.internal/current.pdf",
    "https://user:secret@new-project.example/current.pdf", "https://new-project.example:8080/current.pdf",
    "https://new-project.example:not-a-port/current.pdf"])
def test_official_anchor_cannot_delegate_local_or_credential_bearing_urls(url):
    assert pipeline.find_document_links(f'<a href="{url}">모집공고문 PDF</a>', PAGE) == []


@pytest.mark.asyncio
async def test_unseen_notice_failed_discovery_can_download_its_persisted_current_copy(monkeypatch):
    row = payload()
    attempts = []

    async def extract(url, client, *, payload):
        attempts.append(url)
        return {"rules": copy.deepcopy(row["rules"]), "status": "partial", "document_hash": row["document_hash"],
                "document_url": url, "diagnostics": [pipeline.document_diagnostic("decode", "document_read", url, status="ok")]}

    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client:
        result = await pipeline.enrich_notice(row, client, known_document_hash=row["document_hash"], allow_gemini=False)
    assert attempts == [PDF] and result["document_hash"] == row["document_hash"]


@pytest.mark.asyncio
async def test_public_project_trust_is_local_to_the_current_official_discovery(monkeypatch):
    document = "https://future-project.example/current.pdf"
    row = payload()
    assert not pipeline._trusted_url(document)

    async def extract(url, client, *, payload):
        assert url == document and pipeline._trusted_url(url)
        return {"rules": [{**row["rules"][0], "evidence_url": url}], "status": "partial", "document_hash": "next-copy",
                "document_url": url, "diagnostics": [pipeline.document_diagnostic("decode", "document_read", url, status="ok")]}

    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=f'<a href="{document}">현재 모집공고문 PDF</a>'))) as client:
        result = await pipeline.enrich_notice(row, client, allow_gemini=False)
    assert result["document_hash"] == "next-copy" and not pipeline._trusted_url(document)
