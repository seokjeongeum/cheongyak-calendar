"""Source-bound applicant review; current files must not borrow past facts."""
import copy
import json
from pathlib import Path

import pytest

from app.extract.current_private_admission import REVIEW_VERSION, SOURCE_LAYOUTS
from app.extract.official_rules import PARSER_VERSION, parse_official_rules
from app.extract.reviewed_sources import reviewed_document_urls, reviewed_source_for_document

FIXTURES = Path(__file__).parent / "fixtures"
PRIVATE = json.loads((FIXTURES / "current-private-v5.json").read_text())
YONGIN = next(row for row in PRIVATE if row["external_id"] == "2026000386")
HYANGNAM_ORIGINAL = next(row for row in PRIVATE if row["external_id"] == "2026000463")
HYANGNAM_CORRECTED = json.loads((FIXTURES / "hyangnam-regional-v9.json").read_text())
OSAN = json.loads((FIXTURES / "osan-office-v11.json").read_text())
ROWS = [YONGIN, HYANGNAM_ORIGINAL, HYANGNAM_CORRECTED]


def parse(row, **overrides):
    return parse_official_rules(overrides.get("pages", row["pages"]), url=overrides.get("url", row["document_url"]),
                                digest=overrides.get("digest", row["document_hash"]), payload=overrides.get("payload", row["payload"]))


def rules(result, kind, supply=None):
    return [r for r in result["rules"] if r["kind"] == kind and (supply is None or r.get("supply_type") == supply)]


def walk(items):
    for item in items:
        yield item
        yield from walk(item.get("conditions", []))


def coverage(result):
    return {scope["supply_type"]: scope for scope in rules(result, "condition_coverage")[0]["scopes"]}


@pytest.mark.parametrize("row", ROWS, ids=["yongin", "hyangnam_original", "hyangnam_corrected"])
def test_standard_scopes_are_source_bound_without_blanket_income_or_legal_gaps(row):
    result = parse(row)
    scopes = coverage(result)
    assert scopes["일반공급"]["complete"]
    for supply, scope in scopes.items():
        assert scope["review_version"] == REVIEW_VERSION
        assert scope["completion_basis"] == "document_hash_reviewed_standard_branch"
        assert scope["complete"] == (supply != "신혼부부 특별공급")
        assert scope["missing_topics"] == (["동일 배우자와 재혼한 경우 이전 혼인기간 합산"] if supply == "신혼부부 특별공급" else [])
        assert not any(topic in {"소득·자산 분기", "재당첨·청약 제한 및 법령 예외", "신청 제한·연령 예외의 전체 검토"} for topic in scope["missing_topics"])
        assert any("전환" in topic["topic"] and not topic["required"] for topic in scope["topics"])
        if supply in {"일반공급", "기관추천 특별공급", "다자녀가구 특별공급", "노부모부양 특별공급"}:
            topics = {topic["topic"]: topic for topic in scope["topics"]}
            for name in ("소득 기준", "자산 기준"):
                assert topics[name]["status"] == "not_applicable" and not topics[name]["required"]
    general = [r for r in result["rules"] if r.get("effect") != "metadata" and r.get("purpose") != "first_rank" and r.get("supply_type") in {None, "일반공급"}]
    assert not {r["kind"] for r in general} & {"homeless", "household_head", "special_winning", "private_rank_months", "monthly_income_max_krw", "real_estate_max_krw"}
    assert {r["kind"] for r in general} >= {"domestic_residence", "overseas_residence", "account_type", "account_unused_after_winning", "application_restriction"}


