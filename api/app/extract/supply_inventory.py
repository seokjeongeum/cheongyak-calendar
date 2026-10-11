"""Read positive allocations from an official dwelling/supply table.

Table totals are checked before a row is published. A section heading, a special
application date, or a total special count does not invent a supply subtype.
"""

import re

from .supply_tables import normalize_unit, ordinary_document_inventory, residual_dong_inventory, residual_geometry_inventory

SPECIAL_COLUMNS = ("기관추천", "다자녀가구", "신혼부부", "노부모부양", "생애최초", "신생아", "청년", "이전기관종사자")


def canonical_unit(value):
    return normalize_unit(value)


def document_supplies(pages, *, make):
    """Supported table layouts: residual, type-specific special, ordinary APT.

The final decimal belongs to the area/land-share block. Only the integer count
columns after it are read. Total and special subtotal must reconcile exactly.
"""
    ordinary = _document_inventory(pages, make=make)
    if ordinary.status != "missing":
        return [row for row in ordinary.cells.values() if row["supply_count"] > 0] if ordinary.status == "verified" else []
    return _other_document_supplies(pages, make=make)


def _other_document_supplies(pages, *, make):
    supplies = []
    for index, page in enumerate(pages):
        # Some PDFs split the supply heading and its table across pages.
        body = page["text"]
        previous = pages[index - 1]["text"] if index else ""
        if "공급대상" not in re.sub(r"\s+", "", body) and "공급대상" not in re.sub(r"\s+", "", previous[-700:]):
            continue
        body = re.split(r"(?:■|\n)\s*공급금액(?:\s|표|및)", body)[0]
        rows = []
        for line in body.splitlines():
            unit = re.search(r"(?<![\d.])(\d{2,3}\.\d{4}[A-Z]?)(?![\d.])", line)
            if not unit:
                continue
            decimals = list(re.finditer(r"(?<![\d.])\d+\.\d+(?![\d.])", line[unit.end():]))
            if not decimals:
                continue
            last = unit.end() + decimals[-1].end()
            tail = line[last:].strip()
            if not re.fullmatch(r"(?:[\d,]+|-)(?:\s+(?:[\d,]+|-))*", tail):
                continue
            counts = [0 if value == "-" else int(value.replace(",", "")) for value in tail.split()]
            rows.append((canonical_unit(unit[1]), counts, line))
        if not rows:
            continue
        header = re.sub(r"\s+", "", body[:body.find(rows[0][2])])
        names = sorted((name for name in SPECIAL_COLUMNS if name in header), key=header.find)
        general = "일반공급" in header
        residual = "잔여세대수" in header or ("잔여" in header and not names and not general)
        if not (names or general or residual):
            continue
        has_special_subtotal = bool(names and re.search(r"신생아계|최초계|부양계|특별공급계", header))
        valid = True
        parsed = []
        for unit, values, line in rows:
            if residual:
                if len(values) != 1:
                    valid = False; break
                allocations = [("일반공급", values[0])]
            else:
                # total, named special columns, optional special subtotal,
                # general, optional lowest-floor allocation (not a supply type).
                expected = 1 + len(names) + int(has_special_subtotal) + int(general)
                if len(values) not in (expected, expected + int("최하층" in header)):
                    valid = False; break
                position = 1
                allocations = [(name + " 특별공급", values[position + i]) for i, name in enumerate(names)]
                position += len(names)
                if has_special_subtotal:
                    if values[position] != sum(count for _, count in allocations):
                        valid = False; break
                    position += 1
                if general:
                    allocations.append(("일반공급", values[position]))
                if values[0] != sum(count for _, count in allocations):
                    valid = False; break
            for supply, count in allocations:
                if count > 0:
                    evidence = make("offered_supplies", effect="metadata", quote=line, page=page["page"])
                    parsed.append({"supply_type": supply, "unit_type": unit, "supply_count": count,
                                   **{key: evidence.get(key) for key in ("verification", "source", "evidence_url", "evidence_text", "evidence_page", "document_hash", "criterion_date")}})
        if valid:
            supplies.extend(parsed)
    unique = {(row["supply_type"], row["unit_type"]): row for row in supplies}
    return list(unique.values())


def _document_inventory(pages, *, make):
    ordinary = ordinary_document_inventory(pages, make=make)
    if ordinary.status != "missing":
        return ordinary
    residual = residual_dong_inventory(pages, make=make)
    return residual_geometry_inventory(pages, make=make) if residual.status == "missing" else residual


def official_supplies(pages, payload, *, make):
    ordinary = _document_inventory(pages, make=make)
    supply_rules = [rule for rule in payload.get("rules", []) if rule.get("kind") == "offered_supplies" and rule.get("verification") == "official"]
    # Original service cells precede saved parser copies, but are never edited.
    supply_rules.sort(key=lambda rule: rule.get("source") == "official_document_parser")
    supplied = {}
    # The current document's identity also applies when its table is partial
    # or absent. A stale saved interpretation must not reappear merely because
    # the new attachment cannot be read well enough to emit a table cell.
    current_hash = make("offered_supplies", effect="metadata").get("document_hash")
    for rule in supply_rules:
        if (rule.get("source") == "official_document_parser" and current_hash
                and rule.get("document_hash") and rule["document_hash"] != current_hash):
            continue
        if rule.get("inventory_status") == "conflict" and rule.get("source") != "official_document_parser":
            return [], "conflict"
        for row in rule.get("supplies", []):
            if not isinstance(row, dict) or type(row.get("supply_count")) is not int or row["supply_count"] <= 0:
                continue
            key = (row.get("supply_type"), canonical_unit(row.get("unit_type")))
            if not all(key):
                continue
            if key in supplied and supplied[key]["supply_count"] != row["supply_count"]:
                return [], "conflict"
            supplied.setdefault(key, row)
    source = list(supplied.values())
    if ordinary.status == "verified":
        if any(key not in ordinary.cells or ordinary.cells[key]["supply_count"] != row["supply_count"] for key, row in supplied.items()):
            return [], "conflict"
        return [supplied.get(key, row) for key, row in ordinary.cells.items() if row["supply_count"] > 0], "verified"
    if ordinary.status in {"conflict", "partial"}:
        # Original rows can remain visible, but an unreadable or contradictory
        # PDF table cannot certify completeness or restore a missing subtype.
        return source if ordinary.status == "partial" else [], ordinary.status
    document = _other_document_supplies(pages, make=make)
    if document and source:
        a = {(r["supply_type"], canonical_unit(r["unit_type"])): r["supply_count"] for r in document}
        b = {(r["supply_type"], canonical_unit(r["unit_type"])): r["supply_count"] for r in source}
        # Never silently choose an allocation when current official sources
        # conflict. Recollection/review resolves it, and no type is invented.
        if any(key in a and a[key] != count for key, count in b.items()):
            return [], "conflict"
    merged = {(r["supply_type"], canonical_unit(r["unit_type"])): r for r in document}
    merged.update(supplied)
    return list(merged.values()), "verified" if merged else "missing"
