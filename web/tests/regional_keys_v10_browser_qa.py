"""375px region/key-label QA from the exact backend-parsed official sources.

Public notices contain real source paragraphs, hashes, names and cutoffs; only
the upcoming reception event is synthetic so they remain visible in this QA.
Residence facts and configured-key flags are fresh browser-only fixtures.
"""

import asyncio
import json
import os
from pathlib import Path
import sys

from playwright.async_api import async_playwright, expect

from profile_facts_v10_browser_qa import NOW, PROFILE_KEY, Router

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
from app.extract.official_rules import parse_official_rules  # noqa: E402

BASE = os.environ.get("CHEONGYAK_QA_BASE", "http://127.0.0.1:5193")
OUT = Path(os.environ.get("CHEONGYAK_QA_OUT", "/tmp/cheongyak-regional-keys-v10-qa"))
SOURCE = next(row for row in json.loads((ROOT / "api/tests/fixtures/current-oct8-regions.json").read_text()) if row["external_id"] == "2026000471")
PARSED = parse_official_rules(SOURCE["pages"], url=SOURCE["document_url"], digest=SOURCE["document_hash"], payload=SOURCE["payload"])
ROW = {**SOURCE["payload"], "id": "qa-official-hanyang", "provider": "공식 공고 원문 브라우저 검증", "address": None, "region_name": None, "region_code": None, "housing_kind": "private", "document_hash": SOURCE["document_hash"], "price_cap_status": "no", "events": [{"kind": "first_priority", "label": "1순위", "start_date": "2026-10-12", "end_date": "2026-10-12", "audience": None}], "prices": [], "rules": PARSED["rules"], "rules_complete": False, "updated_at": "2026-10-09T00:55:00Z", "version": 1}
DISTRICTS = [("12210", "동구"), ("12240", "서구"), ("12270", "남구"), ("12300", "북구"), ("12330", "광산구")]
SERVICES = [("DATA_GO_KR_API_KEY", "공공데이터 공통 키 · 청약홈", "15098547"), ("MYHOME_API_KEY", "마이홈", "15108420"), ("LH_API_KEY", "LH", "15058530"), ("IH_API_KEY", "iH 인천도시공사", "15149725"), ("CHEONGYAK_COMPETITION_API_KEY", "청약 경쟁률", "15098905")]
SETTINGS = {"admin_initialized": True, "gemini_unbilled_confirmed": False, "services": [{"name": name, "label": label, "key_url": f"https://www.data.go.kr/data/{identifier}/openapi.do", "configured": True, "storage": "server", "uses_shared_key": index > 0} for index, (name, label, identifier) in enumerate(SERVICES)]}


def person(**extra):
    return {"version": 5, "region": "전남광주통합특별시", "regionCode": "12", "district": "동구", "districtCode": "12210", "movedInDate": "2023-01-01", "districtMovedInDate": "2023-01-01", "militaryCurrentlyServing": False, "factChanges": {"military": {"mode": "never_changed", "date": ""}}, **extra}


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []

    def check(label, value=True):
        assert value, label
        checks.append(label)
        print(label, flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])

        async def create(value):
            context = await browser.new_context(viewport={"width": 375, "height": 900}, timezone_id="Asia/Seoul")
            await context.add_init_script(f"localStorage.setItem({json.dumps(PROFILE_KEY)}, {json.dumps(json.dumps(value))})")
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.clock.set_fixed_time(NOW)
            router = Router([ROW])

            async def route(route):
                if route.request.url.endswith("/api/integrations"):
                    router.requests.append({"url": route.request.url, "method": route.request.method, "body": route.request.post_data})
                    await route.fulfill(status=200, json=SETTINGS)
                else:
                    await router.handle(route)

            await page.route("**/api/**", route)
            await page.route("https://fonts.googleapis.com/**", lambda route: route.fulfill(status=200, body=""))
            await page.goto(BASE, wait_until="domcontentloaded")
            await expect(page.locator(".notice-card")).to_have_count(1, timeout=15000)
            region = page.get_by_role("region", name="내 지역 판정", exact=True)
            await expect(region).to_contain_text("지역 판정 기준일 2026-10-08")
            return page, region, router

        for district_code, district in DISTRICTS:
            page, region, router = await create(person(districtCode=district_code, district=district))
            await expect(region.locator('[data-region-status="local"]')).to_have_count(1)
            check(f"exact-source mapped current district {district_code} {district} has Hanyang local priority")
            if district_code == "12330":
                await region.scroll_into_view_if_needed()
                await page.screenshot(path=str(OUT / "hanyang-mapped-local-375.png"))
            await page.context.close()

        page, region, router = await create(person(districtCode="12860", district="진도군"))
        await expect(region.locator('[data-region-status="other"]')).to_have_count(1)
        await expect(region).to_contain_text("기타지역")
        check("former Jeonnam county remains other-region despite merged province admission")
        await page.context.close()

        page, region, router = await create(person(region="경기도", regionCode="41", district="화성시", districtCode="41590"))
        await expect(region.locator('[data-region-status="outside"]')).to_have_count(1)
        await expect(region).to_contain_text("신청지역 밖")
        check("Hwaseong outside the Hanyang source union stays outside when military is false")
        await page.context.close()

        page, region, router = await create(person(districtMovedInDate="2026-09-01"))
        await expect(region.locator('[data-region-status="source_gap"]')).to_have_count(1)
        await expect(region).to_contain_text("과거 거주 이력 확인 필요")
        await expect(region).not_to_contain_text("선택한 거주지와 공식 신청 지역 조건이 다릅니다")
        await expect(region.locator(".qualification-input-action")).to_have_count(0)
        check("recent mapped-district stay shows historical residence gap without an invented input button")
        await region.scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "hanyang-recent-history-375.png"))
        await page.get_by_role("button", name="API 연결 설정", exact=True).click()
        form = page.get_by_role("form", name="API 연결 설정", exact=True)
        providers = form.locator(".integration-provider")
        await expect(providers).to_have_count(5)
        labels = await providers.locator("small").all_text_contents()
        check("all five configured common-key provider rows use identical saved-key wording", labels == ["공통 키 연결됨"] * 5)
        check("all five provider approval links retain their exact service URLs", await providers.locator("a").evaluate_all("links => links.map(a => a.href)") == [f"https://www.data.go.kr/data/{identifier}/openapi.do" for _, _, identifier in SERVICES])
        await expect(form.locator(".integration-primary-keys small")).to_have_text("공통 키 연결됨")
        await expect(form.locator('input[type="password"]')).to_have_count(6)
        check("saved statuses expose no raw key or administrator credential", all(value == "" for value in [await field.input_value() for field in await form.locator('input[type="password"]').all()]))
        await form.locator(".integration-provider-links").scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "common-key-labels-375.png"))
        check("375px regional and common-key displays have no page overflow", await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        check("regional/key fixture uses only public GETs and sends no residence facts", all(request["method"] == "GET" and request["body"] is None and "2023-01-01" not in request["url"] for request in router.requests) and not router.errors)
        await page.context.close()
        check("real Chromium region/key pages have no JavaScript exceptions", not errors)
        await browser.close()
    result = {"fixture_data_only": True, "official_source_hash": SOURCE["document_hash"], "backend_parser_version": PARSED["parser_version"], "checks_passed": len(checks), "checks": checks, "javascript_errors": errors}
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
