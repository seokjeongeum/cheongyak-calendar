"""Focused browser contract checks against the rebuilt app; all API data mocked.

Run with python web/tests/future_calendar_qa.py (Python Playwright required).
CHEONGYAK_QA_BASE defaults to http://localhost:8080.
No real API keys, service collection, or profile requests are involved.
"""
import asyncio
import copy
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect


TODAY = "2026-09-30"
BASE = os.environ.get("CHEONGYAK_QA_BASE", "http://localhost:8080")
SOURCES = ["cheongyak_home", "myhome", "lh", "ih", "sh", "gh"]


def event(kind, label, start, end=None):
    return {"kind": kind, "label": label, "start_date": start,
            "end_date": end or start, "audience": None}


def notice(identifier, title, category, events, *, rent=False):
    return {
        "id": identifier, "title": title, "category": category,
        "source": "cheongyak_home", "sources": ["cheongyak_home"],
        "provider": "브라우저 검증 예시", "address": "서울특별시 강동구",
        "region_code": "11", "region_name": "서울특별시",
        "announcement_date": "2026-05-01", "sort_date": None,
        "official_url": "https://www.applyhome.co.kr/",
        "price_cap_status": "not_applicable" if rent else "yes",
        "events": events,
        "prices": [{"unit_type": "59A", "area_sqm": 59.8,
                    "price_kind": "rental" if rent else "sale_max",
                    "amount_krw": 43000000 if rent else 512000000,
                    "monthly_krw": 221000 if rent else None,
                    "basis_label": "임대보증금 / 월 임대료" if rent else "주택형별 최고 분양금액",
                    "verification": "official", "source": "cheongyak_home",
                    "evidence_url": "https://www.applyhome.co.kr/",
                    "evidence_text": "통제된 브라우저 검증용 가격"}],
        "rules": [], "rules_complete": False,
        "updated_at": "2026-09-30T03:01:00Z", "version": 1,
    }


FIXTURES = [
    notice("qa-active", "검증용 현재 접수 분양", "apt", [
        event("special", "종료된 특별공급", "2026-05-01", "2026-05-05"),
        event("application", "장기 분양 접수", "2026-05-14", "2027-03-31"),
    ]),
    notice("qa-private", "검증용 민간임대", "private_rental", [
        event("application", "민간임대 접수", "2026-09-28", "2026-10-02"),
    ], rent=True),
    notice("qa-public", "제외되어야 할 공공임대", "public_rental", [
        event("application", "공공임대 접수", "2026-09-30", "2026-10-12"),
    ], rent=True),
    notice("qa-future", "검증용 앞으로의 공공분양", "public_sale", [
        event("application", "공공분양 접수", "2026-10-04", "2026-10-06"),
    ]),
    notice("qa-ended", "제외되어야 할 종료 공고", "apt", [
        event("application", "종료 접수", "2026-09-01", "2026-09-20"),
    ]),
    notice("qa-announcement", "제외되어야 할 발표만 있는 공고", "apt", [
        event("result", "당첨자 발표", "2026-10-01", "2026-10-01"),
    ]),
]


def app_events(row):
    return [e for e in row["events"] if e["kind"] not in {"result", "announcement", "winner", "contract"}]


def response_for(query, complete):
    start, end = query["start"][0], query["end"][0]
    rows = []
    if complete:
        for source in FIXTURES:
            row = copy.deepcopy(source)
            if query.get("exclude_public_rental") == ["true"] and row["category"] == "public_rental":
                continue
            overlapping = [e for e in app_events(row) if e["start_date"] <= end and (e["end_date"] or e["start_date"]) >= start]
            if not overlapping:
                if query.get("application_only") == ["true"]:
                    continue
                if not start <= row["announcement_date"] <= end:
                    continue
            row["sort_date"] = max(start, min(e["start_date"] for e in overlapping)) if overlapping else row["announcement_date"]
            rows.append(row)
    rows.sort(key=lambda r: (r["sort_date"], r["id"]))
    page, page_size = int(query.get("page", ["1"])[0]), int(query.get("page_size", ["100"])[0])
    return {"items": rows[(page - 1) * page_size:page * page_size], "total": len(rows), "page": page, "page_size": page_size}


