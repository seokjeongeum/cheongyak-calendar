"""Read positive allocations from an official dwelling/supply table.

Table totals are checked before a row is published. A section heading, a special
application date, or a total special count does not invent a supply subtype.
"""

import re

SPECIAL_COLUMNS = ("기관추천", "다자녀가구", "신혼부부", "노부모부양", "생애최초", "신생아", "청년", "이전기관종사자")


def canonical_unit(value):
    text = str(value).strip()
    match = re.fullmatch(r"(\d{2,3})\.(\d{4})([A-Z]?)", text)
    return f"{int(match[1]):03d}.{match[2]}{match[3]}" if match else text


def document_supplies(pages, *, make):
    """Supported table layouts: residual, type-specific special, ordinary APT.

The final decimal belongs to the area/land-share block. Only the integer count
columns after it are read. Total and special subtotal must reconcile exactly.
"""
    supplies = []
    for index, page in enumerate(pages[:15]):
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


def official_supplies(pages, payload, *, make):
    document = document_supplies(pages, make=make)
    source = [row for rule in payload.get("rules", []) if rule.get("kind") == "offered_supplies" and rule.get("verification") == "official"
              for row in rule.get("supplies", []) if isinstance(row, dict) and isinstance(row.get("supply_count"), int) and row["supply_count"] > 0]
    if document and source:
        a = {(r["supply_type"], canonical_unit(r["unit_type"])): r["supply_count"] for r in document}
        b = {(r["supply_type"], canonical_unit(r["unit_type"])): r["supply_count"] for r in source}
        # Never silently choose an allocation when current official sources
        # conflict. Recollection/review resolves it, and no type is invented.
        if any(key in a and a[key] != count for key, count in b.items()):
            return [], "conflict"
    return document or source, "verified" if document or source else "missing"
