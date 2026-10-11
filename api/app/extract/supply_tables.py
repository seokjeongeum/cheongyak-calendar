"""Validate dwelling allocations from the table in the current document.

The supported layout identifies count columns from the table header, then
checks each dwelling subtotal and the printed column aggregates. Neither a
project identity nor an expected page, dwelling set or quantity is used.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


SPECIAL_NAMES = (
    ("기관", "추천", "기관추천"), ("다자녀", "가구", "다자녀가구"),
    ("신혼", "부부", "신혼부부"), ("노부모", "부양", "노부모부양"),
    ("생애", "최초", "생애최초"), ("신생아", "", "신생아"),
    ("청년", "", "청년"), ("이전기관종사자", "", "이전기관종사자"),
)
UNIT = re.compile(r"(?<![\d.])(\d{2,3}\.\d{4}(?:[A-Z][A-Z0-9-]*)?)(?![\d.])")
COUNT_TAIL = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+|-)(?:\s+(?:\d{1,3}(?:,\d{3})+|\d+|-))*")
# Some PDF text layers concatenate adjacent area columns (for example,
# ``142.963146.7137``). We only delimit the following allocation columns;
# never split that token or infer either geometric value from it.
AREA_TOKEN = re.compile(r"(?<!\S)\d+(?:\.\d+)+(?!\S)")
HEADING = re.compile(r"(?:■|❚|^|\n)\s*(?:\d+[.\s]*)?공\s*급\s*대\s*상(?!물)", re.MULTILINE)


@dataclass
class TableInventory:
    status: str = "missing"
    # Zero allocations remain here for conflict checking, never as offered rows.
    cells: dict[tuple[str, str], dict] = field(default_factory=dict)


def normalize_unit(value):
    text = str(value).strip()
    match = UNIT.fullmatch(text)
    if not match:
        return text
    whole, remainder = text.split(".", 1)
    return f"{int(whole):03d}.{remainder}"


def _numbers(text):
    text = text.strip().replace('－', '-').replace('−', '-')
    if not COUNT_TAIL.fullmatch(text):
        return None
    return [0 if value == "-" else int(value.replace(",", "")) for value in text.split()]


def _area_count_tail(line, unit):
    areas = list(AREA_TOKEN.finditer(line[unit.end():]))
    return _numbers(line[unit.end() + areas[-1].end():]) if areas else None


def _columns(header):
    """Resolve ordinary APT leaf columns, including vertically split words.

    A split institution/recommendation label is accepted only inside an
    explicit special-supply table. Group headers can appear on an earlier line
    than their leaves, so the named special leaves establish their own order.
    The total / special subtotal / general blocks must also be explicit.
    """
    compact = re.sub(r"\s+", "", header)
    if "총공급" not in compact:
        return None
    # Another round's combined stock cannot be assigned to the current round.
    if re.search(r"\d+\s*[,·/]\s*\d+\s*회차", header):
        return None
    general = "일반공급" in compact or (
        re.search(r"일반공(?:\s|$)", header) and re.search(r"(?:^|\s)급(?:\s|$)", header)
    ) or (re.search(r"(?:^|\s)일반(?:\s|$)", header) and re.search(r"(?:^|\s)공급(?:\s|$)", header))
    found = []
    split_suffixes = []
    for prefix, suffix, name in SPECIAL_NAMES:
        occurrences = list(re.finditer(r"(?<![가-힣])" + prefix, header))
        if not occurrences:
            continue
        if len(occurrences) != 1 or (suffix and suffix not in compact):
            return None
        found.append((occurrences[0].start(), name))
        if suffix and not re.search(prefix + r"\s*" + suffix, header):
            leaves = list(re.finditer(r"(?<![가-힣])" + suffix + r"(?![가-힣])", header))
            if len(leaves) != 1:
                return None
            split_suffixes.append((occurrences[0].start(), leaves[0].start()))
    if not found:
        return ([], "최하층" in compact, False, True) if general and "특별공급" not in compact else None
    if "특별공급" not in compact:
        return None
    if [leaf for _, leaf in sorted(split_suffixes)] != sorted(leaf for _, leaf in split_suffixes):
        return None
    # A named special column need not have a separate subtotal (a single
    # cancelled-supply subtype often has none). A group heading or the word
    # "계약" is not a subtotal. Multiple subtotal leaves are ambiguous.
    subtotals = list(re.finditer(r"(?<!\S)계(?!\S)|특별공급\s*(?:소계|합계|계)", header))
    if len(subtotals) > 1:
        return None
    if subtotals and subtotals[0].start() < max(position for position, _ in found):
        return None
    # A fully explicit, horizontal alternate ordering cannot inherit the
    # supported nested total/special/general layout by arithmetic coincidence.
    for line in header.splitlines():
        if "일반공급" in re.sub(r"\s+", "", line) and any(prefix in line for prefix, _, _ in SPECIAL_NAMES):
            general_position = re.search(r"일반\s*공급", line)
            special_positions = [line.find(prefix) for prefix, _, _ in SPECIAL_NAMES if prefix in line]
            if general_position and general_position.start() < min(special_positions):
                return None
    names = [name for _, name in sorted(found)]
    return names, "최하층" in compact, bool(subtotals), bool(general)


def _ordinary_table(lines, *, make):
    first = next((i for i, (_, text) in enumerate(lines) if UNIT.search(text)), None)
    if first is None:
        return TableInventory()
    header = "\n".join(text for _, text in lines[:first])
    before_totals = []
    header_lines = []
    for line in header.splitlines():
        total = re.match(r"\s*합\s*계\s+(.+)$", line)
        if total:
            before_totals.append(_numbers(total[1]))
        else:
            header_lines.append(line)
    header = "\n".join(header_lines)
    columns = _columns(header)
    if not columns:
        return TableInventory("partial")
    names, lowest, subtotal, general = columns
    expected = 1 + len(names) + int(subtotal) + int(general) + int(lowest)
    aggregates = [0] * expected
    totals = before_totals
    if any(values is None or len(values) != expected for values in totals):
        return TableInventory("partial")
    cells = {}
    row_count = 0
    for page, line in lines[first:]:
        if "※" in line or re.match(r"\s*(?:■|❚)", line):
            break
        unit = UNIT.search(line)
        if not unit:
            total = re.match(r"\s*합\s*계\s+(.+)$", line)
            if total:
                values = _numbers(total[1])
                if values is None or len(values) != expected:
                    return TableInventory("partial")
                totals.append(values)
            continue
        # Geometric area/land-share decimals precede the count columns.
        if re.search(r"\d+\s*[,·/]\s*\d+\s*회차", line[:unit.start()]):
            return TableInventory("partial")
        values = _area_count_tail(line, unit)
        if values is None or len(values) != expected:
            return TableInventory("partial")
        # Every column is nonnegative by grammar. Lowest-floor allocations are
        # included in the total and are never a distinct supply subtype.
        subtotal_index = 1 + len(names)
        general_index = subtotal_index + int(subtotal)
        if ((subtotal and values[subtotal_index] != sum(values[1:subtotal_index]))
                or values[0] != sum(values[1:subtotal_index]) + (values[general_index] if general else 0)):
            return TableInventory("conflict")
        if lowest and values[-1] > values[0]:
            return TableInventory("conflict")
        canonical = normalize_unit(unit[1])
        if any(key[1] == canonical for key in cells):
            # A repeated unit can represent another round/block. Do not add it
            # to the same dwelling merely because quantities are equal.
            return TableInventory("partial")
        evidence = make("offered_supplies", effect="metadata", quote=line.strip(), page=page)
        allocation_names = names + (["일반공급"] if general else [])
        allocation_values = values[1:subtotal_index] + ([values[general_index]] if general else [])
        for name, count in zip(allocation_names, allocation_values):
            supply = name if name == "일반공급" else name + " 특별공급"
            cells[supply, canonical] = {
                "supply_type": supply, "unit_type": canonical, "supply_count": count,
                **{key: evidence.get(key) for key in ("verification", "source", "evidence_url", "evidence_text", "evidence_page", "document_hash", "criterion_date")},
            }
        aggregates = [a + b for a, b in zip(aggregates, values)]
        row_count += 1
    if not row_count or not totals:
        return TableInventory("partial")
    if len(totals) != 1 or totals[0] != aggregates:
        return TableInventory("conflict")
    if not any(row["supply_count"] > 0 for row in cells.values()):
        return TableInventory("partial")
    return TableInventory("verified", cells)


def ordinary_document_inventory(pages, *, make):
    """Find current-document ordinary tables on any page, including overflow.

    A heading delimits the inventory context. Price tables, eligibility
    summaries and a subtype mention elsewhere cannot become allocations.
    Ambiguous or contradictory table data are surfaced to the caller.
    """
    lines = [(page["page"], line) for page in pages for line in page["text"].splitlines()]
    starts = [i for i, (_, line) in enumerate(lines) if HEADING.search(line)]
    result = TableInventory()
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        block = lines[start:end]
        # Only an actual ordinary supply-table header opts into this parser.
        # Public residual, officetel and public-rental layouts stay separate.
        first = next((i for i, (_, text) in enumerate(block) if UNIT.search(text)), None)
        if first is None:
            continue
        header = "\n".join(text for _, text in block[:first])
        compact = re.sub(r"\s+", "", header)
        if not (("특별공급" in compact and ("총공급" in compact or "일반" in compact))
                or ("총공급" in compact and "일반공급" in compact)):
            continue
        parsed = _ordinary_table(block, make=make)
        if parsed.status in {"partial", "conflict"}:
            return parsed
        if parsed.status != "verified":
            continue
        for key, row in parsed.cells.items():
            if key in result.cells and result.cells[key]["supply_count"] != row["supply_count"]:
                return TableInventory("conflict")
            result.cells.setdefault(key, row)
        result.status = "verified"
    return result


def residual_dong_inventory(pages, *, make):
    """Residual counts before the dwelling's enumerated building/room list.

    This table has no area decimals after the unit. Its explicit shorthand and
    residual-count columns determine which integer is the allocation; building
    and room numbers are never counted as dwellings.
    """
    lines = [(page['page'], line) for page in pages for line in page['text'].splitlines()]
    starts = [i for i, (_, line) in enumerate(lines) if HEADING.search(line)]
    found = TableInventory()
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        block = lines[start:end]
        first = next((i for i, (_, text) in enumerate(block) if UNIT.search(text)), None)
        if first is None:
            continue
        header = re.sub(r'\s+', '', '\n'.join(text for _, text in block[:first]))
        if '잔여세대수' not in header or '동' not in header or '호' not in header:
            continue
        alias = '약식표기' in header or '(타입)' in header
        counts, totals = {}, []
        for page, line in block[first:]:
            if '※' in line or re.match(r'\s*(?:■|❚)', line):
                break
            total = re.match(r'\s*합\s*계\s+(\d{1,3}(?:,\d{3})+|\d+)(?:\s*세대)?\s*(?:[-－−]\s*)?$', line)
            if total:
                totals.append(int(total[1].replace(',', '')))
                continue
            unit = UNIT.search(line)
            if not unit:
                continue
            pattern = (r'\s+\d{2,3}[A-Z0-9-]*' if alias else '') + r'\s+(\d{1,3}(?:,\d{3})+|\d+)(?:\s*세대)?(?:\s|$)'
            allocation = re.match(pattern, line[unit.end():])
            if not allocation:
                return TableInventory('partial')
            canonical = normalize_unit(unit[1])
            if canonical in counts:
                return TableInventory('partial')
            proof = make('offered_supplies', effect='metadata', quote=line.strip(), page=page)
            counts[canonical] = {'supply_type': '일반공급', 'unit_type': canonical,
                'supply_count': int(allocation[1].replace(',', '')),
                **{key: proof.get(key) for key in ('verification', 'source', 'evidence_url', 'evidence_text', 'evidence_page', 'document_hash', 'criterion_date')}}
        if not counts or not totals:
            return TableInventory('partial')
        if len(totals) != 1 or sum(row['supply_count'] for row in counts.values()) != totals[0]:
            return TableInventory('conflict')
        if not any(row['supply_count'] > 0 for row in counts.values()):
            return TableInventory('partial')
        for row in counts.values():
            key = ('일반공급', row['unit_type'])
            if key in found.cells and found.cells[key]['supply_count'] != row['supply_count']:
                return TableInventory('conflict')
            found.cells.setdefault(key, row)
        found.status = 'verified'
    return found


def residual_geometry_inventory(pages, *, make):
    """An explicit residual-count column after the geometric area columns.

    Aggregate totals must match. Public current/reserve columns and enumerated
    building/room layouts cannot be interpreted as this single count column.
    """
    lines = [(page['page'], line) for page in pages for line in page['text'].splitlines()]
    starts = [i for i, (_, line) in enumerate(lines) if HEADING.search(line)]
    found = TableInventory()
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        block = lines[start:end]
        first = next((i for i, (_, text) in enumerate(block) if UNIT.search(text)), None)
        if first is None:
            continue
        header = re.sub(r'\s+', '', '\n'.join(text for _, text in block[:first]))
        if '잔여세대수' not in header or '면적' not in header or any(label in header for label in ('금회공급', '예비자', '특별공급')):
            continue
        cells, totals = {}, []
        for page, line in block[first:]:
            if '※' in line or re.match(r'\s*(?:■|❚)', line):
                break
            total = re.match(r'\s*합\s*계\s+(.+)$', line)
            if total:
                values = _numbers(total[1])
                if values is None or len(values) != 1:
                    return TableInventory('partial')
                totals.append(values[0])
                continue
            unit = UNIT.search(line)
            if not unit:
                continue
            counts = _area_count_tail(line, unit)
            if counts is None or len(counts) != 1:
                return TableInventory('partial')
            canonical = normalize_unit(unit[1])
            key = ('일반공급', canonical)
            if key in cells:
                return TableInventory('partial')
            proof = make('offered_supplies', effect='metadata', quote=line.strip(), page=page)
            cells[key] = {'supply_type': '일반공급', 'unit_type': canonical, 'supply_count': counts[0],
                **{key: proof.get(key) for key in ('verification', 'source', 'evidence_url', 'evidence_text', 'evidence_page', 'document_hash', 'criterion_date')}}
        if not cells or not totals:
            return TableInventory('partial')
        if len(totals) != 1 or sum(row['supply_count'] for row in cells.values()) != totals[0]:
            return TableInventory('conflict')
        if not any(row['supply_count'] > 0 for row in cells.values()):
            return TableInventory('partial')
        for key, row in cells.items():
            if key in found.cells and found.cells[key]['supply_count'] != row['supply_count']:
                return TableInventory('conflict')
            found.cells.setdefault(key, row)
        found.status = 'verified'
    return found
