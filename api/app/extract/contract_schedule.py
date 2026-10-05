"""Explicit official contract schedules, separate from application deadlines.

Only a date tied to a contract clause is interpreted. Posting expiry, payment
dates, and a person's intended contract date are never contract schedules.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date


DATE_TOKEN = r"(?:[‘’'`]?(?:20\d{2}|\d{2}))\s*[.년/-]\s*\d{1,2}\s*[.월/-]\s*\d{1,2}\s*(?:일|\.)?"
DATE_RE = re.compile(DATE_TOKEN)
END_TOKEN = r"(?:" + DATE_TOKEN + r"|\d{1,2}\s*[.월/-]\s*\d{1,2}\s*(?:일|\.)?)"
CONTRACT_RE = re.compile(r"(?:정당\s*)?계약(?:\s*체결)?(?:\s*(?:기간|일정|일자|일))?")


def _date_token(raw: str) -> str | None:
    values = re.findall(r"\d+", raw)
    if len(values) != 3:
        return None
    year, month, day = map(int, values)
    year = year + 2000 if year < 100 else year
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _end_token(raw: str, start: str) -> str | None:
    values = re.findall(r"\d+", raw)
    if len(values) == 3:
        return _date_token(raw)
    if len(values) == 2:
        try:
            return date(date.fromisoformat(start).year, *map(int, values)).isoformat()
        except ValueError:
            pass
    return None


def parse_contract_schedule(pages: list[dict], *, url: str, digest: str, parser_version: str) -> dict | None:
    candidates = []
    for page in pages:
        body = re.sub(r"\s+", " ", page["text"])
        # Read the nearest date before the open-ended phrase. A schedule table
        # can also contain a publication date; that earlier date is not chosen.
        for ending in re.finditer(r"(?:~|∼|부터|\-)\s*(?:별도\s*(?:공지|공고)(?:시)?까지|잔여\s*세대\s*(?:소진|마감)\s*(?:시)?까지|소진\s*시까지)", body):
            before = body[max(0, ending.start() - 450):ending.start()]
            dates = list(DATE_RE.finditer(before))
            if not CONTRACT_RE.search(before) or not dates or len(before) - dates[-1].end() > 100:
                continue
            start = _date_token(dates[-1].group())
            if start:
                anchors = list(CONTRACT_RE.finditer(before[:dates[-1].start()]))
                quote_start = max(0, anchors[-1].start() - 35) if anchors else 0
                candidates.append({"status": "ongoing", "start_date": start, "end_date": None,
                    "evidence_page": page["page"], "evidence_text": before[quote_start:] + ending.group()})
        # A fixed/range clause must put the dates directly after its contract
        # label. Do not scan an entire paragraph containing multiple schedules.
        fixed_body = re.sub(r"[^\S\n]+", " ", page["text"])
        pattern = r"(?:정당[ \t]*계약(?:[ \t]*(?:기간|일정))?|계약(?:[ \t]*체결)?[ \t]*(?:기간|일정|일자|일))[ \t]*[:：\[\]()]*[ \t]*(" + DATE_TOKEN + r")(?:\s*\([^)]{0,12}\))?(?:\s*(?:~|∼|부터|\-)\s*(" + END_TOKEN + r"))?"
        for match in re.finditer(pattern, fixed_body):
            start = _date_token(match.group(1))
            end = _end_token(match.group(2), start) if match.group(2) and start else start
            if not start or not end or end < start:
                continue
            trailing = fixed_body[match.end():match.end()+45]
            if re.match(r"\s*(?:\([^)]{0,12}\))?\s*(?:오전|오후|\d{1,2}\s*시)?[^■]{0,18}(?:~|∼|부터)\s*(?:별도|소진|잔여)", trailing):
                continue
            candidates.append({"status": "fixed" if start == end else "range", "start_date": start, "end_date": end,
                "evidence_page": page["page"], "evidence_text": match.group()})
        # A common official table puts all headers on one line and all dates
        # on the next. The final contract column must not take the first
        # publication date. Interpret only an explicitly final contract column.
        for table in re.finditer(r"구분[^\n]{0,250}?(?:계약체결|계약일|계약기간)[ \t]*\n+[ \t]*일정[ \t]+([^\n]+)", fixed_body):
            row = table.group(1)
            dates = list(DATE_RE.finditer(row))
            if len(dates) < 2:
                continue
            # Some PDFs draw the range end dates on another row. The previous
            # date then belongs to document submission, not contract start.
            # Leave that table to the structured official API rather than
            # treating its incomplete final contract range as a fixed date.
            if re.search(r"[~∼]", row[dates[-1].end():]):
                continue
            start = end = _date_token(dates[-1].group())
            if len(dates) >= 2 and re.fullmatch(r"\s*(?:\([^)]{0,12}\))?\s*(?:~|∼|\-)\s*", row[dates[-2].end():dates[-1].start()]):
                start = _date_token(dates[-2].group())
            if start and end and end >= start:
                candidates.append({"status": "fixed" if start == end else "range", "start_date": start, "end_date": end,
                    "evidence_page": page["page"], "evidence_text": table.group()})
    # Repeated statement of the same schedule is one fact. Distinct explicit
    # schedules require review rather than a guessed first/last contract date.
    unique = {(r["status"], r["start_date"], r["end_date"]): r for r in candidates}
    if not unique:
        return None
    chosen = next(iter(unique.values())) if len(unique) == 1 else {
        "status": "unknown", "start_date": None, "end_date": None,
        "evidence_page": candidates[0]["evidence_page"],
        "evidence_text": "공식 문서에 서로 다른 계약 일정이 있어 추가 확인이 필요합니다. " + " / ".join(r["evidence_text"] for r in unique.values()),
    }
    chosen["evidence_text"] = chosen["evidence_text"][:900]
    identity = json.dumps([digest, chosen], ensure_ascii=False, sort_keys=True)
    return {"id": "official-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
        "kind": "contract_schedule", "effect": "metadata", "verification": "official",
        "source": "official_document_parser", "parser_version": parser_version,
        "document_hash": digest, "evidence_url": url, **chosen}
