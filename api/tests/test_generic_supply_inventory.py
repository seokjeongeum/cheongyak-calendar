"""A fresh notice's quantities come from its table, never a project fixture."""
import copy
import json
from pathlib import Path

import pytest

from app.extract.supply_inventory import official_supplies
from app.extract.supply_tables import ordinary_document_inventory

FIXTURES = Path(__file__).parent / "fixtures"
CURRENT = next(row for row in json.loads((FIXTURES / "current-oct8-regions.json").read_text())
               if row["external_id"] == "2026000458")
SIX_FEED = json.loads((FIXTURES / "sangok-current-six-feed.json").read_text())


def make(kind, **values):
    return {"verification": "official", "source": "official_document_parser", "document_hash": "fresh-document",
            "criterion_date": "2027-04-12", "evidence_url": "https://official.example/new-notice.pdf",
            "evidence_page": values.get("page"), "evidence_text": values.get("quote")}


def payload(rows=None):
    rows = copy.deepcopy(SIX_FEED["supplies"] if rows is None else rows)
    return {"rules": [{"kind": "offered_supplies", "verification": "official", "source": "source_api",
                       "supplies": rows}]}


def table(page=6):
    text = next(p["text"] for p in CURRENT["pages"] if p["page"] == 6)
    # A changed project, current issue date and identifier do not control the
    # generic reader. The test is independently about the document table.
    text = text.replace("산곡역자이힐스테이트앤하늘채", "새봄 아파트").replace("2026000458", "2027000999")
    return [{"page": page, "text": text}]


def stock(rows):
    return {(row["supply_type"], row["unit_type"]): row["supply_count"] for row in rows}


def test_actual_six_column_feed_is_preserved_and_missing_column_restored_from_generic_table():
    supplied = payload()
    # A duplicated saved parser inventory is not a new allocation.
    supplied["rules"].insert(0, {"kind": "offered_supplies", "verification": "official",
                                "source": "official_document_parser", "document_hash": "fresh-document",
                                "supplies": copy.deepcopy(SIX_FEED["supplies"] * 2)})
    rows, status = official_supplies(table(), supplied, make=make)
    assert status == "verified" and len(rows) == 62
    assert sum(row["supply_count"] for row in rows) == 1289
    by_key = {(row["supply_type"], row["unit_type"]): row for row in rows}
    for original in supplied["rules"][1]["supplies"]:
        assert by_key[original["supply_type"], original["unit_type"]] is original
    newborn = [row for row in rows if row["supply_type"] == "신생아 특별공급"]
    assert len(newborn) == 9 and sum(row["supply_count"] for row in newborn) == 126
    assert all(row["document_hash"] == "fresh-document" and row["criterion_date"] == "2027-04-12" for row in newborn)
    assert ("노부모부양 특별공급", "084.9200A") not in by_key


def test_new_units_quantities_pages_and_columns_are_read_from_the_current_table():
    pages = table(page=29)
    pages[0]["text"] = pages[0]["text"].replace("050.2600A", "051.9876PX")
    # Increase a newborn allocation: the row total, special subtotal and the
    # printed column totals all change consistently. No cached total is used.
    pages[0]["text"] = pages[0]["text"].replace("112 11 10 16 3 7 11 58 54 4", "113 11 10 16 3 7 12 59 54 4")
    pages[0]["text"] = pages[0]["text"].replace("1,289 126 122 190 35 86 126 685 604 88", "1,290 126 122 190 35 86 127 686 604 88")
    rows, status = official_supplies(pages, {"rules": []}, make=make)
    assert status == "verified" and sum(row["supply_count"] for row in rows) == 1290
    assert stock(rows)["신생아 특별공급", "051.9876PX"] == 12
    assert all(row["evidence_page"] == 29 for row in rows)
    assert not any(row["unit_type"] == "050.2600A" for row in rows)


