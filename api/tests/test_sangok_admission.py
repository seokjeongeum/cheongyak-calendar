"""Current Sangok admission clauses, independently checked against 70 pages."""
import copy
import json
from pathlib import Path

from app.extract.official_rules import parse_official_rules
from app.extract.sangok_admission import REVIEW_VERSION

FIXTURES = Path(__file__).parent / "fixtures"
SANGOK = copy.deepcopy(next(row for row in json.loads((FIXTURES / "current-oct8-regions.json").read_text())
                            if row["external_id"] == "2026000458"))
FEED = json.loads((FIXTURES / "sangok-current-feed-inventory.json").read_text())
SANGOK["payload"]["rules"] = [{"kind": "offered_supplies", "effect": "metadata", "source": "cheongyak_home",
                                "verification": "official", "evidence_url": FEED["official_url"], "supplies": FEED["supplies"]}]


def parse(**overrides):
    return parse_official_rules(overrides.get("pages", SANGOK["pages"]), url=overrides.get("url", SANGOK["document_url"]),
                                digest=overrides.get("digest", SANGOK["document_hash"]), payload=overrides.get("payload", SANGOK["payload"]))


def of_kind(result, kind, supply=None):
    return [rule for rule in result["rules"] if rule["kind"] == kind and (supply is None or rule.get("supply_type") == supply)]


def walk(items):
    for rule in items:
        yield rule
        yield from walk(rule.get("conditions", []))


def scopes(result):
    return {scope["supply_type"]: scope for scope in of_kind(result, "condition_coverage")[0]["scopes"]}


def test_sangok_standard_paths_have_actual_source_bound_coverage_and_conditional_gaps():
    result = parse()
    coverage = scopes(result)
    assert len(coverage) == 7
    for supply, scope in coverage.items():
        assert scope["review_version"] == REVIEW_VERSION
        assert scope["reviewed_pages"] == list(range(1, 71))
        assert scope["complete"] is (supply != "신혼부부 특별공급")
        assert scope["missing_topics"] == (["동일 배우자와 재혼한 경우 이전 혼인기간 합산"] if supply == "신혼부부 특별공급" else [])
        assert all(topic["required"] is False for topic in scope["topics"] if topic.get("phase") == "conditional_admission")
        assert not any(topic in {"재당첨·청약 제한 및 법령 예외", "소득·자산 분기", "신청 제한·연령 예외의 전체 검토"} for topic in scope["missing_topics"])
    general = [rule for rule in result["rules"] if rule.get("effect") != "metadata" and rule.get("purpose") != "first_rank" and rule.get("supply_type") in {None, "일반공급"}]
    assert {rule["kind"] for rule in general} >= {"any", "domestic_residence", "overseas_residence", "application_restriction", "account_type", "account_unused_after_winning"}
    assert not ({"homeless", "household_head", "special_winning", "monthly_income_max_krw", "real_estate_max_krw"} & {rule["kind"] for rule in general})
    assert all(rule["document_hash"] == SANGOK["document_hash"] for rule in result["rules"])
    exempt = {topic["topic"]: topic for topic in coverage["일반공급"]["topics"] if topic["status"] == "not_applicable"}
    assert exempt["무주택 세대구성원"]["evidence_page"] == 5 and "1주택 이상 소유하신 분도" in exempt["무주택 세대구성원"]["evidence_text"]
    assert exempt["세대주"]["evidence_page"] == 1 and exempt["세대주"]["evidence_text"] == "세대주 요건 - - - 필요 - - - -"
    assert exempt["특별공급 횟수 제한"]["evidence_page"] == 11 and exempt["특별공급 횟수 제한"]["evidence_text"].startswith("특별공급은 무주택세대구성원에게 한 차례")


def test_sangok_cutoff_bank_restrictions_and_overseas_are_not_borrowed_from_october_two():
    result = parse()
    active = [rule for rule in walk(result["rules"]) if rule.get("criterion_basis") == "application_date"]
    assert active and all(rule["original_announcement_date"] == "2026-10-08" and rule["criterion_date"] is None for rule in active)
    assert all(rule["evaluation_mode"] == "today_precheck" and rule["requires_maintained_until_application"] for rule in active)
    assert all(rule["criterion_date"] == "2026-10-08" for rule in walk(result["rules"]) if rule["kind"] in {"private_rank_months", "deposit_min_krw"})
    restrictions = of_kind(result, "application_restriction")
    assert {rule["restriction"] for rule in restrictions} == {"ineligible_restriction_active", "resale_restriction_active"}
    assert {rule["evidence_page"] for rule in restrictions} == {4}
    assert next(rule for rule in restrictions if rule["restriction"] == "ineligible_restriction_active")["restriction_months"] == 12
    overseas = of_kind(result, "overseas_residence")[0]
    assert overseas["max_continuous_days"] == 90 and overseas["evidence_page"] == 3
    assert overseas["currently_abroad_only"] and overseas["reentry_same_country"] and overseas["reentry_within_days"] == 7
    assert overseas["livelihood_exception_requires_family"] and "생업에 직접 종사" in overseas["evidence_text"]
    adult = next(rule for rule in of_kind(result, "any") if rule.get("label") == "성년 또는 공고의 미성년 세대주")
    assert adult["evidence_page"] == 5 and adult["conditions"][0]["value"] == 19
    assert adult["conditions"][1]["conditions"][1]["kind"] == "unparsed"


