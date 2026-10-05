"""Public source examples verify classification, independent rank and allocation."""

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.db import init_db, make_engine
from app.extract.official_rules import PARSER_VERSION, parse_official_rules
from app.extract.pipeline import enrich_notice
from app.extract.reprocess import _document_patch
from app.ingest.lh import normalize as normalize_lh
from app.ingest.reb import PAIRS, normalize
from app.qualification import public_classification, public_rank_applicability
from app.repository import notice_public, record_competition_result, upsert_notice

DIRECTORY = Path(__file__).parent / "fixtures"
SOURCES = json.loads((DIRECTORY / "official-rules-v3.json").read_text())
PREVIOUS = json.loads((DIRECTORY / "official-rules-reviewed.json").read_text())


def official(number):
    source = next(s for s in SOURCES + PREVIOUS if s["house_manage_no"] == number)
    return parse_official_rules(source["pages"], url=source["document_url"], digest=source["document_hash"])


def test_actual_jamsil_mixed_operation_label_does_not_make_a_sale_rental():
    detail = json.loads((DIRECTORY / "jamsil-detail.json").read_text())[0]
    models = json.loads((DIRECTORY / "jamsil-models.json").read_text())
    result = normalize(detail, models, PAIRS[1])
    assert result["category"] == "officetel"
    assert {p["unit_type"]: p["amount_krw"] for p in result["prices"]} == {"28D": 588000000, "36A": 819800000, "40B": 913810000, "40C": 937560000}
    assert all(p["price_kind"] == "sale_max" and "부가세 포함" in p["basis_label"] for p in result["prices"])
    assert public_classification(result["rules"])[0] == "not_applicable"
    rank = public_rank_applicability(result["rules"])
    assert rank.status == "not_applicable" and rank.account_required is False
    fees = next(r for r in result["rules"] if r["kind"] == "supply_financial_terms")
    assert len(fees["units"]) == 4
    assert all(f["application_fee_krw"] == 3000000 for f in fees["units"])


def test_lh_shinhee_parent_does_not_make_happiness_rental_a_public_sale():
    row = {"PAN_ID": "2015122300020859", "PAN_NM": "하남시 신혼희망타운 행복주택", "UPP_AIS_TP_CD": "39", "DTL_URL": "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?uppAisTpCd=39&aisTpCd=42"}
    assert normalize_lh(row, "39")["category"] == "public_rental"
    row["AIS_TP_CD"] = "39"
    assert normalize_lh(row, "39")["category"] == "public_sale"


def test_jamsil_exact_review_has_no_rank_and_individual_eligibility_not_an_ai_quote():
    result = official("2026950085")
    assert public_classification(result["rules"])[0] == "not_applicable"
    assert public_rank_applicability(result["rules"]).account_required is False
    assert not any(r.get("purpose") == "first_rank" for r in result["rules"])
    assert next(r for r in result["rules"] if r["kind"] == "age_min")["value"] == 19
    assert next(r for r in result["rules"] if r["kind"] == "condition_coverage")["scopes"][0]["complete"] is True
    assert len(result["prices"]) == 4
    source = next(s for s in SOURCES if s["house_manage_no"] == "2026950085")
    changed = parse_official_rules(source["pages"], url=source["document_url"], digest="replaced-document")
    assert not changed.get("prices")
    assert next(r for r in changed["rules"] if r["kind"] == "condition_coverage")["scopes"][0]["complete"] is False


@pytest.mark.parametrize("number,kinds", [("2026000494", {"account_type", "private_rank_months", "deposit_min_krw"}), ("2026000414", {"account_type", "national_rank_months", "recognized_payments_min"})])
def test_rank_coverage_complete_independently_of_whole_eligibility(number, kinds):
    result = official(number)
    rank = next(r for r in result["rules"] if r["kind"] == "rank_requirements")
    assert rank["complete"] is True and set(rank["required_kinds"]) == kinds
    assert rank["completion_basis"] == "document_hash_review"
    assert all(s["complete"] is False for s in next(r for r in result["rules"] if r["kind"] == "condition_coverage")["scopes"])
    money = next(r for r in result["rules"] if r["kind"] in {"deposit_min_krw", "recognized_payments_min"} and r.get("purpose") == "first_rank")
    assert money["require_as_of_date"] is True


def test_dongin_applicant_regions_and_active_military_exception_are_explicit():
    r = next(r for r in official("2026000494")["rules"] if r["kind"] == "applicant_regions")
    assert [p["region_code"] for p in r["regions"]] == ["27", "47"]
    assert r["local_priority"]["region_code"] == "27"
    exception = r["exceptions"][0]
    assert exception["min_years"] == 10 and exception["currently_serving"] is True
    assert exception["criterion_date"] == "2026-10-02" and exception["evidence_page"] == 5


