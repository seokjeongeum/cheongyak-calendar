"""375px rank explanations with official source fixtures and synthetic facts.

All API responses are intercepted. Optional CHEONGYAK_QA_LIVE_DIR contains
saved public notice DTOs; no production API or personal profile is fetched.
"""

import asyncio
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, expect
from profile_facts_v10_browser_qa import PROFILE_KEY, Router, profile

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("CHEONGYAK_QA_BASE", "http://127.0.0.1:5176")
OUT = Path(os.environ.get("CHEONGYAK_QA_OUT", "/tmp/cheongyak-rank-v15-browser-qa"))
NOW = datetime(2026, 10, 11, 1, 0, tzinfo=timezone.utc)
SOURCES = json.loads((ROOT / "web/src/fixtures/private-ranking-official-v15.json").read_text())


def person(**extra):
    value = profile(
        region="경기도", regionCode="41", district="화성시", districtCode="41590",
        movedInDate="2023-01-01", privateRankBaseDate="2009-07-02", privateDepositKrw="3000000",
        privateDepositAsOfDate="2026-10-02", accountConversionUnclear=False,
        factChanges={"bank_private": {"mode": "never_changed", "date": ""}},
    )
    return {**value, **extra}


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors, times, assets = [], [], [], set()

    def check(label, value=True):
        assert value, label
        checks.append(label)
        print(label, flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])

        async def create(row, value):
            row = copy.deepcopy(row)
            row["events"] = [{"kind": "first_priority", "label": "1순위", "start_date": "2026-10-13", "end_date": "2026-10-13"}]
            context = await browser.new_context(viewport={"width": 375, "height": 900}, timezone_id="Asia/Seoul")
            await context.add_init_script(f"localStorage.setItem({json.dumps(PROFILE_KEY)}, {json.dumps(json.dumps(value))})")
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.clock.set_fixed_time(NOW)
            router = Router([row])
            await page.route("**/api/**", router.handle)
            await page.route("https://fonts.googleapis.com/**", lambda route: route.fulfill(status=200, body=""))
            await page.goto(BASE, wait_until="domcontentloaded")
            await expect(page.locator(".notice-card")).to_have_count(1, timeout=15000)
            await expect(page.locator(".qualification-account-summary")).to_be_visible()
            assets.update(await page.locator('script[src*="/assets/"]').evaluate_all("els => els.map(el => el.src.split('/').pop())"))
            return page, router

        async def no_requests(page, router, before, label):
            await page.evaluate("""() => {window.dispatchEvent(new Event('focus')); Object.defineProperty(document, 'visibilityState', {configurable:true,get:()=> 'hidden'}); document.dispatchEvent(new Event('visibilitychange')); Object.defineProperty(document, 'visibilityState', {configurable:true,get:()=> 'visible'}); document.dispatchEvent(new Event('visibilitychange'));}""")
            await page.wait_for_timeout(400)
            check(label, len(router.requests) == before and not router.errors and all(r["method"] == "GET" and r["body"] is None for r in router.requests))

        rows = [("source-" + str(index), row) for index, row in enumerate(SOURCES)]
        live_dir = os.environ.get("CHEONGYAK_QA_LIVE_DIR")
        if live_dir:
            for name in ["hangang", "hyangnam"]:
                rows.append(("saved-public-" + name, json.loads((Path(live_dir) / (name + ".json")).read_text())))

        for label, row in rows:
            page, router = await create(row, person())
            before = len(router.requests)
            summary = page.locator(".qualification-account-summary")
            await expect(summary).to_contain_text("민영 순위 인정기간 충족")
            await expect(summary).to_contain_text("통장 종류 충족")
            await expect(summary).to_contain_text("주택형의 전용면적별 예치금 기준이 다릅니다")
            check(f"{label}: 207-month and account passes retain the adjacent deposit blocker")
            tiers = summary.locator(".qualification-account-tiers")
            for amount in ["2,000,000원", "4,000,000원", "5,000,000원"]:
                await expect(tiers).to_contain_text(amount)
            await expect(tiers).to_contain_text("내 입력 3,000,000원")
            await expect(tiers).to_contain_text("불일치 · 민영주택 예치금")
            check(f"{label}: 2/4/5-million regional tiers retain actual unit failures")
            await summary.scroll_into_view_if_needed()
            check(f"{label}: 375px rank summary has no horizontal overflow", await page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
            await page.screenshot(path=str(OUT / (label + "-summary-375.png")))
            await page.get_by_role("button", name="유형별 근거", exact=True).click()
            section = page.locator(".qualification-rank-section")
            await expect(section).to_contain_text("추가 확인 필요 · 민영주택 예치금")
            await expect(section).to_contain_text("면적별 청약통장 조건")
            await expect(section).to_contain_text("불일치 · 민영주택 예치금")
            check(f"{label}: expanded rank section explains unresolved tiers beside source evidence")
            await no_requests(page, router, before, f"{label}: expanding evidence and focus return fetch nothing and send no profile")
            await page.context.close()

        for index, row in enumerate(SOURCES):
            page, router = await create(row, person(privateDepositKrw="6000000"))
            before = len(router.requests)
            summary = page.locator(".qualification-account-summary")
            await expect(summary).to_contain_text("민영주택 1순위 조건 충족")
            await expect(summary.locator(".qualification-account-pending")).to_have_count(0)
            await expect(summary.locator(".qualification-account-tiers")).not_to_contain_text("불일치")
            check(f"source-{index}: every tier passing yields first rank without a selection confirmation")
            await no_requests(page, router, before, f"source-{index}: complete rank comparison stays local and focus performs no fetch")
            await page.context.close()

        value = person()
        value["privateDepositKrw"] = ""
        page, router = await create(SOURCES[0], value)
        before = len(router.requests)
        summary = page.locator(".qualification-account-summary")
        action = summary.get_by_role("button", name="민영주택 예치금 입력하기", exact=True)
        await expect(action).to_have_count(1)
        check("missing common deposit asks one question across all area tiers")
        await action.click()
        field = page.get_by_role("dialog").get_by_label("민영주택 예치금 (원)", exact=True)
        await expect(field).to_be_visible()
        await expect(field).to_be_focused()
        check("deposit action opens and focuses its actual shared bank input")
        await field.evaluate("el => {const native=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; const t=performance.now(); native.call(el,'3000000'); el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); requestAnimationFrame(()=>window.__rankInputPaint=performance.now()-t)}")
        await expect(field).to_have_value("3,000,000")
        await page.wait_for_timeout(200)
        times.append(await page.evaluate("window.__rankInputPaint"))
        await page.get_by_role("dialog").locator(".dialog-close").click()
        saved = json.loads(await page.evaluate(f"localStorage.getItem('{PROFILE_KEY}')"))
        check("deposit edit persists only in the browser", saved["privateDepositKrw"] == "3000000")
        await no_requests(page, router, before, "deposit input and focus return transmit no private API requests")
        check("375px bank input and updated rank retain no overflow", await page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        await page.context.close()

        await browser.close()
    check("rank input reaches the next paint within 100ms", bool(times) and max(times) < 100)
    check("browser has no JavaScript errors", not errors)
    result = {"checks": len(checks), "labels": checks, "errors": errors, "input_paint_ms": times, "assets": sorted(assets), "fixtures": len(rows)}
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
