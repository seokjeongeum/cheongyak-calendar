"""New source identities and page layouts use current clauses, not registries."""
import copy
import json
import re
from pathlib import Path

from app.extract.application_regions import explicit_applicant_regions, region_catalog
from app.extract.public_sale_rules import parse_public_sale_rules
from app.extract.selection_rules import parse_selection_rules

FIXTURES = Path(__file__).parent / "fixtures"
PROVINCES = {r["name"]: r["code"] for r in region_catalog()["provinces"]}


def region_make(kind, *, quote, page, **fields):
    return {"kind": kind, "evidence_text": quote, "evidence_page": page, **fields}


def geography(text, *, page=19, cutoff="2027-02-01"):
    return explicit_applicant_regions([{"page": page, "text": text}], cutoff=cutoff,
        make=region_make, provinces=PROVINCES)


def test_new_city_and_priority_duration_are_read_from_eligibility_on_later_page():
    text = "새로운 공동주택의 공급위치: 부산광역시 중구.\n■ 최초 입주자모집공고일(2027.02.01) 현재 경기도 하남시에 거주하거나 수도권(경기도, 서울특별시, 인천광역시)에 거주하는 만19세 이상인 분은 청약이 가능합니다. 다만 경쟁이 있을 경우 해당 주택건설지역인 하남시 2년 이상 거주자가 우선합니다."
    scope = geography(text)[0]
    assert {r["region_code"] for r in scope["regions"]} == {"41", "11", "28"}
    assert scope["local_priority"]["region_code"] == "41450"
    assert scope["local_priority"]["min_months"] == 24
    assert scope["evidence_page"] == 19
    changed = text.replace("수도권(경기도, 서울특별시, 인천광역시)", "충청남도")
    new = geography(changed)[0]
    assert {r["region_code"] for r in new["regions"]} == {"41450", "44"}
    assert "26" not in {r["region_code"] for r in new["regions"]}


def test_unmapped_municipality_is_not_widened_to_its_province():
    assert geography("입주자모집공고일 현재 경기도 새로생긴군에 거주하는 무주택세대구성원은 신청 가능합니다.") == []
    assert geography("입주자모집공고일 현재 서울특별시 또는 경기도 새로생긴군에 거주하는 무주택세대구성원은 신청 가능합니다.") == []
    assert geography("공급위치 경기도 하남시\n입주자모집공고일 현재 청약통장 가입기간 12개월을 충족해야 합니다.") == []
    assert geography("입주자모집공고일(2026.02.01) 현재 경기도 하남시에 거주하는 무주택세대구성원은 신청 가능합니다.") == []


def test_adjacent_province_names_and_priority_duration_keep_their_own_scopes():
    source = "입주자모집공고일 현재 천안시에 거주하거나 충청남도 대전광역시 및 세종특별자치시에 거주하는 만19세 이상인 분은 청약이 가능합니다. 다만 경쟁 시 천안시 3년 이상 거주자가 우선합니다."
    scope = geography(source)[0]
    assert {row["region_code"] for row in scope["regions"]} == {"44", "30", "36"}
    assert scope["local_priority"]["region_code"] == "44130"
    assert scope["local_priority"]["min_months"] == 36
    assert geography("입주자모집공고일 현재 신청자의 청약통장 자격요건을 갖추어야 합니다. 청약예금의 예치금액 특별시 및 부산광역시 300만원 각 청약통장으로 신청가능한 전용면적 이하에만 청약가능함") == []


def test_reordered_military_years_are_bound_to_the_same_operative_sentence():
    text = "입주자모집공고일 현재 충청남도에 거주하는 무주택세대구성원은 신청 가능합니다. ■ 년 이상 장기복무 중인 군인은 해당순위 및 입주자저축 요건을 충족 시 해당 주택건설지역에 거주하지 않아도 해당 주택건14 ( 1 , 2 ) , ■ 설지역 거주자격으로 청약할 수 있습니다."
    scope = geography(text)[0]
    assert scope["exceptions"][0]["min_years"] == 14
    assert scope["exceptions"][0]["residence_area"] == "local"
    assert scope["exceptions"][0]["evidence_page"] == 19
    assert not geography(text.replace("14 ( 1 , 2 )", "( 1 , 2 )"))[0].get("exceptions")


def test_special_only_priority_cannot_replace_a_different_common_application_scope():
    pages = [{"page": 1, "text": "입주자모집공고일 현재 경기도 및 서울특별시에 거주하는 무주택세대구성원은 신청 가능합니다."},
             {"page": 2, "text": "1. 기관추천 특별공급\n대상자 입주자모집공고일 현재 서울특별시에 거주하는 무주택세대구성원은 신청 가능합니다. 다만 경쟁 시 서울특별시 1년 이상 거주자가 우선합니다."}]
    rules = explicit_applicant_regions(pages, cutoff="2027-02-01", make=region_make, provinces=PROVINCES)
    common = next(rule for rule in rules if not rule.get("supply_type"))
    special = next(rule for rule in rules if rule.get("supply_type") == "기관추천 특별공급")
    assert {row["region_code"] for row in common["regions"]} == {"41", "11"}
    assert common.get("priority_applicable") is None
    assert {row["region_code"] for row in special["regions"]} == {"11"}
    assert special["local_priority"]["min_months"] == 12


def parse_public(source, *, pages=None, payload=None, digest="new-document-sha"):
    return parse_public_sale_rules(pages or source["pages"], url="https://apply.lh.or.kr/lhapply/lhFile.do?fileid=999999",
        digest=digest, payload=payload or source["payload"], parser_version="generic-test")


