"""Current officetel applicant clauses, independent of nearby apartment ads."""
import copy
import json
from datetime import date
from pathlib import Path

from app.extract.official_rules import parse_official_rules
from app.extract.pipeline import _with_diagnostics
from app.extract.reviewed_sources import focused_review_version, reviewed_document_urls
from app.ingest.worker import _failed_document_needs_new_pipeline
from app.models import Notice

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "okjung-office-20261008.json").read_text())


def parse(*, digest=None, pages=None, payload=None):
    return parse_official_rules(pages or FIXTURE["pages"], url=FIXTURE["url"],
        digest=digest or FIXTURE["document_hash"], payload=payload or FIXTURE["payload"])


def test_okjung_current_advertisement_domestic_adult_and_unrestricted_region():
    result = parse()
    assert result["status"] == "complete"
    assert len(FIXTURE["pages"]) == 33
    rules = {r["kind"]: r for r in result["rules"]}
    assert rules["age_min"]["value"] == 19
    assert rules["age_min"]["evidence_page"] == 7
    assert rules["domestic_residence"]["value"] is True
    assert rules["applicant_regions"]["unrestricted"] is True
    assert rules["applicant_regions"]["domestic_only"] is True
    assert rules["applicant_regions"]["priority_applicable"] is False
    assert rules["applicant_regions"]["scope_complete"] is True
    assert rules["rank_applicability"]["status"] == "not_applicable"
    assert rules["rank_applicability"]["account_required"] is False
    assert not any(r["kind"] in {"homeless", "citizenship", "private_rank_months", "residence_region"} for r in result["rules"])
    assert all(r["document_hash"] == FIXTURE["document_hash"] and r["criterion_date"] == "2026-10-08" for r in result["rules"])


def test_changed_document_or_missing_applicant_page_cannot_use_completed_review():
    assert parse(digest="0" * 64)["status"] != "complete"
    pages = [p for p in FIXTURE["pages"] if p["page"] != 7]
    assert parse(pages=pages)["status"] != "complete"
    payload = copy.deepcopy(FIXTURE["payload"])
    payload["announcement_date"] = "2026-04-09"
    result = parse(payload=payload)
    assert result["status"] == "unsupported"
    assert not any(r["kind"] in {"age_min", "domestic_residence", "applicant_regions", "condition_coverage"} for r in result["rules"])
    payload = copy.deepcopy(FIXTURE["payload"])
    payload["official_url"] = payload["official_url"].replace("2026950077", "2026950086")
    result = parse(payload=payload)
    assert result["status"] == "unsupported"
    assert not any(r["kind"] in {"age_min", "domestic_residence", "applicant_regions", "condition_coverage"} for r in result["rules"])


def test_only_current_notice_and_date_receive_fallback_and_focused_reprocessing():
    payload = {**FIXTURE["payload"], "external_id": "2026950077"}
    assert reviewed_document_urls(payload["official_url"], announcement_date="2026-10-08") == [FIXTURE["url"]]
    assert reviewed_document_urls(payload["official_url"], announcement_date="2026-04-09") == []
    assert focused_review_version(payload["official_url"], "2026-10-08") == "okjung-office-2026-10-10-v1"
    assert focused_review_version(payload["official_url"], "2026-04-09") is None
    row = Notice(source="cheongyak_home", external_id="2026950077", official_url=payload["official_url"], announcement_date=date(2026, 10, 8), rules=[])
    assert _failed_document_needs_new_pipeline(row) is True
    row.rules = _with_diagnostics(payload, [], "complete")["rules"]
    assert _failed_document_needs_new_pipeline(row) is False
