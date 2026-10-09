"""The exact Hangang source's admission requirements and real exemptions."""
import copy
import json
from pathlib import Path

import pytest

from app.extract.hangang_admission import HANGANG_HASH
from app.extract.official_rules import PARSER_VERSION, parse_official_rules, parser_version_usable
from app.qualification import requirements_complete

ROWS = json.loads((Path(__file__).parent / "fixtures/current-private-v5.json").read_text())
SOURCE = next(row for row in ROWS if row["external_id"] == "2026000468")


def parse(row=SOURCE, **overrides):
    return parse_official_rules(overrides.get("pages", row["pages"]), url=overrides.get("url", row["document_url"]),
                                digest=overrides.get("digest", row["document_hash"]), payload=overrides.get("payload", row["payload"]))


def of_kind(result, kind, supply=None):
    return [r for r in result["rules"] if r["kind"] == kind and (supply is None or r.get("supply_type") == supply)]


def scopes(result):
    return {scope["supply_type"]: scope for scope in of_kind(result, "condition_coverage")[0]["scopes"]}


def walk(rules):
    for rule in rules:
        yield rule
        yield from walk(rule.get("conditions", []))


def test_general_admission_is_complete_without_inheriting_special_or_first_rank_requirements():
    result = parse()
    general = scopes(result)["일반공급"]
    assert general["complete"] and not general["missing_topics"]
    assert general["reviewed_pages"] == list(range(1, 63))
    rules = [r for r in result["rules"] if r.get("effect") != "metadata" and r.get("purpose") != "first_rank"
             and r.get("supply_type") in {None, "일반공급"}]
    kinds = {r["kind"] for r in rules}
    assert {"domestic_residence", "overseas_residence", "application_restriction", "account_type", "account_unused_after_winning"} <= kinds
    assert not kinds & {"homeless", "special_winning", "household_head", "private_rank_months", "monthly_income_max_krw", "real_estate_max_krw"}
    assert not any(r.get("restriction") == "rewinning_restriction_active" for r in rules)
    account = next(r for r in rules if r["kind"] == "account_type")
    assert account["evidence_page"] == 21 and "2순위" in account["evidence_text"]
    assert account["allowed_values"] == ["comprehensive", "deposit", "installment"]
    current_use = of_kind(result, "account_unused_after_winning", "일반공급")[0]
    assert current_use["criterion_basis"] == "application_date" and current_use["criterion_date"] is None
    assert current_use["evaluation_mode"] == "today_precheck" and current_use["requires_maintained_until_application"]
    assert not requirements_complete(result["rules"], True)  # Other supply branches remain incomplete.


def test_current_restrictions_and_overseas_fact_have_exact_scope_and_boundaries():
    result = parse()
    restricted = of_kind(result, "application_restriction")
    assert {(r["restriction"], r["scope"], r["value"]) for r in restricted} == {
        ("resale_restriction_active", "applicant", False), ("ineligible_restriction_active", "applicant", False)}
    assert all(r["evidence_page"] == 3 for r in restricted)
    abroad = of_kind(result, "overseas_residence")[0]
    assert abroad["max_continuous_days"] == 90 and abroad["currently_abroad_only"]
    assert abroad["reentry_same_country"] and abroad["reentry_within_days"] == 7
    assert abroad["livelihood_exception"] and abroad["livelihood_exception_requires_family"]
    assert "기타지역 거주자로도 인정되지 않습니다" in abroad["evidence_text"]


@pytest.mark.parametrize("supply", ["일반공급", "기관추천 특별공급", "다자녀가구 특별공급", "노부모부양 특별공급"])
def test_income_and_asset_exemptions_are_not_reported_as_missing(supply):
    scope = scopes(parse())[supply]
    topics = {r["topic"]: r for r in scope["topics"]}
    assert topics["소득 기준"]["status"] == topics["자산 기준"]["status"] == "not_applicable"
    assert not topics["소득 기준"]["required"] and topics["소득 기준"]["evidence_page"] == 1
    assert not any("소득" in topic or "자산" in topic for topic in scope["missing_topics"])


def test_specials_have_korean_citizenship_scoped_accounts_and_parent_ownership_without_birth_misapplication():
    result = parse()
    assert len(of_kind(result, "citizenship")) == 6
    assert all(r["allowed_values"] == ["korean"] and r["evidence_page"] == 12 for r in of_kind(result, "citizenship"))
    for supply in ["기관추천 특별공급", "생애최초 특별공급"]:
        assert not of_kind(result, "homeless", supply)[0].get("exceptions")
    for kind in ["parent_owns_home", "parent_spouse_owns_home"]:
        rule = of_kind(result, kind, "노부모부양 특별공급")[0]
        assert rule["value"] is False and rule["evidence_page"] == 16
    institution = next(r for r in of_kind(result, "all", "기관추천 특별공급") if "통장" in r.get("label", ""))
    assert institution.get("exceptions") and "면제" in institution["exceptions"][0]["label"]
    assert scopes(result)["기관추천 특별공급"]["complete"]


