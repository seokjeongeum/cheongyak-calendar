"""인천도시공사 official sale/rental announcement API.

Source: https://www.data.go.kr/data/15149725/openapi.do
This feed exposes notice title, board creation date, and original link, but no
application dates, type prices, or price cap. Those remain explicitly unknown.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

import httpx

from .common import FeedError, body_rows, date_iso, get_json, omit_empty_enrichment, public_url, value

URL = "https://apis.data.go.kr/B552831/ih/slls-posts"
SOURCE = "ih"
PAGE_SIZE = 30  # Official Swagger rejects numOfRows outside 1–30 (result code 421).


def normalize(row: dict[str, Any]) -> dict[str, Any] | None:
    title = value(row, "sj")
    url = public_url(value(row, "link"))
    if title is None or url is None:
        return None
    kind_text = " ".join(str(value(row, key) or "") for key in ("tyNm", "seNm", "sj"))
    if any(word in kind_text for word in ("토지", "상가", "산업용지", "입찰공고")) and not any(word in kind_text for word in ("주택", "아파트", "입주자")):
        return None
    category = "public_rental" if "임대" in str(row.get("seNm") or "") else "public_sale" if "분양" in str(row.get("seNm") or "") else "other"
    payload: dict[str, Any] = {
        "source": SOURCE,
        "external_id": hashlib.sha256(url.encode()).hexdigest()[:32],
        "title": str(title),
        "provider": "인천도시공사 iH",
        "category": category,
        "region_name": "인천광역시",
        "announcement_date": date_iso(row.get("crtYmd")),
        "official_url": url,
        "price_cap_status": "not_applicable" if category == "public_rental" else "unknown",
        "events": [],
        "rules_complete": False,
    }
    return omit_empty_enrichment(payload)


async def collect(client: httpx.AsyncClient, key: str, start: date, end: date) -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    for page in range(1, 51):
        body = await get_json(client, URL, {
            "serviceKey": key,
            "pageNo": page,
            "numOfRows": PAGE_SIZE,
            "startCrtrYmd": start.isoformat(),
            "endCrtrYmd": end.isoformat(),
        })
        rows, total = body_rows(body, "posts")
        for row in rows:
            normalized = normalize(row)
            if normalized:
                notices.append(normalized)
        if not rows or (total is not None and page * PAGE_SIZE >= total) or len(rows) < PAGE_SIZE:
            break
    else:
        raise FeedError("iH 페이지 상한 초과")
    return notices
