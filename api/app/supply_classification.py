"""Reviewed supply categories tied to an exact public announcement identity.

National/private housing rank classification does not establish rental tenure.
These cross-links are independent official supply facts, never title guesses.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse


REVIEWED_SUPPLY_CATEGORIES = {
    "2026000402": {
        "category": "public_rental", "title": "익산 부송에코르 10년 공공임대주택",
        "announcement_date": "2026-10-08", "provider": "전북개발공사",
        "evidence_url": "https://www.jbdc.co.kr/notice/notice.do?bbsId=BBSMSTR_000000000011&mode=view&nttId=16011&pageIndex=1",
        "evidence_text": "전북개발공사 공고 제2026-60호(2026.10.8.): 익산 부송에코르 10년 공공임대주택 입주자 모집 · 59형 300세대",
    },
}


def reviewed_supply_classification(*, official_url: str | None, announcement_date,
                                   title: str, provider: str | None) -> dict | None:
    parsed = urlparse(official_url or "")
    if parsed.scheme != "https" or parsed.hostname not in {"www.applyhome.co.kr", "applyhome.co.kr"}:
        return None
    params = parse_qs(parsed.query)
    numbers = params.get("houseManageNo", [])
    if len(numbers) != 1 or params.get("pblancNo") != numbers:
        return None
    reviewed = REVIEWED_SUPPLY_CATEGORIES.get(numbers[0])
    if not reviewed or (str(announcement_date)[:10], title, provider) != (
            reviewed["announcement_date"], reviewed["title"], reviewed["provider"]):
        return None
    return {"kind": "supply_classification", "effect": "metadata", "verification": "official",
            "category": reviewed["category"], "source": "reviewed_official_provider",
            "criterion_date": reviewed["announcement_date"],
            "evidence_url": reviewed["evidence_url"], "evidence_text": reviewed["evidence_text"]}
