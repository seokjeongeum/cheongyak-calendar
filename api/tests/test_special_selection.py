"""Official Hangang sections and adversarial scope boundaries for selection."""
import copy
import json
from pathlib import Path

from app.extract.official_rules import PARSER_VERSION, parse_official_rules, parser_version_usable
from app.extract.reprocess import _document_patch
from app.extract.selection_rules import parse_selection_rules


FIXTURE = next(row for row in json.loads((Path(__file__).parent / "fixtures/current-private-v5.json").read_text())
               if row["external_id"] == "2026000468")


def hangang():
    return parse_official_rules(FIXTURE["pages"], url=FIXTURE["document_url"],
                                digest=FIXTURE["document_hash"], payload=FIXTURE["payload"])


def test_hangang_special_selection_uses_exact_official_pages_and_positive_stock():
    result = hangang()
    allocations = {r["supply_type"]: r for r in result["rules"] if r["kind"] == "regional_allocation"}
    expected = {"기관추천 특별공급": 13, "다자녀가구 특별공급": 13,
                "신혼부부 특별공급": 15, "노부모부양 특별공급": 16,
                "생애최초 특별공급": 18, "신생아 특별공급": 20}
    assert set(allocations) == {"일반공급", *expected}
    stock = next(r["supplies"] for r in result["rules"] if r["kind"] == "offered_supplies")
    for supply, page in expected.items():
        allocation = allocations[supply]
        assert allocation["evidence_page"] == page
        assert allocation["document_hash"] == FIXTURE["document_hash"]
        assert allocation["evidence_url"] == FIXTURE["document_url"]
        assert allocation["parser_version"] == PARSER_VERSION
        assert allocation["criterion_date"] == "2026-10-02"
        assert set(allocation["unit_types"]) == {row["unit_type"] for row in stock
                                                if row["supply_type"] == supply and row["supply_count"] > 0}
        assert "146.8598P" not in allocation["unit_types"]
    assert "123.7781" in allocations["다자녀가구 특별공급"]["unit_types"]
    assert "123.7781" in allocations["노부모부양 특별공급"]["unit_types"]
    assert "123.7781" not in allocations["신생아 특별공급"]["unit_types"]
    # The October 2026 document genuinely offers this category; older rules must
    # not silently remove the official 29 dwellings.
    assert sum(row["supply_count"] for row in stock if row["supply_type"] == "신생아 특별공급") == 29


def test_hangang_multi_child_quota_is_provincial_and_keeps_second_stage_reentry():
    rules = hangang()["rules"]
    quota = next(r for r in rules if r["kind"] == "regional_allocation" and r["supply_type"] == "다자녀가구 특별공급")
    assert quota["allocation_method"] == "regional_quota"
    assert quota["local_share_percent"] is None
    assert [(r["residence_area"], r["percent"], r["region_codes"]) for r in quota["regional_shares"]] == [
        ("local_and_other_gyeonggi", 50, ["41"]), ("other", 50, ["11", "28"])]
    assert quota["local_region"]["region_code"] == "41830"
    assert quota["local_priority_within_first_quota"] is True
    assert quota["unsuccessful_applicants_advance"] is True
    assert quota["local_priority_in_remaining_quota"] is False
    assert "우선공급 요건은 적용되지 않습니다" in quota["remaining_quota_evidence_text"]
    region = next(r for r in rules if r["kind"] == "applicant_regions" and r.get("supply_type") == "다자녀가구 특별공급")
    assert region["other_gyeonggi"] == {"region_code": "41", "region_name": "경기도"}
    assert {r["region_code"] for r in region["regions"]} == {"11", "28", "41"}


def test_hangang_income_percentages_do_not_become_regional_quotas():
    allocations = {r["supply_type"]: r for r in hangang()["rules"] if r["kind"] == "regional_allocation"}
    orders = {"신혼부부 특별공급": ["소득구분", "순위", "지역", "미성년 자녀수", "추첨"],
              "노부모부양 특별공급": ["지역", "가점", "청약통장 가입기간", "추첨"],
              "생애최초 특별공급": ["소득구분", "지역", "추첨"],
              "신생아 특별공급": ["소득구분", "지역", "추첨"]}
    for supply, order in orders.items():
        assert allocations[supply]["allocation_method"] == "region_priority"
        assert allocations[supply]["local_share_percent"] is None
        assert "regional_shares" not in allocations[supply]
        assert allocations[supply]["selection_order"] == order
        assert "양평군" in allocations[supply]["evidence_text"]
    institution = allocations["기관추천 특별공급"]
    assert institution["allocation_method"] == "institution_recommendation"
    assert "기관의 장이 정하는 우선순위" in institution["evidence_text"]
    assert "확정대상자 및 예비대상자" in institution["recommendation_evidence_text"]
    exception = allocations["신혼부부 특별공급"]["selection_stage_exceptions"][0]
    assert exception["stage_number"] == 3 and exception["rank_applies"] is False
    assert exception["selection_order"] == ["지역", "추첨"]
    assert exception["evidence_page"] == 15
    assert "순위와 관계없이" in exception["evidence_text"]
    for supply in ["신혼부부 특별공급", "생애최초 특별공급", "신생아 특별공급"]:
        assert allocations[supply]["income_stage_unsuccessful_applicants_advance"] is True
    assert "selection_stage_exceptions" not in allocations["생애최초 특별공급"]
    assert "selection_stage_exceptions" not in allocations["신생아 특별공급"]


