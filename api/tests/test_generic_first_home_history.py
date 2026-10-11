"""First-home ownership evidence survives unrelated document review gaps."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.extract.official_rules import parse_official_rules


FIXTURES = Path(__file__).parent / "fixtures"
SOURCE = next(row for row in json.loads((FIXTURES / "current-oct8-regions.json").read_text())
              if row["external_id"] == "2026000458")
FIRST = "생애최초 특별공급"


def parse(row):
    return parse_official_rules(row["pages"], url=row["document_url"], digest=row["document_hash"],
                                payload=row["payload"])


def past_rule(result):
    rules = [rule for rule in result["rules"] if rule["kind"] == "never_owned_home" and rule.get("supply_type") == FIRST]
    assert len(rules) == 1
    return rules[0]


def coverage(result):
    return next(scope for rule in result["rules"] if rule["kind"] == "condition_coverage"
                for scope in rule["scopes"] if scope["supply_type"] == FIRST)


@pytest.mark.parametrize("missing", ["250만원", "해외체류기간", "납부 의무액이 없는 경우를 포함"])
def test_unrelated_gap_does_not_discard_current_first_home_ownership_exemptions(missing):
    row = copy.deepcopy(SOURCE)
    assert any(missing in page["text"] for page in row["pages"])
    for page in row["pages"]:
        page["text"] = page["text"].replace(missing, "해당 내용 미확보")
    result = parse(row)
    rule = past_rule(result)
    assert rule["scope"] == "household" and rule["exclude_spouse_pre_marriage_disposed"]
    assert rule["evidence_page"] == 21
    assert rule["exceptions"][0]["evidence_page"] == 40
    assert "만 60세 이상의 직계존속" in rule["exceptions"][0]["evidence_text"]
    assert rule["document_hash"] == rule["exceptions"][0]["document_hash"] == row["document_hash"]
    assert not coverage(result)["complete"]


def test_new_identity_shifted_pages_and_missing_bank_table_keep_only_current_source_facts():
    row = copy.deepcopy(SOURCE)
    row["payload"].update(title="새봄역 주택", announcement_date="2030-09-10", rules=[],
        official_url="https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2030000041&pblancNo=2030000041")
    row["document_url"] = "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2030000041&pblancNo=2030000041&atchmnflSeqNo=41&atchmnflSn=1"
    for page in row["pages"]:
        page["page"] += 11
        page["text"] = page["text"].replace("2026000458", "2030000041").replace("2026.10.08", "2030.09.10").replace("250만원", "표 미확보")
    row["document_hash"] = hashlib.sha256(json.dumps(row["pages"], ensure_ascii=False).encode()).hexdigest()
    result = parse(row)
    rule = past_rule(result)
    assert rule["criterion_date"] == "2030-09-10" and rule["evidence_url"] == row["document_url"]
    assert rule["evidence_page"] == 32 and rule["spouse_exception_evidence_page"] == 32
    assert rule["exceptions"][0]["evidence_page"] == 51
    assert rule["document_hash"] == rule["exceptions"][0]["document_hash"] == row["document_hash"]
    assert not coverage(result)["complete"]


def test_absent_ancestor_clause_does_not_become_a_factual_ancestor_exemption():
    row = copy.deepcopy(SOURCE)
    for page in row["pages"]:
        page["text"] = page["text"].replace("250만원", "표 미확보")
        # Other uses of age 60 in point scoring cannot replace Article 53's
        # actual ownership exemption and its elder-parent exclusion.
        page["text"] = page["text"].replace("만 60세 이상의 직계존속(배우자의 직계존속을 포함한다)", "해당 법령 조항 미확보")
    rule = past_rule(parse(row))
    assert rule["exclude_spouse_pre_marriage_disposed"]
    assert "60세" not in rule["exceptions"][0]["evidence_text"]
    assert rule["exceptions"][0]["evidence_page"] == rule["evidence_page"]


def test_spouse_exemption_must_be_in_the_actual_first_home_applicant_section():
    row = copy.deepcopy(SOURCE)
    phrase = "청약신청자의 배우자가 혼인 전 주택을 소유하였다가 혼인 전 처분한 이력은 배제합니다"
    for page in row["pages"]:
        page["text"] = page["text"].replace("250만원", "표 미확보")
        if page["page"] == 21:
            page["text"] = page["text"].replace(phrase, "혼인 전 취득·처분의 적용 범위 미확보")
    row["pages"][0]["text"] += f"\n과거 다른 공급의 안내 예시: {phrase}."
    assert any(phrase in page["text"] for page in row["pages"])
    rule = past_rule(parse(row))
    assert "exclude_spouse_pre_marriage_disposed" not in rule
    assert "spouse_exception_evidence_text" not in rule
    assert "만 60세 이상의 직계존속" in rule["exceptions"][0]["evidence_text"]


def test_unreadable_smallest_deposit_row_is_not_replaced_by_readable_larger_area_row():
    row = copy.deepcopy(SOURCE)
    for page in row["pages"]:
        page["text"] = page["text"].replace("250만원", "금액 미확보")
    result = parse(row)
    assert not coverage(result)["complete"]
    assert any("예치금 표" in topic for topic in coverage(result)["missing_topics"])
    assert past_rule(result)["exceptions"][0]["evidence_page"] == 40
