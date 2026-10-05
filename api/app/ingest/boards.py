"""Best-effort, read-only official housing announcement boards for SH and GH.

SH's links are exposed on Seoul Metropolitan Government's housing portal,
which points each item to the original SH announcement. GH uses its own public
sale/rental board. HTML layout changes fail visibly in source coverage.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx

from .common import FeedError, add_event, date_iso, omit_empty_enrichment, public_url

SH_BASE = "https://housing.seoul.go.kr/site/main/sh"
GH_URL = "https://www.gh.or.kr/gh/announcement-of-salerental001.do"
GH_APPLY_BASE = "https://apply.gh.or.kr"
GH_RENTAL_BOARDS = (
    "/sb/sr/sr7150/selectPbancRentHouseList.do",
    "/sb/sr/sr7155/selectPbancRentHouseList.do",
)


class TableRowsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_tbody = 0
        self.current_row: list[dict[str, Any]] | None = None
        self.current_cell: dict[str, Any] | None = None
        self.rows: list[list[dict[str, Any]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "tbody":
            self.in_tbody += 1
        elif self.in_tbody and tag == "tr":
            self.current_row = []
        elif self.current_row is not None and tag == "td":
            # GH's public board omits some closing </td> tags. Close the old
            # cell when the next one starts to keep dates in their columns.
            self._close_cell()
            self.current_cell = {"class": attr.get("class", ""), "parts": [], "hrefs": [], "links": []}
        elif self.current_cell is not None and tag == "a" and attr.get("href"):
            self.current_cell["hrefs"].append(attr["href"])
            self.current_cell["links"].append(attr)

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self._close_cell()
        elif tag == "tr" and self.current_row is not None:
            self._close_cell()
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = None
        elif tag == "tbody" and self.in_tbody:
            self.in_tbody -= 1

    def _close_cell(self) -> None:
        if self.current_cell is not None and self.current_row is not None:
            self.current_cell["text"] = " ".join("".join(self.current_cell["parts"]).split())
            self.current_row.append(self.current_cell)
            self.current_cell = None


def table_rows(html: str) -> list[list[dict[str, Any]]]:
    parser = TableRowsParser()
    parser.feed(html)
    return parser.rows


_CORRECTION_PREFIX = re.compile(r"^\s*[\[(](?:정정(?:공고)?|수정(?:공고)?)[\])]\s*", re.I)


def link_board_corrections(notices: list[dict[str, Any]]) -> None:
    """Link a labeled board correction only to the exact earlier base title."""
    originals: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for notice in notices:
        key = (notice["category"], str(notice["title"]).strip())
        if not _CORRECTION_PREFIX.match(key[1]):
            originals.setdefault(key, []).append(notice)
    for notice in notices:
        title = str(notice["title"])
        if not _CORRECTION_PREFIX.match(title):
            continue
        base_title = _CORRECTION_PREFIX.sub("", title).strip()
        candidates = [
            item for item in originals.get((notice["category"], base_title), [])
            if item.get("announcement_date") and notice.get("announcement_date")
            and item["announcement_date"] < notice["announcement_date"]
        ]
        if candidates:
            previous = max(candidates, key=lambda item: item["announcement_date"])
            notice["correction_of_external_id"] = previous["external_id"]


async def _get_html(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> str:
    for attempt in range(3):
        try:
            response = await client.get(url, params=params, timeout=25)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            if response.status_code >= 400:
                raise FeedError(f"공식 게시판 HTTP {response.status_code}")
            return response.text
        except httpx.RequestError:
            if attempt == 2:
                raise FeedError("공식 게시판 연결 실패") from None
            await asyncio.sleep(0.5 * (2 ** attempt))
    raise FeedError("공식 게시판 재시도 실패")


def normalize_sh(row: list[dict[str, Any]], category: str) -> dict[str, Any] | None:
    if len(row) < 7:
        return None
    title = row[2]["text"]
    links = [urljoin(SH_BASE + "/", href) for cell in row for href in cell["hrefs"]]
    official_url = next((public_url(link) for link in links if "i-sh.co.kr" in urlparse(link).netloc), None)
    if not title or not official_url:
        return None
    seq = parse_qs(urlparse(official_url).query).get("seq", [None])[0]
    external_id = seq or hashlib.sha256(official_url.encode()).hexdigest()[:32]
    events: list[dict[str, Any]] = []
    # The portal labels this column 발표일; it is not a reception deadline.
    add_event(events, "announcement", "발표일", row[4]["text"])
    return omit_empty_enrichment({
        "source": "sh",
        "external_id": external_id,
        "title": title,
        "provider": "서울주택도시개발공사 SH",
        "category": category,
        "region_name": "서울특별시",
        "announcement_date": date_iso(row[3]["text"]),
        "official_url": official_url,
        "price_cap_status": "not_applicable" if category == "public_rental" else "unknown",
        "events": events,
        "rules_complete": False,
    })


async def collect_sh(client: httpx.AsyncClient, start: date, end: date) -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    for path, category, supply_type in (("publicLease", "public_rental", "publicLease"), ("publicSale", "public_sale", "publicSale")):
        seen_pages: set[tuple[str, ...]] = set()
        for page in range(1, 21):
            html = await _get_html(client, f"{SH_BASE}/{path}/list", {"cp": page, "supplyType": supply_type})
            rows = table_rows(html)
            if not rows:
                if page == 1:
                    raise FeedError(f"SH {path} 게시판 행을 찾지 못했습니다")
                break
            signature = tuple(row[2]["text"] for row in rows if len(row) > 2)
            if signature in seen_pages:
                break
            seen_pages.add(signature)
            oldest: str | None = None
            for row in rows:
                notice = normalize_sh(row, category)
                if notice and notice.get("announcement_date"):
                    oldest = min(oldest, notice["announcement_date"]) if oldest else notice["announcement_date"]
                    if start.isoformat() <= notice["announcement_date"] <= end.isoformat():
                        notices.append(notice)
            if oldest and oldest < start.isoformat():
                break
        else:
            raise FeedError(f"SH {path} 페이지 상한 초과")
    link_board_corrections(notices)
    return notices


def _gh_date(raw: str) -> str | None:
    match = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{2})", raw.strip())
    return date_iso(f"20{match.group(1)}-{match.group(2)}-{match.group(3)}") if match else date_iso(raw)


def normalize_gh(row: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(row) < 5 or row[1]["text"] != "주택":
        return None
    title = row[2]["text"]
    if not re.search(r"입주자|예비자|청약|분양주택|임대주택|공공분양|주택 공급", title):
        return None
    href = next((href for href in row[2]["hrefs"] if "articleNo=" in href), None)
    if not href:
        return None
    official_url = public_url(urljoin(GH_URL, href))
    if not official_url:
        return None
    article_no = parse_qs(urlparse(official_url).query).get("articleNo", [None])[0]
    if not article_no:
        return None
    category = "public_sale" if "분양" in title and "임대" not in title else "public_rental" if "임대" in title else "other"
    return omit_empty_enrichment({
        "source": "gh",
        "external_id": article_no,
        "title": title,
        "provider": "경기주택도시공사 GH",
        "category": category,
        "region_name": "경기도",
        "announcement_date": _gh_date(row[4]["text"]),
        "official_url": official_url,
        "price_cap_status": "not_applicable" if category == "public_rental" else "unknown",
        "events": [],
        "rules_complete": False,
    })


def normalize_gh_apply(row: list[dict[str, Any]], board_path: str) -> dict[str, Any] | None:
    if len(row) < 7:
        return None
    title = row[2]["text"]
    link = next((link for link in row[2].get("links", []) if link.get("data-pbancno")), None)
    if not title or not link:
        return None
    number = link["data-pbancno"]
    detail_path = board_path.replace("selectPbancRentHouseList.do", "selectPbancDetailView.do")
    official_url = f"{GH_APPLY_BASE}{detail_path}?{urlencode({'pbancNo': number})}"
    announced = date_iso(row[5]["text"])
    events: list[dict[str, Any]] = []
    # The board's 마감일 is a posting/status deadline, and need not be an
    # application deadline. Only the original notice can establish that date.
    return omit_empty_enrichment({
        "source": "gh",
        "external_id": f"apply:{number}",
        "title": title,
        "provider": "경기주택도시공사 GH",
        "category": "public_rental",
        "region_name": f"경기도 {row[3]['text']}".strip(),
        "announcement_date": announced,
        "official_url": official_url,
        "price_cap_status": "not_applicable",
        "events": events,
        "rules_complete": False,
    })


async def _collect_gh_corporate(client: httpx.AsyncClient, start: date, end: date) -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    seen_pages: set[tuple[str, ...]] = set()
    for page in range(25):
        html = await _get_html(client, GH_URL, {"mode": "list", "srCategoryId": "12", "article.offset": page * 10})
        rows = table_rows(html)
        if not rows:
            if page == 0:
                raise FeedError("GH 주택 게시판 행을 찾지 못했습니다")
            break
        signature = tuple(row[2]["text"] for row in rows if len(row) > 2)
        if signature in seen_pages:
            break
        seen_pages.add(signature)
        page_dates: list[str] = []
        for row in rows:
            if len(row) >= 5 and _gh_date(row[4]["text"]):
                page_dates.append(_gh_date(row[4]["text"]))
            notice = normalize_gh(row)
            if notice and notice.get("announcement_date") and start.isoformat() <= notice["announcement_date"] <= end.isoformat():
                notices.append(notice)
        if page_dates and min(page_dates) < start.isoformat():
            break
    else:
        raise FeedError("GH 게시판 페이지 상한 초과")
    link_board_corrections(notices)
    return notices


async def _collect_gh_apply(client: httpx.AsyncClient, start: date, end: date) -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    for path in GH_RENTAL_BOARDS:
        seen_pages: set[tuple[str, ...]] = set()
        for page in range(1, 26):
            page_html = await _get_html(client, f"{GH_APPLY_BASE}{path}", {"pageIndex": page})
            rows = table_rows(page_html)
            if not rows:
                if page == 1:
                    raise FeedError(f"GH 청약센터 {path} 게시판 행을 찾지 못했습니다")
                break
            signature = tuple(row[2]["text"] for row in rows if len(row) > 2)
            if signature in seen_pages:
                break
            seen_pages.add(signature)
            dates: list[str] = []
            for row in rows:
                notice = normalize_gh_apply(row, path)
                if notice and notice["announcement_date"]:
                    dates.append(notice["announcement_date"])
                    if start.isoformat() <= notice["announcement_date"] <= end.isoformat():
                        notices.append(notice)
            if dates and min(dates) < start.isoformat():
                break
        else:
            raise FeedError(f"GH 청약센터 {path} 페이지 상한 초과")
    return notices


async def collect_gh(client: httpx.AsyncClient, start: date, end: date) -> tuple[list[dict[str, Any]], str | None]:
    """Collect the corporate board plus GH's dedicated public rental boards.

    Corporate pages have recently returned HTTP 410 from some networks. In
    that case rental notices remain available, and coverage reports the gap.
    """
    warning = None
    try:
        corporate = await _collect_gh_corporate(client, start, end)
    except FeedError:
        corporate = []
        warning = "GH 분양/임대 공고 게시판 접근 실패; 청약센터 임대 공고만 수집"
    rental = await _collect_gh_apply(client, start, end)
    return corporate + rental, warning
