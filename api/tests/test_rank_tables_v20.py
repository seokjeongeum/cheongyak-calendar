import json
from pathlib import Path

import pytest

from app.extract.official_rules import PARSER_VERSION, parse_official_rules
from app.extract.rank_tables import deposit_table_with_shared_unit


FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = {source["key"]: source for source in json.loads((FIXTURES / "official-rank-tables-202610.json").read_text())}


def extract(source, *, rank_pages=None):
    return parse_official_rules(source["pages"], url=source["document_url"], digest=source["document_hash"],
                                payload=source["payload"], rank_pages=rank_pages)


def find_rule(result, kind, **fields):
    return next(rule for rule in result["rules"] if rule["kind"] == kind and all(rule.get(key) == value for key, value in fields.items()))


@pytest.mark.parametrize(("key", "page"), [("gwanggyo", 23), ("equity", 28)])
def test_national_rank_from_each_official_general_table(key, page):
    source = SOURCES[key]
    result = extract(source, rank_pages=source["rank_pages"])
    for kind, value in [("national_rank_months", 24), ("recognized_payments_min", 24), ("household_head", True), ("homeless", True)]:
        rule = find_rule(result, kind, purpose="first_rank")
        assert (rule["value"], rule["evidence_page"], rule["criterion_date"]) == (value, page, "2026-10-30")
        assert rule["document_hash"] == source["document_hash"] and rule["parser_version"] == PARSER_VERSION
    assert find_rule(result, "previous_winning", purpose="first_rank")["months"] == 60
    assert find_rule(result, "account_type", purpose="first_rank")["allowed_values"] == ["comprehensive", "savings"]
    assert find_rule(result, "rank_requirements")["complete"]


def test_known_national_items_survive_incomplete_additional_restriction():
    source = SOURCES["gwanggyo"]
    rank_pages = [{**page, "text": page["text"].replace("과거 5년 이내 당첨된 자의 세대에 속하지 않은 분", "이전 당첨 제한 별도 안내")}
                  for page in source["rank_pages"]]
    result = extract(source, rank_pages=rank_pages)
    assert find_rule(result, "national_rank_months", purpose="first_rank")["value"] == 24
    assert find_rule(result, "recognized_payments_min", purpose="first_rank")["value"] == 24
    assert not find_rule(result, "rank_requirements")["complete"]


def test_regulated_private_deposits_and_corrected_publication():
    result = extract(SOURCES["central"])
    context = find_rule(result, "qualification_context")["value"]
    assert context["application_criterion_date"] == "2026-10-29"
    assert context["correction_publication_date"] == "2026-10-30"
    assert find_rule(result, "rank_requirements")["complete"]
    assert find_rule(result, "household_head", purpose="first_rank")["value"] is True
    assert find_rule(result, "private_rank_months", purpose="first_rank")["value"] == 24
    assert find_rule(result, "account_type", purpose="first_rank")["area_limit_for_installment"] == 85
    table = find_rule(result, "deposit_min_krw", purpose="first_rank")["deposit_table"]
    assert [row["max_area_sqm"] for row in table] == [85, 102, 135, None]
    assert table[0]["amounts_krw"] == {"seoul_busan": 3_000_000, "other_metropolitan": 2_500_000, "other": 2_000_000}


def test_shared_deposit_unit_and_column_order():
    text = """[청약예금의 예치금액]
    단위: 만원
    구분 특별시 및 광역시를 제외한 지역
    특별시 및 부산광역시 그 밖의 광역시
    85㎡ 이하 200
    300 250
    모든 면적 500 1,500 1,000
    """
    table, source = deposit_table_with_shared_unit([{"page": 8, "text": text}])
    assert table[0]["amounts_krw"] == {"seoul_busan": 3_000_000, "other_metropolitan": 2_500_000, "other": 2_000_000}
    assert source["page"] == 8
    assert deposit_table_with_shared_unit([{"page": 8, "text": text.replace("300 250", "300")}]) == ([], None)


def test_a2_residual_family_paths_share_current_waivers_and_keep_proof_separate():
    source = json.loads((FIXTURES / "public-family-a2-20261030.json").read_text())
    result = extract(source)
    assert result["status"] == "complete"
    assert result["offered_supply_types"] == ["신혼부부(신혼희망타운)", "예비신혼부부(신혼희망타운)", "한부모가족(신혼희망타운)"]
    assert find_rule(result, "rank_applicability")["account_required"] is False
    assert not any(rule["kind"] in {"subscription_months", "recognized_payments_min", "shinhee_income", "shinhee_assets"} for rule in result["rules"])
    scopes = find_rule(result, "condition_coverage")["scopes"]
    assert all(scope["complete"] and scope["reviewed_document_hash"] == source["document_hash"] and 7 in scope["reviewed_pages"] for scope in scopes)
    assert all(rule["evidence_page"] == 7 for rule in result["rules"] if rule["kind"] == "family_route")
