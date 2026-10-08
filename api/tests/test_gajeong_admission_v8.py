"""Current corrected LH Gajeong B2 admission and inventory, checked by hash."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from app.extract.gajeong_admission import GAJEONG_HASH, GAJEONG_PROJECT
from app.extract.official_rules import parse_official_rules
from app.qualification import public_offered_supplies, requirements_complete

FIXTURE = json.loads((Path(__file__).parent / "fixtures/gajeong-admission-v8.json").read_text())


def parse(*, digest=GAJEONG_HASH, pages=None):
    return parse_official_rules(pages if pages is not None else FIXTURE["pages"],
        url=FIXTURE["document_url"], digest=digest, payload=FIXTURE["payload"])


def rule(result, kind):
    return next(r for r in result["rules"] if r["kind"] == kind)


def test_full_current_document_certifies_specific_admission_branches():
    result = parse()
    assert result["status"] == "complete"
    assert requirements_complete(result["rules"], False)
    scope = rule(result, "condition_coverage")["scopes"][0]
    assert scope["complete"] is True
    assert scope["missing_topics"] == []
    assert scope["source_gaps"] == []
    assert scope["reviewed_document_hash"] == FIXTURE["document_hash"] == GAJEONG_HASH
    assert {branch["branch_id"] for branch in scope["branches"]} == {"adult", "minor_household_head", "overseas_livelihood", "ownership_exceptions"}
    assert {topic["topic"] for topic in scope["topics"] if topic["required"]} == {
        "age", "domestic_residence", "citizenship", "home_ownership", "overseas_residence", "original_contract_ownership", "application_restrictions"}
    assert all(r["criterion_date"] == "2026-09-23" for r in result["rules"])
    assert rule(result, "qualification_context")["value"]["original_announcement_date"] == "2026-04-15"


def test_overseas_source_includes_exact_current_stay_and_livelihood_exclusions():
    result = parse()
    overseas = rule(result, "overseas_residence")
    assert overseas["max_continuous_days"] == 90
    assert overseas["currently_abroad_only"] is True
    assert overseas["reentry_same_country"] is True and overseas["reentry_within_days"] == 7
    assert "같은 국가" in overseas["evidence_text"]
    assert overseas["livelihood_exception"] is True
    assert overseas["livelihood_exception_requires_family"] is True
    assert overseas["livelihood_exception_excludes"] == ["sole_household_head", "cohabitant_household_member"]
    assert "단독세대주 또는 동거인의 세대원" in overseas["exception_evidence_text"]
    assert "2026.09.22" in overseas["return_evidence_text"]
    assert rule(result, "domestic_residence")["overseas_residence_equivalence"] is True


def test_original_first_winner_then_contract_is_ownership_not_win_or_ineligible_ban():
    result = parse()
    ownership = rule(result, "original_project_contract_ownership")
    assert ownership["project_id"] == GAJEONG_PROJECT
    assert ownership["requires_original_winning"] is True
    assert ownership["ownership_effect"] == "contract_date"
    assert ownership["scope"] == "applicant"
    assert ownership["original_announcement_date"] == "2026-04-15"
    assert ownership["first_winning_alone_allowed"] is True
    assert ownership["ineligible_winning_alone_allowed"] is True
    assert "당첨 후 부적격" in ownership["permission_evidence_text"]
    restrictions = [r for r in result["rules"] if r["kind"] == "application_restriction"]
    assert [(r["restriction"], r["scope"]) for r in restrictions] == [("resale_restriction_active", "applicant")]
    assert not any(r["kind"] in {"previous_winning", "special_winning"} for r in result["rules"])


def test_only_current_residual_units_count_towards_252_not_the_308_total_stock():
    result = parse()
    summary = rule(result, "supply_inventory_summary")
    assert summary["total_households"] == 308
    assert summary["current_supply_count"] == 252
    assert "308세대 중 잔여 252세대" in summary["evidence_text"]
    assert summary["official_supply_url"] == FIXTURE["official_supply_evidence"]["url"]
    assert "308세대 중 252세대" in FIXTURE["official_supply_evidence"]["text"]
    inventory = public_offered_supplies(result["rules"])
    assert [(r.unit_type, r.supply_count) for r in inventory] == [
        ("74.9500A", 18), ("84.0000A", 154), ("84.0000B", 58), ("84.9800C", 22)]
    assert sum(r.supply_count for r in inventory) == 252
    assert all(r.evidence_page == 3 and r.document_hash == GAJEONG_HASH for r in inventory)
    # A changed document is not certified by the old review; the explicit
    # residual total still comes from its current text, never total stock.
    changed_inventory = public_offered_supplies(parse(digest="corrected-new-file")["rules"])
    assert len(changed_inventory) == 1 and changed_inventory[0].supply_count == 252


def test_duplicate_couple_and_post_selection_procedures_are_instructions():
    result = parse()
    metadata = rule(result, "application_instructions")
    assert metadata["effect"] == "metadata"
    duplicates = next(i for i in metadata["instructions"] if i["phase"] == "application")
    assert "부부(예비신혼부부 제외)" in duplicates["detail"]
    assert "분 단위" in duplicates["detail"] and "연장자" in duplicates["detail"]
    assert "동일블록" in duplicates["evidence_text"]
    assert any(i["phase"] == "post_selection" for i in metadata["instructions"])
    conditions = [r for r in result["rules"] if r.get("effect") != "metadata"]
    assert len(conditions) == 7
    assert not any("서류" in r.get("label", "") or "납부" in r.get("kind", "") for r in conditions)
    assert {"account", "income", "assets", "prior_win", "rewinning_restriction"} <= set(rule(result, "condition_exemptions")["topics"])


def test_changed_hash_missing_pages_and_missing_clause_never_certify_review():
    changed = parse(digest="corrected-new-file")
    assert changed["status"] == "partial" and not requirements_complete(changed["rules"], True)
    changed_scope = rule(changed, "condition_coverage")["scopes"][0]
    assert "문서의 나머지 신청 제한·예외 검토" not in changed_scope["missing_topics"]
    assert "국내 거주·해외 연속 체류 제한 및 예외" in changed_scope["missing_topics"]
    missing_pages = parse(pages=FIXTURE["pages"][:-1])
    scope = rule(missing_pages, "condition_coverage")["scopes"][0]
    assert scope["complete"] is False
    assert {"item": "검토한 원문 페이지 미확보", "pages": [19], "stage": "document_text"} in scope["source_gaps"]
    absent_exception = copy.deepcopy(FIXTURE["pages"])
    absent_exception[1]["text"] = absent_exception[1]["text"].replace("단독세대주 또는 동거인의 세대원", "원문 누락")
    # The exception is still mandatory to interpret accurately. Do not certify
    # a parser output after a text extractor has dropped its operative words.
    missing = parse(pages=absent_exception)
    assert missing["status"] == "partial"
    assert "해외 연속 체류 90일 초과 제한·생업 예외" in rule(missing, "condition_coverage")["scopes"][0]["missing_topics"]
