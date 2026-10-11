"""375px region regression with deployed assets and isolated public responses.

The source case reads a saved notice_public DTO. Other cases deliberately vary
regional scope order/content to check new notices without project-specific code.
Only synthetic personal facts are stored in fresh browser contexts; API traffic
is intercepted and must remain GET-only with no profile values in requests.

Set CHEONGYAK_QA_SOURCE_ONLY=1 after reprocessing to require the saved source
case and skip the already-verified synthetic cases. The deployed asset can be
overridden with CHEONGYAK_QA_EXPECTED_ASSET for a later build.
"""

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect

from profile_facts_v10_browser_qa import NOW, PROFILE_KEY, Router, profile, rule

BASE = os.environ.get("CHEONGYAK_QA_BASE", "https://cheongyak-calendar.onrender.com")
OUT = Path(os.environ.get("CHEONGYAK_QA_OUT", "/tmp/cheongyak-capital-region-browser-qa"))
SOURCE = Path(os.environ.get("CHEONGYAK_QA_SOURCE", "/tmp/cheongyak-v17-public/after-sangdong.json"))
BASELINE = Path(os.environ.get("CHEONGYAK_QA_SOURCE_BASELINE", str(SOURCE.with_name("before-sangdong.json"))))
EXPECTED_ASSET = os.environ.get("CHEONGYAK_QA_EXPECTED_ASSET", "index-iDPuMwe4.js")
SOURCE_ONLY = os.environ.get("CHEONGYAK_QA_SOURCE_ONLY") == "1"
REQUIRE_SOURCE = os.environ.get("CHEONGYAK_QA_REQUIRE_SOURCE") == "1" or SOURCE_ONLY
PROVINCES = [
    {"region_code": "41", "region_name": "경기도"},
    {"region_code": "11", "region_name": "서울특별시"},
    {"region_code": "28", "region_name": "인천광역시"},
]


def person(**patch):
    return profile(**{
        "region": "경기도", "regionCode": "41", "district": "화성시", "districtCode": "41590",
        "movedInDate": "2020-01-01", "districtMovedInDate": "2020-01-01", "cityMovedInDate": "2020-01-01",
        "householdMembers": [], "pointsFamily": {}, "additionalFamilyPresence": False,
        "currentlyDomesticResident": True, "domesticResidenceFactsAsOfDate": "2026-10-01",
        **patch,
    })


def metadata(supply, regions):
    return rule("applicant_regions", None, effect="metadata", supply_type=supply,
                regions=regions, scope_complete=True, priority_applicable=False,
                exceptions=[], criterion_date="2026-10-02")


