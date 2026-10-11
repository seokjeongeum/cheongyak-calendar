"""Applicant scope comes from current clauses, independent of printed order."""
import copy
import json
from pathlib import Path

import pytest

from app.extract.application_regions import explicit_applicant_regions, region_catalog
from app.extract.official_rules import PARSER_VERSION, parse_official_rules, parser_version_usable


SOURCE = json.loads((Path(__file__).parent / "fixtures/official-unranked-capital-route.json").read_text())


def parse(source=None, **changes):
    source = copy.deepcopy(source or SOURCE)
    payload = {"title": source["title"], "category": "unsold", "announcement_date": source["announcement_date"],
               "official_url": "https://www.applyhome.co.kr/ai/aia/selectAPTRemndrLttotPblancDetailView.do?houseManageNo=" + source["house_manage_no"]}
    return parse_official_rules(source["pages"], url=source["document_url"], digest=source["document_hash"],
                                payload={**payload, **changes})


def common_regions(result):
    return [rule for rule in result["rules"] if rule["kind"] == "applicant_regions" and not rule.get("supply_type")]


def test_current_capital_applicant_scope_and_ownership_use_the_operative_table():
    result = parse()
    region, = common_regions(result)
    assert [row["region_code"] for row in region["regions"]] == ["11", "28", "41"]
    assert region["evidence_page"] == 8 and region["criterion_date"] == "2026-10-06"
    assert region["document_hash"] == SOURCE["document_hash"] and region["parser_version"] == PARSER_VERSION
    assert region["priority_applicable"] is False
    selection = region["regional_selection_evidence"]
    assert selection["evidence_page"] == 8 and selection["document_hash"] == SOURCE["document_hash"]
    assert "주택형별 무작위 추첨" in selection["evidence_text"]
    home = next(rule for rule in result["rules"] if rule["kind"] == "homeless")
    assert home["value"] is True and home["evidence_page"] == 8
    assert not any("거주지역" in topic for rule in result["rules"] if rule["kind"] == "condition_coverage"
                   for scope in rule["scopes"] for topic in scope["missing_topics"])


def test_identical_or_scopes_deduplicate_despite_order_and_pdf_name_wraps():
    pages = [{"page": 2, "text": "입주자모집공고일 현재 서울특별시, 인천광역시, 경기도에 거주하는 무주택세대구성원"},
             {"page": 9, "text": "입주자모집공고일 현재 경 기 도, 서울특별시, 인 천 광 역 시에 거주하는 무주택세대구성원"}]
    make = lambda kind, **fields: {"kind": kind, **fields}
    provinces = {row["name"]: row["code"] for row in region_catalog()["provinces"]}
    region, = explicit_applicant_regions(pages, cutoff="2027-04-12", make=make, provinces=provinces)
    assert [row["region_code"] for row in region["regions"]] == ["11", "28", "41"]


def test_new_identity_date_hash_and_moved_table_need_no_notice_registry():
    source = copy.deepcopy(SOURCE)
    for page in source["pages"]:
        page["text"] = (page["text"].replace(source["title"], "새 공동주택")
                        .replace("2026.10.06", "2027.04.12").replace(source["house_manage_no"], "2027999123"))
        page["page"] += 11
    source.update(title="새 공동주택", announcement_date="2027-04-12", house_manage_no="2027999123",
                  document_hash="different-current-source",
                  document_url=source["document_url"].replace("2026910256", "2027999123"))
    region, = common_regions(parse(source))
    assert region["evidence_page"] == 19 and region["criterion_date"] == "2027-04-12"
    assert region["document_hash"] == "different-current-source" and region["priority_applicable"] is False


def test_a_genuinely_conflicting_current_region_stays_unresolved():
    source = copy.deepcopy(SOURCE)
    source["pages"][-1]["text"] = source["pages"][-1]["text"].replace(
        "수도권(경기도,   서울특별시,   인천광역시)", "대전광역시")
    result = parse(source)
    assert {tuple(row["region_code"] for row in region["regions"]) for region in common_regions(result)} == {
        ("11", "28", "41"), ("30",)}
    assert result["status"] == "partial"
    assert all(region["scope_complete"] is False for region in common_regions(result))
    assert any("거주지역 조건 불일치" in topic for rule in result["rules"] if rule["kind"] == "condition_coverage"
               for scope in rule["scopes"] for topic in scope["missing_topics"])


@pytest.mark.parametrize("change", ["remove_selection", "add_priority"])
def test_random_draw_is_not_used_to_waive_a_missing_or_explicit_regional_priority(change):
    source = copy.deepcopy(SOURCE)
    page = source["pages"][-1]
    if change == "remove_selection":
        page["text"] = page["text"].replace("한국부동산원", "사업주체")
    else:
        page["text"] = page["text"].replace("당첨자 및", "■ 해당지역\n거주자 우선공급\n당첨자 및", 1)
    region, = common_regions(parse(source))
    assert region.get("priority_applicable") is not False
    assert "regional_selection_evidence" not in region


def test_removed_operative_table_cannot_certify_the_cover_summary_as_full_eligibility():
    source = copy.deepcopy(SOURCE)
    source["pages"] = source["pages"][:-1]
    result = parse(source)
    assert result["status"] == "partial"
    assert any("문단의 전체 범위" in topic for rule in result["rules"] if rule["kind"] == "condition_coverage"
               for scope in rule["scopes"] for topic in scope["missing_topics"])
    assert all(region.get("priority_applicable") is not False for region in common_regions(result))


def test_an_explicit_priority_in_current_general_notes_survives_the_table_draw():
    source = copy.deepcopy(SOURCE)
    notes = next(page for page in source["pages"] if page["page"] == 2)
    notes["text"] = notes["text"].replace("공급합니다(외국인 청약불가).",
        "공급합니다(외국인 청약불가). 다만 경쟁이 있는 경우 인천광역시 거주자에게 우선공급합니다.")
    region, = common_regions(parse(source))
    assert region["evidence_page"] == 8 and region["priority_applicable"] is True
    assert region["local_priority"]["region_code"] == "28"
    assert region["regional_priority_evidence"]["evidence_page"] == 2
    assert "regional_selection_evidence" not in region


def test_previous_same_source_parser_facts_stay_available_during_reprocessing():
    assert parser_version_usable({"source": "official_document_parser", "parser_version": "official-sections-2026-10-11-v16"})
    assert parse(announcement_date="2026-10-05")["identity_status"] == "mismatch"
