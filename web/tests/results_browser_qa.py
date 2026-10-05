"""Results tabs and readable qualification evidence browser regression checks.

Run with /home/seokj/kaggle/.venv/bin/python and CHEONGYAK_QA_BASE
(default localhost:8080). Controlled public responses test the new flow;
an additional read-only live check verifies retained archived official rows.
No API keys, environment files, server writes or shared profiles are used.
Set CHEONGYAK_QA_SKIP_LIVE=1 only for a frontend preview without the API.
"""

import asyncio
import copy
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect

from competition_browser_qa import PROFILE, competition, rank_rules
from profile_browser_qa import notice as profile_notice, rule


BASE = os.environ.get("CHEONGYAK_QA_BASE", "http://localhost:8080")
NOW = datetime(2026, 10, 3, 3, tzinfo=timezone.utc)
FRESH = "2026-10-03T02:55:00Z"
OLD = "2026-09-01T01:00:00Z"
PROFILE_KEY = "cheongyak-profile-v2"
OVERRIDE_KEY = "cheongyak-residence-overrides-v1"
BODY_SELECTOR = ".qualification-reason-body"
SOURCES = ["cheongyak_home", "myhome", "lh", "ih", "sh", "gh", "cheongyak_competition"]
SCREENSHOTS = {
    "desktop_evidence": "/tmp/cheongyak-readable-evidence-desktop.png",
    "mobile_evidence": "/tmp/cheongyak-readable-evidence-mobile.png",
    "mobile_results": "/tmp/cheongyak-results-mobile.png",
    "live_results": "/tmp/cheongyak-results-live.png",
}
PRIVATE_PROFILE = {**PROFILE, "privateRankBaseDate": "2010-01-01", "annualIncomeKrw": "60000000"}


def schedule_fixture():
    row = profile_notice("qa-readable-evidence", "검증 읽을 수 있는 유형별 근거", "private")
    row["rules"] = [*rank_rules(), rule("homeless", True, id="common-homeless"),
                    rule("income_max_krw", 70_000_000, period="annual", id="common-income"),
                    rule("income_max_krw", 5_000_000, period="monthly", id="missing-monthly-income"),
                    rule("deposit_min_krw", 2_000_000, unit_type="59A", id="unit-59-deposit"),
                    rule("deposit_min_krw", 3_000_000, unit_type="84A", id="unit-84-deposit")]
    row["rules"][2]["evidence_text"] = "법정 확인 대상 세대원 전원이 주택 및 권리를 소유하지 않아야 합니다. " * 8
    row["events"] = [{"kind": "general", "label": "일반공급", "start_date": "2026-10-05", "end_date": "2026-10-07", "audience": "기타지역"}]
    row["application_end_date"] = "2026-10-07"
    row["rules_complete"] = True
    return row


def result_fixture(index, state="ok"):
    row = schedule_fixture()
    row.update(id=f"qa-result-{index:03}", title=f"검증 종료된 공식 결과 {index:03}",
               sort_date="2026-09-29", application_end_date="2026-10-02")
    row["events"] = [{"kind": "first_priority", "label": "1순위", "start_date": "2026-09-29", "end_date": "2026-10-02", "audience": "기타지역"}]
    observed = FRESH if state == "ok" else OLD
    rows = [competition(unit, rate=rate, observed=observed)
            for unit, rate in [("59A", "68.71"), ("84A", "(△57)")]]
    rows += [competition(unit, area="other", rate="-", observed=observed) for unit in ["59A", "84A"]]
    for result in rows:
        result.update(supply_type="general", supply_type_label="일반공급")
    row["competitions"] = rows
    row["competition"] = {"status": state, "last_attempt_at": FRESH, "last_success_at": observed,
                          "complete": state == "ok", "unit_types": ["59A", "84A"],
                          "evidence_url": rows[0]["evidence_url"], "message": "공식 결과 원본 보존"}
    return row


