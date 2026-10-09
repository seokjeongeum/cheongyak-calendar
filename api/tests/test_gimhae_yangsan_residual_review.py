"""Current Sept 30 LH offer, independent of both similarly named Seonun offers."""
import copy
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.extract.official_rules import parse_official_rules
from app.extract.pipeline import _with_diagnostics, enrich_notice
from app.extract.public_residual_sources import reviewed_public_residual_source
from app.extract.reviewed_sources import focused_review_version, reviewed_document_urls
from app.ingest.worker import _failed_document_needs_new_pipeline
from app.models import Notice

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "gimhae-yangsan-residual-20260930.json").read_text())


def parse(*, digest=None, payload=None, pages=None):
    return parse_official_rules(pages or FIXTURE["pages"], url=FIXTURE["document_url"],
        digest=digest or FIXTURE["document_hash"], payload=payload or FIXTURE["payload"])


def coverage(result):
    return next((rule for rule in result["rules"] if rule["kind"] == "condition_coverage"), None)


def test_current_lh_applicant_scope_preserves_restrictions_and_age_exception():
    result = parse()
    assert result["status"] == "complete"
    reviewed = coverage(result)["scopes"][0]
    assert reviewed["supply_type"] == "일반공급" and reviewed["complete"] is True
    assert reviewed["missing_topics"] == []
    assert reviewed["reviewed_document_hash"] == FIXTURE["document_hash"]
    assert reviewed["completion_basis"] == "document_hash_review"
    assert len(FIXTURE["pages"]) == 15
    assert all(rule["criterion_date"] == "2026-09-30" for rule in result["rules"])
    regional = next(rule for rule in result["rules"] if rule["kind"] == "applicant_regions")
    assert regional["unrestricted"] is True and regional["domestic_only"] is True
    assert regional["priority_applicable"] is False and regional["scope_complete"] is True
    restrictions = {r["restriction"]: r for r in result["rules"] if r["kind"] == "application_restriction"}
    assert set(restrictions) == {"rewinning_restriction_active", "ineligible_restriction_active"}
    assert restrictions["rewinning_restriction_active"]["scope"] == "household"
    assert restrictions["ineligible_restriction_active"]["scope"] == "applicant"
    adult_or_minor = next(rule for rule in result["rules"] if rule["kind"] == "any")
    assert adult_or_minor["conditions"][0]["value"] == 19
    assert adult_or_minor["conditions"][1]["kind"] == "minor_household_head"
    assert adult_or_minor["conditions"][1]["required_same_register"] is True
    assert next(rule for rule in result["rules"] if rule["kind"] == "citizenship")["allowed_values"] == ["korean"]
    exemption = next(rule for rule in result["rules"] if rule["kind"] == "condition_exemptions")
    assert exemption["topics"] == ["account"]
    assert not any(rule["kind"] == "provider_employee_restriction" for rule in result["rules"])
    # There are 14 independent projects in this PDF. Its group total is not
    # assigned as the inventory count of each separately collected project.
    assert not any(s.get("supply_count") == 153 for rule in result["rules"] if rule["kind"] == "offered_supplies" for s in rule["supplies"])


def test_changed_hash_missing_pages_or_restriction_cannot_claim_complete_review():
    assert parse(digest="0" * 64)["status"] != "complete"
    result = parse(pages=[page for page in FIXTURE["pages"] if page["page"] != 15])
    assert result["status"] != "complete"
    assert any(gap.get("pages") == [15] for gap in coverage(result)["scopes"][0]["source_gaps"])
    pages = copy.deepcopy(FIXTURE["pages"])
    pages[0]["text"] = pages[0]["text"].replace("청약할 수 없습니다", "조항 텍스트 미확보")
    result = parse(pages=pages)
    assert result["status"] != "complete"
    assert any("재당첨 제한 적용" in item for item in coverage(result)["scopes"][0]["missing_topics"])


def test_current_pdf_cannot_be_attached_to_a_different_notice_or_july_source():
    for field, value in [
        ("announcement_date", "2026-07-06"),
        ("announcement_date", "2026-07-08"),
        ("official_url", FIXTURE["payload"]["official_url"].replace("2015122300020860", "2015122300020823")),
        ("official_url", "https://www.gmcc.co.kr/board.es?mid=a10402030000&bid=0018&act=view&list_no=19275"),
    ]:
        payload = copy.deepcopy(FIXTURE["payload"])
        payload[field] = value
        assert reviewed_public_residual_source(url=FIXTURE["document_url"], digest=FIXTURE["document_hash"], payload=payload) is None
        result = parse(payload=payload)
        assert result["status"] == "unsupported"
        assert not any(rule["kind"] in {"condition_coverage", "applicant_regions", "homeless"} for rule in result["rules"])


def test_targeted_reprocessing_runs_once_for_lh_and_myhome_and_retains_other_audits():
    payload = FIXTURE["payload"]
    url = payload["official_url"]
    assert reviewed_document_urls(url, announcement_date="2026-09-30") == [FIXTURE["document_url"]]
    assert reviewed_document_urls(url, announcement_date="2026-07-06") == []
    assert focused_review_version(url, "2026-09-30") == "gimhae-yangsan-residual-2026-10-10-v1"
    assert focused_review_version(url, "2026-07-06") is None
    for source in ("lh", "myhome"):
        row = Notice(source=source, external_id="2015122300020860", official_url=url, announcement_date=date(2026, 9, 30), rules=[])
        assert _failed_document_needs_new_pipeline(row) is True
        row.rules = _with_diagnostics(copy.deepcopy(payload), [], "complete")["rules"]
        assert _failed_document_needs_new_pipeline(row) is False
    row = Notice(source="myhome", external_id="unrelated", official_url=url.replace("2015122300020860", "2015122300020823"), announcement_date=date(2026, 9, 30), rules=[])
    assert _failed_document_needs_new_pipeline(row) is False


@pytest.mark.asyncio
async def test_gmcc_503_retains_failure_stage_without_borrowing_current_lh_region(monkeypatch):
    monkeypatch.setattr("app.extract.pipeline.DOWNLOAD_RETRY_DELAY_SECONDS", 0)
    url = "https://www.gmcc.co.kr/board.es?mid=a10402030000&bid=0018&act=view&list_no=19275"
    def respond(request):
        assert str(request.url) == url
        return httpx.Response(503, text="Service unavailable", request=request)
    payload = {"title": "선운지구다사로움 일반공급 잔여세대 (선착순) 입주자 모집공고", "announcement_date": "2026-07-08", "official_url": url, "source": "myhome", "rules": []}
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await enrich_notice(payload, client=client, allow_gemini=False)
    assert result["local_extraction_status"] == "unreadable"
    diagnostics = next(rule["diagnostics"] for rule in result["rules"] if rule["kind"] == "document_diagnostics")
    assert any(entry["stage"] == "discovery" and entry.get("http_status") == 503 and entry["code"] == "announcement_download_failed" for entry in diagnostics)
    assert any("현재 모집공고문의 첨부 주소" in entry.get("missing_items", []) for entry in diagnostics)
    assert not any(rule["kind"] in {"applicant_regions", "residence_region", "condition_coverage"} for rule in result["rules"])
