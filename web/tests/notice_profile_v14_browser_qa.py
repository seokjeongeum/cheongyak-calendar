"""Offline Chromium QA for complete notice disclosure and factual profile input.

Every request to qa.invalid is fulfilled from web/dist or synthetic public API
responses. External requests are fulfilled without network access; no server,
live app, API keys, or actual user profile is used.
"""

import asyncio
import hashlib
import json
import mimetypes
import os
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from playwright.async_api import async_playwright, expect
from profile_facts_v10_browser_qa import NOW, PROFILE_KEY, Router, profile, rule

BASE = "https://qa.invalid"
DIST = Path(__file__).resolve().parents[1] / "dist"
OUT = Path(os.environ.get("CHEONGYAK_QA_OUT", "/tmp/cheongyak-notice-profile-v14-qa"))
EVIDENCE = "https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2026000494&pblancNo=2026000494"


def fixture(identifier, title, rules, supplies=None):
    return {
        "id": identifier, "title": title, "category": "apt", "housing_kind": "private",
        "source": "cheongyak_home", "provider": "공개 응답 회귀 검증",
        "address": "대구광역시 중구 동인동1가 9 일원", "region_code": "27", "region_name": "대구광역시",
        "announcement_date": "2026-10-02", "official_url": EVIDENCE,
        "price_cap_status": "no", "updated_at": "2026-10-09T01:00:00Z", "version": 2,
        "qualification_context": {"speculation_zone": False, "subscription_overheated": False},
        "events": [{"kind": "general", "label": "신청 접수", "start_date": "2026-10-12", "end_date": "2026-10-13"}],
        "prices": [{"unit_type": "084.2551A", "price_kind": "sale", "amount_krw": 588000000, "verification": "official", "evidence_url": EVIDENCE}],
        "rules": rules, "rules_complete": True,
        "offered_supplies": [{"supply_type": supply, "unit_type": "084.2551A", "supply_count": 2, "verification": "official"} for supply in supplies or ["일반공급"]],
        "competitions": [], "competition": {"status": "pending", "complete": False, "unit_types": []},
    }


def fixtures():
    outside = fixture("qa-outside", "더샵 동인센트리체", [rule("applicant_regions", None, effect="metadata", regions=[{"region_code": "27", "region_name": "대구광역시"}, {"region_code": "47", "region_name": "경상북도"}], scope_complete=True, exceptions=[])])
    possible = fixture("qa-possible", "천안 아이파크 시티 2단지(2회차)", [rule("age_min", 19, supply_type="일반공급")])
    unknown = fixture("qa-unknown", "미확인 국적 회귀 검증", [rule("citizenship", ["korean"], supply_type="일반공급")])
    mixed = fixture("qa-mixed", "일반공급 가능·노부모 불일치 검증", [rule("age_min", 19, supply_type="일반공급"), rule("parent_age_min", 65, supply_type="노부모부양 특별공급")], ["일반공급", "노부모부양 특별공급"])
    return [outside, possible, unknown, mixed]