class Router:
    def __init__(self):
        self.schedule = schedule_fixture()
        # Cross the public API's 100-row page boundary and UI's 20-card limit.
        self.results = [result_fixture(index, ["ok", "pending", "error"][index % 3]) for index in range(101)]
        self.requests = []
        self.errors = []
        self.success = FRESH
        self.delay_schedule = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        self.requests.append({"url": request.url, "method": request.method, "body": request.post_data})
        if parsed.path == "/api/coverage":
            response = {"sources": [{"source": source, "status": "ok", "last_attempt_at": self.success,
                                     "last_success_at": self.success, "record_count": 101} for source in SOURCES]}
        elif parsed.path == "/api/notices":
            query = parse_qs(parsed.query)
            results = query.get("view") == ["results"]
            if self.delay_schedule and not results:
                self.started.set()
                await self.release.wait()
            candidates = self.results if results else [self.schedule]
            start, end = query["start"][0], query["end"][0]
            rows = [row for row in candidates if any(event["start_date"] <= end and event["end_date"] >= start for event in row["events"])]
            page, size = int(query.get("page", ["1"])[0]), int(query.get("page_size", ["100"])[0])
            response = {"items": copy.deepcopy(rows[(page - 1) * size:page * size]),
                        "total": len(rows), "page": page, "page_size": size}
        else:
            self.errors.append(parsed.path)
            await route.fulfill(status=404, json={"detail": "unexpected endpoint"})
            return
        await route.fulfill(status=200, json=response)

    def calls(self, view=None):
        rows = [request for request in self.requests if urlsplit(request["url"]).path == "/api/notices"]
        if view:
            return [request for request in rows if parse_qs(urlsplit(request["url"]).query).get("view", ["schedule"])[0] == view]
        return rows


async def visibility(page, state):
    await page.evaluate("state => { Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state }); document.dispatchEvent(new Event('visibilitychange')); }", state)


async def evidence_metrics(card):
    return await card.locator(BODY_SELECTOR).evaluate_all("""bodies => bodies.map(body => {
      const row = body.parentElement, icon = row.querySelector('.qualification-icon');
      const b = body.getBoundingClientRect(), r = row.getBoundingClientRect(), i = icon?.getBoundingClientRect();
      return { bodyWidth: b.width, rowWidth: r.width, iconWidth: i?.width || 0,
        remainingWidth: r.right - b.left, bodyRight: b.right, rowRight: r.right, height: b.height };
    })""")