def test_sangok_financial_family_tax_parent_and_nomination_facts_are_explicit():
    result = parse()
    institution = of_kind(result, "recommendation", "기관추천 특별공급")[0]
    assert institution["includes_reserve_nomination"] and institution["require_confirmed"]
    assert institution["evidence_page"] == 13
    assert institution["allowed_reasons"] == ["장애인", "국가유공자·보훈", "중소기업 장기근속", "장기복무 군인"]
    assert "장기복무 제대군인" in institution["unsupported_reason_evidence_text"]
    assert "제대군인" not in institution["unsupported_reason_label"]
    for supply, months in [("다자녀가구 특별공급", 6), ("신혼부부 특별공급", 6), ("노부모부양 특별공급", 12), ("생애최초 특별공급", 12), ("신생아 특별공급", 12)]:
        assert of_kind(result, "private_rank_months", supply)[0]["value"] == months
        deposit = of_kind(result, "deposit_min_krw", supply)[0]
        assert deposit["evidence_page"] == 12
        assert deposit["deposit_table"][0]["amounts_krw"] == {"seoul_busan": 3000000, "other_metropolitan": 2500000, "other": 2000000}
    family = of_kind(result, "first_home_family")[0]
    assert family["solo_max_area_sqm"] == 60 and family["non_solo_requires_ascendant"]
    assert family["unmarried_applicant_child_same_register"] and family["evidence_page"] == 21
    tax = of_kind(result, "first_home_tax_activity")[0]
    assert tax["tax_years_min"] == 5 and tax["recent_tax_months"] == 12 and tax["includes_tax_exemption"]
    assert tax["evidence_page"] == 21 and "납부 의무액이 없는 경우" in tax["evidence_text"]
    past = of_kind(result, "never_owned_home")[0]
    assert past["exclude_spouse_pre_marriage_disposed"] and past["exceptions"][0]["evidence_page"] == 40
    for kind in ["parent_owns_home", "parent_spouse_owns_home"]:
        rule = of_kind(result, kind, "노부모부양 특별공급")[0]
        assert rule["value"] is False and rule["evidence_page"] == 19
    for supply, income_page, asset_page in [("생애최초 특별공급", 22, 23), ("신생아 특별공급", 24, 25)]:
        group = next(rule for rule in of_kind(result, "any", supply) if rule.get("label") == "월평균소득 또는 부동산 기준")
        income, assets = group["conditions"]
        assert income["income_percent"] == 160 and income["income_table"][0]["max_krw"] == 12054021 and income["evidence_page"] == income_page
        assert assets["value"] == 331000000 and assets["evidence_page"] == asset_page
    dual = next(rule for rule in walk(result["rules"]) if rule["kind"] == "unparsed" and "140%" in rule.get("label", ""))
    assert dual["label"] == "부부 중 1인의 140% 소득 상한" and "각각" not in dual["text"]
    assert dual["evidence_page"] == 16 and "부부 중 1인의 소득" in dual["evidence_text"]


def test_sangok_changed_identity_or_missing_compulsory_clause_is_not_certified():
    assert not scopes(parse(digest="changed-file"))["일반공급"]["complete"]
    assert not scopes(parse(pages=SANGOK["pages"][:-1]))["일반공급"]["complete"]
    for page_number, phrase in [(3, "해외체류기간"), (5, "재당첨 제한을 적용받지"), (12, "250만원"), (19, "만65세"), (24, "2세 미만")]:
        pages = copy.deepcopy(SANGOK["pages"])
        page = next(page for page in pages if page["page"] == page_number)
        assert phrase in page["text"]
        page["text"] = page["text"].replace(phrase, "미확보")
        assert not scopes(parse(pages=pages))["일반공급"]["complete"]
    payload = {**SANGOK["payload"], "announcement_date": "2026-10-02"}
    assert parse(payload=payload)["identity_status"] == "mismatch"


def test_sangok_document_stock_and_instructions_remain_separate_from_eligibility():
    result = parse()
    stock = of_kind(result, "offered_supplies")[0]["supplies"]
    assert sum(item["supply_count"] for item in stock) == 1289
    assert sum(item["supply_count"] for item in stock if item["supply_type"] == "일반공급") == 604
    assert not any(item["supply_type"] == "노부모부양 특별공급" and item["unit_type"] == "084.9200A" for item in stock)
    instructions = of_kind(result, "application_instructions")[0]
    assert instructions["effect"] == "metadata"
    assert {item["phase"] for item in instructions["instructions"]} == {"application", "post_selection"}
    assert all(item["document_hash"] == SANGOK["document_hash"] for item in instructions["instructions"])