@pytest.mark.parametrize("row", ROWS)
def test_nomination_types_are_not_inferred_from_other_project_or_area(row):
    rule = rules(parse(row), "recommendation", "기관추천 특별공급")[0]
    assert rule["require_confirmed"] and rule["includes_reserve_nomination"]
    assert rule["evidence_page"] == SOURCE_LAYOUTS[row["document_hash"]]["nomination"]
    assert "추천 및 인정서류" in rule["evidence_text"]
    assert rule["allowed_reasons"] == (["장애인", "국가유공자·보훈"] if row is YONGIN else ["장애인", "국가유공자·보훈", "중소기업 장기근속", "장기복무 군인"])
    assert "제대군인" in rule["unsupported_reason_label"]
    assert rule["unsupported_reasons"] == (["장기복무 군인", "기타"] if row is YONGIN else ["기타"])
    # The exact Yongin table lists only disabled, national-merit and retired
    # military recommendations. A known SME/refugee category is not a missing
    # interpretation of one of those listed categories.
    assert "북한이탈주민" not in rule["allowed_reasons"] + rule["unsupported_reasons"]
    if row is YONGIN:
        assert "중소기업 장기근속" not in rule["allowed_reasons"] + rule["unsupported_reasons"]


@pytest.mark.parametrize("row", ROWS)
def test_active_bank_is_current_but_membership_and_deposit_keep_notice_date(row):
    result = parse(row)
    current = [r for r in walk(result["rules"]) if r.get("criterion_basis") == "application_date"]
    assert current and {r["kind"] for r in current} == {"account_type", "account_unused_after_winning"}
    assert all(r["criterion_date"] is None and r["evaluation_mode"] == "today_precheck" and r["requires_maintained_until_application"] for r in current)
    active = [r for r in current if r["kind"] == "account_type"]
    assert all("해지한 경우" in r["evidence_text"] and r["evidence_page"] == SOURCE_LAYOUTS[row["document_hash"]]["active"] for r in active)
    assert all("none" not in r["allowed_values"] for r in active)
    assert all(r["criterion_date"] == "2026-10-02" for r in walk(result["rules"]) if r["kind"] in {"private_rank_months", "deposit_min_krw"})
    assert not any(r["kind"] == "account_type" and r.get("criterion_basis") == "application_date" and r.get("supply_type") == "기관추천 특별공급" for r in result["rules"])
    group = next(r for r in rules(result, "all", "기관추천 특별공급") if "통장" in r.get("label", ""))
    assert any(r["kind"] == "account_type" and r["criterion_basis"] == "application_date" for r in group["conditions"])
    disability, demolition = group["exceptions"]
    assert disability["kind"] == "recommendation" and disability["allowed_reasons"] == ["장애인", "국가유공자·보훈"]
    assert disability["allowed_recommendation_reasons"] == disability["allowed_reasons"]
    assert demolition["kind"] == "unparsed" and demolition["allowed_recommendation_reasons"] == ["철거주택 소유자", "도시재생 부지제공자"]


@pytest.mark.parametrize("row", ROWS)
def test_remarriage_evidence_is_actual_newlywed_condition_not_multi_child_points(row):
    rule = rules(parse(row), "marriage_months_max", "신혼부부 특별공급")[0]
    assert rule["value"] == 84
    assert rule["evidence_page"] == (13 if row is YONGIN else 16)
    exception = rule["exceptions"][0]
    assert exception["evidence_page"] == rule["evidence_page"]
    assert "동일인과의 재혼" in exception["evidence_text"] and "이전 혼인기간을 포함" in exception["evidence_text"]
    assert not any(term in exception["evidence_text"] for term in ("배점항목", "전혼자녀", "다자녀"))


