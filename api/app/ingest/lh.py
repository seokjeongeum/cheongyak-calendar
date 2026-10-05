"""LH's official nationwide 분양임대공고문 list API.

Source: https://www.data.go.kr/data/15058530/openapi.do
Only housing announcement categories 05, 06, 13, and 39 are requested; land
and shops are outside this application's housing calendar. The list API does
not document type-level prices, so no price is inferred from it.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from .common import FeedError, add_event, body_rows, date_iso, get_json, omit_empty_enrichment, public_url, value

URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
SOURCE = "lh"
HOUSING_CATEGORIES = {"05": "public_sale", "06": "public_rental", "13": "public_rental", "39": "public_sale"}


def normalize(row: dict[str, Any], category_code: str) -> dict[str, Any] | None:
    title = value(row, "PAN_NM")
    url = public_url(value(row, "DTL_URL"))
    notice_id = value(row, "PAN_ID")
    if notice_id is None and url:
        found = re.search(r"PAN_ID[:=]([0-9]+)", url, re.I)
        notice_id = found.group(1) if found else None
    if title is None or notice_id is None:
        return None
    parent = str(value(row, "UPP_AIS_TP_CD") or category_code)
    # 신혼희망타운 parent39 includes publicsale39 and 행복주택42.
    # The official detail's subtype overrides the bundled parent category.
    query = parse_qs(urlparse(url or "").query)
    subtype = str(value(row, "AIS_TP_CD") or (query.get("aisTpCd") or [""])[0])
    category = "public_rental" if parent == "39" and subtype == "42" else HOUSING_CATEGORIES.get(parent, "other")
    events: list[dict[str, Any]] = []
    # These fields are present on some LH revisions of the API. A posting
    # deadline (CLSG_DT) alone is not proof of a 청약 reception date.
    add_event(events, "general", "신청 접수", value(row, "RQS_ST_DT", "RCPT_ST_DT"), value(row, "RQS_ED_DT", "RCPT_ED_DT"))
    add_event(events, "announcement", "당첨자 발표", value(row, "PRZWN_ANN_DT", "PRZWNER_PRESNATN_DE"))
    payload: dict[str, Any] = {
        "source": SOURCE,
        "external_id": str(notice_id),
        "title": str(title),
        "provider": "한국토지주택공사 LH",
        "category": category,
        "region_name": value(row, "CNP_CD_NM"),
        "region_code": value(row, "CNP_CD"),
        "announcement_date": date_iso(value(row, "PAN_NT_ST_DT", "PAN_DT")),
        "official_url": url,
        "price_cap_status": "not_applicable" if category == "public_rental" else "unknown",
        "events": events,
        "rules_complete": False,
    }
    return omit_empty_enrichment(payload)


async def collect(client: httpx.AsyncClient, key: str, start: date, end: date) -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    for code in HOUSING_CATEGORIES:
        for page in range(1, 51):
            body = await get_json(client, URL, {
                "ServiceKey": key,
                "PG_SZ": 100,
                "PAGE": page,
                "UPP_AIS_TP_CD": code,
                "PAN_NT_ST_DT": start.strftime("%Y.%m.%d"),
                "CLSG_DT": end.strftime("%Y.%m.%d"),
            })
            rows, total = body_rows(body, "dsList", "data", "items")
            for row in rows:
                normalized = normalize(row, code)
                if normalized:
                    notices.append(normalized)
            if not rows or (total is not None and page * 100 >= total) or len(rows) < 100:
                break
        else:
            raise FeedError(f"LH {code} 페이지 상한 초과")
    return notices