class FixtureRouter:
    def __init__(self):
        self.phase = "pending"
        self.requests = []
        self.coverage_calls = 0
        self.errors = []
        self.initial_empty_responses = 0
        self.success_timestamp = "2026-09-30T03:01:00Z"

    def coverage(self):
        timestamp = "2026-09-30T03:00:30Z" if self.phase == "running" else self.success_timestamp
        return {"sources": [{"source": source, "status": self.phase,
                             "message": "아직 수집되지 않았습니다." if self.phase == "pending" else "공식 공고 수집 중" if self.phase == "running" else "공식 공고 수집 완료",
                             "last_attempt_at": None if self.phase == "pending" else timestamp,
                             "last_success_at": timestamp if self.phase == "ok" else None,
                             "record_count": 3 if self.phase == "ok" else 0}
                            for source in SOURCES]}

    async def handle(self, route):
        req = route.request
        parsed = urlsplit(req.url)
        self.requests.append({"url": req.url, "method": req.method, "body": req.post_data, "headers": req.headers})
        if parsed.path == "/api/coverage":
            self.coverage_calls += 1
            payload = self.coverage()
        elif parsed.path == "/api/notices":
            deliberately_empty = self.initial_empty_responses > 0
            if deliberately_empty:
                self.initial_empty_responses -= 1
            payload = response_for(parse_qs(parsed.query), self.phase == "ok" and not deliberately_empty)
        else:
            self.errors.append(parsed.path)
            await route.fulfill(status=404, json={"detail": "unexpected API request"})
            return
        await route.fulfill(status=200, json=payload)

    def notice_requests(self):
        return [r for r in self.requests if urlsplit(r["url"]).path == "/api/notices"]


async def settle(page):
    await page.wait_for_timeout(120)


async def check(steps, label, condition):
    assert condition, label
    steps.append(label)