def test_header_order_can_change_when_row_and_aggregate_columns_change_together():
    pages = table()
    text = pages[0]["text"].replace("기관 다자녀 신혼 노부모 생애 신생아 계", "다자녀 기관 신혼 노부모 생애 신생아 계")
    text = text.replace("추천 가구 부부 부양 최초 세대수 세대수", "가구 추천 부부 부양 최초 세대수 세대수")
    lines = []
    for line in text.splitlines():
        if " " in line and (".2600" in line or ".9500" in line or ".9900" in line or ".9300" in line or ".5600" in line or ".6200" in line or ".9200" in line or ".9800" in line):
            values = line.split()
            if len(values) >= 10 and all(value.replace(",", "").isdigit() or value == "-" for value in values[-10:]):
                values[-9], values[-8] = values[-8], values[-9]
                line = " ".join(values)
        if line.startswith("합 계 "):
            values = line.split()
            values[3], values[4] = values[4], values[3]
            line = " ".join(values)
        lines.append(line)
    pages[0]["text"] = "\n".join(lines)
    rows, status = official_supplies(pages, payload(), make=make)
    assert status == "verified"
    for original in SIX_FEED["supplies"]:
        assert stock(rows)[original["supply_type"], original["unit_type"]] == original["supply_count"]


def test_table_continues_across_pages_and_accepts_a_printed_total_above_rows():
    pages = table(page=32)
    text = pages[0]["text"]
    marker = "합 계 1,289 126 122 190 35 86 126 685 604 88"
    text = text.replace(marker + "\n", "")
    text = text.replace("01 050.2600A", marker + "\n01 050.2600A")
    first, rest = text.split("06 075.5600A", 1)
    rows, status = official_supplies([{"page": 32, "text": first}, {"page": 33, "text": "06 075.5600A" + rest}], {}, make=make)
    assert status == "verified" and len(rows) == 62
    assert {row["evidence_page"] for row in rows} == {32, 33}


@pytest.mark.parametrize("old,new,status", [
    ("112 11 10 16 3 7 11 58 54 4", "112 11 10 16 3 7 10 58 54 4", "conflict"),
    ("1,289 126 122 190 35 86 126 685 604 88", "1,288 126 122 190 35 86 126 685 604 88", "conflict"),
    ("기관 다자녀 신혼 노부모 생애 신생아 계", "기관 다자녀 신혼 노부모 생애 신생아", "partial"),
    ("기관 다자녀 신혼 노부모 생애 신생아 계", "기관 다자녀 신혼 노부모 생애 신생아 계 계", "partial"),
    ("합 계 1,289 126 122 190 35 86 126 685 604 88", "", "partial"),
    ("112 11 10 16 3 7 11 58 54 4", "112 11 10 16 -3 7 11 58 54 4", "partial"),
])
def test_bad_numbers_or_ambiguous_headers_cannot_restore_or_certify_inventory(old, new, status):
    pages = table()
    assert old in pages[0]["text"]
    pages[0]["text"] = pages[0]["text"].replace(old, new)
    rows, actual = official_supplies(pages, payload(), make=make)
    assert actual == status
    assert not any(row["supply_type"] == "신생아 특별공급" for row in rows)


@pytest.mark.parametrize("change", ["count", "extra_unit", "zero_cell", "duplicate_conflict"])
def test_current_api_conflicts_are_explicit_and_never_overwritten(change):
    supplied = payload()
    rows = supplied["rules"][0]["supplies"]
    if change == "count":
        rows[0]["supply_count"] += 1
    elif change == "extra_unit":
        rows.append({**rows[0], "unit_type": "099.9999X"})
    elif change == "zero_cell":
        rows.append({**rows[0], "unit_type": "084.9200A", "supply_type": "노부모부양 특별공급", "supply_count": 1})
    else:
        rows.append({**rows[0], "supply_count": rows[0]["supply_count"] + 1})
    assert official_supplies(table(), supplied, make=make) == ([], "conflict")


