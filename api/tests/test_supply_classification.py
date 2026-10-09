"""Tenure corrections use the provider's exact current announcement identity."""
from __future__ import annotations

import copy

import pytest

from app.ingest.reb import PAIRS, normalize
from app.main import list_notices
from app.repository import notice_public, upsert_notice
from app.supply_classification import reviewed_supply_classification
from test_repository_api import db, example_notice


IDENTITY = {
    "official_url": "https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2026000402&pblancNo=2026000402",
    "announcement_date": "2026-10-08", "title": "익산 부송에코르 10년 공공임대주택",
    "provider": "전북개발공사",
}


@pytest.mark.parametrize("changes", [
    {"announcement_date": "2026-09-08"}, {"provider": "다른 공급기관"},
    {"title": "익산 부송에코르 공공임대주택 이전 공고"},
    {"official_url": IDENTITY["official_url"].replace("2026000402", "2026000999")},
    {"official_url": IDENTITY["official_url"].replace("www.applyhome.co.kr", "example.com")},
    {"official_url": IDENTITY["official_url"] + "&houseManageNo=2026000999"},
])
def test_provider_category_cannot_be_reused_for_a_different_notice(changes):
    assert reviewed_supply_classification(**{**IDENTITY, **changes}) is None


def test_apt_national_and_rental_codes_keep_rank_classification_separate_from_tenure():
    detail = {"HOUSE_MANAGE_NO": "2026000402", "PBLANC_NO": "2026000402",
              "HOUSE_NM": IDENTITY["title"], "BSNS_MBY_NM": IDENTITY["provider"],
              "RCRIT_PBLANC_DE": "2026-10-08", "PBLANC_URL": IDENTITY["official_url"],
              "HOUSE_DTL_SECD": "03", "RENT_SECD": "1", "PARCPRC_ULS_AT": "Y"}
    result = normalize(detail, [{"HOUSE_TY": "059.9288A", "LTTOT_TOP_AMOUNT": "10000"}], PAIRS[0])
    assert result["category"] == "public_rental"
    assert result["price_cap_status"] == "not_applicable"
    assert next(r for r in result["rules"] if r["kind"] == "housing_classification")["housing_kind"] == "national"
    assert next(r for r in result["rules"] if r["kind"] == "supply_classification")["evidence_url"].startswith("https://www.jbdc.co.kr/")
    assert result["prices"][0]["price_kind"] == "deposit" and result["prices"][0]["amount_krw"] is None
    # 국민주택 and a rental flag alone do not establish a legal public rental.
    other = normalize({**detail, "HOUSE_MANAGE_NO": "2026000999", "PBLANC_NO": "2026000999",
                       "PBLANC_URL": IDENTITY["official_url"].replace("2026000402", "2026000999")}, [], PAIRS[0])
    assert other["category"] == "apt"


def test_retained_apt_row_is_excluded_by_reviewed_public_rental_projection_without_rewriting_source(db):
    row = {**example_notice(external_id="getAPTLttotPblancDetail:2026000402:2026000402"), **IDENTITY}
    notice = upsert_notice(db, row)
    db.commit()
    before = copy.deepcopy(notice.rules)
    assert notice.category == "apt"
    projected = notice_public([notice])
    assert projected.category == "public_rental" and projected.price_cap_status == "not_applicable"
    assert next(r for r in projected.rules if r["kind"] == "supply_classification")["verification"] == "official"
    assert list_notices(exclude_public_rental=True, page=1, page_size=20, session=db).total == 0
    assert list_notices(exclude_public_rental=False, page=1, page_size=20, session=db).total == 1
    assert notice.category == "apt" and notice.rules == before
