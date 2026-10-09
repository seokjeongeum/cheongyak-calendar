"""The latest official attachment keeps the round's October 2 criterion."""
import json
from pathlib import Path

import pytest

from app.extract.official_rules import parse_official_rules
from app.extract.reviewed_sources import reviewed_document_urls, reviewed_source_for_document

SOURCE = json.loads((Path(__file__).parent / "fixtures/cheonan-corrected-20261008.json").read_text())


def parsed(**overrides):
    return parse_official_rules(SOURCE["pages"], url=overrides.get("url", SOURCE["document_url"]),
        digest=overrides.get("digest", SOURCE["document_hash"]), payload={**SOURCE["payload"], **overrides.get("payload", {})})


def test_current_corrected_bytes_have_own_review_and_original_qualification_date():
    assert len(SOURCE["pages"]) == 65
    assert "2026.10.08." in SOURCE["pages"][0]["text"]
    assert "2026.10.02." in SOURCE["pages"][4]["text"]
    review = reviewed_source_for_document(SOURCE["document_url"], SOURCE["document_hash"])
    assert review["correction_publication_date"] == "2026-10-08"
    assert review["announcement_date"] == "2026-10-02"
    assert review["document_page_count"] == 65
    assert review["supersedes_document_hash"] != review["document_hash"]
    assert SOURCE["document_url"] in reviewed_document_urls(SOURCE["payload"]["official_url"], announcement_date="2026-10-02")
    assert SOURCE["document_url"] not in reviewed_document_urls(SOURCE["payload"]["official_url"], announcement_date="2026-10-08")
    assert reviewed_source_for_document(SOURCE["document_url"], review["supersedes_document_hash"]) is None
    result = parsed()
    assert result["status"] == "partial" and result.get("identity_status") != "mismatch"
    assert all(rule.get("criterion_date") == "2026-10-02" for rule in result["rules"])


def test_corrected_region_and_local_military_exception_are_from_new_pages():
    result = parsed()
    region = next(rule for rule in result["rules"] if rule["kind"] == "applicant_regions")
    assert region["scope_complete"] and region["priority_applicable"]
    assert {item["region_code"] for item in region["regions"]} == {"44", "30", "36"}
    assert region["local_priority"] == {"region_code": "44130", "region_name": "충청남도 천안시", "min_months": 0, "criterion_date": "2026-10-02"}
    assert region["evidence_page"] == 5 and region["document_hash"] == SOURCE["document_hash"]
    assert "천안시에 거주하거나 충청남도 대전광역시 및 세종특별자치시" in region["evidence_text"]
    military = region["exceptions"][0]
    assert military["min_years"] == 10 and military["currently_serving"] and military["residence_area"] == "local"
    assert military["evidence_page"] == 6 and military["document_hash"] == SOURCE["document_hash"]
    assert "년 이상 장기복무 중인 군인" in military["evidence_text"]
    assert "거주자격으로 청약할 수 있습니다" in military["evidence_text"]


def test_new_supply_table_has_fourteen_positive_rows_total_sixty_one_without_admission_certificate():
    result = parsed()
    inventory = next(rule for rule in result["rules"] if rule["kind"] == "offered_supplies")["supplies"]
    assert len(inventory) == 14 and sum(row["supply_count"] for row in inventory) == 61
    assert all(row["evidence_page"] == 6 and row["document_hash"] == SOURCE["document_hash"] for row in inventory)
    expected = {
        "084.9800A": [4, 4, 5, 1, 3, 4, 16],
        "084.9700B": [2, 2, 4, 1, 1, 2, 12],
    }
    supplies = ["기관추천 특별공급", "다자녀가구 특별공급", "신혼부부 특별공급", "노부모부양 특별공급", "생애최초 특별공급", "신생아 특별공급", "일반공급"]
    for unit, counts in expected.items():
        assert {row["supply_type"]: row["supply_count"] for row in inventory if row["unit_type"] == unit} == dict(zip(supplies, counts))
    coverage = next(rule for rule in result["rules"] if rule["kind"] == "condition_coverage")
    assert coverage["status"] == "partial" and all(not scope["complete"] for scope in coverage["scopes"])
    assert not any(rule["kind"] == "rank_requirements" and rule.get("complete") for rule in result["rules"])


@pytest.mark.parametrize("changes", [
    {"digest": "changed-current-file"},
    {"payload": {"announcement_date": "2026-10-08"}},
    {"payload": {"official_url": SOURCE["payload"]["official_url"].replace("2026000498", "2026000999")}},
])
def test_changed_bytes_notice_or_qualification_date_do_not_borrow_current_region(changes):
    result = parsed(**changes)
    assert result["status"] == "unsupported"
    assert not any(rule["kind"] == "applicant_regions" for rule in result["rules"])
