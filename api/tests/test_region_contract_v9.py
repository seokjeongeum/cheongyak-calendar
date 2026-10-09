"""Current official attachment identities, regional scope, and LH contracts."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.extract import pipeline
from app.extract.application_regions import normalize_region_text
from app.extract.contract_schedule import parse_lh_detail_contract_schedule
from app.extract.official_rules import PARSER_VERSION, parse_official_rules
from app.extract.reprocess import _document_patch
from app.qualification import public_contract_schedule
from app.repository import upsert_notice
from test_repository_api import db, client, example_notice


FIXTURES = Path(__file__).parent / "fixtures"
CURRENT = json.loads((FIXTURES / "current-regional-v9.json").read_text())
HYANGNAM = json.loads((FIXTURES / "hyangnam-regional-v9.json").read_text())
GYEONGSAN = json.loads((FIXTURES / "gyeongsan-contract-detail-v9.json").read_text())
DANGSAN_FAILURE = json.loads((FIXTURES / "dangsan-document-failure-v9.json").read_text())


def parsed(source, **changes):
    return parse_official_rules(source["pages"], url=source["document_url"],
        digest=source["document_hash"], payload={**source["payload"], **changes})


@pytest.mark.parametrize("source,regions,unrestricted", [
    (CURRENT[0], set(), True),
    (CURRENT[1], {"30"}, False),
    (CURRENT[2], {"11", "28", "41"}, False),
    (CURRENT[3], set(), True),
])
def test_current_qualification_paragraph_matches_exact_notice_and_date(source, regions, unrestricted):
    result = parsed(source)
    assert result["status"] in {"partial", "complete"}
    scope = next(r for r in result["rules"] if r["kind"] == "applicant_regions")
    assert scope["scope_complete"] is True
    assert {r["region_code"] for r in scope.get("regions", [])} == regions
    assert bool(scope.get("unrestricted")) is unrestricted
    assert scope["criterion_date"] == source["payload"]["announcement_date"]
    assert scope["document_hash"] == source["document_hash"]
    assert scope["evidence_page"] is not None
    assert all(r.get("criterion_date") == source["payload"]["announcement_date"]
               for r in result["rules"] if r.get("criterion_date"))
    links = pipeline.find_document_links(source["official_detail_html"], source["payload"]["official_url"])
    assert source["document_url"] in [*links, *(pipeline.applyhome_attachment_fallback_url(link) for link in links)]


@pytest.mark.parametrize("source", CURRENT)
def test_prior_date_and_other_notice_attachment_cannot_validate_current_notice(source):
    assert parsed(source, announcement_date="2026-09-01")["status"] == "unsupported"
    wrong = {**source["payload"], "official_url": source["payload"]["official_url"].replace(source["external_id"], "2026950999")}
    assert parsed(source, official_url=wrong["official_url"])["rules"] == []


def test_hyangnam_normalized_capital_region_and_separate_special_supply_quotas():
    result = parsed(HYANGNAM)
    scopes = [r for r in result["rules"] if r["kind"] == "applicant_regions"]
    general = next(r for r in scopes if not r.get("supply_type"))
    assert {r["region_code"] for r in general["regions"]} == {"41", "11", "28"}
    assert general["local_priority"]["region_code"] == "41590"
    assert general["local_priority"]["min_months"] == 0
    assert general["priority_applicable"] is True
    assert "10년 이상 장기복무" in general["exceptions"][0]["evidence_text"]
    assert general["exceptions"][0]["evidence_page"] == 6
    assert normalize_region_text("화 성 특\n례 시 거주자가 우선") == "화성시 거주자가 우선"
    allocation = next(r for r in result["rules"] if r["kind"] == "regional_allocation" and r.get("supply_type") == "다자녀가구 특별공급")
    assert [r["percent"] for r in allocation["regional_shares"]] == [50, 50]
    assert [r["region_codes"] for r in allocation["regional_shares"]] == [["41"], ["11", "28"]]
    assert allocation["local_share_percent"] is None
    assert allocation["local_priority_within_first_quota"] is True
    assert allocation["unsuccessful_applicants_advance"] is True
    assert allocation["local_priority_in_remaining_quota"] is False
    assert allocation["document_hash"] == HYANGNAM["document_hash"]
    assert next(r for r in scopes if r.get("supply_type") == "다자녀가구 특별공급")["other_gyeonggi"]["region_code"] == "41"
    assert not any(r.get("supply_type") == "일반공급" and r.get("regional_shares") for r in result["rules"])


def test_address_and_old_first_announcement_are_not_applicant_regions():
    source = CURRENT[0]
    pages = [{"page": 1, "text": "잠실에떼르넬비욘드 오피스텔 분양광고\n분양광고일(2026.09.30.)\n공급위치 서울특별시 송파구 방이동\n최초 입주자모집공고일 현재 대전광역시에 거주하는 분을 대상으로 했던 2024년 공고 설명"}]
    result = parse_official_rules(pages, url=source["document_url"], digest="unreviewed-new-file", payload=source["payload"])
    assert not any(r["kind"] == "applicant_regions" for r in result["rules"])


@pytest.mark.parametrize("path", ["APT", "APTRemndr", "PRMO"])
def test_public_detail_view_keeps_exact_notice_number_when_fixing_obsolete_path(path):
    url = f"https://www.applyhome.co.kr/ai/aia/select{path}LttotPblancDetail.do?houseManageNo=2026950087&pblancNo=2026950087&houseSecd=02"
    assert pipeline.announcement_page_url(url) == url.replace("Detail.do", "DetailView.do")
    assert pipeline.announcement_page_url(url.replace("www.applyhome.co.kr", "example.com")) == url.replace("www.applyhome.co.kr", "example.com")


def reviewed_region(kind="applicant_regions", **changes):
    return {"kind": kind, "effect": "metadata", "verification": "official", "source": "official_document_parser",
            "document_hash": "same-file", "parser_version": "official-sections-2026-10-07-v8",
            "evidence_url": "https://static.applyhome.co.kr/notice.pdf", "scope_complete": True,
            "regions": [{"region_code": "41", "region_name": "경기도"}], **changes}


@pytest.mark.parametrize("weaker", [
    reviewed_region(scope_complete=False, regions=[]),
    reviewed_region("regional_allocation", allocation_method="unknown", scope_complete=False),
])
def test_same_hash_partial_reparse_preserves_complete_review_and_is_idempotent(weaker):
    prior = reviewed_region(weaker["kind"], allocation_method="regional_quota", regional_shares=[{"percent": 50}, {"percent": 50}])
    merged = pipeline._retain_same_hash_regions([prior], [weaker], "same-file")
    assert len(merged) == 1
    assert merged[0]["scope_complete"] is True
    assert merged[0]["parser_version"] == PARSER_VERSION
    assert merged[0]["preserved_review_parser_version"] == prior["parser_version"]
    assert pipeline._retain_same_hash_regions(merged, [weaker], "same-file") == merged
    assert pipeline._retain_same_hash_regions([prior], [weaker], "changed-file") == [weaker]


@pytest.mark.asyncio
@pytest.mark.parametrize("static_status", [200, 403, 500])
async def test_official_www_attachment_fallback_uses_actual_source_and_has_no_unresolved_failure(monkeypatch, static_status):
    source = CURRENT[3]
    original = source["document_url"].replace("www.applyhome.co.kr", "static.applyhome.co.kr")
    fake_pdf = b"%PDF-current-notice"
    monkeypatch.setattr(pipeline, "document_pages", lambda *args: source["pages"])
    # Simulate provider bytes in the transport while using the separately
    # recorded hash-bound source review for the independent parser test above.
    real_parser = pipeline.parse_official_rules
    def parse(pages, **kwargs):
        assert kwargs["url"] == source["document_url"]
        return real_parser(pages, **{**kwargs, "digest": source["document_hash"]})
    monkeypatch.setattr(pipeline, "parse_official_rules", parse)
    requests = []
    def handler(request):
        requests.append(str(request.url))
        if str(request.url) == original:
            return httpx.Response(static_status, text="The requested URL was not found on this server.<br><br><br>")
        assert str(request.url) == source["document_url"]
        return httpx.Response(200, content=fake_pdf, headers={"Content-Type": "application/octet-stream"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await pipeline.extract_local_document(original, http, payload=source["payload"])
    assert requests == [original, source["document_url"]]
    assert result["status"] == "complete"
    region = next(r for r in result["rules"] if r["kind"] == "applicant_regions")
    assert region["unrestricted"] and region["evidence_url"] == source["document_url"]
    assert not any(d["status"] == "error" for d in result["diagnostics"])
    assert next(d for d in result["diagnostics"] if d["code"] == "attachment_fallback_succeeded")["status"] == "ok"
    assert pipeline.applyhome_attachment_fallback_url(original.replace("2026950087", "not-an-id")) is None
    assert pipeline.applyhome_attachment_fallback_url(original.replace("static.applyhome.co.kr", "example.com")) is None


def test_same_official_attachment_www_host_retains_hash_bound_review():
    from app.extract.reviewed_sources import REVIEWED_SOURCES, reviewed_source_for_document
    source = REVIEWED_SOURCES["2026000498"]
    www = source["document_url"].replace("static.applyhome.co.kr", "www.applyhome.co.kr")
    assert reviewed_source_for_document(www, source["document_hash"]) is source
    assert reviewed_source_for_document(www, "changed-file") is None
    assert reviewed_source_for_document(www.replace("www.applyhome.co.kr", "example.com"), source["document_hash"]) is None
    assert reviewed_source_for_document(www.replace("atchmnflSn=1", "atchmnflSn=2"), source["document_hash"]) is None
    assert reviewed_source_for_document(www + "#other", source["document_hash"]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("ancillary_links", [False, True])
async def test_hyangnam_corrected_project_fallback_after_provider_page_and_attachment_fail(monkeypatch, ancillary_links):
    from app.extract.reviewed_sources import reviewed_document_urls
    source = HYANGNAM
    candidates = reviewed_document_urls(source["payload"]["official_url"], announcement_date="2026-10-02")
    assert candidates[-1] == source["document_url"]
    assert not reviewed_document_urls(source["payload"]["official_url"], announcement_date="2026-09-01")
    assert not reviewed_document_urls(source["payload"]["official_url"].replace("2026000463", "2026000999"), announcement_date="2026-10-02")
    calls = []
    async def extract(url, client, *, payload):
        calls.append(url)
        if url != source["document_url"]:
            request = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("provider unavailable", request=request, response=httpx.Response(500, request=request))
        return {**parsed(source), "document_hash": source["document_hash"], "diagnostics": []}
    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=''.join(
        f'<a href="/ancillary-{number}.pdf">첨부 PDF</a>' for number in range(3))) if ancillary_links else httpx.Response(404))
    async with httpx.AsyncClient(transport=transport) as http:
        result = await pipeline.enrich_notice(source["payload"], http, allow_gemini=False)
    assert calls == (["https://www.applyhome.co.kr/ancillary-0.pdf", "https://www.applyhome.co.kr/ancillary-1.pdf", source["document_url"]] if ancillary_links else candidates)
    assert result["document_hash"] == source["document_hash"]
    scope = next(r for r in result["rules"] if r["kind"] == "applicant_regions" and not r.get("supply_type"))
    assert {r["region_code"] for r in scope["regions"]} == {"41", "11", "28"}
    assert scope["local_priority"]["region_code"] == "41590"
    assert scope["evidence_url"] == source["document_url"]


@pytest.mark.asyncio
async def test_geographic_only_same_hash_reparse_retains_reviewed_admission_facts(monkeypatch):
    region = reviewed_region()
    admission = {"kind": "age_min", "value": 19, "verification": "official", "source": "official_document_parser",
                 "document_hash": "same-file", "parser_version": PARSER_VERSION}
    current = {"official_url": "https://www.applyhome.co.kr/notice", "document_hash": "same-file",
               "rules": [region, admission]}
    async def extract(*args, **kwargs):
        return {"document_hash": "same-file", "rules": [region], "diagnostics": [], "status": "partial"}
    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text='<a href="/notice.pdf">모집공고</a>'))) as http:
        result = await pipeline.enrich_notice(current, http, known_document_hash="same-file", allow_gemini=False)
    assert admission in result["rules"] and region in result["rules"]
    assert result["rules_complete"] is False


@pytest.mark.asyncio
async def test_same_hash_reprocessing_patch_keeps_region_even_if_partial_parser_omits_it(monkeypatch):
    prior = reviewed_region()
    current = {"source": "cheongyak_home", "external_id": "2026950087", "document_hash": "same-file",
        "official_url": "https://www.applyhome.co.kr/notice", "rules": [prior]}
    async def extract(*args, **kwargs):
        return {"document_hash": "same-file", "rules": [{"kind": "age_min", "value": 19, "verification": "official", "source": "official_document_parser", "parser_version": PARSER_VERSION, "document_hash": "same-file"}], "diagnostics": [], "status": "partial"}
    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text='<a href="/notice.pdf">모집공고</a>'))
    async with httpx.AsyncClient(transport=transport) as http:
        enriched = await pipeline.enrich_notice(current, http, known_document_hash="same-file", allow_gemini=False)
    patch = _document_patch(current, enriched)
    assert next(r for r in patch["rules"] if r["kind"] == "applicant_regions")["scope_complete"] is True


@pytest.mark.asyncio
async def test_changed_pdf_retires_old_regions_and_reports_exact_missing_review(monkeypatch):
    prior = reviewed_region()
    current = {"official_url": "https://www.applyhome.co.kr/notice", "document_hash": "same-file", "rules": [prior]}
    async def extract(*args, **kwargs):
        return {"document_hash": "changed-file", "rules": [], "diagnostics": [], "status": "partial"}
    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text='<a href="/notice.pdf">모집공고</a>'))
    async with httpx.AsyncClient(transport=transport) as http:
        enriched = await pipeline.enrich_notice(current, http, known_document_hash="same-file", allow_gemini=False)
    assert not any(r["kind"] == "applicant_regions" for r in enriched["rules"])
    assert enriched["document_hash"] == "changed-file"
    diagnostic = next(d for r in enriched["rules"] if r["kind"] == "document_diagnostics" for d in r["diagnostics"] if d["code"] == "document_changed")
    assert diagnostic["stage"] == "identity" and diagnostic["missing_items"]


@pytest.mark.asyncio
async def test_current_dangsan_failed_attachment_has_no_region_inference_or_fake_document_hash():
    source = DANGSAN_FAILURE
    current = {**source["payload"], "document_hash": "previous-real-pdf", "rules": [reviewed_region(document_hash="previous-real-pdf")]}
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == source["payload"]["official_url"]:
            return httpx.Response(200, text=source["official_detail_html"])
        assert str(request.url) in {source["document_url"], source["document_url"].replace("static.applyhome.co.kr", "www.applyhome.co.kr")}
        return httpx.Response(200, text=source["attachment_response"]["body"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        enriched = await pipeline.enrich_notice(copy.deepcopy(current), http, known_document_hash=current["document_hash"], allow_gemini=False)
    assert enriched["document_hash"] == current["document_hash"]
    assert next(r for r in enriched["rules"] if r["kind"] == "applicant_regions") == current["rules"][0]
    diagnostics = next(r for r in enriched["rules"] if r["kind"] == "document_diagnostics")
    assert diagnostics["status"] == "unreadable"
    error = next(d for d in diagnostics["diagnostics"] if d["status"] == "error")
    assert error["code"] == "unexpected_response" and error["stage"] == "decode"
    assert error["evidence_url"] in {source["document_url"], source["document_url"].replace("static.applyhome.co.kr", "www.applyhome.co.kr")} and error["missing_items"]
    assert len(calls) == 3
    empty = {**source["payload"], "rules": []}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        failed = await pipeline.enrich_notice(empty, http, allow_gemini=False)
    assert not failed.get("document_hash")
    assert not any(r["kind"] == "applicant_regions" for r in failed["rules"])


def lh_schedule():
    return parse_lh_detail_contract_schedule(GYEONGSAN["html_fragment"], url=GYEONGSAN["official_url"], external_id=GYEONGSAN["external_id"])


def test_gyeongsan_actual_official_contract_field_overrides_attached_ongoing_schedule():
    rule = lh_schedule()
    assert rule["start_date"] == "2026-10-27" and rule["end_date"] == "2027-08-31"
    assert rule["evidence_location"] == "#sta_ctrtDt"
    assert rule["source_hash"] == hashlib.sha256(GYEONGSAN["html_fragment"].encode()).hexdigest()
    ongoing = {"kind": "contract_schedule", "status": "ongoing", "start_date": "2026-10-27", "verification": "official", "document_hash": "actual-pdf", "source": "official_document_parser"}
    projected = public_contract_schedule([ongoing, rule], contract_events=[{"start_date": date(2026, 10, 26), "end_date": date(2026, 10, 26)}])
    assert projected.status == "range" and projected.start_date == date(2026, 10, 27) and projected.end_date == date(2027, 8, 31)
    assert projected.source_hash == rule["source_hash"] and projected.evidence_location == "#sta_ctrtDt"


@pytest.mark.parametrize("html,url,identity", [
    (GYEONGSAN["html_fragment"], GYEONGSAN["official_url"], "another-notice"),
    (GYEONGSAN["html_fragment"].replace("계약기간", "공고게시기간"), GYEONGSAN["official_url"], GYEONGSAN["external_id"]),
    (GYEONGSAN["html_fragment"].replace("2027.08.31", "2026.02.30"), GYEONGSAN["official_url"], GYEONGSAN["external_id"]),
    (GYEONGSAN["html_fragment"], GYEONGSAN["official_url"].replace("apply.lh.or.kr", "example.com"), GYEONGSAN["external_id"]),
])
def test_other_notice_posting_period_and_invalid_contract_field_are_rejected(html, url, identity):
    assert parse_lh_detail_contract_schedule(html, url=url, external_id=identity) is None


def test_lh_detail_contract_survives_document_patch_and_matches_list_detail_api(db, client):
    raw = {**example_notice(source="lh", external_id=GYEONGSAN["external_id"]), "official_url": GYEONGSAN["official_url"]}
    enriched = {**raw, "rules": [*raw["rules"], lh_schedule()]}
    patch = _document_patch(raw, enriched)
    assert next(r for r in patch["rules"] if r["kind"] == "contract_schedule")["source"] == "lh_official_detail"
    notice = upsert_notice(db, {**raw, **patch})
    db.commit()
    listed = client.get("/api/notices").json()["items"][0]["contract_schedule"]
    detailed = client.get(f"/api/notices/{notice.id}").json()["contract_schedule"]
    assert listed == detailed
    assert listed["start_date"] == "2026-10-27" and listed["end_date"] == "2027-08-31"
    assert listed["evidence_url"] == raw["official_url"] and listed["source_hash"]
    assert listed["evidence_location"] == "#sta_ctrtDt"
