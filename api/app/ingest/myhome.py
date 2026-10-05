"""국토교통부 마이홈 official public sale and rental announcement API.

Source: https://www.data.go.kr/data/15108420/openapi.do
The official embedded Swagger documents both rsdtRcritNtcList (rental) and
ltRsdtRcritNtcList (sale). The list API does not document type prices. For
sale notices the public MyHome detail page supplies type-level ``sumPrice``
under the explicit ``공급금액(원) / 계`` heading.
"""

from __future__ import annotations

import html
import re
from datetime import date
from typing import Any
from urllib.parse import urlencode

import httpx

from .common import FeedError, add_event, body_rows, date_iso, get_json, integer, omit_empty_enrichment, public_url, value

BASE = "https://apis.data.go.kr/1613000/HWSPR02"
SOURCE = "myhome"
OPERATIONS = (("ltRsdtRcritNtcList", "public_sale"), ("rsdtRcritNtcList", "public_rental"))
SALE_DETAIL_URL = "https://m.myhome.go.kr/hws/portal/sch/selectLttotHouseDetailView.do"


def _js_objects(page: str, array_name: str) -> list[dict[str, str]]:
    """Read quoted scalar fields from the portal's public inline data, never eval JS."""
    objects = []
    pattern = rf"\b{re.escape(array_name)}\.push\s*\(\s*\{{(.*?)\}}\s*\)"
    for body in re.findall(pattern, page, flags=re.S):
        fields = {
            key: html.unescape(raw)
            for key, raw in re.findall(r"([A-Za-z][A-Za-z0-9]*)\s*:\s*\"([^\"]*)\"", body)
        }
        if fields:
            objects.append(fields)
    return objects


