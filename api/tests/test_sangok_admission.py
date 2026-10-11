"""Current Sangok admission clauses, independently checked against 70 pages."""
import copy
import json
from pathlib import Path

from app.extract.official_rules import parse_official_rules
from app.extract.generic_admission import REVIEW_VERSION

FIXTURES = Path(__file__).parent / "fixtures"
SANGOK = copy.deepcopy(next(row for row in json.loads((FIXTURES / "current-oct8-regions.json").read_text())
                            if row["external_id"] == "2026000458"))
FEED = json.loads((FIXTURES / "sangok-current-feed-inventory.json").read_text())
CURRENT_SIX_FEED = json.loads((FIXTURES / "sangok-current-six-feed.json").read_text())
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
    assert adult["evidence_page"] == 26 and adult["conditions"][0]["value"] == 19
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
    assert scopes(parse(digest="changed-file"))["일반공급"]["complete"]
    assert scopes(parse(pages=SANGOK["pages"][:-1]))["일반공급"]["complete"]
    for page_number, phrase in [(3, "해외체류기간"), (5, "재당첨 제한을 적용받지"), (12, "250만원"), (19, "만65세"), (24, "2세 미만"), (24, "무주택세대구성원")]:
        pages = copy.deepcopy(SANGOK["pages"])
        page = next(page for page in pages if page["page"] == page_number)
        assert phrase in page["text"]
        page["text"] = page["text"].replace(phrase, "미확보")
        affected = "노부모부양 특별공급" if page_number == 19 else "신생아 특별공급" if page_number == 24 else "일반공급"
        assert not scopes(parse(pages=pages))[affected]["complete"]
        if affected != "일반공급":
            assert scopes(parse(pages=pages))["일반공급"]["complete"]
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


def six_column_payload():
    payload = copy.deepcopy(SANGOK["payload"])
    supplied = CURRENT_SIX_FEED["supplies"]
    payload["rules"] = [
        {"kind": "offered_supplies", "effect": "metadata", "source": "cheongyak_home", "verification": "official",
         "evidence_url": CURRENT_SIX_FEED["official_url"], "supplies": copy.deepcopy(supplied)},
        # The public detail carried a previous parser copy twice. The original
        # known API cells remain authoritative once the counts match the PDF.
        {"kind": "offered_supplies", "effect": "metadata", "source": "official_document_parser", "verification": "official",
         "inventory_status": "verified", "document_hash": SANGOK["document_hash"], "supplies": copy.deepcopy(supplied * 2)},
    ]
    return payload


def test_actual_current_six_column_feed_restores_missing_newborn_rows_from_pdf():
    assert len(CURRENT_SIX_FEED["supplies"]) == 53
    assert sum(row["supply_count"] for row in CURRENT_SIX_FEED["supplies"]) == 1163
    assert not any(row["supply_type"] == "신생아 특별공급" for row in CURRENT_SIX_FEED["supplies"])
    result = parse(payload=six_column_payload())
    inventory = of_kind(result, "offered_supplies")
    assert len(inventory) == 1 and inventory[0]["inventory_status"] == "verified"
    stock = inventory[0]["supplies"]
    assert len(stock) == 62 and sum(row["supply_count"] for row in stock) == 1289
    actual = {(row["supply_type"], row["unit_type"]): row for row in stock}
    for row in CURRENT_SIX_FEED["supplies"]:
        assert actual[row["supply_type"], row["unit_type"]] == row
    newborn = [row for row in stock if row["supply_type"] == "신생아 특별공급"]
    assert len(newborn) == 9 and sum(row["supply_count"] for row in newborn) == 126
    assert all(row["source"] == "official_document_parser" and row["evidence_page"] == 6
               and row["document_hash"] == SANGOK["document_hash"] and row["criterion_date"] == "2026-10-08" for row in newborn)
    coverage = scopes(result)
    assert len(coverage) == 7 and coverage["일반공급"]["complete"] and coverage["신생아 특별공급"]["complete"]
    assert all(scope["review_version"] == REVIEW_VERSION for scope in coverage.values())
    assert of_kind(result, "homeless", "신생아 특별공급")[0]["value"] is True
    child = of_kind(result, "newborn_children_min", "신생아 특별공급")[0]
    assert child["evidence_page"] == 24 and child["child_age_inclusive"] and child["include_pregnancy"] and child["include_adoption"]
    assert of_kind(result, "special_winning", "신생아 특별공급")
    assert of_kind(result, "private_rank_months", "신생아 특별공급")[0]["value"] == 12
    assert of_kind(result, "income_household_scope", "신생아 특별공급")[0]["evidence_page"] == 25


def test_conflicting_known_api_cell_does_not_receive_complete_admission_or_pdf_overwrite():
    payload = six_column_payload()
    payload["rules"][0]["supplies"][0]["supply_count"] += 1
    result = parse(payload=payload)
    assert not scopes(result)["일반공급"]["complete"]
    assert not any(rule.get("inventory_status") == "verified" for rule in of_kind(result, "offered_supplies"))
    assert of_kind(result, "newborn_children_min", "신생아 특별공급")
    assert not scopes(result)["신생아 특별공급"]["complete"]


def test_changed_pdf_table_totals_or_column_order_cannot_supply_missing_allocations():
    for old, replacement in [("112 11 10 16 3 7 11 58 54 4", "112 11 10 16 3 7 10 58 54 4"),
                             ("1,289 126 122 190 35 86 126 685 604 88", "1,288 126 122 190 35 86 126 685 604 88"),
                             ("기관 다자녀 신혼 노부모 생애 신생아 계", "기관 신생아 신혼 노부모 생애 다자녀 계")]:
        pages = copy.deepcopy(SANGOK["pages"])
        page = next(page for page in pages if page["page"] == 6)
        assert old in page["text"]
        page["text"] = page["text"].replace(old, replacement)
        result = parse(pages=pages, payload=six_column_payload())
        assert not scopes(result)["일반공급"]["complete"]
        assert not any(rule.get("inventory_status") == "verified" for rule in of_kind(result, "offered_supplies"))