def fixture(different=False):
    return {
        "id": "qa-new-differing-scope" if different else "qa-new-reordered-scope",
        "title": "새 공고 · 분기별 신청지역 검증" if different else "새 공고 · 같은 수도권 순서 검증",
        "category": "apt", "housing_kind": "private", "source": "cheongyak_home",
        "provider": "공개 응답 브라우저 검증", "address": "서울특별시 강동구",
        "region_code": "11", "region_name": "서울특별시", "announcement_date": "2026-10-02",
        "official_url": "https://example.org/regional-qa.pdf", "price_cap_status": "unknown",
        "updated_at": "2026-10-09T00:55:00Z", "version": 1,
        "events": [{"kind": "general", "label": "청약 접수", "start_date": "2026-10-12", "end_date": "2026-10-12"}],
        "prices": [], "competitions": [], "competition": {"status": "pending", "complete": False, "unit_types": []},
        "rules_complete": True,
        "offered_supplies": [{"supply_type": supply, "unit_type": "079.1234Z", "supply_count": 2, "verification": "official"}
                             for supply in ["일반공급", "생애최초 특별공급"]],
        "rules": [metadata("일반공급", deepcopy(PROVINCES)),
                  metadata("생애최초 특별공급", [deepcopy(PROVINCES[1])] if different else list(reversed(deepcopy(PROVINCES)))),
                  rule("age_min", 19, criterion_date="2026-10-02")],
    }


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors, api_requests, assets = [], [], [], set()
    source_evidence = None

    def check(label, value=True):
        assert value, label
        checks.append(label)
        print(label, flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])

        async def create(row, facts):
            context = await browser.new_context(viewport={"width": 375, "height": 900}, timezone_id="Asia/Seoul")
            await context.add_init_script(f"localStorage.setItem({json.dumps(PROFILE_KEY)}, {json.dumps(json.dumps(facts))})")
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            context_assets = set()

            def record_asset(request):
                if "/assets/" in request.url:
                    assets.add(request.url)
                    context_assets.add(request.url)

            page.on("request", record_asset)
            await page.clock.set_fixed_time(NOW)
            router = Router([row])
            await page.route("**/api/**", router.handle)
            await page.route("https://fonts.googleapis.com/**", lambda route: route.fulfill(status=200, body=""))
            # A free Render instance may need roughly 50 seconds to wake up.
            await page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
            await expect(page.locator('.notice-card[data-evaluation-ready="true"]')).to_have_count(1, timeout=20000)
            if EXPECTED_ASSET:
                check("deployed asset matches the regional comparison build", any(EXPECTED_ASSET in asset for asset in context_assets))
            await page.wait_for_timeout(250)
            return page, page.locator(".notice-card"), router

        async def privacy(page, router, before, label):
            await page.evaluate("""() => {window.dispatchEvent(new Event('focus')); Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'}); document.dispatchEvent(new Event('visibilitychange')); Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'}); document.dispatchEvent(new Event('visibilitychange'));}""")
            await page.wait_for_timeout(450)
            check(label, len(router.requests) == before and not router.errors)
            check("regional comparison transmits no personal facts or POST", all(
                item["method"] == "GET" and item["body"] is None and
                set(parse_qs(urlsplit(item["url"]).query)) <= {
                    "start", "end", "page", "page_size", "exclude_public_rental", "application_only", "price_cap_status"} and
                not any(value in item["url"] for value in ["1990-01-01", "41590", "2020-01-01"])
                for item in router.requests))
            api_requests.extend(router.requests)

        async def geometry(page, label):
            check(label, await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

        if not SOURCE_ONLY:
            row = fixture()
            before_row = deepcopy(row)
            page, card, router = await create(row, person())
            before = len(router.requests)
            await expect(card.locator('[data-region-status="not_divided"]')).to_have_count(2)
            await expect(card.get_by_role("region", name="내 지역 판정", exact=True)).not_to_contain_text("공식 지역 조건 확인 필요")
            await expect(card.locator(".event-candidate .candidate-note")).to_contain_text("접수일 후보")
            check("same regional OR set in reverse order retains a shared admission and candidate despite a different property address")
            check("comparing unordered regional alternatives preserves public fixture data", row == before_row)
            await card.get_by_role("button", name="유형별 근거", exact=True).click()
            await expect(card.locator(".qualification-details")).to_be_visible()
            await expect(card.locator(".qualification-details")).to_contain_text("충족 · 신청 가능한 지역")
            await geometry(page, "375px equivalent regional scopes and open evidence have no overflow")
            await card.get_by_role("region", name="내 지역 판정", exact=True).scroll_into_view_if_needed()
            await page.screenshot(path=str(OUT / "new-notice-reversed-scope-375.png"))
            await privacy(page, router, before, "expanding equivalent regional evidence and focus causes no API query")
            await page.context.close()

            page, card, router = await create(fixture(different=True), person())
            before = len(router.requests)
            await expect(card.locator("details.notice-content-fold")).to_have_js_property("open", True)
            region = card.get_by_role("region", name="내 지역 판정", exact=True)
            await expect(region.locator('[data-region-status="not_divided"]')).to_have_count(1)
            await expect(region.locator('[data-region-status="outside"]')).to_have_count(1)
            await expect(region.locator('[data-region-status="not_divided"]')).to_contain_text("일반공급")
            await expect(region.locator('[data-region-status="outside"]')).to_contain_text("생애최초 특별공급")
            special = card.locator(".qualification-supply-overview details.qualification-supply-collapse")
            await expect(special).to_have_count(1)
            await expect(special).to_contain_text("생애최초 특별공급")
            await expect(special).to_have_js_property("open", False)
            check("a genuinely different regional scope remains separate; only its failed supply collapses")
            await geometry(page, "375px supply-specific regional disagreement has no overflow")
            await region.scroll_into_view_if_needed()
            await page.screenshot(path=str(OUT / "new-notice-different-scopes-375.png"))
            await privacy(page, router, before, "different offer regions and focus cause no API query")
            await page.context.close()

        if SOURCE.exists():
            row = json.loads(SOURCE.read_text())
            if BASELINE.exists():
                baseline = json.loads(BASELINE.read_text())
                check("saved actual source retains the announcement identity and official document hash", all(
                    row.get(key) == baseline.get(key) for key in ["id", "official_url", "announcement_date", "document_hash"]))
            elif REQUIRE_SOURCE:
                raise AssertionError(f"missing source identity baseline: {BASELINE}")
            regions = [item for item in row["rules"] if item.get("kind") == "applicant_regions" and item.get("verification") == "official"]
            check("saved actual official DTO contains one operative regional scope", len(regions) == 1)
            check("actual scope proves all three capital provinces on the operative page", {
                item["region_code"] for item in regions[0]["regions"]} == {"11", "28", "41"} and regions[0].get("evidence_page") == 8)
            check("actual random selection proof does not divide regional allocations", regions[0].get("priority_applicable") is False)
            check("actual regional proof is bound to the source document and announcement date", bool(row.get("document_hash")) and
                  regions[0].get("document_hash") == row["document_hash"] and
                  regions[0].get("criterion_date") == row["announcement_date"])
            source_evidence = {"title": row["title"], "document_hash": row.get("document_hash"),
                               "parser_version": regions[0].get("parser_version"),
                               "criterion_date": regions[0].get("criterion_date"),
                               "evidence_page": regions[0].get("evidence_page"),
                               "evidence_url": regions[0].get("evidence_url"),
                               "regional_selection_evidence": regions[0].get("regional_selection_evidence")}
            page, card, router = await create(row, person())
            before = len(router.requests)
            region = card.get_by_role("region", name="내 지역 판정", exact=True)
            await expect(region.locator('[data-region-status="not_divided"]')).to_have_count(1)
            await expect(region).to_contain_text("신청지역 충족")
            await expect(region).not_to_contain_text("공식 지역 조건 확인 필요")
            await expect(region).to_contain_text("지역 판정 기준일 2026-10-06")
            check("actual Sangdong official response admits Hwaseong and displays no regional division")
            await geometry(page, "375px actual Sangdong regional comparison has no overflow")
            await region.scroll_into_view_if_needed()
            await page.screenshot(path=str(OUT / "sangdong-capital-admission-375.png"))
            await privacy(page, router, before, "actual Sangdong regional comparison and focus cause no API query")
            await page.context.close()

            page, card, router = await create(row, person(region="대전광역시", regionCode="30", district="유성구", districtCode="30200"))
            before = len(router.requests)
            fold = card.locator("details.notice-content-fold")
            await expect(fold).to_have_js_property("open", False)
            reason = card.get_by_label("신청 불가 이유", exact=True)
            await expect(reason).to_be_visible()
            await expect(reason).to_contain_text("신청 범위 밖")
            await expect(reason).to_contain_text("대전광역시")
            await expect(card.locator(".schedule-row")).to_be_hidden()
            check("actual non-capital profile is excluded with the regional reason visible on the closed card")
            await geometry(page, "375px actual regional exclusion stays within the closed card")
            await card.scroll_into_view_if_needed()
            await page.screenshot(path=str(OUT / "sangdong-outside-collapsed-reason-375.png"))
            await fold.locator(":scope > summary").click()
            await expect(fold).to_have_js_property("open", True)
            await expect(card.locator('[data-region-status="outside"]')).to_have_count(1)
            await privacy(page, router, before, "expanding actual regional exclusion and focus causes no API query")
            await page.context.close()
        else:
            assert not REQUIRE_SOURCE, f"missing source DTO: {SOURCE}"

        check("real Chromium regional pages have no JavaScript exceptions", not errors)
        await browser.close()

    result = {"fixture_data_only": True, "deployed_asset": EXPECTED_ASSET,
              "browser_fixed_time": NOW.isoformat(),
              "public_source_file": str(SOURCE) if SOURCE.exists() else None,
              "source_evidence": source_evidence,
              "checks_passed": len(checks), "checks": checks, "javascript_errors": errors,
              "api_requests": api_requests, "deployed_assets": sorted(assets)}
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