def _korean_dates(fragment: str) -> list[str]:
    return [
        date_iso(f"{year}-{month.zfill(2)}-{day.zfill(2)}")
        for year, month, day in re.findall(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", fragment)
    ]


def parse_sale_detail(page: str, detail_url: str) -> dict[str, Any]:
    """Use only explicitly labeled dates and won-denominated supply totals."""
    houses = {item.get("houseSn"): item for item in _js_objects(page, "houseList")}
    raw_prices = _js_objects(page, "suplyList")
    prices: list[dict[str, Any]] = []
    for item in raw_prices:
        unit = item.get("styleNm", "").strip()
        if not unit:
            continue
        house = houses.get(item.get("houseSn"), {})
        complex_name = house.get("hsmpNm", "").strip()
        unit_name = f"{complex_name} · {unit}" if len(houses) > 1 and complex_name else unit
        amount = integer(item.get("sumPrice"))
        if amount == 0:
            amount = None
        area = item.get("prvuseAr")
        note = html.unescape(house.get("partclrMatter", ""))
        basis = "마이홈 공급금액(원) 계"
        if "1층" in note and "기본형" in note:
            basis += " · 1층 기본형 기준"
        prices.append({
            "unit_type": unit_name,
            "area_sqm": float(area) if area and re.fullmatch(r"\d+(?:\.\d+)?", area) else None,
            "price_kind": "sale_total",
            "amount_krw": amount,
            "basis_label": basis,
            "verification": "official" if amount is not None else "unknown",
            "evidence_url": detail_url,
            "evidence_text": f"공급금액(원) 계: {item.get('sumPrice')}" if amount is not None else None,
        })
    events: list[dict[str, Any]] = []
    # This label appears in the server-rendered schedule. Other dates on the
    # page (posting/result/move-in) must not be mistaken for application days.
    section = re.search(r"접수\s*일정\s*</th>\s*<td>(.*?)(?:<tr\b|</td>)", page, re.S)
    if section:
        dates = [item for item in _korean_dates(section.group(1)) if item]
        if dates:
            add_event(events, "general", "신청 접수", dates[0], dates[1] if len(dates) > 1 else None)
    return {"prices": prices, "events": events}


async def enrich_sale_detail(client: httpx.AsyncClient, payload: dict[str, Any], notice_id: str) -> dict[str, Any]:
    detail_url = f"{SALE_DETAIL_URL}?{urlencode({'pblancId': notice_id})}"
    response = await client.get(detail_url, timeout=25)
    if response.status_code != 200 or "공급 정보" not in response.text:
        raise FeedError(f"마이홈 분양 상세 HTTP {response.status_code} 또는 형식 오류")
    detail = parse_sale_detail(response.text, detail_url)
    if detail["prices"]:
        payload["prices"] = detail["prices"]
    else:
        payload["ingest_warning"] = "마이홈 분양 상세 주택형 가격 없음"
    if detail["events"]:
        payload["events"] = detail["events"] + payload.get("events", [])
    return payload


def normalize(row: dict[str, Any], category: str) -> dict[str, Any] | None:
    notice_id = value(row, "pblancId")
    title = value(row, "pblancNm")
    if notice_id is None or title is None:
        return None
    house_no = value(row, "houseSn")
    external_id = f"{notice_id}:{house_no}" if house_no is not None else str(notice_id)
    official_url = public_url(value(row, "url", "pcUrl", "mobileUrl"))
    if official_url is None:
        # Both routes are linked from the official MyHome portal's notice pages.
        if category == "public_sale":
            official_url = "https://www.myhome.go.kr/hws/portal/sch/selectLttotHouseDetailView.do?" + urlencode({"pblancId": notice_id})
        elif house_no is not None:
            official_url = "https://www.myhome.go.kr/hws/portal/sch/selectRsdtRcritNtcDetailView.do?" + urlencode({"pblancId": notice_id, "houseSn": house_no})
    events: list[dict[str, Any]] = []
    add_event(events, "general", "신청 접수", row.get("beginDe"), row.get("endDe"))
    add_event(events, "announcement", "당첨자 발표", row.get("przwnerPresnatnDe"))
    region_name = " ".join(str(part) for part in (value(row, "brtcNm", "brtcCodeNm"), value(row, "signguNm")) if part)
    payload: dict[str, Any] = {
        "source": SOURCE,
        "external_id": external_id,
        "title": str(title),
        "provider": value(row, "suplyInsttNm") or "마이홈",
        "category": category,
        "address": value(row, "fullAdres"),
        "region_name": region_name or None,
        "announcement_date": date_iso(row.get("rcritPblancDe")),
        "official_url": official_url,
        "price_cap_status": "unknown" if category == "public_sale" else "not_applicable",
        "events": events,
        "rules_complete": False,
    }
    if value(row, "beforePblancId"):
        payload["correction_of_external_id"] = str(row["beforePblancId"])
    return omit_empty_enrichment(payload)


async def collect(client: httpx.AsyncClient, key: str, start: date, end: date) -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    for operation, category in OPERATIONS:
        for page in range(1, 101):
            body = await get_json(client, f"{BASE}/{operation}", {
                "serviceKey": key,
                "numOfRows": 100,
                "pageNo": page,
                "yearMtBegin": start.strftime("%Y%m"),
                "yearMtEnd": end.strftime("%Y%m"),
            })
            rows, total = body_rows(body, "item")
            for row in rows:
                normalized = normalize(row, category)
                if normalized:
                    if category == "public_sale":
                        try:
                            await enrich_sale_detail(client, normalized, str(value(row, "pblancId")))
                        except (httpx.RequestError, FeedError):
                            # List coverage still succeeds; absent type prices and
                            # reception dates remain visible as unknown.
                            normalized["ingest_warning"] = "마이홈 분양 상세 조회 실패"
                    notices.append(normalized)
            if not rows or (total is not None and page * 100 >= total) or len(rows) < 100:
                break
        else:
            raise FeedError(f"마이홈 {operation} 페이지 상한 초과")
    return notices