@pytest.mark.parametrize("row", ROWS)
def test_first_home_family_tax_and_financial_branches_have_separate_exact_scope(row):
    result = parse(row)
    family = rules(result, "first_home_family", "생애최초 특별공급")[0]
    assert family["unmarried_child_required"] and family["unmarried_applicant_child_same_register"]
    assert family["non_solo_requires_ascendant"] and family["solo_max_area_sqm"] == 60
    assert family["include_pregnancy"] and family["include_adoption"]
    assert family["evidence_page"] == SOURCE_LAYOUTS[row["document_hash"]]["first"]
    tax = rules(result, "first_home_tax_activity")[0]
    assert tax["tax_years_min"] == 5 and tax["recent_tax_months"] == 12 and tax["includes_tax_exemption"]
    assert "납부의무액이 없는 경우를 포함" in tax["evidence_text"]
    past = rules(result, "never_owned_home")[0]
    assert past["exclude_spouse_pre_marriage_disposed"]
    assert "혼인 전 처분한 이력은 배제합니다" in past["evidence_text"]
    assert past["exceptions"][0]["evidence_page"] == SOURCE_LAYOUTS[row["document_hash"]]["ownership"]
    for supply in ["생애최초 특별공급", "신생아 특별공급"]:
        financial = next(r for r in rules(result, "any", supply) if r.get("label") == "월평균소득 또는 부동산 기준")
        income, assets = financial["conditions"]
        assert income["income_percent"] == 160 and income["income_table"][-1]["max_krw"] == 17703710
        assert income["extra_person_base_krw"] == 579278 and income["extra_person_krw"] == 926845
        assert assets["value"] == 331000000 and assets["household_scope"] == "all_legal_household_members"
        scope = rules(result, "income_household_scope", supply)[0]
        assert scope["ascendant_same_register_min_months"] == 12 and scope["income_year"] == 2025
    newlywed = next(r for r in rules(result, "any", "신혼부부 특별공급") if r.get("label") == "월평균소득 또는 부동산 기준")
    assert newlywed["conditions"][0]["income_percent"] == 140
    assert newlywed["conditions"][0]["income_table"][0]["max_krw"] == 10547268
    assert any(r["kind"] == "unparsed" and "각각" in r["label"] for r in walk(newlywed["conditions"]))
    assert all(r["operator"] == ">" for r in walk(newlywed["conditions"][2]["conditions"][0]["conditions"]) if r["kind"] == "monthly_income_max_krw")


@pytest.mark.parametrize("row", [HYANGNAM_ORIGINAL, HYANGNAM_CORRECTED])
def test_elder_parent_and_separate_spouse_ownership_are_strict(row):
    for kind in ["parent_owns_home", "parent_spouse_owns_home"]:
        rule = rules(parse(row), kind, "노부모부양 특별공급")[0]
        assert rule["value"] is False and "배우자도 무주택자" in rule["evidence_text"]


@pytest.mark.parametrize("row", ROWS)
def test_changed_hash_incomplete_document_and_wrong_identity_do_not_borrow_review(row):
    assert not coverage(parse(row, digest="changed-file"))["일반공급"]["complete"]
    assert not coverage(parse(row, pages=row["pages"][:-1]))["일반공급"]["complete"]
    payload = copy.deepcopy(row["payload"])
    payload["announcement_date"] = "2026-10-08"
    assert parse(row, payload=payload)["identity_status"] == "mismatch"
    assert reviewed_source_for_document(row["document_url"], row["document_hash"])
    assert reviewed_source_for_document(row["document_url"], "changed-file") is None
    assert all(rule["document_hash"] == row["document_hash"] and rule["parser_version"] == PARSER_VERSION for rule in parse(row)["rules"])


def test_osans_exact_current_office_source_is_domestic_unrestricted_without_apartment_bank_or_rank():
    result = parse(OSAN)
    assert result["status"] == "complete" and coverage(result)["일반공급"]["complete"]
    region = rules(result, "applicant_regions")[0]
    assert region["unrestricted"] and region["domestic_only"] and region["priority_applicable"] is False
    assert region["evidence_page"] == 4 and "2026.10.07." in region["evidence_text"]
    assert "재외동포" in region["evidence_text"] and "외국인 포함" in region["evidence_text"]
    assert rules(result, "age_min")[0]["value"] == 19 and rules(result, "domestic_residence")[0]["value"] is True
    rank = rules(result, "rank_applicability")[0]
    assert rank["status"] == "not_applicable" and rank["account_required"] is False
    assert not rules(result, "account_type") and not rules(result, "private_rank_months")
    assert all(rule["criterion_date"] == "2026-10-07" for rule in result["rules"])
    assert reviewed_document_urls(OSAN["payload"]["official_url"], announcement_date="2026-10-07") == [OSAN["document_url"]]
    assert reviewed_document_urls(OSAN["payload"]["official_url"], announcement_date="2026-10-06") == []
    changed = parse(OSAN, digest="changed-file")
    assert changed["status"] == "unsupported" and not changed["rules"]
