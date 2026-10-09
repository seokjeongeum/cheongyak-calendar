"""Current October 8 applicant paragraphs, never inferred from project addresses.

Fixtures contain all text pages extracted locally from the exact official PDFs.
The review certifies regional scope only; it does not certify all eligibility.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import pytest

from app.extract.official_rules import parse_official_rules
from app.extract.reviewed_sources import reviewed_source_for_document


SOURCES = json.loads((Path(__file__).parent / "fixtures/current-oct8-regions.json").read_text())


def test_sangok_25_year_local_exception_retains_required_official_recommendation():
    source = next(row for row in SOURCES if row["external_id"] == "2026000458")
    scope = next(rule for rule in parsed(source)["rules"] if rule.get("kind") == "applicant_regions")
    exception = next(rule for rule in scope["exceptions"] if rule.get("min_years") == 25)
    assert exception["residence_area"] == "local" and exception["currently_serving"] is True
    assert exception["recommendation_required"] is True
    assert exception["recommendation_authority"] == "국방부(국군복지단)"
    assert exception["evidence_page"] == 5 and exception["document_hash"] == source["document_hash"]
    assert "추천" in exception["evidence_text"] and "거주자격" in exception["evidence_text"]


def parsed(source, **payload_changes):
    return parse_official_rules(source["pages"], url=source["document_url"],
        digest=source["document_hash"], payload={**source["payload"], **payload_changes})


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source["external_id"])
def test_current_oct8_applicant_scope_and_priority_match_exact_official_paragraph(source):
    expected = source["regional_expectation"]
    result = parsed(source)
    assert result["status"] == "partial"
    scopes = [rule for rule in result["rules"]
              if rule.get("kind") == "applicant_regions" and not rule.get("supply_type")]
    assert scopes
    scope = scopes[0]
    assert scope["scope_complete"] is True
    assert {region["region_code"] for region in scope["regions"]} == set(expected["region_codes"])
    assert scope["priority_applicable"] is True
    if expected.get("local_district_codes"):
        assert {region["region_code"] for region in scope["local_priority"]["regions"]} == set(expected["local_district_codes"])
        mapping = scope["local_priority"]["mapping_evidence"]
        assert mapping["evidence_page"] == 1
        assert mapping["document_hash"] == source["document_hash"]
        assert "기존 광주광역시" in mapping["evidence_text"]
    else:
        assert scope["local_priority"]["region_code"] == expected["local_region_code"]
    assert scope["local_priority"]["min_months"] == expected["local_min_months"]
    assert scope["criterion_date"] == "2026-10-08"
    assert scope["evidence_page"] == expected["evidence_page"]
    assert scope["document_hash"] == source["document_hash"]
    assert "입주자모집공고일 현재" in scope["evidence_text"]
    assert "우선" in scope["evidence_text"].replace(" ", "")
    military_expected = source["military_expectation"]
    military = next(rule for rule in scope["exceptions"] if rule.get("kind") == "military_service_years" and rule.get("min_years") == 10)
    assert military["currently_serving"] is True
    assert military["residence_area"] == military_expected["residence_area"]
    assert military["require_as_of_date"] is True
    assert military["evidence_page"] == military_expected["evidence_page"]
    assert military["document_hash"] == source["document_hash"]
    assert re.search(r"10[^■▌]{0,80}년\s*이상", military["evidence_text"])
    assert "장기복무" in military["evidence_text"]
    assert "거주자격" in military["evidence_text"].replace(" ", "")


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source["external_id"])
def test_oct8_review_is_bound_to_official_attachment_bytes_and_notice(source):
    source_query = parse_qs(urlparse(source["document_url"]).query)
    assert source_query["houseManageNo"] == source_query["pblancNo"] == [source["external_id"]]
    assert any(source["external_id"] in page["text"] for page in source["pages"])
    review = reviewed_source_for_document(source["document_url"], source["document_hash"])
    assert review is not None
    assert review["announcement_date"] == "2026-10-08"
    assert reviewed_source_for_document(source["document_url"], "0" * 64) is None
    wrong_notice = source["payload"]["official_url"].replace(source["external_id"], "2026000999")
    assert parsed(source, official_url=wrong_notice)["rules"] == []
    assert parsed(source, announcement_date="2026-09-08")["status"] == "unsupported"


@pytest.mark.parametrize("external_id", ["2026000466", "2026000471"])
def test_former_gwangju_and_jeonnam_boundaries_remain_explicit(external_id):
    source = next(row for row in SOURCES if row["external_id"] == external_id)
    scope = next(rule for rule in parsed(source)["rules"] if rule.get("kind") == "applicant_regions")
    assert {region["region_code"] for region in scope["regions"]} == {"12"}
    assert {region["region_code"] for region in scope["source_regions"]} == {"29", "46"}
    assert "기존" in scope["evidence_text"]
    # A document's former-territory priority must not become a blanket priority
    # for the newly merged province.
    if external_id == "2026000466":
        assert scope["local_priority"]["region_code"] == "12860"
    else:
        assert {region["region_code"] for region in scope["local_priority"]["regions"]} == {"12210", "12240", "12270", "12300", "12330"}
