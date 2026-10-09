"""Native disclosure QA for failed supply paths, using public API fixtures."""

import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright, expect
from profile_facts_v10_browser_qa import NOW, PROFILE_KEY, Router

BASE = os.environ.get("CHEONGYAK_QA_BASE", "http://127.0.0.1:5193")
OUT = Path(os.environ.get("CHEONGYAK_QA_OUT", "/tmp/cheongyak-supply-collapse-qa"))
EVIDENCE = "https://example.org/qa-public-notice.pdf"
ROW = {"id": "qa-supply-collapse", "title": "회귀 검증용 공급유형", "category": "apt", "source": "cheongyak_home", "provider": "공개 응답 브라우저 검증", "address": None, "region_code": None, "region_name": None, "announcement_date": "2026-10-08", "official_url": EVIDENCE, "price_cap_status": "no", "events": [{"kind": "special", "label": "특별공급", "start_date": "2026-10-12", "end_date": "2026-10-12"}], "prices": [], "rules": [{"kind": kind, "value": value, "supply_type": supply_type, "verification": "official", "evidence_url": EVIDENCE, "evidence_text": "검증용 공개 신청 조건"} for kind, value, supply_type in [("age_min", 19, "일반공급"), ("parent_age_min", 65, "노부모부양 특별공급")]], "rules_complete": True, "offered_supplies": [{"supply_type": "일반공급", "unit_type": "084", "supply_count": 12, "verification": "official"}, {"supply_type": "노부모부양 특별공급", "unit_type": "074", "supply_count": 1, "verification": "official"}, {"supply_type": "노부모부양 특별공급", "unit_type": "084", "supply_count": 1, "verification": "official"}], "updated_at": "2026-10-09T00:55:00Z", "version": 1}


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []

    def check(label, condition=True):
        assert condition, label
        checks.append(label)
        print(label, flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])

        async def create(width, parent_birth="1966-01-01"):
            context = await browser.new_context(viewport={"width": width, "height": 900}, timezone_id="Asia/Seoul")
            value = {"version": 5, "dateOfBirth": "1990-01-01", "parentDateOfBirth": parent_birth}
            await context.add_init_script(f"localStorage.setItem({json.dumps(PROFILE_KEY)}, {json.dumps(json.dumps(value))})")
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.clock.set_fixed_time(NOW)
            router = Router([ROW])
            await page.route("**/api/**", router.handle)
            await page.route("https://fonts.googleapis.com/**", lambda route: route.fulfill(status=200, body=""))
            await page.goto(BASE, wait_until="domcontentloaded")
            await expect(page.locator(".notice-card")).to_have_count(1, timeout=15000)
            await page.wait_for_timeout(350)
            return page, router

        for width in [375, 1280]:
            page, router = await create(width)
            before = len(router.requests)
            overview = page.locator(".qualification-supply-overview")
            failed = overview.locator("details.qualification-supply-collapse")
            await expect(failed).to_have_count(1)
            await expect(failed).to_have_js_property("open", False)
            await expect(failed.locator("summary")).to_contain_text("노부모부양 특별공급")
            await expect(failed.locator("summary")).to_contain_text("내 조건으로 신청 불가")
            await expect(failed.locator("summary")).to_contain_text("074 · 모집 1세대 / 084 · 모집 1세대")
            await expect(page.get_by_text("불일치 · 부모 만 나이", exact=True)).to_be_hidden()
            check(f"{width}px failed brief path starts closed with no failure facts exposed outside")
            await expect(overview.locator("section.qualification-possible .qualification-brief-row")).to_be_visible()
            check(f"{width}px possible general supply remains expanded")
            await failed.locator("summary").scroll_into_view_if_needed()
            await page.screenshot(path=str(OUT / f"closed-brief-{width}.png"))
            await failed.locator("summary").click()
            await expect(failed).to_have_js_property("open", True)
            await expect(failed.get_by_text("불일치 · 부모 만 나이", exact=True)).to_be_visible()
            await expect(failed.locator(".qualification-reason-body a")).to_have_attribute("href", EVIDENCE)
            await expect(failed.locator(".qualification-reason-body a")).to_be_visible()
            check(f"{width}px brief expansion reveals 60-versus-65 comparison and public evidence")
            await failed.locator("summary").focus()
            await failed.locator("summary").press("Enter")
            await expect(failed).to_have_js_property("open", False)
            check(f"{width}px native summary keyboard toggle closes evidence")

            await page.get_by_role("button", name="유형별 근거", exact=True).click()
            details = page.locator(".qualification-details")
            failed_detail = details.locator("details.qualification-supply-collapse")
            await expect(failed_detail).to_have_count(1)
            await expect(failed_detail).to_have_js_property("open", False)
            failure_rows = page.get_by_text("불일치 · 부모 만 나이", exact=True)
            for row in await failure_rows.all():
                await expect(row).to_be_hidden()
            await expect(details.locator("section.qualification-supply")).to_contain_text("일반공급")
            check(f"{width}px detailed mismatch also starts closed without promoted shared failure facts")
            await failed_detail.locator("summary").focus()
            await failed_detail.locator("summary").press("Enter")
            await expect(failed_detail).to_have_js_property("open", True)
            await expect(failed_detail.get_by_text("불일치 · 부모 만 나이", exact=True)).to_be_visible()
            await expect(failed_detail.locator(".qualification-reason-body a")).to_be_visible()
            check(f"{width}px detailed keyboard expansion retains original source evidence")
            await failed_detail.scroll_into_view_if_needed()
            await page.screenshot(path=str(OUT / f"open-detail-{width}.png"))
            check(f"{width}px disclosure preserves page width", await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
            check(f"{width}px all disclosure actions are local without API requests", len(router.requests) == before and not router.errors and all(request["method"] == "GET" and request["body"] is None for request in router.requests))
            await page.context.close()

        page, router = await create(375, "")
        overview = page.locator(".qualification-supply-overview")
        await expect(overview.locator("details.qualification-supply-collapse")).to_have_count(0)
        await expect(overview.get_by_text("내 입력 부족 · 부모 만 나이", exact=True)).to_be_visible()
        check("missing parent age stays expanded as a review path")
        await page.context.close()
        check("all disclosure pages have no JavaScript exceptions", not errors)
        await browser.close()

    result = {"fixture_data_only": True, "checks_passed": len(checks), "checks": checks, "javascript_errors": errors}
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