@pytest.mark.parametrize("supply,income_page,asset_page", [("생애최초 특별공급", 18, 19), ("신생아 특별공급", 20, 21)])
def test_income_or_real_estate_branch_preserves_official_table_and_distinct_family_scopes(supply, income_page, asset_page):
    group = next(r for r in of_kind(parse(), "any", supply) if r.get("label") == "월평균소득 또는 부동산 기준")
    income, assets = group["conditions"]
    assert income["income_table"][0] == {"household_size": 3, "max_krw": 12054021}
    assert income["income_table"][-1] == {"household_size": 8, "max_krw": 17703710}
    assert income["min_household_size"] == 3 and income["evidence_page"] == income_page
    assert assets["value"] == 331000000 and assets["evidence_page"] == asset_page
    assert assets["household_scope"] == "all_legal_household_members"
    assert any("국민기초생활" in r["label"] for r in group["exceptions"])


def test_first_home_review_keeps_strict_family_and_tax_waivers_and_newlywed_unreviewed_scenarios():
    result = parse()
    family = of_kind(result, "first_home_family")[0]
    assert family["include_pregnancy"] and family["include_adoption"]
    assert family["unmarried_child_required"] and family["unmarried_applicant_child_same_register"]
    assert family["non_solo_requires_ascendant"] and family["solo_max_area_sqm"] == 60
    tax = of_kind(result, "first_home_tax_activity")[0]
    assert tax["tax_years_min"] == 5 and tax["recent_tax_months"] == 12 and tax["includes_tax_exemption"]
    assert tax["tax_years_basis"] == "separate_calendar_years_not_60_months"
    past_ownership = of_kind(result, "never_owned_home")[0]
    assert past_ownership["exclude_spouse_pre_marriage_disposed"]
    assert past_ownership["exceptions"][0]["evidence_page"] == 38
    assert "제53조" in past_ownership["exceptions"][0]["label"]
    newlywed = next(r for r in of_kind(result, "any", "신혼부부 특별공급") if r.get("label") == "월평균소득 또는 부동산 기준")
    assert newlywed["conditions"][0]["income_table"][0]["max_krw"] == 10547268 and newlywed["exceptions"]
    lottery = newlywed["conditions"][2]
    assert lottery["conditions"][1]["value"] == 331000000
    assert {r["operator"] for r in walk(lottery["conditions"][0]["conditions"]) if r["kind"] == "monthly_income_max_krw"} == {">"}
    assert not scopes(result)["신혼부부 특별공급"]["complete"]
    assert scopes(result)["신혼부부 특별공급"]["missing_topics"] == ["동일 배우자와 재혼한 경우 이전 혼인기간 합산"]


@pytest.mark.parametrize("supply", ["기관추천 특별공급", "다자녀가구 특별공급", "노부모부양 특별공급", "생애최초 특별공급", "신생아 특별공급"])
def test_standard_special_paths_do_not_require_unused_waiver_branches(supply):
    scope = scopes(parse())[supply]
    assert scope["complete"] and scope["missing_topics"] == []
    assert scope["completion_basis"] == "document_hash_reviewed_standard_branch"
    conditional = [topic for topic in scope["topics"] if topic.get("phase") == "conditional_admission"]
    assert conditional and all(topic["status"] == "partial" and not topic["required"] for topic in conditional)
    assert all("미혼 자녀의 혼인" not in topic["topic"] for topic in scope["topics"])
    # Scope completion certifies the supported ordinary path. Activation of
    # an unparsed alternative still produces review in the browser evaluator.
    assert scope["unresolved_branches"]


@pytest.mark.parametrize("percent,expected_nine,expected_thirteen", [(140, 16301736, 19545693), (160, 18630555, 22337934)])
def test_nine_plus_income_scales_official_base_before_rounding(percent, expected_nine, expected_thirteen):
    rule = next(r for r in walk(parse()["rules"]) if r["kind"] == "monthly_income_max_krw" and r.get("income_percent") == percent)
    assert rule["extra_person_base_krw"] == 579278
    assert rule["extra_person_income_base_last_krw"] == 11064819
    # The PDF's added-person amount belongs to the 100% base. Applying it
    # directly to an already expanded threshold would undercount a 9th person.
    def threshold(size):
        return round((rule["extra_person_income_base_last_krw"] + (size - 8) * rule["extra_person_base_krw"]) * percent / 100)
    assert threshold(9) == expected_nine and threshold(13) == expected_thirteen


def test_exact_hash_complete_page_set_and_original_identity_are_required_for_review():
    assert SOURCE["document_hash"] == HANGANG_HASH
    assert not scopes(parse(digest="changed-document"))["일반공급"]["complete"]
    assert not scopes(parse(pages=[page for page in SOURCE["pages"] if page["page"] != 62]))["일반공급"]["complete"]
    payload = copy.deepcopy(SOURCE["payload"])
    payload["announcement_date"] = "2026-10-08"
    assert parse(payload=payload)["identity_status"] == "mismatch"
    assert parse(url=SOURCE["document_url"].replace("2026000468", "2026000463"))["identity_status"] == "mismatch"
    for rule in parse()["rules"]:
        assert rule["document_hash"] == HANGANG_HASH
        assert rule["criterion_date"] == (None if rule["kind"] == "account_unused_after_winning" else "2026-10-02")
        assert rule["parser_version"] == PARSER_VERSION


def test_procedure_guidance_and_compatible_previous_parser_facts_remain_available():
    instructions = of_kind(parse(), "application_instructions")[0]
    assert instructions["effect"] == "metadata"
    assert {r["phase"] for r in instructions["instructions"]} == {"application", "post_selection"}
    assert all("서류" not in topic for scope in scopes(parse()).values() for topic in scope["missing_topics"])
    assert parser_version_usable({"source": "official_document_parser", "parser_version": "official-sections-2026-10-07-v9"})
