"""Offer tables remain source bound when applicant routes or PDF columns move."""
import copy
import json
from pathlib import Path

import pytest

from app.extract.official_rules import PARSER_VERSION, _document_area_facts, _document_cap_fact, parse_official_rules, parser_version_usable


def fact(kind, value=None, **fields):
    return {"kind": kind, "value": value, **fields}


def test_exclusive_column_is_not_a_supply_area_and_split_header_is_supported():
    page = {"page": 31, "text": """공급대상 주택형 (전용 (타입) 주택공급면적 면적기준)
주거 주거 소계 전용면적 공용면적
01 072.3456A 72A 72.3456 22.1234 94.4690 40.0 134.4690
02 092.1234B 92B 92.1234 29.5678 121.6912 55.0 176.6912"""}
    result = _document_area_facts([page], fact)
    assert result[0]["units"] == [{"unit_type": "072.3456A", "exclusive_area_sqm": 72.3456},
                                   {"unit_type": "092.1234B", "exclusive_area_sqm": 92.1234}]
    assert result[0]["page"] == 31
    marketing = {**page, "text": page["text"].replace("전용면적", "공급면적")}
    assert _document_area_facts([marketing], fact) == []
    wrong_column = {**page, "text": page["text"].replace("72.3456 22.1234", "94.4690 22.1234")}
    assert [unit["unit_type"] for unit in _document_area_facts([wrong_column], fact)[0]["units"]] == ["092.1234B"]


def test_actual_joined_supply_cells_restore_every_official_exclusive_area():
    source = json.loads((Path(__file__).parent / 'fixtures/hyangnam-regional-v9.json').read_text())
    parsed = parse_official_rules(source['pages'], url=source['document_url'],
        digest=source['document_hash'], payload=source['payload'])
    areas = next(rule for rule in parsed['rules'] if rule['kind'] == 'unit_exclusive_areas')
    assert areas['units'] == [
        {'unit_type': '071.8178', 'exclusive_area_sqm': 71.8178},
        {'unit_type': '084.9592A', 'exclusive_area_sqm': 84.9592},
        {'unit_type': '084.9767B', 'exclusive_area_sqm': 84.9767},
        {'unit_type': '084.9221C', 'exclusive_area_sqm': 84.9221},
        {'unit_type': '084.9140D', 'exclusive_area_sqm': 84.9140},
        {'unit_type': '107.9722A', 'exclusive_area_sqm': 107.9722},
        {'unit_type': '107.8263B', 'exclusive_area_sqm': 107.8263},
        {'unit_type': '147.9931P', 'exclusive_area_sqm': 147.9931},
    ]
    assert areas['document_hash'] == source['document_hash'] and areas['evidence_page'] == 8
    assert areas['parser_version'] == PARSER_VERSION
    assert '24.8285109.7877' in areas['evidence_text']


def test_new_unit_codes_joined_cells_and_spaced_variable_precision_share_sum_validation():
    page = {'page': 42, 'text': '''주택형 주택공급면적 전용면적 공용면적 소계
01 079.1234Z 79Z 79.1234 21.4321100.5555 50.1234
02 113.4567Y 113Y 113.4567 30.5 143.9567 60.1234'''}
    result = _document_area_facts([page], fact)
    assert result[0]['units'] == [{'unit_type': '079.1234Z', 'exclusive_area_sqm': 79.1234},
                                  {'unit_type': '113.4567Y', 'exclusive_area_sqm': 113.4567}]
    assert result[0]['page'] == 42


@pytest.mark.parametrize('joined', ['21.4321100.7555', '21.43211100.5555', '21.4321100.55555'])
def test_joined_cells_with_wrong_sum_or_ambiguous_precision_are_rejected(joined):
    page = {'page': 3, 'text': '주택형 주택공급면적 전용면적 공용면적\n'
            f'01 079.1234Z 79Z 79.1234 {joined} 50.1234'}
    assert _document_area_facts([page], fact) == []


def test_previous_parser_facts_stay_compatible_while_new_area_review_is_pending():
    old = {'source': 'official_document_parser', 'parser_version': 'official-sections-2026-10-11-v15'}
    assert parser_version_usable(old, category='apt') is True


def test_price_cap_declaration_ignores_another_housing_kind_in_statute_table():
    page = {"page": 12, "text": """■ 본 주택은 민간택지에서 공급하는 분양가상한제 미적용 민영주택으로 공급합니다.
당첨된 주택의 구분: 투기과열지구에서 공급되는 주택, 분양가상한제 적용주택 (제1항제3호)
■ 본 아파트는 분양가상한제 미적용 주택으로 책정합니다."""}
    result = _document_cap_fact([page], fact)
    assert len(result) == 1 and result[0]["value"] == "no" and result[0]["page"] == 12
    statutory_only = {"page": 12, "text": page["text"].splitlines()[1]}
    assert _document_cap_fact([statutory_only], fact) == []
    contradiction = {"page": 30, "text": "본 주택은 분양가상한제 적용 민영주택으로 공급합니다."}
    assert _document_cap_fact([page, contradiction], fact) == []
    general_prose = {"page": 12, "text": "본 주택은 거주지역에 상관없이 청약 가능합니다. 분양가상한제 적용 주택의 일반적인 전매제한 규정은 아래 표와 같습니다."}
    assert _document_cap_fact([general_prose], fact) == []
    excluded = {"page": 12, "text": "본 주택은 분양가상한제가 적용되지 않는 주택입니다."}
    assert _document_cap_fact([excluded], fact)[0]["value"] == "no"


def test_new_cancellation_special_only_route_uses_current_financial_and_area_tables():
    fixtures = Path(__file__).parent / "fixtures"
    row = copy.deepcopy(next(row for row in json.loads((fixtures / "regional-v5.json").read_text())
                             if row["house_manage_no"] == "2026930039"))
    for page in row["pages"]:
        page["page"] += 10
        page["text"] = page["text"].replace("2026930039", "2030930077").replace("2026.10.02", "2030.11.09")
    url = row["document_url"].replace("2026930039", "2030930077")
    result = parse_official_rules(row["pages"], url=url, digest="new-cancellation-special-source",
                                 payload={"category": "unsold", "announcement_date": "2030-11-09",
                                          "official_url": "https://www.applyhome.co.kr/ai/aia/selectAPTRemndrLttotPblancDetail.do?houseManageNo=2030930077"})
    assert result["offered_supply_types"] == ["생애최초 특별공급"]
    assert all(rule.get("supply_type") in {None, "생애최초 특별공급"} for rule in result["rules"])
    financial = next(rule for rule in result["rules"] if rule.get("label") == "월평균소득 또는 부동산 기준")
    assert financial["conditions"][0]["income_table"][0]["max_krw"] == 12054021
    assert financial["conditions"][0]["extra_person_krw"] == 926845
    assert financial["conditions"][1]["value"] == 331000000
    assert financial["evidence_page"] == 18
    areas = next(rule for rule in result["rules"] if rule["kind"] == "unit_exclusive_areas")
    assert {unit["exclusive_area_sqm"] for unit in areas["units"]} == {59.9901, 74.8177}
    scope = next(rule for rule in result["rules"] if rule["kind"] == "condition_coverage")["scopes"][0]
    assert not scope["complete"] and scope["missing_topics"]  # The remaining legal exceptions are explicit.
    assert all(rule["document_hash"] == "new-cancellation-special-source" for rule in result["rules"])
