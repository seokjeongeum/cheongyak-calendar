"""Read current residual quantities separately from a complex's total stock.

The table must name total / already supplied / current supply columns and
reconcile every current dwelling row with the printed aggregates. Physical
subtypes without a dwelling code never become separate application choices.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


UNIT = re.compile(r"(?<![\d.])(\d{2,3}\.\d{4}[A-Z][A-Z0-9-]*)(?![\d.])")
AREA = re.compile(r"(?<![\d.])\d+\.\d{3,}(?![\d.])")
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+|-)"
HEADING = re.compile(r"^\s*(?:[■❚]|\d+[.]?)?\s*공\s*급\s*대\s*상(?:\s|[:(（]|$)")


@dataclass
class ResidualInventory:
    status: str = "missing"
    rows: list[dict] = field(default_factory=list)
    total_households: int | None = None
    current_supply_count: int | None = None


def _integer(value):
    return 0 if value == "-" else int(value.replace(",", ""))


def _count_columns(header):
    compact = re.sub(r"\s+", "", header)
    # Exact current-column semantics keep a price, old round or area table
    # from acquiring quantities by a coincidental sequence of integers.
    matched = re.search(r"(?:합계|계)기공급금회공급", compact)
    if not matched or "주택형" not in compact or "공급세대수" not in compact:
        return None
    remainder = compact[matched.end():]
    floor = "층수" in remainder and "최고" in compact
    ground = "1층" in compact and "세대수" in remainder
    return floor, ground


def _parse_table(lines):
    first = next((i for i, (_, line) in enumerate(lines) if UNIT.search(line)), None)
    if first is None:
        return ResidualInventory()
    header = "\n".join(line for _, line in lines[:first])
    columns = _count_columns(header)
    if columns is None:
        return ResidualInventory()
    floor, ground = columns
    expected = 3 + int(floor) + int(ground)
    printed_totals = []
    for _, line in lines[:first]:
        total = re.fullmatch(r"\s*합\s*계\s+((?:" + NUMBER + r")(?:\s+(?:" + NUMBER + r"))*)\s*", line)
        if total:
            values = [_integer(value) for value in total[1].split()]
            if len(values) != 3 + int(ground):
                return ResidualInventory("partial")
            if ground and values[-1] > values[2]:
                return ResidualInventory("conflict")
            printed_totals.append(values[:3])
    if len(printed_totals) != 1:
        return ResidualInventory("partial")
    rows, totals, seen = [], [0] * 3, set()
    counts = re.compile(r"^\s*" + r"\s+".join("(" + NUMBER + ")" for _ in range(expected)))
    for page, line in lines[first:]:
        if re.match(r"\s*(?:※|■|❚)", line):
            break
        unit = UNIT.search(line)
        if not unit:
            continue
        areas = list(AREA.finditer(line[unit.end():]))
        if not areas:
            return ResidualInventory("partial")
        tail = line[unit.end() + areas[-1].end():]
        matched = counts.match(tail)
        if not matched:
            return ResidualInventory("partial")
        # A merged occupation-date cell may immediately follow the ground
        # quantity, for example 1’28.07. It never joins the count columns.
        extra = tail[matched.end():].strip()
        if extra and not re.fullmatch(r"['’‘]?\d{2,4}[.년/-]\s*\d{1,2}(?:[.월/-]\s*\d{1,2})?\.?", extra):
            return ResidualInventory("partial")
        values = [_integer(value) for value in matched.groups()]
        if values[0] != values[1] + values[2]:
            return ResidualInventory("conflict")
        if ground and values[-1] > values[2]:
            return ResidualInventory("conflict")
        if unit[1] in seen:
            return ResidualInventory("partial")
        seen.add(unit[1])
        # Floor counts can belong to physical subtype cells split over the
        # next line. The three supply columns belong to the merged dwelling
        # code and must independently reconcile with their printed totals.
        totals = [a + b for a, b in zip(totals, values[:3])]
        if values[2] > 0:
            rows.append({"supply_type": "일반공급", "unit_type": unit[1], "supply_count": values[2],
                         "evidence_page": page, "evidence_text": line.strip()})
    if not rows or totals != printed_totals[0]:
        return ResidualInventory("conflict" if rows else "partial")
    return ResidualInventory("verified", rows, totals[0], totals[2])


def residual_document_inventory(pages):
    """Discover supported residual tables on any page in the current source."""
    lines = [(page["page"], line) for page in pages for line in page["text"].splitlines()]
    starts = [i for i, (_, line) in enumerate(lines) if HEADING.search(line)]
    result = ResidualInventory()
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        parsed = _parse_table(lines[start:end])
        if parsed.status == "missing":
            continue
        if parsed.status != "verified":
            return parsed
        if result.status == "verified":
            # Several independently printed current tables need a template
            # that identifies their block/round before they can be merged.
            return ResidualInventory("partial")
        result = parsed
    return result
