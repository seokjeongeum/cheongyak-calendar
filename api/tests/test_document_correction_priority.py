"""Reviewed corrections precede superseded fallback copies, not new discovery."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from app.extract import pipeline
from app.extract.official_rules import parse_official_rules

FIXTURES = Path(__file__).parent / "fixtures"
CORRECTED = json.loads((FIXTURES / "hyangnam-regional-v9.json").read_text())
ORIGINAL = next(row for row in json.loads((FIXTURES / "current-private-v5.json").read_text())
                if row["external_id"] == "2026000463")


def local(source):
    result = parse_official_rules(source["pages"], url=source["document_url"],
                                  digest=source["document_hash"], payload=source["payload"])
    assert pipeline._has_reviewed_geography(result["rules"])
    return {**result, "document_hash": source["document_hash"], "document_url": source["document_url"],
            "diagnostics": [pipeline.document_diagnostic("decode", "document_read", source["document_url"], status="ok")]}


@pytest.mark.asyncio
async def test_failed_discovery_prefers_explicit_current_correction_even_when_original_would_succeed(monkeypatch):
    original, corrected = local(ORIGINAL), local(CORRECTED)
    calls = []

    async def extract(url, client, *, payload):
        calls.append(url)
        return corrected if url == CORRECTED["document_url"] else original

    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client:
        result = await pipeline.enrich_notice(CORRECTED["payload"], client, allow_gemini=False)
    assert calls == [CORRECTED["document_url"]]
    assert result["document_hash"] == CORRECTED["document_hash"] != ORIGINAL["document_hash"]
    allocation = next(rule for rule in result["rules"] if rule["kind"] == "regional_allocation" and rule.get("supply_type") == "다자녀가구 특별공급")
    assert [share["percent"] for share in allocation["regional_shares"]] == [50, 50]
    assert allocation["evidence_url"] == CORRECTED["document_url"]


@pytest.mark.asyncio
async def test_successful_current_official_discovery_stays_ahead_of_reviewed_correction(monkeypatch):
    current_url = "https://www.applyhome.co.kr/new-current.pdf"
    calls = []

    async def extract(url, client, *, payload):
        calls.append(url)
        assert url == current_url
        region = {"kind": "applicant_regions", "effect": "metadata", "verification": "official",
                  "document_hash": "new-current-discovered-bytes", "scope_complete": True,
                  "regions": [{"region_code": "41", "region_name": "경기도"}], "evidence_url": url}
        return {"rules": [region], "document_hash": region["document_hash"], "document_url": url,
                "status": "partial", "diagnostics": [pipeline.document_diagnostic("decode", "document_read", url, status="ok")]}

    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    html = f'<a href="{current_url}">현재 모집공고문 PDF</a>'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html))) as client:
        result = await pipeline.enrich_notice(CORRECTED["payload"], client, allow_gemini=False)
    assert calls == [current_url]
    assert result["document_hash"] == "new-current-discovered-bytes"


@pytest.mark.asyncio
@pytest.mark.parametrize("known", [None, "original", "corrected"])
async def test_failed_current_correction_remains_visible_and_never_downgrades_reviewed_successor(monkeypatch, known):
    original, corrected = local(ORIGINAL), local(CORRECTED)
    prior = corrected if known == "corrected" else original if known == "original" else None
    payload = {**CORRECTED["payload"], "rules": copy.deepcopy(prior["rules"]) if prior else []}
    known_hash = prior["document_hash"] if prior else None
    calls = []

    async def extract(url, client, *, payload):
        calls.append(url)
        if url == CORRECTED["document_url"]:
            request = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("unavailable", request=request, response=httpx.Response(503, request=request))
        assert url == ORIGINAL["document_url"]
        return original

    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client:
        result = await pipeline.enrich_notice(payload, client, known_document_hash=known_hash, allow_gemini=False)
    assert calls == [CORRECTED["document_url"], ORIGINAL["document_url"]]
    assert result["document_hash"] == (CORRECTED["document_hash"] if known == "corrected" else ORIGINAL["document_hash"])
    diagnostic = next(rule for rule in result["rules"] if rule["kind"] == "document_diagnostics")
    failure = next(entry for entry in diagnostic["diagnostics"] if entry["code"] == "document_download_failed")
    assert diagnostic["status"] == "unreadable" and failure["status"] == "error"
    assert failure["evidence_url"] == CORRECTED["document_url"] and failure["missing_items"]
    if known == "corrected":
        assert all(rule in result["rules"] for rule in corrected["rules"])
        assert not any(rule.get("document_hash") == ORIGINAL["document_hash"] for rule in result["rules"])
    else:
        region = next(rule for rule in result["rules"] if rule["kind"] == "applicant_regions" and not rule.get("supply_type"))
        assert region["document_hash"] == ORIGINAL["document_hash"] and region["evidence_url"] == ORIGINAL["document_url"]