def test_other_rounds_and_public_residual_headers_do_not_inherit_private_inventory():
    pages = table()
    pages[0]["text"] = pages[0]["text"].replace("01 050.2600A", "1,2회차 050.2600A")
    assert ordinary_document_inventory(pages, make=make).status == "partial"
    residual = [{"page": 27, "text": "■ 공급대상\n잔여세대수\n01 050.2600A 50.2600 3\n합 계 3"}]
    assert ordinary_document_inventory(residual, make=make).status == "missing"
    rows, status = official_supplies(residual, {}, make=make)
    assert status == "verified" and stock(rows) == {("일반공급", "050.2600A"): 3}


def test_general_only_table_uses_its_totals_and_never_invents_a_special_subtype():
    pages = [{"page": 22, "text": "■ 공급대상\n주택형 총공급 일반공급 최하층 우선배정\n01 063.4567A 63.4567 8 8 2\n02 080.1234B 80.1234 2 2 0\n합 계 10 10 2"}]
    rows, status = official_supplies(pages, {}, make=make)
    assert status == "verified" and stock(rows) == {("일반공급", "063.4567A"): 8, ("일반공급", "080.1234B"): 2}
    pages[0]["text"] = pages[0]["text"].replace("합 계 10 10 2", "합 계 11 11 2")
    assert official_supplies(pages, {}, make=make) == ([], "conflict")


def test_zero_stock_has_no_offered_rows_and_old_parser_hash_cannot_conflict_with_new_document():
    text = "■ 공급대상\n총공급 특별공급 세대수 일반공급\n기관추천 계\n01 050.2600A 50.2600 0 0 0 0\n합 계 0 0 0 0"
    assert official_supplies([{"page": 20, "text": text}], {}, make=make) == ([], "partial")
    supplied = payload()
    supplied["rules"].append({"kind": "offered_supplies", "verification": "official", "source": "official_document_parser",
                              "document_hash": "old-document", "inventory_status": "conflict",
                              "supplies": [{**SIX_FEED["supplies"][0], "supply_count": 999}]})
    rows, status = official_supplies(table(), supplied, make=make)
    assert status == "verified" and sum(row["supply_count"] for row in rows) == 1289


@pytest.mark.parametrize("file,identity,cells,total", [
    ("regional-v5.json", "2026910251", 2, 35),
    ("regional-v5.json", "2026930038", 4, 6),
    ("regional-v5.json", "2026930039", 2, 3),
    ("regional-v5.json", "2026000498", 14, 61),
    ("current-private-v5.json", "2026910253", 1, 12),
    ("current-regional-v9.json", "2026910256", 7, 785),
    ("hyangnam-regional-v9.json", "2026000463", 42, 933),
    ("cheonan-corrected-20261008.json", "2026000498", 14, 61),
])
def test_actual_residual_and_corrected_layouts_read_current_source_counts(file, identity, cells, total):
    data = json.loads((FIXTURES / file).read_text())
    fixtures = data if isinstance(data, list) else [data]
    document = next(row for row in fixtures if row.get("external_id", row.get("house_manage_no")) == identity)
    pages = copy.deepcopy(document["pages"])
    # Identities and page positions are fixture selectors, never parser input
    # decisions. The same table must still work in a differently named notice.
    for page in pages:
        page["text"] = page["text"].replace(identity, "2031000123")
        page["page"] += 19
    rows, status = official_supplies(pages, {}, make=make)
    assert status == "verified" and len(rows) == cells
    assert sum(row["supply_count"] for row in rows) == total
    assert all(row["supply_count"] > 0 and row["evidence_page"] >= 20 for row in rows)


