"""Current LH residual admission and changed-source regressions without allowlists."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from app.extract.official_rules import parse_official_rules
from app.qualification import public_offered_supplies, requirements_complete

FIXTURE = json.loads((Path(__file__).parent / "fixtures/gajeong-admission-v8.json").read_text())


def parse(*, digest=None, pages=None, payload=None):
    return parse_official_rules(pages if pages is not None else FIXTURE["pages"],
        url=FIXTURE["document_url"], digest=digest or FIXTURE["document_hash"], payload=payload or FIXTURE["payload"])


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
    assert scope["reviewed_document_hash"] == FIXTURE["document_hash"]
    adult_or_minor = rule(result, "any")
    assert {condition["kind"] for condition in adult_or_minor["conditions"]} == {"age_min", "minor_household_head"}
    minor = next(condition for condition in adult_or_minor["conditions"] if condition["kind"] == "minor_household_head")
    assert minor["required_same_register"] is True
    assert set(minor["reasons"]) == {"support_children", "support_siblings_parents_dead_or_missing"}
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
    assert ownership["project_id"] == FIXTURE["external_id"]
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
    assert all(r.evidence_page == 3 and r.document_hash == FIXTURE["document_hash"] for r in inventory)
    # A newly downloaded source is interpreted anew and bound to its own
    # hash. Valid unchanged content needs no remembered project/hash entry.
    changed_inventory = public_offered_supplies(parse(digest="corrected-new-file")["rules"])
    assert [(r.unit_type, r.supply_count) for r in changed_inventory] == [(r.unit_type, r.supply_count) for r in inventory]
    assert all(r.document_hash == "corrected-new-file" for r in changed_inventory)


def test_duplicate_couple_and_post_selection_procedures_are_instructions():
    result = parse()
    metadata = rule(result, "application_instructions")
    assert metadata["effect"] == "metadata"
    duplicates = next(i for i in metadata["instructions"] if i["phase"] == "application")
    assert "부부(예비신혼부부 제외)" in duplicates["detail"]
    assert "분 단위" in duplicates["detail"]
    assert "연령(연월일 계산)이 많은 자" in duplicates["detail"]
    assert "동일블록" in duplicates["evidence_text"]
    assert any(i["phase"] == "post_selection" for i in metadata["instructions"])
    conditions = [r for r in result["rules"] if r.get("effect") != "metadata"]
    assert len(conditions) == 7
    assert not any("서류" in r.get("label", "") or "납부" in r.get("kind", "") for r in conditions)
    assert {"account", "income", "assets", "prior_win", "rewinning_restriction"} <= set(rule(result, "condition_exemptions")["topics"])


def test_new_hash_is_reviewed_from_current_content_and_missing_operative_source_stays_partial():
    changed = parse(digest="corrected-new-file")
    assert changed["status"] == "complete" and requirements_complete(changed["rules"], True)
    changed_scope = rule(changed, "condition_coverage")["scopes"][0]
    assert changed_scope["reviewed_document_hash"] == "corrected-new-file"
    assert changed_scope["missing_topics"] == []
    missing_pages = parse(pages=[page for page in FIXTURE["pages"] if page["page"] != 2])
    scope = rule(missing_pages, "condition_coverage")["scopes"][0]
    assert scope["complete"] is False
    assert any(gap["stage"] == "document_text" for gap in scope["source_gaps"])
    absent_exception = copy.deepcopy(FIXTURE["pages"])
    absent_exception[1]["text"] = absent_exception[1]["text"].replace("단독세대주 또는 동거인의 세대원", "원문 누락")
    # The exception is still mandatory to interpret accurately. Do not certify
    # a parser output after a text extractor has dropped its operative words.
    missing = parse(pages=absent_exception)
    assert missing["status"] == "partial"
    gaps = rule(missing, "condition_coverage")["scopes"][0]["source_gaps"]
    assert any("생업" in gap["item"] for gap in gaps)


def test_new_project_and_dates_use_the_current_source_instead_of_a_named_review():
    pages, payload = copy.deepcopy(FIXTURE["pages"]), copy.deepcopy(FIXTURE["payload"])
    for page in pages:
        page["text"] = page["text"].replace("인천가정2", "새로운공공단지").replace("2026.09.23", "2027.10.11").replace("2026.04.15", "2027.02.03")
    payload.update(title="새로운공공단지 공공분양 잔여세대 추가 입주자모집공고", external_id="0000099999",
        announcement_date="2027-10-11", official_url="https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?panId=0000099999")
    result = parse(pages=pages, payload=payload, digest="new-project-current-pdf")
    assert result["status"] == "complete"
    assert requirements_complete(result["rules"], False)
    ownership = rule(result, "original_project_contract_ownership")
    assert ownership["project_id"] == "0000099999"
    assert ownership["original_announcement_date"] == "2027-02-03"
    assert ownership["criterion_date"] == "2027-10-11"
    assert ownership["document_hash"] == "new-project-current-pdf"
    assert len(public_offered_supplies(result["rules"])) == 4
