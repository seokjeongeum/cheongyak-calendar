"""Recovered discovery must not hide real attachment or identity failures."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest

from app.extract import pipeline
from app.extract.official_rules import parse_official_rules


SOURCE = json.loads((Path(__file__).parent / "fixtures/official-rules-hangang-layout.json").read_text())
PAGE_URL = ("https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetailView.do"
            "?houseManageNo=2026000468&pblancNo=2026000468")
PDF_URL = SOURCE["document_url"].replace("static.applyhome.co.kr", "www.applyhome.co.kr")


def notice():
    return {"official_url": PAGE_URL, "announcement_date": SOURCE["announcement_date"],
            "external_id": SOURCE["house_manage_no"], "title": SOURCE["title"],
            "category": "apartment", "rules": [], "prices": []}


def diagnostics(result):
    return next(rule for rule in result["rules"] if rule["kind"] == "document_diagnostics")["diagnostics"]


@pytest.mark.asyncio
async def test_exact_current_reviewed_pdf_resolves_failed_page_with_actual_source_provenance(monkeypatch):
    payload = notice()
    parsed = parse_official_rules(SOURCE["pages"], url=PDF_URL,
                                 digest=SOURCE["document_hash"], payload=payload)
    assert any(rule.get("effect") != "metadata" for rule in parsed["rules"])

    async def extract(url, client, *, payload):
        return {**parsed, "document_url": PDF_URL, "document_hash": SOURCE["document_hash"],
                "diagnostics": [pipeline.document_diagnostic("decode", "document_read", PDF_URL, status="ok")]}

    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client:
        result = await pipeline.enrich_notice(payload, client, allow_gemini=False)
    failure = next(entry for entry in diagnostics(result) if entry["code"] == "announcement_download_failed")
    assert failure["status"] == "resolved" and "missing_items" not in failure
    assert failure["http_status"] == 403 and failure["evidence_url"] == PAGE_URL
    assert failure["resolved_evidence_url"] == PDF_URL
    assert failure["resolved_document_hash"] == result["document_hash"] == SOURCE["document_hash"]
    assert not any(entry["stage"] == "discovery" and entry["status"] == "error" for entry in diagnostics(result))


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,code,status,readable", [
    ("download", "document_download_failed", "unreadable", False),
    ("conversion", "hwp_conversion_failed", "unreadable", False),
    ("decode", "document_decode_failed", "unreadable", False),
    ("interpretation", "context_not_supported", "unsupported", True),
    ("identity", "current_document_mismatch", "unsupported", True),
])
async def test_page_error_remains_when_no_current_attachment_is_successfully_parsed(monkeypatch, stage, code, status, readable):
    payload = {**notice(), "document_hash": "last-reviewed-document", "rules": [
        {"kind": "age_min", "effect": "admission", "value": 19,
         "verification": "official", "source": "official_document_parser",
         "document_hash": "last-reviewed-document"}]}

    async def extract(url, client, *, payload):
        if stage == "download":
            request = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("not available", request=request,
                                        response=httpx.Response(500, request=request))
        return {"rules": [], "status": status,
                "document_hash": None if stage == "identity" else "last-reviewed-document",
                "identity_status": "mismatch" if stage == "identity" else None,
                "document_url": url,
                "diagnostics": [*([pipeline.document_diagnostic("decode", "document_read", url, status="ok")] if readable else []),
                                pipeline.document_diagnostic(stage, code, url, status="partial" if status == "unsupported" and stage != "identity" else "error")]}

    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client:
        result = await pipeline.enrich_notice(copy.deepcopy(payload), client,
                                              known_document_hash=payload["document_hash"], allow_gemini=False)
    entries = diagnostics(result)
    page = next(entry for entry in entries if entry["code"] == "announcement_download_failed")
    attachment = next(entry for entry in entries if entry["code"] == code)
    assert page["status"] == "error" and page["missing_items"]
    assert attachment["status"] != "resolved" and attachment["missing_items"]
    assert result["document_hash"] == payload["document_hash"]
    assert any(rule.get("kind") == "age_min" for rule in result["rules"])


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"official_url": PAGE_URL.replace("2026000468", "2026000999")},
                                  {"announcement_date": "2026-10-08"}])
async def test_wrong_notice_or_date_pdf_never_replaces_current_hash_or_resolves_discovery(monkeypatch, change):
    payload = {**notice(), **change, "document_hash": "last-reviewed-document", "rules": [
        {"kind": "applicant_regions", "effect": "metadata", "verification": "official",
         "source": "official_document_parser", "document_hash": "last-reviewed-document",
         "scope_complete": True, "regions": [{"region_code": "41", "region_name": "경기도"}]}]}
    monkeypatch.setattr(pipeline, "reviewed_document_urls", lambda *args, **kwargs: [PDF_URL])
    monkeypatch.setattr(pipeline, "document_pages", lambda *args: SOURCE["pages"])

    def transport(request):
        return httpx.Response(200, content=b"%PDF-test-current-identity") if str(request.url) == PDF_URL else httpx.Response(403)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await pipeline.enrich_notice(copy.deepcopy(payload), client,
                                              known_document_hash=payload["document_hash"], allow_gemini=False)
    assert result["document_hash"] == payload["document_hash"]
    assert payload["rules"][0] in result["rules"]
    mismatch = next(entry for entry in diagnostics(result) if entry["code"] == "current_document_mismatch")
    assert mismatch["stage"] == "identity" and mismatch["status"] == "error" and mismatch["missing_items"]
    assert mismatch["attachment_hash"] != payload["document_hash"]
    assert next(entry for entry in diagnostics(result) if entry["code"] == "announcement_download_failed")["status"] == "error"


@pytest.mark.asyncio
async def test_changed_document_diagnostic_uses_chosen_attachment_and_preserves_other_failures(monkeypatch):
    first = "https://www.applyhome.co.kr/first.pdf"
    later = "https://www.applyhome.co.kr/later.pdf"
    payload = {"official_url": "https://www.applyhome.co.kr/notice", "document_hash": "old-file", "rules": []}

    async def extract(url, client, *, payload):
        if url == later:
            request = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("unavailable", request=request, response=httpx.Response(500, request=request))
        return {"document_hash": "changed-file", "document_url": first, "rules": [], "status": "unsupported",
                "diagnostics": [pipeline.document_diagnostic("decode", "document_read", first, status="ok"),
                                pipeline.document_diagnostic("interpretation", "context_not_supported", first, status="partial")]}

    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    html = f'<a href="{first}">모집공고문</a><a href="{later}">모집공고문</a>'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html))) as client:
        result = await pipeline.enrich_notice(payload, client, known_document_hash="old-file", allow_gemini=False)
    changed = next(entry for entry in diagnostics(result) if entry["code"] == "document_changed")
    failure = next(entry for entry in diagnostics(result) if entry["code"] == "document_download_failed")
    assert changed["evidence_url"] == first and changed["missing_items"]
    assert failure["evidence_url"] == later and failure["status"] == "error" and failure["missing_items"]


@pytest.mark.asyncio
async def test_failed_feed_attempt_retains_known_hash_in_diagnostics_when_feed_omits_hash():
    payload = notice()
    assert "document_hash" not in payload
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client:
        result = await pipeline.enrich_notice(payload, client, known_document_hash="last-reviewed-document", allow_gemini=False)
    rule = next(rule for rule in result["rules"] if rule["kind"] == "document_diagnostics")
    assert result["document_hash"] == rule["document_hash"] == "last-reviewed-document"
    assert rule["status"] == "unreadable"
    assert any(entry["status"] == "error" and entry["stage"] == "download" for entry in rule["diagnostics"])


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
async def test_changed_reviewed_document_has_identity_event_and_only_actual_unreviewed_topics(monkeypatch, complete):
    page_url = "https://www.applyhome.co.kr/notice"
    pdf_url = "https://www.applyhome.co.kr/current.pdf"
    missing = [] if complete else ["신혼부부 개인별 소득 상한 예외 검토"]
    coverage = {"kind": "condition_coverage", "effect": "metadata", "verification": "official",
                "source": "official_document_parser", "document_hash": "new-reviewed-file",
                "status": "complete" if complete else "partial",
                "scopes": [{"supply_type": "일반공급" if complete else "신혼부부 특별공급",
                            "complete": complete, "missing_topics": missing}]}
    region = {"kind": "applicant_regions", "effect": "metadata", "verification": "official",
              "source": "official_document_parser", "document_hash": "new-reviewed-file",
              "scope_complete": True, "regions": [{"region_code": "41", "region_name": "경기도"}]}
    payload = {"official_url": page_url, "document_hash": "old-reviewed-file", "rules": []}

    async def extract(url, client, *, payload):
        return {"document_hash": "new-reviewed-file", "document_url": pdf_url,
                "status": coverage["status"], "rules": [region, coverage], "diagnostics": [
                    pipeline.document_diagnostic("decode", "document_read", pdf_url, status="ok"),
                    pipeline.document_diagnostic("interpretation", "conditions_parsed", pdf_url, status="ok")]}

    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=f'<a href="{pdf_url}">모집공고문</a>'))) as client:
        result = await pipeline.enrich_notice(payload, client, known_document_hash="old-reviewed-file", allow_gemini=False)
    event = next(entry for entry in diagnostics(result) if entry["code"] == "document_changed")
    assert event["status"] == "ok" and "missing_items" not in event
    assert event["previous_document_hash"] == "old-reviewed-file" and event["document_hash"] == "new-reviewed-file"
    assert event["evidence_url"] == pdf_url
    assert region in result["rules"] and coverage in result["rules"]
    assert result["rules_complete"] is complete
    assert coverage["scopes"][0]["missing_topics"] == missing