class OfflineRouter(Router):
    def __init__(self, rows):
        super().__init__(rows)
        self.static_requests, self.external_requests = [], []

    async def offline(self, route):
        req = route.request
        parsed = urlsplit(req.url)
        if parsed.hostname != "qa.invalid":
            self.external_requests.append({"url": req.url, "method": req.method})
            await route.fulfill(status=200, body="")
            return
        if parsed.path.startswith("/api/"):
            await self.handle(route)
            return
        relative = "index.html" if parsed.path == "/" else unquote(parsed.path).lstrip("/")
        local = (DIST / relative).resolve()
        self.static_requests.append(parsed.path)
        if not local.is_relative_to(DIST.resolve()) or not local.is_file():
            self.errors.append(f"missing local asset: {parsed.path}")
            await route.fulfill(status=404, body="missing local fixture asset")
            return
        await route.fulfill(status=200, body=local.read_bytes(), content_type=mimetypes.guess_type(local.name)[0] or "application/octet-stream")


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert (DIST / "index.html").is_file(), "Run the final web build first"
    index = (DIST / "index.html").read_text()
    asset = re.search(r'src="([^"]+\.js)"', index).group(1)
    checks, errors, requests = [], [], []

    def check(label, value=True):
        assert value, label
        checks.append(label)
        print(label, flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox", "--disable-background-networking", "--disable-component-update", "--disable-sync"])

        async def create(width, rows=None, facts=None):
            context = await browser.new_context(viewport={"width": width, "height": 900}, timezone_id="Asia/Seoul", service_workers="block")
            value = facts or profile(region="경기도", regionCode="41", district="화성시", districtCode="41590", citizenship="unknown", parentDateOfBirth="1966-01-01", householdMembers=[], pointsFamily={}, additionalFamilyPresence=False, applicantOnRegister=None)
            await context.add_init_script(f"localStorage.setItem({json.dumps(PROFILE_KEY)}, {json.dumps(json.dumps(value))})")
            router = OfflineRouter(deepcopy(rows or fixtures()))
            await context.route("**/*", router.offline)
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.clock.set_fixed_time(NOW)
            await page.goto(BASE, wait_until="domcontentloaded")
            await expect(page.locator(".notice-card")).to_have_count(len(router.rows), timeout=20000)
            await expect(page.locator('.notice-card[data-evaluation-ready="true"]')).to_have_count(len(router.rows), timeout=20000)
            await page.wait_for_timeout(300)
            return page, router

        async def step(page, name):
            dialog = page.get_by_role("dialog")
            await dialog.locator(".step-progress").get_by_role("button", name=re.compile(name)).click()
            return dialog

        async def privacy(page, router, before, label):
            await page.evaluate("""() => {window.dispatchEvent(new Event('focus')); Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'}); document.dispatchEvent(new Event('visibilitychange')); Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'}); document.dispatchEvent(new Event('visibilitychange'));}""")
            await page.wait_for_timeout(450)
            check(label, len(router.requests) == before and not router.errors and all(item["method"] == "GET" and item["body"] is None for item in router.requests))

        for width in [365, 375, 1280]:
            page, router = await create(width)
            before = len(router.requests)
            outside = page.locator('.notice-card').filter(has=page.get_by_role("heading", name="더샵 동인센트리체", exact=True))
            fold = outside.locator("details.notice-content-fold")
            await expect(outside).to_have_attribute("data-unavailable", "true")
            await expect(outside).to_have_attribute("data-content-expanded", "false")
            await expect(fold).to_have_js_property("open", False)
            await expect(outside.get_by_role("heading", name="더샵 동인센트리체", exact=True)).to_be_visible()
            await expect(outside.locator(".notice-address")).to_be_visible()
            await expect(outside.locator(".notice-head .unavailable-badge")).to_be_visible()
            await expect(outside.locator(".schedule-row")).to_be_hidden()
            await expect(outside.locator(".prices-section")).to_be_hidden()
            await expect(outside.locator(".notice-foot")).to_be_hidden()
            check(f"{width}px entire unavailable card starts closed with title/address/status retained")
            await expect(outside.get_by_role("link", name="더샵 동인센트리체 공식 공고 보기", exact=True)).to_have_attribute("href", EVIDENCE)
            await expect(outside.get_by_role("link", name="더샵 동인센트리체 공식 공고 보기", exact=True)).to_be_visible()
            check(f"{width}px closed card retains clickable official source")
            for row in fixtures():
                card = page.locator(".notice-card").filter(has=page.get_by_role("heading", name=row["title"], exact=True))
                link = card.get_by_role("link", name=f'{row["title"]} 호갱노노 검색', exact=True)
                await expect(link).to_be_visible()
                url = urlsplit(await link.get_attribute("href"))
                expected_title = "천안 아이파크 시티 2단지" if row["id"] == "qa-possible" else row["title"]
                check(f'{width}px {row["id"]} external query contains only apartment title', url.hostname == "hogangnono.com" and url.path == "/search" and parse_qs(url.query) == {"q": [expected_title]} and await link.get_attribute("rel") == "noopener noreferrer")
            for identifier in ["qa-possible", "qa-unknown", "qa-mixed"]:
                row = next(row for row in fixtures() if row["id"] == identifier)
                card = page.locator(".notice-card").filter(has=page.get_by_role("heading", name=row["title"], exact=True))
                await expect(card.locator("details.notice-content-fold")).to_have_js_property("open", True)
                await expect(card.locator(".schedule-row")).to_be_visible()
                await expect(card.locator(".prices-section")).to_be_visible()
                check(f"{width}px {identifier} remains expanded")
            mixed = page.locator(".notice-card").filter(has=page.get_by_role("heading", name="일반공급 가능·노부모 불일치 검증", exact=True))
            await expect(mixed.locator(".qualification-supply-overview details.qualification-supply-collapse")).to_have_count(1)
            await expect(mixed.locator(".qualification-supply-overview details.qualification-supply-collapse")).to_have_js_property("open", False)
            check(f"{width}px one failed supply does not collapse another eligible supply's notice")
            await outside.scroll_into_view_if_needed()
            await page.screenshot(path=str(OUT / f"whole-notice-closed-{width}.png"))
            summary = fold.locator(":scope > summary")
            await summary.focus()
            await summary.press("Enter")
            await expect(fold).to_have_js_property("open", True)
            await expect(outside).to_have_attribute("data-content-expanded", "true")
            await expect(outside.locator(".schedule-row")).to_be_visible()
            await expect(outside.get_by_text("5억 8,800만원", exact=True)).to_be_visible()
            await expect(outside.locator(".price-row a").first).to_have_attribute("href", EVIDENCE)
            await expect(outside.locator(".price-row a").first).to_be_visible()
            check(f"{width}px keyboard expansion reveals schedules/prices/public evidence")
            await outside.get_by_role("button", name="유형별 근거", exact=True).click()
            await expect(outside.locator(".qualification-details")).to_be_visible()
            await outside.locator(".qualification-details").scroll_into_view_if_needed()
            await page.screenshot(path=str(OUT / f"whole-notice-open-{width}.png"))
            await summary.focus()
            await summary.press("Space")
            await expect(fold).to_have_js_property("open", False)
            await expect(outside.locator(".qualification-details")).to_be_hidden()
            check(f"{width}px keyboard closing hides whole card body again")
            check(f"{width}px entire notice disclosures have no horizontal overflow", await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
            await privacy(page, router, before, f"{width}px disclosures/focus issue no API request and no POST")
            requests.extend(router.requests)
            await page.context.close()

        institution = fixture("qa-institution", "기관추천 해당 없음 검증", [rule("age_min", 19, supply_type="일반공급"), rule("recommendation", True, supply_type="기관추천 특별공급", allowed_reasons=["장애인"], require_confirmed=True)], ["일반공급", "기관추천 특별공급"])
        history = fixture("qa-history", "공통 사실 이력 재사용 검증", [rule("previous_winning", False, scope="household", supply_type="일반공급")])
        facts = profile(region="경기도", regionCode="41", district="화성시", districtCode="41590", householdMembers=[], pointsFamily={}, additionalFamilyPresence=False, applicantOnRegister=None, recommendationReason="", recommendationStatus="unknown", applicationHistoryPresence=True, applicationHistoryComplete=False, applicationHistoryEvents=[{"id": "qa-event", "personId": "applicant", "projectId": "2026000001", "eventKind": "winning", "eventDate": "2020-01-01"}])
        for width in [365, 375, 1280]:
            page, router = await create(width, [institution, history], facts)
            before = len(router.requests)
            await page.get_by_role("button", name="내 조건 설정", exact=True).click()
            dialog = await step(page, "세대·주택")
            check(f"{width}px applicant registration no longer asks a baseline affirmation", "본인이 주민등록등본에 등재되어 있나요?" not in await dialog.inner_text())
            exceptional = dialog.get_by_text("주민등록 말소·등본 없음 등 예외 상태", exact=True)
            await expect(exceptional).to_be_visible()
            await exceptional.click()
            await expect(dialog.get_by_role("checkbox", name="주민등록 말소 또는 본인 등본 없음", exact=True)).to_be_visible()
            check(f"{width}px actual registration exception remains editable")
            dialog = await step(page, "청약통장")
            check(f"{width}px application history no longer asks completeness confirmation", "위 확인 대상의 당첨·계약 이력을 모두 입력했나요?" not in await dialog.inner_text())
            actual_date = dialog.get_by_label("실제 사건 날짜", exact=True)
            await expect(actual_date).to_have_value("2020-01-01")
            await actual_date.fill("2020-02-01")
            check(f"{width}px stored event remains editable using its actual date")
            project = dialog.get_by_label("사업번호 · 같은 사업 판정에만 필요", exact=True)
            await project.fill("")
            check(f"{width}px generic dated history accepts an empty optional project number", not await project.evaluate("el => el.required"))
            dialog = await step(page, "특별공급")
            recommendation = dialog.get_by_role("combobox", name="추천 대상 사유", exact=True)
            await expect(recommendation).to_be_visible()
            await expect(recommendation.locator('option[value="none"]')).to_have_text("해당 없음")
            await recommendation.select_option("none")
            check(f"{width}px factual profile controls fit inside the viewport", await page.evaluate("""() => {const dialog=document.querySelector('.profile-dialog'); return document.documentElement.scrollWidth<=window.innerWidth && dialog.scrollWidth<=dialog.clientWidth && [...dialog.querySelectorAll('input,select')].filter(el=>el.getClientRects().length).every(el=>el.getBoundingClientRect().right<=window.innerWidth)}"""))
            await page.screenshot(path=str(OUT / f"institution-inapplicable-{width}.png"))
            await dialog.locator(".dialog-close").click()
            card = page.locator(".notice-card").filter(has=page.get_by_role("heading", name="기관추천 해당 없음 검증", exact=True))
            failed = card.locator(".qualification-supply-overview details.qualification-supply-collapse")
            await expect(failed).to_have_count(1)
            await expect(failed.locator(":scope > summary")).to_contain_text("기관추천 특별공급")
            await expect(failed.locator(":scope > summary")).to_contain_text("내 조건으로 신청 불가")
            await expect(failed).to_have_js_property("open", False)
            await expect(card.locator("details.notice-content-fold")).to_have_js_property("open", True)
            check(f"{width}px institution-none rules out only institution while general remains expanded")
            saved = json.loads(await page.evaluate(f"localStorage.getItem({json.dumps(PROFILE_KEY)})"))
            check(f"{width}px concrete recommendation/history facts persist in browser", saved["recommendationReason"] == "none" and saved["applicationHistoryEvents"][0]["eventDate"] == "2020-02-01" and saved["applicationHistoryEvents"][0]["projectId"] == "")
            check(f"{width}px profile changes have no horizontal overflow", await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
            await privacy(page, router, before, f"{width}px profile edits and focus remain browser-only with no API request")
            requests.extend(router.requests)
            await page.context.close()

        # The exact people with a legacy saved no-history answer retain that
        # answer. New factual events and newly added family members use their
        # own person IDs; the test never certifies an entire list as complete.
        legacy = profile(region="경기도", regionCode="41", district="화성시", districtCode="41590", maritalStatus="married", marriageDate="2020-01-01", hasSpouse=True, spouseSameRegister=True, spouseOwnsHome=False, spousePreviouslyOwnedHome=False, householdMembers=[], pointsFamily={}, additionalFamilyPresence=False, applicantOnRegister=None, applicationHistoryPresence=False, applicationHistoryComplete=True, applicationHistoryPeople=["applicant", "spouse"], applicationHistoryEvents=[])
        page, router = await create(375, [history], legacy)
        before = len(router.requests)
        await page.get_by_role("button", name="내 조건 설정", exact=True).click()
        dialog = await step(page, "청약통장")
        history_section = dialog.locator('.application-facts [data-profile-field="applicationHistoryPresence"]')
        await expect(history_section).to_contain_text("본인 · 당첨·예비당첨·공급계약 이력 없음")
        await expect(history_section).to_contain_text("배우자 · 당첨·예비당첨·공급계약 이력 없음")
        await history_section.get_by_role("button", name="이력 추가", exact=True).click()
        await expect(history_section.get_by_role("combobox", name="해당 사람", exact=True)).to_have_value("applicant")
        await expect(history_section).to_contain_text("배우자 · 당첨·예비당첨·공급계약 이력 없음")
        check("375px adding applicant history retains exact spouse absence")
        await history_section.get_by_label("사업번호 · 같은 사업 판정에만 필요", exact=True).fill("2026000001")
        await history_section.get_by_label("실제 사건 날짜", exact=True).fill("2020-01-01")
        check("375px valid dated event does not trigger a completeness question", "위 확인 대상의 당첨·계약 이력을 모두 입력했나요?" not in await history_section.inner_text())
        await history_section.get_by_role("button", name="이력 삭제", exact=True).click()
        await expect(history_section.get_by_role("group", name="본인에게 당첨·예비당첨 또는 주택 공급계약 이력이 있나요?", exact=True)).to_be_visible()
        await expect(history_section).to_contain_text("배우자 · 당첨·예비당첨·공급계약 이력 없음")
        check("375px deleting last applicant event asks only applicant's actual history")
        await history_section.get_by_role("group", name="본인에게 당첨·예비당첨 또는 주택 공급계약 이력이 있나요?", exact=True).get_by_role("button", name="아니요", exact=True).click()
        dialog = await step(page, "세대·주택")
        await dialog.get_by_role("button", name="가족 추가", exact=True).click()
        member = dialog.locator(".household-member")
        await member.get_by_role("combobox", name="본인과의 가족 관계", exact=True).select_option("applicant_parent")
        await member.get_by_role("combobox", name="어느 주민등록등본에 함께 있나요?", exact=True).select_option("applicant")
        dialog = await step(page, "청약통장")
        history_section = dialog.locator('.application-facts [data-profile-field="applicationHistoryPresence"]')
        missing = history_section.get_by_role("group", name=re.compile("본인의 부모.*당첨·예비당첨 또는 주택 공급계약 이력이 있나요"))
        await expect(missing).to_have_count(1)
        await expect(missing).to_be_visible()
        await expect(history_section).to_contain_text("본인 · 당첨·예비당첨·공급계약 이력 없음")
        await expect(history_section).to_contain_text("배우자 · 당첨·예비당첨·공급계약 이력 없음")
        check("375px new canonical parent alone needs an actual history answer")
        await missing.get_by_role("button", name="예", exact=True).click()
        await expect(history_section.get_by_role("combobox", name="해당 사람", exact=True)).not_to_have_value("applicant")
        await history_section.get_by_label("사업번호 · 같은 사업 판정에만 필요", exact=True).fill("2026000002")
        await history_section.get_by_label("실제 사건 날짜", exact=True).fill("2020-01-01")
        await page.screenshot(path=str(OUT / "canonical-history-person-375.png"))
        await dialog.locator(".dialog-close").click()
        saved = json.loads(await page.evaluate(f"localStorage.getItem({json.dumps(PROFILE_KEY)})"))
        check("375px parent event saves exact canonical parent ID and retains applicant/spouse absence", saved["applicationHistoryEvents"][0]["personId"] == saved["householdMembers"][0]["id"] and sorted(saved["applicationHistoryAbsencePeople"]) == ["applicant", "spouse"])
        await privacy(page, router, before, "375px add/delete/new-parent history interactions remain local without API requests")
        requests.extend(router.requests)
        await page.context.close()

        check("all offline Chromium pages have no JavaScript exceptions", not errors)
        await browser.close()

    result = {"offline_only": True, "synthetic_profiles_only": True, "public_api_fixtures_only": True, "base": BASE, "build_asset": asset, "build_asset_sha256": hashlib.sha256((DIST / asset.lstrip("/")).read_bytes()).hexdigest(), "checks_passed": len(checks), "checks": checks, "api_requests": requests, "javascript_errors": errors}
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"checks_passed": len(checks), "build_asset": asset}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
