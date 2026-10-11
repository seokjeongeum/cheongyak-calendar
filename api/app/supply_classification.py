"""Explicit tenure declarations in an official notice, without a project catalog.

National/private housing rank classification does not establish rental tenure.
Only an explicit public/private rental declaration in the official feed's notice
name is recognized here; the PDF parser can provide stronger subsequent facts.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import parse_qs, urlparse


def reviewed_supply_classification(*, official_url: str | None, announcement_date,
                                   title: str, provider: str | None) -> dict | None:
    parsed = urlparse(official_url or "")
    if parsed.scheme != "https" or parsed.hostname not in {"www.applyhome.co.kr", "applyhome.co.kr"}:
        return None
    params = parse_qs(parsed.query)
    numbers = params.get("houseManageNo", [])
    if len(numbers) != 1 or not re.fullmatch(r"\d{10}", numbers[0]) or params.get("pblancNo") != numbers:
        return None
    try:
        announced = date.fromisoformat(str(announcement_date)[:10]).isoformat()
    except ValueError:
        return None
    text = re.sub(r"\s+", "", title)
    public = "공공임대" in text
    private = bool(re.search(r"민간임대|민영임대", text))
    if public == private:
        return None
    return {"kind": "supply_classification", "effect": "metadata", "verification": "official",
            "category": "public_rental" if public else "private_rental", "source": "official_notice_title",
            "criterion_date": announced, "evidence_url": official_url,
            "evidence_text": "청약홈 공식 공고명: " + title}
