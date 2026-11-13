import json
from pathlib import Path

import pytest

from app.extract.price_tables import parse_price_tables, rebuild_document_prices
from app.prices import current_price_rule, project_prices
from app.schemas import PricePublic


FIXTURES = {
    row["fileid"]: row
    for row in json.loads((Path(__file__).parent / "fixtures" / "official-price-tables-202611.json").read_text())
}


def read(fileid, **overrides):
    fixture = FIXTURES[fileid]
    return parse_price_tables(fixture["pages"], url=fixture["document_url"], digest=fixture["document_hash"],
                              payload={**fixture["payload"], **overrides})


@pytest.mark.parametrize("fileid,building,room,total,down,balance,exclusive,supply", [
    ("69315656", "4016", "2603", 939_000_000, 93_900_000, 845_100_000, 84.81, 113.0131),
    ("69142995", "101", "101", 121_750_000, 6_087_500, 115_662_500, 84.6814, 109.6254),
    ("69290744", "A", "102", 110_000_000, 11_000_000, 99_000_000, 59.71, 73.02),
    ("68963717", "301", "204", 186_300_000, 18_630_000, 167_670_000, 84.96, 111.721),
])
def test_checked_dwelling_total_and_printed_areas(fileid, building, room, total, down, balance, exclusive, supply):
    result = read(fileid)
    assert result["price_identity_confirmed"]
    projected, costs = project_prices([PricePublic(source="lh", **p) for p in result["prices"]], result["rules"])
    matches = [p for p in projected if p.building == building and p.room == room and p.area_sqm == exclusive]
    assert len(matches) == 1
    price = matches[0]
    assert (price.price_kind, price.amount_krw, price.supply_area_sqm) == ("sale_total", total, supply)
    assert [c.amount_krw for c in price.payment_components] == [down, balance]
    assert all(c.unit == "KRW" and c.evidence_page == price.evidence_page and c.document_hash == price.document_hash
               for c in price.payment_components)
    assert not costs


def test_fee_is_separate_and_equal_prices_keep_different_dwellings():
    result = read("67196474")
    prices, costs = project_prices([], result["rules"])
    assert not prices
    assert {(c.kind, c.amount_krw) for c in costs} == {("management_deposit", 238_000), ("management_deposit", 236_000)}
    result = read("69298075")
    prices, _ = project_prices([], result["rules"])
    assert len(prices) == 8
    assert {p.room for p in prices if p.amount_krw == 323_000_000} == {"1104", "1204", "1604"}
    assert {p.building for p in prices} == {"103"}


def test_same_hash_rebuild_retires_wrong_rent_and_preserves_api_and_manual_prices():
    result = read("69315656")
    digest = FIXTURES["69315656"]["document_hash"]
    stale = {"price_kind": "deposit", "verification": "ai_unverified", "unit_type": "4016동 2603호",
             "amount_krw": 845_100_000, "basis_label": "분양가격 잔금", "document_hash": digest}
    api = {"price_kind": "sale_max", "verification": "official", "unit_type": "84A", "amount_krw": 1_000_000_000}
    manual = {**stale, "verification": "official", "price_kind": "sale_total", "basis_label": "검토 보정"}
    merged = rebuild_document_prices([stale, api, manual], result["prices"], result["rules"], digest)
    assert stale not in merged and api in merged and manual in merged
    assert rebuild_document_prices(merged, result["prices"], result["rules"], digest) == merged
    assert not read("69315656", announcement_date="2026-11-04")["price_identity_confirmed"]
    assert not read("69315656", title="다른 사업 파주시")["price_identity_confirmed"]


def test_supplement_is_bound_to_current_hash_role_and_url():
    result = read("69315656")
    detail = next(r for r in result["rules"] if r["kind"] == "price_details")
    primary = "a" * 64
    attached = {**detail, "source_document_role": "price_table", "selected_document_hash": primary}
    attachment = {"role": "price_table", "document_hash": detail["document_hash"], "url": detail["evidence_url"],
                  "selected_document_hash": primary}
    bundle = {"kind": "document_bundle", "source": "official_document_parser", "verification": "official",
              "document_hash": primary, "documents": [attachment]}
    assert current_price_rule(attached, {"document_hash": primary, "rules": [bundle]})
    assert not current_price_rule(attached, {"document_hash": "b" * 64, "rules": [bundle]})
    assert not current_price_rule({**attached, "evidence_url": "https://apply.lh.or.kr/other.pdf"},
                                  {"document_hash": primary, "rules": [bundle]})