def test_gwangmyeong_general_priority_is_not_a_special_supply_percentage():
    result = official("2026000453")
    r = next(r for r in result["rules"] if r["kind"] == "regional_allocation")
    assert r["supply_type"] == "일반공급" and r["allocation_method"] == "all_local_first"
    assert r["local_share_percent"] == 100
    assert r["local_region"]["region_code"] == "41210" and r["local_region"]["min_months"] == 24
    assert r["evidence_page"] == 26 and "해당지역 거주자" in r["evidence_text"]
    rank = next(r for r in result["rules"] if r["kind"] == "rank_requirements")
    assert rank["complete"] is True
    assert {"household_head", "ownership_count_max", "previous_winning"} <= set(rank["required_kinds"])
    previous = next(r for r in result["rules"] if r["kind"] == "previous_winning")
    assert previous["months"] == 60 and previous["value"] is False


def test_public_prices_use_exclusive_area_from_official_table_not_supply_area(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'areas.db'}")
    init_db(engine)
    parsed = official("2026000494")
    with Session(engine) as db:
        notice = upsert_notice(db, {"source": "cheongyak_home", "external_id": "area", "title": "더샵 동인센트리체", "category": "apt",
                                   "document_hash": next(r["document_hash"] for r in parsed["rules"]), "rules": parsed["rules"],
                                   "prices": [{"unit_type": "084.2551A", "area_sqm": 115.374, "price_kind": "sale_max", "amount_krw": 844330000, "verification": "official"}]})
        price = notice_public([notice]).prices[0]
        assert price.area_sqm == 115.374 and price.exclusive_area_sqm == 84.2551
        assert price.area_basis == "supply"
        notice.document_hash = "corrected-document"
        assert notice_public([notice]).prices[0].exclusive_area_sqm is None
    engine.dispose()


def test_local_patch_corrects_existing_lh_happiness_category_without_prices():
    current = {"source": "lh", "external_id": "happiness", "category": "public_sale", "official_url": "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?uppAisTpCd=39&aisTpCd=42", "rules": [], "prices": []}
    patched = _document_patch(current, current)
    assert patched["category"] == "public_rental" and patched["price_cap_status"] == "not_applicable"


def test_shinhee_requires_an_account_but_has_no_general_rank():
    r = public_rank_applicability(official("2026820010")["rules"])
    assert r.status == "not_applicable" and r.account_required is True


def test_first_come_document_can_publish_applicability_without_guessing_kind():
    pages = [{"page": 1, "text": "잔여세대 입주자모집공고\n선착순 동호지정 계약\n청약통장이 필요하지 않습니다."}]
    r = parse_official_rules(pages, url="https://apply.lh.or.kr/public.pdf", digest="first-come")
    assert public_rank_applicability(r["rules"]).status == "not_applicable"
    assert public_classification(r["rules"])[0] == "unknown"


def test_local_document_patch_repairs_wrong_prices_without_snapshot_feed_overwrite():
    result = official("2026950085")
    current = {"source": "cheongyak_home", "external_id": "jamsil", "document_hash": result["prices"][0]["document_hash"], "rules": [], "prices": [{"unit_type": "28D", "price_kind": "deposit", "amount_krw": None}]}
    patch = _document_patch(current, {**current, "rules": result["rules"], "prices": result["prices"]})
    assert patch["replace_prices"] is True and len(patch["prices"]) == 4
    assert all(p["price_kind"] == "sale_max" for p in patch["prices"])


def test_additive_competition_invalidation_migration_retains_rows(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE competition_state (notice_id TEXT PRIMARY KEY, status TEXT, last_attempt_at DATETIME, last_success_at DATETIME, complete BOOLEAN, unit_types JSON, evidence_url TEXT, message TEXT)"))
        c.execute(text("INSERT INTO competition_state (notice_id,status,complete,unit_types,message) VALUES ('legacy','pending',0,'[]',:message)"), {"message": "공고 변경 후 경쟁률 재확인 대기"})
    init_db(engine)
    init_db(engine)
    with engine.connect() as c:
        assert "proof_invalidated" in {p["name"] for p in inspect(c).get_columns("competition_state")}
        assert c.execute(text("SELECT proof_invalidated FROM competition_state WHERE notice_id='legacy'")).scalar() == 1
    engine.dispose()


def test_correction_proof_invalidation_survives_failed_retries_and_clears_on_success(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'proof.db'}")
    init_db(engine)
    with Session(engine) as db:
        notice = upsert_notice(db, {"source": "cheongyak_home", "external_id": "proof", "title": "공식 공고", "category": "apt", "prices": [{"unit_type": "84", "price_kind": "sale_max", "amount_krw": 100000000}]})
        row = {"unit_type": "84", "residence_area": "local", "competition_rate": "2.0", "result_status": "first_closed", "verification": "official", "evidence_url": "https://www.applyhome.co.kr/result"}
        record_competition_result(db, notice, "ok", rows=[row])
        assert notice.competition_state.proof_invalidated is False
        upsert_notice(db, {"source": "cheongyak_home", "external_id": "proof", "title": "정정 공식 공고"})
        for state in ["running", "error"]:
            record_competition_result(db, notice, state)
            assert notice.competition_state.proof_invalidated is True
        assert notice_public([notice]).competition.proof_invalidated is True
        assert len(notice.competitions) == 1
        record_competition_result(db, notice, "partial", rows=[row])
        assert notice.competition_state.proof_invalidated is False
    engine.dispose()