def test_special_only_and_no_subtotal_tables_need_no_invented_general_or_subtotal_columns():
    pages = [{"page": 38, "text": "■ 공급대상\n주택형 총공급 특별공급\n생애최초\n01 061.1111Z 61.1111 5 5\n합 계 5 5"}]
    rows, status = official_supplies(pages, {}, make=make)
    assert status == "verified" and stock(rows) == {("생애최초 특별공급", "061.1111Z"): 5}
    pages[0]["text"] = "■ 공급대상\n주택형 총공급 특별공급 일반공급\n노부모부양\n01 061.1111Z 61.1111 7 2 5\n합 계 7 2 5"
    rows, status = official_supplies(pages, {}, make=make)
    assert status == "verified" and stock(rows) == {("노부모부양 특별공급", "061.1111Z"): 2, ("일반공급", "061.1111Z"): 5}
    pages[0]["text"] = pages[0]["text"].replace("7 2 5", "8 2 5")
    assert official_supplies(pages, {}, make=make) == ([], "conflict")


def test_concatenated_area_columns_are_only_delimiters_and_quantities_still_need_matching_totals():
    pages = [{"page": 45, "text": "■ 공급대상\n주택형 총공급 특별공급 일반공급\n생애최초 계\n01 091.2345X 91.2345 18.8765110.1110 55.5000165.6110 8 3 3 5\n합 계 8 3 3 5"}]
    rows, status = official_supplies(pages, {}, make=make)
    assert status == "verified" and stock(rows) == {("생애최초 특별공급", "091.2345X"): 3, ("일반공급", "091.2345X"): 5}
    pages[0]["text"] = pages[0]["text"].replace("8 3 3 5", "9 4 4 5")
    rows, status = official_supplies(pages, {}, make=make)
    assert status == "verified" and stock(rows)["생애최초 특별공급", "091.2345X"] == 4
    pages[0]["text"] = pages[0]["text"].replace("합 계 9 4 4 5", "합 계 10 4 4 5")
    assert official_supplies(pages, {}, make=make) == ([], "conflict")


def test_roomlist_allocations_ignore_building_numbers_and_require_printed_total():
    pages = [{"page": 51, "text": "■ 공급대상\n주택형 약식표기 잔여세대수 동 호\n070.1111A 70A 3 101 201, 202, 203\n084.9999B 84B 0 102 -\n합 계 3세대 －\n계약 절차 ※\n070.1111A 70A 999 103 999"}]
    rows, status = official_supplies(pages, {}, make=make)
    assert status == "verified" and stock(rows) == {("일반공급", "070.1111A"): 3}
    pages[0]["text"] = pages[0]["text"].replace("3세대", "4세대")
    assert official_supplies(pages, {}, make=make) == ([], "conflict")


def test_residual_area_table_validates_aggregate_and_never_duplicates_current_reserve_counts():
    pages = [{"page": 49, "text": "■ 공급대상\n주택형 주택공급면적 잔여세대수\n01 082.3333X 82.3333 17.000099.3333 4\n02 079.2222Z 79.2222 2\n합 계 6\n■ 공급금액 표\n082.3333X 82.3333 999"}]
    rows, status = official_supplies(pages, {}, make=make)
    assert status == "verified" and stock(rows) == {("일반공급", "082.3333X"): 4, ("일반공급", "079.2222Z"): 2}
    pages[0]["text"] = pages[0]["text"].replace("합 계 6", "합 계 7")
    assert official_supplies(pages, {}, make=make) == ([], "conflict")
    pages[0]["text"] = pages[0]["text"].replace("잔여세대수", "잔여세대수 금회공급 예비자")
    from app.extract.supply_tables import residual_geometry_inventory
    assert residual_geometry_inventory(pages, make=make).status == "missing"


def test_changed_unreadable_document_cannot_reuse_saved_stock_from_old_hash():
    pages = table()
    pages[0]["text"] = pages[0]["text"].replace("합 계 1,289 126 122 190 35 86 126 685 604 88", "")
    supplied = {"rules": [{"kind": "offered_supplies", "verification": "official", "source": "official_document_parser",
                           "document_hash": "old-document", "supplies": copy.deepcopy(SIX_FEED["supplies"])}]}
    assert official_supplies(pages, supplied, make=make) == ([], "partial")
    supplied["rules"].append(payload()["rules"][0])
    rows, status = official_supplies(pages, supplied, make=make)
    assert status == "partial" and rows == supplied["rules"][1]["supplies"]
