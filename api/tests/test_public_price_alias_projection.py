"""Only an explicit current official table can hide a redundant AI price alias."""
from copy import deepcopy

import pytest

from app.extract.official_rules import PARSER_VERSION
from app.repository import notice_public, upsert_notice
from test_repository_api import db, example_notice


def payload(code="084.9821A", alias="84A", area=84.9821):
    document_url = "https://official.example/current.pdf"
    rule = {"kind": "unit_exclusive_areas", "effect": "metadata", "source": "official_document_parser",
            "verification": "official", "parser_version": PARSER_VERSION, "document_hash": "current-bytes",
            "evidence_url": document_url, "evidence_page": 5,
            "evidence_text": f"{code} {alias} {area} 27.2684 112.2505",
            "units": [{"unit_type": code, "exclusive_area_sqm": area}]}
    official = {"unit_type": code, "price_kind": "sale_max", "amount_krw": 477_700_000,
                "verification": "official", "evidence_url": "https://official.example/current-notice",
                "evidence_text": "LTTOT_TOP_AMOUNT=47770 (단위: 만원)"}
    candidate = {"unit_type": alias, "area_sqm": area, "price_kind": "sale_total", "amount_krw": 477_700_000,
                 "verification": "ai_unverified", "document_hash": "current-bytes", "evidence_url": document_url,
                 "evidence_text": f"{code} {alias} 113-1303 477,700,000"}
    return {**example_notice(), "document_hash": "current-bytes", "rules": [rule],
            "prices": [official, candidate]}


@pytest.mark.parametrize("code,alias,area", [("084.9821A", "84A", 84.9821), ("075.6789Q", "75Q", 75.6789)])
def test_explicit_official_table_alias_is_hidden_in_list_and_detail_without_changing_originals(db, code, alias, area):
    raw = payload(code, alias, area)
    notice = upsert_notice(db, raw)
    db.commit()
    original = deepcopy(notice.revisions[0].payload)
    for detail in (False, True):
        public = notice_public([notice], detail=detail)
        assert [(price.unit_type, price.amount_krw, price.verification) for price in public.prices] == [
            (code, 477_700_000, "official")]
    assert [price.unit_type for price in notice.prices] == [code, alias]
    assert notice.version == 1 and len(notice.revisions) == 1
    assert notice.revisions[0].payload == original and len(original["prices"]) == 2


@pytest.mark.parametrize("change", [
    "different_amount", "different_monthly", "candidate_old_hash", "official_old_hash", "proof_old_hash",
    "unverified_proof", "api_only_proof", "no_alias_pair", "area_only", "wrong_quoted_area", "missing_page",
    "other_price_kind", "unknown_candidate", "two_official_amounts", "two_identical_official_prices",
    "ambiguous_alias", "unknown_mapping",
])
def test_unproven_or_ambiguous_price_alias_remains_visible(db, change):
    raw = payload()
    official, candidate = raw["prices"]
    proof = raw["rules"][0]
    if change == "different_amount":
        candidate["amount_krw"] += 1
    elif change == "different_monthly":
        candidate["monthly_krw"] = 1
    elif change == "candidate_old_hash":
        candidate["document_hash"] = "old-bytes"
    elif change == "official_old_hash":
        official["document_hash"] = "old-bytes"
    elif change == "proof_old_hash":
        proof["document_hash"] = "old-bytes"
    elif change == "unverified_proof":
        proof["verification"] = "ai_unverified"
    elif change == "api_only_proof":
        proof["source"] = "cheongyak_home"
    elif change == "no_alias_pair":
        proof["evidence_text"] = "084.9821A 84.9821 27.2684 112.2505"
    elif change == "area_only":
        proof["evidence_text"] = "084.9821A 전용면적 84.9821㎡"
    elif change == "wrong_quoted_area":
        proof["evidence_text"] = "084.9821A 84A 84.9822 27.2684 112.2505"
    elif change == "missing_page":
        proof["evidence_page"] = None
    elif change == "other_price_kind":
        candidate["price_kind"] = "deposit"
    elif change == "unknown_candidate":
        candidate["verification"] = "unknown"
    elif change == "two_official_amounts":
        raw["prices"].append({**official, "amount_krw": official["amount_krw"] + 1})
    elif change == "two_identical_official_prices":
        raw["prices"].append({**official, "unit_type": "084.9876A"})
    elif change == "ambiguous_alias":
        proof["units"].append({"unit_type": "084.9876A", "exclusive_area_sqm": 84.9876})
        proof["evidence_text"] += " 084.9876A 84A 84.9876 27.2684 112.2505"
    elif change == "unknown_mapping":
        proof["units"] = []
    notice = upsert_notice(db, raw)
    db.commit()
    for detail in (False, True):
        public = notice_public([notice], detail=detail)
        assert any(price.unit_type == "84A" for price in public.prices)
    assert any(price.unit_type == "84A" for price in notice.prices)


def test_other_document_alias_evidence_cannot_hide_canonical_candidate(db):
    raw = payload()
    raw["rules"] = []
    canonical = upsert_notice(db, raw)
    duplicate_raw = payload()
    duplicate_raw.update(source="myhome", external_id="OTHER-COPY", document_hash="other-bytes", prices=[])
    duplicate_raw["rules"][0]["document_hash"] = "other-bytes"
    duplicate = upsert_notice(db, duplicate_raw)
    db.commit()
    assert duplicate.duplicate_of_id == canonical.id
    assert any(price.unit_type == "84A" for price in notice_public([canonical, duplicate]).prices)