async def main():
    steps = []
    router = FixtureRouter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 375, "height": 812}, timezone_id="Asia/Seoul")
        page = await context.new_page()
        await page.clock.install(time=datetime(2026, 9, 30, 3, 0, 0, tzinfo=timezone.utc))
        await page.route("**/api/**", router.handle)
        await page.goto(BASE, wait_until="networkidle")
        await expect(page.locator(".empty-state")).to_be_visible()
        await check(steps, "cold initial pending response shows collection-specific guidance", "수집" in await page.locator(".empty-state").inner_text())
        await expect(page.get_by_role("button", name="이전 달", exact=True)).to_be_disabled()
        await check(steps, "current-month calendar contains only September30, no past date buttons", await page.locator("button.calendar-day").count() == 1)
        await check(steps, "current-month past calendar cells are blank", await page.locator(".calendar-empty.past").count() == 29 and not any(text.strip() for text in await page.locator(".calendar-empty.past").all_text_contents()))

        router.phase = "running"
        calls = router.coverage_calls
        await page.clock.fast_forward(30000)
        await expect(page.locator(".coverage-item").first).to_contain_text("수집 중")
        await expect(page.locator(".coverage-item").first.locator(".coverage-meta")).to_contain_text("수집 중")
        await check(steps, "pending coverage polls again after30s", router.coverage_calls > calls)
        router.phase = "ok"
        await page.clock.fast_forward(30000)
        await expect(page.locator(".notice-card")).to_have_count(3)
        await expect(page.locator(".coverage-item").first).to_contain_text("정상")
        await check(steps, "collection completion updates3 notices without navigation or reload", True)

        titles = await page.locator(".notice-card h4").all_text_contents()
        await check(steps, "public rental and completed/result-only notices excluded; private rental shown", "검증용 민간임대" in titles and not any("제외되어야" in title for title in titles))
        headings = await page.locator(".day-heading h3").all_text_contents()
        await check(steps, "active sale belongs to current reception group, no May/June headings", any("현재 접수 중" in text for text in headings) and not any(re.search(r"[56]월", text) for text in headings))
        active = page.locator(".notice-card").filter(has=page.get_by_role("heading", name="검증용 현재 접수 분양", exact=True))
        await check(steps, "ended supply hidden from card schedule", "종료된 특별공급" not in await active.locator(".event-list").inner_text())
        await check(steps, "current cross-year reception explicitly shows2027 end year", "2027" in await active.locator(".event-list").inner_text())
        await check(steps, "375px exposes all3 fixture price rows without detail clicks", await page.locator(".price-row").count() == 3)
        await check(steps, "375px no horizontal overflow", await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        await page.screenshot(path="/tmp/cheongyak-followup-mobile.png", full_page=True)

        requests_before = len(router.requests)
        await page.get_by_label("현재 거주 지역", exact=True).select_option("11")
        await page.get_by_label("현재 거주 시군구", exact=True).select_option("11740")
        await page.get_by_label("시도 연속 거주 시작일", exact=True).fill("2024-01-01")
        await settle(page)
        await check(steps, "editing residence and move-in date makes no API request", len(router.requests) == requests_before)
        stored = json.loads(await page.evaluate("localStorage.getItem('cheongyak-profile-v4')"))
        await check(steps, "residence profile persists locally", stored["version"] == 4 and stored["regionCode"] == "11" and stored["districtCode"] == "11740" and stored["movedInDate"] == "2024-01-01")

        await page.get_by_role("button", name="민간임대", exact=True).click()
        await expect(page.locator(".notice-card")).to_have_count(1)
        await page.get_by_role("button", name="유형별 근거", exact=True).click()
        router.success_timestamp = "2026-09-30T03:02:00Z"
        async with page.expect_response(lambda response: urlsplit(response.url).path == "/api/coverage"):
            await page.get_by_role("button", name="새로고침", exact=True).click()
        await page.wait_for_load_state("networkidle")
        await expect(page.locator(".notice-card")).to_have_count(1)
        await check(steps, "manual refresh plus new collection success preserves private-rental filter", await page.get_by_role("button", name="민간임대", exact=True).get_attribute("aria-pressed") == "true")
        await check(steps, "background data replacement keeps an expanded card mounted", await page.get_by_role("button", name="근거 접기", exact=True).count() == 1)
        await check(steps, "manual refresh retains residence and move-in profile", await page.get_by_label("현재 거주 시군구", exact=True).input_value() == "11740" and await page.get_by_label("시도 연속 거주 시작일", exact=True).input_value() == "2024-01-01")
        await page.get_by_role("button", name="전체 공고", exact=True).click()
        await expect(page.locator(".notice-card")).to_have_count(3)

        await page.get_by_role("button", name="다음 달", exact=True).click()
        await expect(page.locator(".calendar-month strong")).to_have_text("2026년 10월")
        await page.get_by_role("button", name=re.compile(r"^10월 4일.*접수 일정 있음")).click()
        await expect(page.locator(".notice-card")).to_have_count(2)
        await check(steps, "selected future date groups active and upcoming notices under that day", all("10월 4일" in text for text in await page.locator(".day-heading h3").all_text_contents()))
        await check(steps, "future date selection retains local profile", await page.get_by_label("현재 거주 시군구", exact=True).input_value() == "11740")
        await page.get_by_role("button", name="다가오는 일정", exact=True).click()
        await expect(page.locator(".calendar-month strong")).to_have_text("2026년 9월")

        calls = router.coverage_calls
        await page.clock.fast_forward(280000)
        await settle(page)
        await check(steps, "completed coverage avoids30s polling", router.coverage_calls == calls)
        await page.clock.fast_forward(21000)
        await settle(page)
        await check(steps, "completed coverage polls after5min", router.coverage_calls > calls)

        await page.evaluate("Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' }); document.dispatchEvent(new Event('visibilitychange'))")
        calls = router.coverage_calls
        await page.clock.fast_forward(301000)
        await settle(page)
        await check(steps, "hidden tab stops periodic coverage requests", router.coverage_calls == calls)
        await page.evaluate("Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' }); document.dispatchEvent(new Event('visibilitychange'))")
        await settle(page)
        await check(steps, "long hidden-tab return makes no immediate coverage request", router.coverage_calls == calls)
        calls = router.coverage_calls
        request_count = len(router.requests)
        await page.clock.fast_forward(1001)
        await page.evaluate("window.dispatchEvent(new Event('focus'))")
        await settle(page)
        await check(steps, "short focus out/in makes no API request", router.coverage_calls == calls and len(router.requests) == request_count)

        target = int(datetime(2026, 9, 30, 14, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        now = await page.evaluate("Date.now()")
        await page.clock.fast_forward(target - now)
        await settle(page)
        await page.get_by_role("button", name=re.compile(r"^9월 30일.*접수 일정 있음")).click()
        await settle(page)
        requests_before_midnight = len(router.notice_requests())
        await page.clock.fast_forward(2000)
        await expect(page.locator(".calendar-month strong")).to_have_text("2026년 10월")
        await check(steps, "KST midnight advances current month and drops September navigation", await page.get_by_role("button", name="이전 달", exact=True).is_disabled())
        await check(steps, "actual KST date transition refreshes the public date range", len(router.notice_requests()) > requests_before_midnight and any(parse_qs(urlsplit(r["url"]).query)["start"] == ["2026-10-01"] for r in router.notice_requests()[requests_before_midnight:]))
        await check(steps, "KST midnight updates profile date maximum", await page.get_by_label("시도 연속 거주 시작일", exact=True).get_attribute("max") == "2026-10-01")
        await check(steps, "midnight with a selected previous day never sends start after end", all(parse_qs(urlsplit(r["url"]).query)["start"][0] <= parse_qs(urlsplit(r["url"]).query)["end"][0] for r in router.notice_requests()))
        await check(steps, "every notice request sends both accepted server filters", all(parse_qs(urlsplit(r["url"]).query).get("exclude_public_rental") == ["true"] and parse_qs(urlsplit(r["url"]).query).get("application_only") == ["true"] for r in router.notice_requests()))
        serialized = json.dumps(router.requests, ensure_ascii=False)
        await check(steps, "all API requests remain GET with no local profile values or fields", all(r["method"] == "GET" and not r["body"] for r in router.requests) and not any(secret in serialized for secret in ["서울특별시", "강동구", "2024-01-01", "movedInDate", "regionCode", "districtCode", "11740", "annualIncomeKrw"]))
        await check(steps, "no unexpected API endpoints", not router.errors)

        race_router = FixtureRouter()
        race_router.phase = "ok"
        race_router.initial_empty_responses = 2
        race_context = await browser.new_context(viewport={"width": 375, "height": 812}, timezone_id="Asia/Seoul")
        race_page = await race_context.new_page()
        await race_page.clock.install(time=datetime(2026, 9, 30, 3, 0, 0, tzinfo=timezone.utc))
        await race_page.route("**/api/**", race_router.handle)
        await race_page.goto(BASE, wait_until="networkidle")
        if await race_page.locator(".notice-card").count() == 0:
            await race_page.clock.fast_forward(301000)
        await expect(race_page.locator(".notice-card")).to_have_count(3)
        await check(steps, "initial empty data plus already-completed first coverage recovers automatically", True)
        await browser.close()
    print(json.dumps({"passed": len(steps), "checks": steps, "coverage_calls": router.coverage_calls, "notice_requests": len(router.notice_requests()), "screenshot": "/tmp/cheongyak-followup-mobile.png"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
