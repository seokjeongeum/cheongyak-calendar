"""Current residual quantities survive new identities and changed source tables."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from app.extract.residual_inventory import residual_document_inventory


SOURCE = json.loads((Path(__file__).parent / "fixtures/gajeong-admission-v8.json").read_text())


def table_pages():
    return [copy.deepcopy(next(page for page in SOURCE["pages"] if page["page"] == 3))]


def test_current_quantities_and_merged_dwelling_choices_match_the_official_source():
    result = residual_document_inventory(SOURCE["pages"])
    assert result.status == "verified"
    assert result.total_households == 308
    assert result.current_supply_count == 252
    assert [(row["unit_type"], row["supply_count"]) for row in result.rows] == [
        ("74.9500A", 18), ("84.0000A", 154), ("84.0000B", 58), ("84.9800C", 22)]
    assert all(row["evidence_page"] == 3 for row in result.rows)
    # 84A/84A1/84A2 are physical subtypes of one offered dwelling choice.
    assert all(row["unit_type"] not in {"84A", "84A1", "84A2"} for row in result.rows)
    assert "1’28.07" in result.rows[1]["evidence_text"]


def test_new_dwelling_codes_valid_changed_quantities_and_arbitrary_page_are_read():
    pages = table_pages()
    pages[0]["page"] = 37
    pages[0]["text"] = pages[0]["text"].replace("74.9500A", "073.1200X").replace(
        "41 23 18 23 0", "51 25 26 23 0").replace("합 계 308 56 252 7", "합 계 318 58 260 7")
    result = residual_document_inventory(pages)
    assert result.status == "verified"
    assert result.total_households == 318 and result.current_supply_count == 260
    assert result.rows[0]["unit_type"] == "073.1200X"
    assert result.rows[0]["supply_count"] == 26
    assert result.rows[0]["evidence_page"] == 37


def test_stock_and_current_columns_cannot_be_interchanged_or_silently_reconciled():
    pages = table_pages()
    pages[0]["text"] = pages[0]["text"].replace("41 23 18 23 0", "41 23 41 23 0")
    result = residual_document_inventory(pages)
    assert result.status == "conflict" and result.rows == []
    pages = table_pages()
    pages[0]["text"] = pages[0]["text"].replace("합 계 308 56 252 7", "합 계 308 56 253 7")
    result = residual_document_inventory(pages)
    assert result.status == "conflict" and result.rows == []


def test_current_column_evidence_and_table_context_are_required():
    for old, new in [("금회공급", "금회가격"), ("2. 공급대상", "2. 공급가격")]:
        pages = table_pages()
        pages[0]["text"] = pages[0]["text"].replace(old, new)
        result = residual_document_inventory(pages)
        assert result.status != "verified" and result.rows == []


def test_missing_or_duplicate_offered_dwelling_row_keeps_inventory_unverified():
    pages = table_pages()
    line = next(line for line in pages[0]["text"].splitlines() if line.startswith("74.9500A"))
    for replacement in ["", line + "\n" + line]:
        changed = copy.deepcopy(pages)
        changed[0]["text"] = changed[0]["text"].replace(line, replacement)
        result = residual_document_inventory(changed)
        assert result.status != "verified" and result.rows == []


def test_supply_table_can_continue_on_the_next_source_page():
    pages = table_pages()
    text = pages[0]["text"]
    split = text.index("84.0000B 84B")
    pages = [{"page": 21, "text": text[:split]}, {"page": 22, "text": text[split:]}]
    result = residual_document_inventory(pages)
    assert result.status == "verified" and result.current_supply_count == 252
    assert [row["evidence_page"] for row in result.rows] == [21, 21, 22, 22]


def test_several_current_tables_need_explicit_block_or_round_identity_before_merging():
    pages = table_pages()
    duplicate = copy.deepcopy(pages[0])
    duplicate["page"] = 18
    result = residual_document_inventory([*pages, duplicate])
    assert result.status == "partial" and result.rows == []
