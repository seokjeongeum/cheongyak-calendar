import io
import json
import hashlib
import zipfile

import httpx
import pytest

from app.extract.pipeline import (
    ExtractionDeferred,
    _clean_extraction,
    _hwpx_text,
    _trusted_url,
    enrich_notice,
    extraction_configured,
    extract_document,
    find_document_links,
)


def test_document_links_accept_only_official_https_documents():
    html = (
        '<a href="/files/notice.pdf">PDF</a>'
        '<a href="https://evil.example/notice.pdf">external</a>'
        '<a href="/download?id=1">모집공고.hwp</a>'
        '<a href="/atchFileDownload.do?id=2" title="모집공고문">내려받기</a>'
        '<a href="/files/nested.pdf"><span>공고문</span></a>'
        '<a href="/files/notice.pdf">duplicate</a>'
    )
    assert find_document_links(html, "https://apply.lh.or.kr/notice") == [
        "https://apply.lh.or.kr/files/notice.pdf",
        "https://apply.lh.or.kr/download?id=1",
        "https://apply.lh.or.kr/atchFileDownload.do?id=2",
        "https://apply.lh.or.kr/files/nested.pdf",
    ]
    assert not _trusted_url("http://apply.lh.or.kr/file.pdf")
    assert not _trusted_url("https://apply.lh.or.kr.evil.example/file.pdf")


def test_hwpx_sections_are_read_in_order():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Contents/section1.xml", "<root><p>84㎡</p><p>8억</p></root>")
        archive.writestr("Contents/section0.xml", "<root><p>공고문</p></root>")
        archive.writestr("Contents/section10.xml", "<root><p>끝</p></root>")
        archive.writestr("Contents/section2.xml", "<root><p>중간</p></root>")
    assert _hwpx_text(buffer.getvalue()) == "공고문\n84㎡ 8억\n중간\n끝"


def test_invalid_or_unproven_prices_are_dropped():
    cleaned = _clean_extraction(
        {
            "prices": [
                {"unit_type": "84A", "price_kind": "sale_max", "amount_krw": 850000000, "evidence_text": "84A 8억5천"},
                {"unit_type": "59A", "price_kind": "sale_max", "amount_krw": 520000000, "evidence_text": ""},
                {"unit_type": "기타", "price_kind": "guess", "amount_krw": 1, "evidence_text": "text"},
                {"unit_type": "36A", "price_kind": "deposit_monthly", "amount_krw": None, "monthly_krw": 220000, "evidence_text": "36A 월 22만원"},
            ],
            "conditions": [{"text": "해당지역 2년", "evidence_text": "해당지역 2년 이상"}],
        },
        "https://apply.lh.or.kr/file.pdf",
        "abc123",
    )
    assert len(cleaned["prices"]) == 2
    assert cleaned["prices"][0]["verification"] == "auto_unverified"
    assert cleaned["prices"][1]["amount_krw"] is None
    assert cleaned["prices"][1]["monthly_krw"] == 220000
    assert cleaned["rules"][0]["verification"] == "ai_unverified"


@pytest.mark.asyncio
async def test_extract_document_preserves_evidence_and_defers_on_quota(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_UNBILLED_PROJECT_CONFIRMED", "1")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "apply.lh.or.kr":
            return httpx.Response(200, content=b"%PDF-1.4\npublic notice", headers={"content-type": "application/pdf"})
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps({"prices": [{"unit_type": "84A", "price_kind": "sale_total", "amount_krw": 810000000, "evidence_text": "84A 810,000,000원"}], "conditions": []})}]}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await extract_document("https://apply.lh.or.kr/notice.pdf", client)
    assert result["prices"][0]["amount_krw"] == 810000000
    assert result["prices"][0]["evidence_url"] == "https://apply.lh.or.kr/notice.pdf"
    assert len(calls) == 2

    calls.clear()
    known_hash = hashlib.sha256(b"%PDF-1.4\npublic notice").hexdigest()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        unchanged = await extract_document("https://apply.lh.or.kr/notice.pdf", client, known_hash=known_hash)
    assert unchanged["unchanged"] is True
    assert len(calls) == 1  # No Gemini request for the same document.

    def quota_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "apply.lh.or.kr":
            return httpx.Response(200, content=b"%PDF-1.4\npublic notice")
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(quota_handler)) as client:
        with pytest.raises(ExtractionDeferred):
            await extract_document("https://apply.lh.or.kr/notice.pdf", client)
        waiting = await enrich_notice({"official_url": "https://apply.lh.or.kr/notice.pdf"}, client)
    assert waiting["extraction_status"] == "quota"