async def main():
    checks = []
    measurements = {}
    live_summary = None

    def check(label, value=True):
        assert value, label
        checks.append(label)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        router = Router()
        context = await browser.new_context(viewport={"width": 1280, "height": 900}, timezone_id="Asia/Seoul")
        overrides = {row["id"]: "other" for row in [router.schedule, *router.results]}
        await context.add_init_script(f"localStorage.setItem({json.dumps(PROFILE_KEY)}, {json.dumps(json.dumps(PRIVATE_PROFILE))}); localStorage.setItem({json.dumps(OVERRIDE_KEY)}, {json.dumps(json.dumps(overrides))});")
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.clock.install(time=NOW)
        await page.route("**/api/**", router.handle)
        await page.goto(BASE, wait_until="networkidle")
        schedule_panel = page.locator("#schedule-panel")
        card = schedule_panel.locator(".notice-card")
        await expect(card).to_have_count(1)
        await card.get_by_role("button", name="유형별 근거", exact=True).click()
        await expect(card.locator(BODY_SELECTOR).first).to_be_visible()
        for width, name in [(1280, "desktop"), (375, "mobile")]:
            await page.set_viewport_size({"width": width, "height": 900 if width == 1280 else 812})
            await page.wait_for_timeout(100)
            measured = await evidence_metrics(card)
            measurements[name] = measured
            check(f"{name} evidence has readable body width, fixed icon and no one-character column",
                  bool(measured) and all(row["bodyWidth"] >= (350 if width == 1280 else 200)
                                        and 0 < row["iconWidth"] <= 20
                                        and row["bodyWidth"] >= row["remainingWidth"] - 8
                                        and row["bodyRight"] <= row["rowRight"] + 2 for row in measured))
            check(f"{name} long official evidence wraps without horizontal page overflow",
                  await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
            await card.screenshot(path=SCREENSHOTS[f"{name}_evidence"])
        details = card.locator(".qualification-details")
        check("common homeless requirement appears once in expanded evidence across both units",
              await details.locator(f"{BODY_SELECTOR} > strong").filter(has_text="무주택 세대구성원").count() == 1)
        detail_text = await details.inner_text()
        check("the old repeated placeholder requirements are absent",
              not any(text in detail_text for text in ["미입력 또는 범위 확인 필요", "원문 조건 확인 필요", "조건 범위"]))
        before_question = len(router.requests)
        await details.get_by_role("button", name="공고 기준 월평균소득 입력하기", exact=True).click()
        question_dialog = page.get_by_role("dialog")
        monthly_income = question_dialog.get_by_label("공고 기준 가구 월평균소득 (원)", exact=True)
        await expect(monthly_income).to_be_visible()
        await expect(monthly_income).to_be_focused()
        await expect(question_dialog.locator(".step-progress [aria-current='step']")).to_contain_text("소득·자산")
        check("missing monthly-income action opens the required question step and focuses the field")
        check("missing-input question linking makes no API request", len(router.requests) == before_question)
        await question_dialog.get_by_role("button", name="닫기", exact=True).first.click()
        check("closing the linked question preserves expanded card evidence",
              await card.get_by_role("button", name="근거 접기", exact=True).count() == 1)

        # Focus alone must not trigger data requests, including after a long
        # period spent hidden; legitimate periodic polling is tested separately.
        before = len(router.requests)
        await page.evaluate("window.dispatchEvent(new Event('blur')); window.dispatchEvent(new Event('focus'))")
        await visibility(page, "hidden")
        await page.clock.fast_forward(2_000)
        await visibility(page, "visible")
        await page.wait_for_timeout(100)
        check("short focus/visibility return makes zero API requests", len(router.requests) == before)
        await visibility(page, "hidden")
        await page.clock.fast_forward(20 * 60 * 1000)
        await visibility(page, "visible")
        await page.evaluate("window.dispatchEvent(new Event('focus'))")
        await page.wait_for_timeout(100)
        check("long hidden focus return makes zero API requests", len(router.requests) == before)

        await page.get_by_role("button", name="내 조건 설정", exact=True).click()
        dialog = page.get_by_role("dialog")
        await dialog.get_by_role("button", name=re.compile("소득·자산")).click()
        income = dialog.get_by_label(re.compile(r"^가구 연 소득 합계 \(원\)"))
        await income.fill("-120")
        router.success = "2026-10-03T03:30:00Z"
        router.delay_schedule = True
        await page.clock.fast_forward(300_001)
        await asyncio.wait_for(router.started.wait(), timeout=5)
        check("collection completion refresh retains card and expanded evidence while loading",
              await card.count() == 1 and await card.get_by_role("button", name="근거 접기", exact=True).count() == 1)
        check("background loading retains invalid input in active conditions dialog",
              await income.input_value() == "-120" and await income.get_attribute("aria-invalid") == "true")
        router.delay_schedule = False
        router.release.set()
        await page.wait_for_load_state("networkidle")
        check("updated response retains expanded evidence and in-progress profile input",
              await card.get_by_role("button", name="근거 접기", exact=True).count() == 1 and await income.input_value() == "-120")
        await dialog.get_by_role("button", name="닫기", exact=True).first.click()

        await page.get_by_role("tab", name="경쟁률·청약결과", exact=True).click()
        results_panel = page.locator("#results-panel")
        await expect(results_panel.locator(".notice-card")).to_have_count(20)
        await expect(schedule_panel).to_be_hidden()
        result_requests = router.calls("results")
        query = parse_qs(urlsplit(result_requests[0]["url"]).query)
        check("results default range is the inclusive last90days and uses public results mode",
              query["start"] == ["2026-07-06"] and query["end"] == ["2026-10-03"]
              and query["application_only"] == ["true"] and query["exclude_public_rental"] == ["true"])
        check("results fetch includes page2 beyond the public100row limit",
              any(parse_qs(urlsplit(request["url"]).query).get("page") == ["2"] for request in result_requests))
        await expect(results_panel.locator(".results-explanation")).to_contain_text("101건")
        check("archive results keep fully locally closed units for an other-area first-rank profile",
              await results_panel.locator(".notice-card").count() == 20 and await results_panel.locator(".competition-row").count() == 80)
        check("archive cards keep all prices expanded independently of closure",
              await results_panel.locator(".price-row").count() == 40)
        check("archive has no private eligibility, candidate labels or residence override controls",
              await results_panel.locator(".eligibility-summary,.qualification-brief,.qualification-details,.rank-explanation,.competition-personal,.notice-card select,.local-tag,.event-candidate,.candidate-note,.local-notice").count() == 0)
        check("past monthly calendar is never introduced for result browsing", not await page.locator(".calendar-card").is_visible())
        result_cards = results_panel.locator(".notice-card")
        for index in (1, 2):
            archived = result_cards.nth(index)
            await expect(archived.locator(".competition-row")).to_have_count(4)
        check("pending and failed stale official result snapshots remain readable")
        first = result_cards.first
        await expect(first.locator(".competition-table")).to_contain_text("68.71")
        await expect(first.locator(".competition-table")).to_contain_text("미달 57세대")
        await expect(first.locator(".competition-table")).to_contain_text("미공개")
        check("raw competition ratio, shortage and unavailable marks remain distinct")
        await expect(results_panel.get_by_role("button", name=re.compile("결과 더 보기"))).to_be_visible()
        await results_panel.get_by_role("button", name=re.compile("결과 더 보기")).click()
        await expect(result_cards).to_have_count(40)
        check("result loadmore exposes another20cards without refiltering by private eligibility")
        await first.screenshot(path=SCREENSHOTS["mobile_results"])
        check("375px result prices and competition rows cause no horizontal overflow",
              await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        calls = len(router.calls("results"))
        await results_panel.get_by_role("button", name="새로고침", exact=False).click()
        await page.wait_for_load_state("networkidle")
        check("manual results refresh fetches public data and preserves expanded40cards",
              len(router.calls("results")) > calls and await result_cards.count() == 40)
        await page.get_by_label("결과 접수 기간 시작", exact=True).fill("2026-09-01")
        await expect(results_panel.locator(".notice-card")).to_have_count(20)
        check("changing results date range performs a real query and preserves ended rows",
              any(parse_qs(urlsplit(request["url"]).query).get("start") == ["2026-09-01"] for request in router.calls("results"))
              and await results_panel.locator(".notice-card").count() == 20)
        await page.get_by_role("tab", name="접수 일정", exact=True).click()
        await expect(schedule_panel).to_be_visible()
        await expect(card).to_have_count(1)
        check("returning to schedule retains expanded evidence and only upcoming receptions",
              await card.get_by_role("button", name="근거 접기", exact=True).count() == 1
              and "검증 종료된 공식 결과" not in await schedule_panel.inner_text())
        allowed = {"start", "end", "page", "page_size", "exclude_public_rental", "application_only", "cap_only", "view"}
        check("all controlled API requests are profile-free GET with only public query fields",
              all(request["method"] == "GET" and not request["body"]
                  and set(parse_qs(urlsplit(request["url"]).query)) <= allowed for request in router.requests)
              and not any(value in json.dumps(router.requests) for value in ["privateRankBaseDate", "60000000", "annualIncomeKrw", "2010-01-01"]))
        check("no unexpected endpoint or browser exception", not errors and not router.errors)
        await context.close()

        if os.environ.get("CHEONGYAK_QA_SKIP_LIVE") != "1":
            live_context = await browser.new_context(viewport={"width": 375, "height": 812}, timezone_id="Asia/Seoul")
            live = await live_context.new_page()
            await live.goto(BASE, wait_until="networkidle")
            await live.get_by_role("tab", name="경쟁률·청약결과", exact=True).click()
            live_panel = live.locator("#results-panel")
            await expect(live_panel.locator(".notice-card").first).to_be_visible(timeout=20_000)
            start = await live.get_by_label("결과 접수 기간 시작", exact=True).input_value()
            end = await live.get_by_label("결과 접수 기간 끝", exact=True).input_value()
            response = await live.request.get(f"{BASE}/api/notices", params={"view": "results", "start": start, "end": end,
                                               "exclude_public_rental": "true", "application_only": "true", "page_size": 100, "page": 1})
            check("deployed results API is reachable", response.ok)
            body = await response.json()
            saved = list(body["items"])
            for number in range(2, (body["total"] + body["page_size"] - 1) // body["page_size"] + 1):
                response = await live.request.get(f"{BASE}/api/notices", params={"view": "results", "start": start, "end": end,
                                                   "exclude_public_rental": "true", "application_only": "true", "page_size": 100, "page": number})
                saved.extend((await response.json())["items"])
            official_count = sum(sum(result.get("verification") == "official" for result in row.get("competitions", [])) for row in saved)
            check("deployed database retains at least64saved official competition rows", official_count >= 64)
            displayed = min(20, len(saved))
            await expect(live_panel.locator(".notice-card")).to_have_count(displayed)
            expected_rows = sum(len(row.get("competitions", [])) for row in saved[:displayed])
            check("real result cards render every stored competition row without opening a notice",
                  await live_panel.locator(".competition-row").count() == expected_rows and expected_rows > 0)
            check("real archived result cards show prices and omit qualification controls",
                  await live_panel.locator(".price-row").count() > 0
                  and await live_panel.locator(".competition-personal,.eligibility-summary").count() == 0)
            check("real375px results fit viewport", await live.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
            await live_panel.locator(".notice-card").first.screenshot(path=SCREENSHOTS["live_results"])
            live_summary = {"notices": len(saved), "official_rows": official_count, "displayed_rows": expected_rows}
            await live_context.close()
        await browser.close()
    print(json.dumps({"passed": len(checks), "checks": checks, "measurements": measurements,
                      "live": live_summary, "screenshots": SCREENSHOTS}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