def test_grouped_rooms_and_interim_payment_without_converting_rental_amounts():
    payload = {"title": "테스트단지 일반매각", "announcement_date": "2026-11-12"}
    pages = [{"page": 1, "text": """테스트단지 일반매각 모집공고일 2026.11.12.
분양가격(원) 전용면적 주거공용 소계 계 계약금 중도금 잔금
101 201, 301 59.7100 13.3100 73.0200 110,000,000 11,000,000 44,000,000 55,000,000"""}]
    result = parse_price_tables(pages, url="https://apply.lh.or.kr/current.pdf", digest="a" * 64, payload=payload)
    prices, _ = project_prices([], result["rules"])
    assert len(prices) == 1 and prices[0].room == "201, 301"
    assert [c.kind for c in prices[0].payment_components] == ["down_payment", "interim_payment", "balance"]
    rental = [{"page": 1, "text": "테스트단지 임대 모집공고일 2026.11.12. 전용면적 임대보증금 계약금 잔금 월임대료"}]
    assert not parse_price_tables(rental, url="https://apply.lh.or.kr/current.pdf", digest="a" * 64, payload=payload)["rules"]


def test_changwon_price_appendix_requires_selected_primary_and_its_printed_date():
    url = "https://apply.lh.or.kr/lhapply/lhFile.do?fileid=67196489"
    digest = "3cbef63cfd6e3b73909d22f1bb8ddbdeb13ff5a54303c3ddf8b1b17e35eb37ee"
    pages = [{"page": 1, "text": """공급대상 및 공급가격 - '26.06.10. 기준
(면적단위: ㎡, 금액단위: 원)
순번 동 호 계약면적단지 분양가격(원)공급면적 공용면적
계 전용 주거공용 기타공용 지하주차장 총 주택가격 계약금(10%) 잔금
1 우림필유 114 301 112.4600 84.9900 27.4700 2.6600 32.7300 148.9100 331,000,000 33,100,000 297,900,000
2 청안해오름 103 1501 112.9928 84.9170 28.0758 0.0000 18.1210 131.1138 88,000,000 8,800,000 79,200,000"""}]
    payload = FIXTURES["67196474"]["payload"]
    assert not parse_price_tables(pages, url=url, digest=digest, payload=payload)["prices"]
    linked = {**payload, "price_appendix_reference": {"url": url, "selected_document_hash": FIXTURES["67196474"]["document_hash"]}}
    parsed = parse_price_tables(pages, url=url, digest=digest, payload=linked)
    prices, _ = project_prices([], parsed["rules"])
    assert {(p.building, p.room, p.amount_krw, p.supply_area_sqm) for p in prices} == {
        ("114", "301", 331_000_000, 112.46), ("103", "1501", 88_000_000, 112.9928),
    }
    assert not parse_price_tables(pages, url=url, digest=digest, payload={**linked, "announcement_date": "2026-06-11"})["prices"]


def test_actual_a2_price_tiers_use_printed_thousand_won_and_separate_unit_options():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "public-family-a2-20261030.json").read_text())
    parsed = parse_price_tables(fixture["pages"], url=fixture["document_url"], digest=fixture["document_hash"], payload=fixture["payload"])
    prices, costs = project_prices([PricePublic(source="lh", **p) for p in parsed["prices"]], parsed["rules"])
    assert len(prices) == 4 and len(costs) == 9
    assert len({(cost.building, cost.room) for cost in costs}) == 9
    assert next(cost for cost in costs if (cost.building, cost.room) == ("208", "1203")).amount_krw == 10_972_000
    row = next(p for p in prices if p.unit_type == "55C · 3층")
    assert row.amount_krw == 363_300_000 and row.price_kind == "sale_total"
    assert [c.amount_krw for c in row.payment_components] == [36_330_000, 271_970_000, 55_000_000]
    assert "이용 불가" in row.payment_components[-1].label
    assert row.evidence_page == 4 and all(cost.evidence_page == 5 for cost in costs)
