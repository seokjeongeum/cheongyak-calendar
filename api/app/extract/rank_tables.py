"""Rank facts from operative general-supply rows and separately printed deposit tables."""
from __future__ import annotations

import io
import re


NATIONAL_TABLE = r"(?:일반공급\s*순위별\s*자격요건|순위\s+순위별\s*자격요건)"


def rank_pdf_pages(data: bytes, pages: list[dict]) -> list[dict]:
    """Recover the position of isolated numeric glyphs on targeted pages."""
    if not data.startswith(b"%PDF-"):
        return pages
    targets = {page["page"] - 1 for page in pages if re.search(NATIONAL_TABLE, page["text"])}
    if not targets or len(targets) > 12:
        return pages

    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTChar, LTContainer

    def glyphs(node):
        if isinstance(node, LTChar):
            if node.upright:
                yield node
        elif isinstance(node, LTContainer):
            for child in node:
                yield from glyphs(child)

    restored = {}
    for index, page in zip(sorted(targets), extract_pages(io.BytesIO(data), page_numbers=targets), strict=True):
        rows = []
        for glyph in sorted(glyphs(page), key=lambda char: (-char.y0, char.x0)):
            row = next((row for y, row in reversed(rows[-4:]) if abs(y - glyph.y0) < 2.4), None)
            if row is None:
                row = []
                rows.append((glyph.y0, row))
            row.append(glyph)
        lines = []
        for _, row in rows:
            fragments = []
            end = None
            for glyph in sorted(row, key=lambda char: char.x0):
                if end is not None and glyph.x0 - end > 1.4:
                    fragments.append(" ")
                fragments.append(glyph.get_text())
                end = glyph.x1
            lines.append("".join(fragments).strip())
        if any(lines):
            restored[index + 1] = "\n".join(lines)
    return [{**page, "text": restored.get(page["page"], page["text"])} for page in pages]


def national_rank_table(pages, *, make):
    candidates = []
    for page in pages:
        body = "\n".join(" ".join(line.split()) for line in page["text"].splitlines())
        table = re.search(NATIONAL_TABLE + r"\s*\n[\s\S]{0,160}?\n1\s*순위\b([\s\S]{5,800}?)(?=\n2\s*순위\b)", body)
        if not table:
            continue
        row = " ".join(table[1].split())
        # Use the printed term and payment count independently. The two
        # facts can remain usable while a separate rank restriction is read.
        period = re.search(r"입주자\s*저축에\s*가입하여\s*(?:(\d+)\s*년\s*\(\s*(\d+)\s*개월\s*\)|(\d+)\s*개월|(\d+)\s*년)\s*(?:이|가)?\s*(?:경과|이상|지나)", row)
        payments = re.search(r"(?:월\s*납입금(?:을)?|약정\s*납입일에)\s*(\d+)\s*회\s*이상\s*납입", row)
        head = re.search(r"무주택\s*세대주|세대주일\s*것", row)
        homeless = re.search(r"무주택\s*세대(?:주|구성원)", row)
        winning = re.search(r"과거\s*(\d+)\s*년\s*이내\s*당첨된\s*(?:자|분)(?:의)?\s*세대에\s*속하지\s*않(?:은|을)", row)
        fields = dict(page=page["page"], quote=table[0], purpose="first_rank")
        rules = []
        if period:
            years, explicit_months, months, only_years = period.groups()
            if not years or int(years) * 12 == int(explicit_months):
                value = int(explicit_months or months or int(only_years) * 12)
                rules.append(make("national_rank_months", value, operator=">=", unit="months", **fields))
                # The national table's 입주자저축 is the account type defined
                # for 국민주택. Legacy 청약예금/청약부금 are private accounts.
                rules.append(make("account_type", allowed_values=["comprehensive", "savings"], **fields))
        if payments:
            rules.append(make("recognized_payments_min", int(payments[1]), operator=">=", unit="payments",
                              require_as_of_date=True, value_basis="announcement_payments", **fields))
        if head:
            rules.append(make("household_head", True, **fields))
        if homeless:
            rules.append(make("homeless", True, **fields))
        if winning:
            rules.append(make("previous_winning", False, months=int(winning[1]) * 12, scope="household", **fields))
        if rules:
            candidates.append(rules)
    # Prefer a populated operative row but refuse competing values from two
    # tables. This does not bind an eligibility table to the rank scope.
    facts = {}
    for rules in candidates:
        for rule in rules:
            facts.setdefault(rule["kind"], []).append(rule)
    return [matches[0] for matches in facts.values()
            if all((rule.get("value"), rule.get("months")) == (matches[0].get("value"), matches[0].get("months"))
                   for rule in matches)]


def deposit_table_with_shared_unit(pages):
    """Read a contiguous table with one printed unit rather than three per row."""
    candidates = []
    header = re.compile(r"\[\s*청약예금의\s*예치금액\s*\]\s*\(?\s*단위\s*[:：]?\s*(만원|원)\s*\)?")
    columns = {"seoul_busan": r"특별시\s*및\s*부산광역시", "other_metropolitan": r"그\s*밖의\s*광역시",
               "other": r"특별시\s*및\s*광역시를\s*제외한\s*지역"}
    area = r"(?:(?:전용\s*면적\s*)?(\d+(?:\.\d+)?)\s*(?:㎡|m²)\s*이하|모든\s*면적)"
    number = r"([\d,]+)"
    row = re.compile(area + r"\s+" + r"\s+".join([number] * 3) + r"(?![\d,])")
    for page in pages:
        body = " ".join(page["text"].split())
        anchor = header.search(body)
        if not anchor:
            continue
        table = body[anchor.end():anchor.end() + 800]
        first = re.search(area, table)
        if not first:
            continue
        heading = table[:first.start()]
        positions = {name: re.search(label, heading) for name, label in columns.items()}
        if any(value is None for value in positions.values()):
            continue
        order = sorted(positions, key=lambda name: positions[name].start())
        multiplier = 10_000 if anchor[1] == "만원" else 1
        start = first.start()
        end = start
        values = []
        while match := row.match(table, end):
            values.append({"max_area_sqm": float(match[1]) if match[1] else None,
                           "amounts_krw": dict(zip(order, [int(v.replace(",", "")) * multiplier for v in match.groups()[1:]], strict=True))})
            end = match.end()
            if match[1] is None:
                break
            while end < len(table) and table[end].isspace():
                end += 1
        if len(values) < 2 or values[-1]["max_area_sqm"] is not None:
            continue
        limits = [item["max_area_sqm"] for item in values[:-1]]
        if limits != sorted(set(limits)):
            continue
        candidates.append((values, {"page": page["page"], "text": body[anchor.start():anchor.end() + end]}))
    if candidates and all(values == candidates[0][0] for values, _ in candidates):
        return candidates[0]
    return [], None