@pytest.mark.asyncio
async def test_enrichment_without_key_reads_public_document_locally(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Contents/section0.xml", '<root><p>민영주택으로 공급하는 입주자모집공고</p><p>본 주택의 최초 입주자모집공고일은 2026.10.02입니다.</p><p>5 일반공급 (「주택공급에 관한 규칙」 제28조)</p><p>대상자 청약예금에 가입하여 6개월이 경과하고 지역별 예치금액 이상인 분</p></root>')
    calls = []
    def handler(request):
        calls.append(request.url.host)
        assert request.url.host == "apply.lh.or.kr"
        return httpx.Response(200, content=buffer.getvalue())
    notice = {"official_url": "https://apply.lh.or.kr/notice.hwpx", "prices": [{"unit_type": "84A", "verification": "official", "amount_krw": 900000000}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await enrich_notice(notice, client)
    assert result["prices"] == notice["prices"]
    assert any(r["kind"] == "private_rank_months" and r["verification"] == "official" and r["value"] == 6 for r in result["rules"])
    assert "generativelanguage.googleapis.com" not in calls


@pytest.mark.asyncio
async def test_key_alone_cannot_make_a_paid_request(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "billing-enabled-key")
    monkeypatch.delenv("GEMINI_UNBILLED_PROJECT_CONFIRMED", raising=False)
    assert not extraction_configured()

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("No HTTP request should occur without the free-tier guard")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExtractionDeferred):
            await extract_document("https://apply.lh.or.kr/notice.pdf", client)
    assert calls == []


@pytest.mark.asyncio
async def test_extensionless_official_document_is_extracted(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_UNBILLED_PROJECT_CONFIRMED", "1")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.host == "www.myhome.go.kr":
            return httpx.Response(200, content=b"%PDF-1.4\npublic notice")
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps({"prices": [{"unit_type": "59", "price_kind": "sale_total", "amount_krw": 500000000, "evidence_text": "59 500000000원"}], "conditions": []})}]}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await enrich_notice({"official_url": "https://www.myhome.go.kr/hws/com/fms/cvplFileDownload.do?atchFileId=1"}, client)
    assert result["prices"][0]["unit_type"] == "59"
    assert seen.count("generativelanguage.googleapis.com") == 1


@pytest.mark.asyncio
async def test_unverified_rental_price_replaces_empty_type_placeholder(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_UNBILLED_PROJECT_CONFIRMED", "1")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "apply.lh.or.kr":
            return httpx.Response(200, content=b"%PDF-1.4\npublic notice", headers={"content-type": "application/pdf"})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps({
            "prices": [
                {"unit_type": "36A", "price_kind": "deposit_monthly", "amount_krw": None,
                 "monthly_krw": 220000, "evidence_text": "36A 월 220,000원"},
                {"unit_type": "84A", "price_kind": "sale_max", "amount_krw": 1,
                 "evidence_text": "84A 1원"},
            ], "conditions": [],
        })}]}}]})

    notice = {"official_url": "https://apply.lh.or.kr/notice.pdf", "prices": [
        {"unit_type": "36A", "price_kind": "deposit", "amount_krw": None,
         "monthly_krw": None, "verification": "unknown"},
        {"unit_type": "84A", "price_kind": "sale_max", "amount_krw": 900000000,
         "verification": "official"},
    ]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await enrich_notice(notice, client)
    assert len(result["prices"]) == 2
    assert result["prices"][0]["price_kind"] == "deposit_monthly"
    assert result["prices"][0]["monthly_krw"] == 220000
    assert result["prices"][0]["verification"] == "auto_unverified"
    assert result["prices"][1]["amount_krw"] == 900000000
    assert result["prices"][1]["verification"] == "official"