def selection(pages, extra_rules=None):
    rules = [{"kind": "housing_classification", "verification": "official", "housing_kind": "private", "criterion_date": "2026-10-02"},
             {"kind": "offered_supplies", "verification": "official", "supplies": [
                 {"unit_type": unit, "supply_type": supply, "supply_count": 2}
                 for unit, supply in [("84A", "일반공급"), ("84B", "신혼부부 특별공급"), ("84C", "생애최초 특별공급")]]}]
    return parse_selection_rules(pages, url="https://official.example/notice.pdf", digest="document",
                                 rules=rules + (extra_rules or []), parser_version="test")


def test_special_region_order_cannot_be_borrowed_for_general_supply():
    text = "1. 신혼부부 특별공급\n대상자 입주자모집공고일 현재 무주택세대구성원\n■ ③지역 : 해당지역 거주자(양평군 거주자) → 기타지역 거주자(경기도 및 서울특별시, 인천광역시 거주자)\n2. 일반공급\n대상자 입주자모집공고일 현재 성년인 분"
    allocations = [r for r in selection([{"page": 1, "text": text}]) if r["kind"] == "regional_allocation"]
    assert [r["supply_type"] for r in allocations] == ["신혼부부 특별공급"]
    # A supplied special allocation also cannot suppress a genuine general
    # order that appears on a later page of the same document.
    general = "2. 일반공급\n대상자 입주자모집공고일 현재 성년인 분\n■ ①지역 : 해당지역 거주자(양평군 거주자) → 기타지역 거주자(경기도 및 서울특별시, 인천광역시 거주자)"
    old_special = {"kind": "regional_allocation", "supply_type": "신혼부부 특별공급", "verification": "official"}
    allocations = [r for r in selection([{"page": 2, "text": general}], [old_special]) if r["kind"] == "regional_allocation"]
    assert [r["supply_type"] for r in allocations] == ["일반공급"]


def test_generic_quota_table_requires_a_known_supply_scope():
    table = "우선공급 단계별 지역우선 공급기준 지역구분 우선공급 비율 해당지역 50% 기타지역 50% ※ 다음 안내"
    text = "1. 신혼부부 특별공급\n대상자 입주자모집공고일 현재 무주택세대구성원\n" + table + "\n2. 생애최초 특별공급\n대상자 입주자모집공고일 현재 무주택세대구성원"
    quota = next(r for r in selection([{"page": 1, "text": text}]) if r["kind"] == "regional_allocation")
    assert quota["supply_types"] == ["신혼부부 특별공급"]
    assert quota["unit_types"] == ["84B"]
    assert selection([{"page": 1, "text": table}]) == []


def test_multi_child_municipality_label_cannot_be_widened_to_province_quota():
    rules = [{"kind": "housing_classification", "verification": "official", "housing_kind": "private", "criterion_date": "2026-10-02"},
             {"kind": "offered_supplies", "verification": "official", "supplies": [
                 {"unit_type": "84A", "supply_type": "다자녀가구 특별공급", "supply_count": 2}]}]
    text = "1. 다자녀가구 특별공급\n대상자 입주자모집공고일 현재 무주택세대구성원\n■ ①지역 : 해당시·도 거주자 50%(경기도 양평군 거주자) → 기타지역 거주자 50%(서울특별시 및 인천광역시 거주자)"
    assert parse_selection_rules([{"page": 1, "text": text}], url="https://official.example/notice.pdf", digest="document",
                                 rules=rules, parser_version="test") == []


def test_v7_admission_facts_survive_until_current_reprocessing_replaces_metadata():
    parsed = hangang()
    old_rules = copy.deepcopy(parsed["rules"])
    for rule in old_rules:
        rule["parser_version"] = "official-sections-2026-10-05-v7"
    current = {**FIXTURE["payload"], "source": "cheongyak_home", "external_id": FIXTURE["external_id"],
               "document_hash": FIXTURE["document_hash"], "rules": old_rules}
    assert parser_version_usable(next(r for r in old_rules if r.get("effect") != "metadata"), category="apt")
    patch = _document_patch(current, {**parsed, "document_hash": FIXTURE["document_hash"]})
    assert all(r["parser_version"] == PARSER_VERSION for r in patch["rules"] if r.get("source") == "official_document_parser")
    assert len([r for r in patch["rules"] if r["kind"] == "regional_allocation"]) == 7