def test_complete_residual_clauses_survive_new_name_id_hash_and_cover_sheets():
    source = json.loads((FIXTURES / "gimhae-yangsan-residual-20260930.json").read_text())
    payload = {**source["payload"], "title": "새 도시 다세대주택 공가세대 일반매각", "external_id": "future-offer-009",
        "official_url": "https://apply.lh.or.kr/current?panId=future-offer-009"}
    pages = [{"page": p["page"] + 3, "text": p["text"].replace("김해시", "새도시").replace("양산시", "새군")} for p in source["pages"]]
    pages = [{"page": n, "text": "현재 모집공고 표지 안내"} for n in range(1, 4)] + pages
    result = parse_public(source, pages=pages, payload=payload)
    assert result["status"] == "complete"
    scope = next(r for r in result["rules"] if r["kind"] == "condition_coverage")["scopes"][0]
    assert scope["reviewed_document_hash"] == "new-document-sha"
    assert scope["completion_basis"] == "current_document_clause_coverage"
    assert min(scope["reviewed_section_pages"]) > 3
    assert {r["restriction"] for r in result["rules"] if r["kind"] == "application_restriction"} == {"rewinning_restriction_active", "ineligible_restriction_active"}
    assert all(r["criterion_date"] == "2026-09-30" for r in result["rules"])


def test_new_numeric_age_clause_is_used_and_unmodeled_extra_gate_keeps_source_incomplete():
    source = json.loads((FIXTURES / "gimhae-yangsan-residual-20260930.json").read_text())
    pages = copy.deepcopy(source["pages"])
    for page in pages:
        page["text"] = re.sub(r"(만\s*)?19\s*세", lambda m: (m[1] or "") + "20세", page["text"])
    result = parse_public(source, pages=pages)
    adult = next(r for r in result["rules"] if r["kind"] == "any")
    assert adult["conditions"][0]["value"] == 20
    pages[8]["text"] += "\n■ 별도 자격요건: 최근 벌점 3점 이하인 자만 신청 가능합니다."
    partial = parse_public(source, pages=pages)
    assert partial["status"] == "partial"
    gaps = next(r for r in partial["rules"] if r["kind"] == "condition_coverage")["scopes"][0]["source_gaps"]
    assert any(g["item"] == "비정형 신청 제한·요건" and "벌점 3점" in g["evidence_text"] for g in gaps)


def test_special_quota_reads_new_percentages_and_regions_without_inventing_local_share():
    rules = [{"kind": "housing_classification", "verification": "official", "housing_kind": "private", "criterion_date": "2027-02-01"},
        {"kind": "offered_supplies", "verification": "official", "supplies": [{"unit_type": "84A", "supply_type": "다자녀가구 특별공급", "supply_count": 7}]}]
    text = "1. 다자녀가구 특별공급\n대상자 입주자모집공고일 현재 무주택세대구성원\n■ ①지역 : 해당시·도 거주자 30%(충청남도 거주자) → 기타지역 거주자 70%(대전광역시 및 세종특별자치시 거주자)"
    result = parse_selection_rules([{"page": 27, "text": text}], url="https://official.example/new.pdf", digest="new-document", rules=rules, parser_version="generic-test")
    quota = next(r for r in result if r["kind"] == "regional_allocation")
    assert [r["percent"] for r in quota["regional_shares"]] == [30, 70]
    assert [set(r["region_codes"]) for r in quota["regional_shares"]] == [{"44"}, {"30", "36"}]
    assert quota["local_share_percent"] is None
    assert quota["evidence_page"] == 27 and quota["document_hash"] == "new-document"


def test_unrecognized_numeric_requirement_in_known_eligibility_bullet_is_a_source_gap():
    source = json.loads((FIXTURES / "gimhae-yangsan-residual-20260930.json").read_text())
    pages = copy.deepcopy(source["pages"])
    # This adds a new subject without familiar unknown-topic keywords. A
    # supported age clause in the same bullet must not hide this requirement.
    pages[8]["text"] += "\n■ 국내에 거주하는 만19세 이상 성년자는 신청 가능합니다. 신청자는 자동차 평가액이 1천만원 이하여야 청약신청이 가능합니다."
    partial = parse_public(source, pages=pages)
    assert partial["status"] == "partial"
    gaps = next(r for r in partial["rules"] if r["kind"] == "condition_coverage")["scopes"][0]["source_gaps"]
    assert any(g["item"] == "비정형 신청 제한·요건" and "자동차 평가액" in g["evidence_text"] for g in gaps)
    assert any(g["evidence_page"] == 9 for g in gaps)


def test_boundary_mapping_and_applicant_section_survive_moved_pages():
    source = next(row for row in json.loads((FIXTURES / "current-oct8-regions.json").read_text()) if row["external_id"] == "2026000471")
    shifted = [{"page": page["page"] + 12, "text": page["text"]} for page in source["pages"]]
    provinces = {**PROVINCES, "광주광역시": "29", "전라남도": "46"}
    rules = explicit_applicant_regions(shifted, cutoff="2026-10-08", make=region_make, provinces=provinces)
    scope = rules[0]
    assert {region["region_code"] for region in scope["regions"]} == {"12"}
    assert {region["region_code"] for region in scope["local_priority"]["regions"]} == {"12210", "12240", "12270", "12300", "12330"}
    assert scope["local_priority"]["mapping_evidence"]["evidence_page"] == 13
    assert scope["evidence_page"] == source["regional_expectation"]["evidence_page"] + 12
