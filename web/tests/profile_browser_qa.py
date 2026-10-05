"""Profile v2, explanation and non-disruptive refresh browser contracts.

Run with Python Playwright and CHEONGYAK_QA_BASE (default localhost:8080).
Public API responses are controlled; no API keys or .env are read. The only
profile writes happen inside fresh isolated browser contexts.
"""

import asyncio
import copy
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect


BASE = os.environ.get("CHEONGYAK_QA_BASE", "http://localhost:8080")
NOW = datetime(2026, 10, 3, 3, 0, tzinfo=timezone.utc)
PROFILE_KEY = "cheongyak-profile-v2"
LEGACY_KEY = "cheongyak-profile-v1"
SOURCES = ["cheongyak_home", "myhome", "lh", "ih", "sh", "gh"]
LEGACY = {
    "region": "서울특별시", "district": "강동구", "movedInDate": "2023-01-01",
    "householdSize": "3", "annualIncomeKrw": "60000000", "assetsKrw": "300000000",
    "homeless": True, "subscriptionMonths": "36", "subscriptionRank": "first",
    "specialEligibility": True, "specialCategory": "신혼부부",
}
V2 = {
    "version": 2, "region": "서울특별시", "district": "강동구", "regionCode": "11", "districtCode": "11740",
    "movedInDate": "2023-01-01", "districtMovedInDate": "2023-01-01", "householdSize": "3",
    "hasSpouse": False, "familyOnRegister": False, "householdScopeKnown": True,
    "applicantOwnsHome": False, "ownershipException": False, "accountType": "comprehensive",
    "privateRankBaseDate": "2024-01-01", "nationalRankBaseDate": "2025-10-01",
    "privateDepositKrw": "6000000", "nationalRecognizedPayments": "3",
    "accountConversionUnclear": False, "restrictedFromApplying": False,
    "annualIncomeKrw": "60000000", "assetsKrw": "300000000",
}


def rule(kind, value, **extra):
    return {"kind": kind, "value": value, "verification": "official", "evidence_url": "https://www.applyhome.co.kr/",
            "evidence_text": "통제된 공고 기준 비교를 위한 공개 공식 조건", **extra}


def notice(identifier, title, kind):
    rules = [rule("homeless", True), rule("residence_months", 24, region_code="11", criterion_basis="announcement")]
    rank = "private_rank_months" if kind == "private" else "national_rank_months"
    rules.extend([rule(rank, 12, purpose="first_rank", housing_kind=kind, rank_rules_complete=True),
                  rule("deposit_min_krw" if kind == "private" else "recognized_payments_min", 3_000_000 if kind == "private" else 12,
                       purpose="first_rank", housing_kind=kind)])
    if kind == "private":
        rules.extend([rule("marital_status", "married", supply_type="신혼부부"),
                      rule("children_min", 1, supply_type="신생아", maximum_child_age=2),
                      rule("tax_years_min", 5, supply_type="생애최초"),
                      rule("parent_age_min", 65, supply_type="노부모부양"),
                      rule("recommendation", True, supply_type="기관추천"),
                      rule("relocated_worker", True, supply_type="이전기관 종사자"),
                      rule("income_max_krw", 5_000_000, period="monthly", supply_type="신혼부부"),
                      rule("assets_max_krw", 300_000_000, asset_basis="real_estate", supply_type="신혼부부")])
    return {
        "id": identifier, "title": title, "category": "apt", "source": "cheongyak_home", "sources": ["cheongyak_home"],
        "provider": "공개 응답 브라우저 검증", "address": "서울특별시 강동구", "region_name": "서울특별시", "region_code": "11",
        "housing_kind": kind, "housing_kind_evidence": {"verification": "official", "source": "cheongyak_home", "evidence_url": "https://www.applyhome.co.kr/", "evidence_text": "공식 주택 구분"},
        "qualification_context": {"public_housing": None, "speculation_zone": False, "subscription_overheated": False, "weakened_area": None, "capital_region": True, "rule_effective_date": None},
        "announcement_date": "2026-10-01", "sort_date": "2026-10-05", "official_url": "https://www.applyhome.co.kr/", "price_cap_status": "yes",
        "events": [{"kind": "general", "label": "일반공급", "start_date": "2026-10-05", "end_date": "2026-10-07", "audience": "해당지역"},
                   {"kind": "special", "label": "특별공급", "start_date": "2026-10-08", "end_date": "2026-10-08", "audience": None}],
        "prices": [{"unit_type": unit, "area_sqm": area, "price_kind": "sale_max", "amount_krw": amount, "monthly_krw": None,
                    "basis_label": "주택형별 최고 분양금액", "verification": "official", "source": "cheongyak_home", "evidence_url": "https://www.applyhome.co.kr/"}
                   for unit, area, amount in [("59A", 59.9, 510_000_000), ("84A", 84.9, 690_000_000)]],
        "rules": rules, "rules_complete": True, "competitions": [], "competition": {"status": "pending", "last_attempt_at": None, "last_success_at": None, "complete": False, "unit_types": []},
        "updated_at": "2026-10-03T02:55:00Z", "version": 1,
    }


FIXTURES = [notice("qa-profile-private", "검증 민영주택 조건 설명", "private"), notice("qa-profile-national", "검증 국민주택 조건 설명", "national")]


class Router:
    def __init__(self):
        self.rows = copy.deepcopy(FIXTURES)
        self.requests = []
        self.errors = []
        self.success = "2026-10-03T02:55:00Z"
        self.phase = "ok"
        self.delay = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def handle(self, route):
        req = route.request
        parsed = urlsplit(req.url)
        self.requests.append({"url": req.url, "method": req.method, "body": req.post_data})
        if parsed.path == "/api/coverage":
            payload = {"sources": [{"source": source, "status": self.phase, "last_success_at": self.success,
                                    "last_attempt_at": self.success, "record_count": len(self.rows)} for source in SOURCES]}
        elif parsed.path == "/api/notices":
            if self.delay:
                self.started.set()
                await self.release.wait()
            q = parse_qs(parsed.query)
            rows = [copy.deepcopy(row) for row in self.rows if any(e["start_date"] <= q["end"][0] and e["end_date"] >= q["start"][0] for e in row["events"])]
            page, size = int(q.get("page", ["1"])[0]), int(q.get("page_size", ["100"])[0])
            payload = {"items": rows[(page - 1) * size:page * size], "total": len(rows), "page": page, "page_size": size}
        else:
            self.errors.append(parsed.path)
            await route.fulfill(status=404, json={"detail": "unexpected public endpoint"})
            return
        await route.fulfill(status=200, json=payload)

    def calls(self, path=None):
        return [req for req in self.requests if path is None or urlsplit(req["url"]).path == path]


async def create_page(browser, router, *, profile=V2, legacy=False, now=NOW):
    context = await browser.new_context(viewport={"width": 375, "height": 812}, timezone_id="Asia/Seoul")
    await context.add_init_script(f"localStorage.setItem({json.dumps(LEGACY_KEY if legacy else PROFILE_KEY)}, {json.dumps(json.dumps(profile))})")
    page = await context.new_page()
    await page.clock.install(time=now)
    await page.route("**/api/**", router.handle)
    await page.goto(BASE, wait_until="networkidle")
    await expect(page.locator(".notice-card")).to_have_count(2)
    return page


async def settle(page):
    await page.wait_for_timeout(120)


async def visibility(page, state):
    await page.evaluate("state => { Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state }); document.dispatchEvent(new Event('visibilitychange')); }", state)


async def stored(page):
    return json.loads(await page.evaluate(f"localStorage.getItem('{PROFILE_KEY}')"))


async def main():
    checks = []

    def check(label, value=True):
        assert value, label
        checks.append(label)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        router = Router()
        page = await create_page(browser, router, profile=LEGACY, legacy=True)
        migrated = await stored(page)
        check("legacy v1 monetary and province tenure values migrate to v2", migrated["version"] == 2 and migrated["annualIncomeKrw"] == "60000000" and migrated["movedInDate"] == "2023-01-01")
        check("unique exact legacy district resolves to code", migrated["regionCode"] == "11" and migrated["districtCode"] == "11740" and not migrated["regionNeedsReview"])
        check("legacy rank months and special self-assessments never become new facts", not any(key in migrated for key in ["homeless", "subscriptionRank", "subscriptionMonths", "specialEligibility", "specialCategory"]) and migrated["privateRankBaseDate"] == "" and migrated["nationalRankBaseDate"] == "" and migrated["householdScopeKnown"] is None)
        district = page.get_by_label("현재 거주 시군구", exact=True)
        check("top-level district is a native dropdown", await district.evaluate("el => el.tagName") == "SELECT")
        before = len(router.requests)
        await page.get_by_label("현재 거주 지역", exact=True).select_option(label="경기도")
        await district.select_option(label="수원시")
        check("province controls district dropdown at subscription relevant city level", await district.input_value() == "41110" and "강동구" not in await district.locator("option").all_text_contents())
        await page.get_by_label("현재 거주 지역", exact=True).select_option(label="제주특별자치도")
        check("Jeju offers both cities", all([name in await district.locator("option").all_text_contents() for name in ["제주시", "서귀포시"]]))
        await page.get_by_label("현재 거주 지역", exact=True).select_option(label="세종특별자치시")
        check("Sejong has one current municipality option", await district.locator("option[value]:not([value=''])").count() == 1)
        check("residence edits make no API request", len(router.requests) == before)
        await page.get_by_role("button", name="내 조건 설정", exact=True).click()
        dialog = page.get_by_role("dialog")
        check("profile district uses same native dropdown", await dialog.get_by_label(re.compile(r"^시·군·구")).evaluate("el => el.tagName") == "SELECT")
        await dialog.get_by_label(re.compile(r"^시·군·구")).select_option(index=1)
        check("province and district tenure dates are separate", await dialog.get_by_label("현재 시·군·구 연속 거주 시작일", exact=True).count() == 1 and await dialog.get_by_label("현재 시도 연속 거주 시작일", exact=True).count() == 1)
        await dialog.get_by_label(re.compile(r"^현재 거주 지역")).select_option(label="경기도")
        await dialog.get_by_label(re.compile(r"^시·군·구")).select_option(label="수원시 영통구")
        await dialog.get_by_label("수원시 전체 연속 거주 시작일", exact=True).fill("2022-01-01")
        await dialog.get_by_label("현재 시·군·구 연속 거주 시작일", exact=True).fill("2025-01-01")
        check("parent city and selected child-district continuity are distinct facts", (await stored(page))["cityMovedInDate"] == "2022-01-01" and (await stored(page))["districtMovedInDate"] == "2025-01-01")
        await dialog.get_by_role("button", name=re.compile("세대·주택")).click()
        explanation = await dialog.locator(".term-explanation").inner_text()
        check("homeless household explanation covers separate spouse and property rights", all(text in explanation for text in ["무주택 세대구성원", "배우자", "주소가 달라도", "분양권", "입주권", "공유지분", "예외"]))
        check("household definition and exceptions link official articles", len(await dialog.locator(".term-explanation a").all_text_contents()) == 2)
        check("household facts replace homeless yes-no self-assessment", await dialog.get_by_text("무주택 세대구성원인가요?", exact=True).count() == 0 and await dialog.get_by_role("group", name="현재 법률상 배우자가 있나요?", exact=True).count() == 1)
        await dialog.get_by_role("button", name=re.compile("청약통장")).click()
        check("no manual common rank or subscription-month input remains", await dialog.get_by_label("청약순위", exact=True).count() == 0 and await dialog.get_by_label("가입 기간 (개월)", exact=True).count() == 0)
        private_date = dialog.get_by_label("민영주택 순위기산일", exact=True)
        national_date = dialog.get_by_label("국민주택 순위기산일", exact=True)
        await private_date.fill("2024-01-01")
        await national_date.fill("2025-10-01")
        await dialog.get_by_label("국민주택 납입인정횟수 (회)", exact=True).fill("12")
        deposit = dialog.get_by_label("민영주택 예치금 (원)", exact=True)
        await deposit.fill("6000000")
        await expect(deposit).to_have_value("6,000,000")
        profile = await stored(page)
        check("separate private/national rank dates and recognized payments persist", profile["privateRankBaseDate"] != profile["nationalRankBaseDate"] and profile["nationalRecognizedPayments"] == "12")
        check("deposit renders commas but stores integer KRW", profile["privateDepositKrw"] == "6000000")
        await dialog.get_by_role("button", name=re.compile("소득·자산")).click()
        income = dialog.get_by_label(re.compile(r"^가구 연 소득 합계 \(원\)"))
        assets = dialog.get_by_label("가구 자산 합계 (원)", exact=True)
        await expect(income).to_have_value("60,000,000")
        await expect(assets).to_have_value("300,000,000")
        check("both migrated income and assets are comma-separated")
        await income.fill("1234567")
        await expect(income).to_have_value("1,234,567")
        await income.fill("60,000,000")
        await income.evaluate("el => { el.focus(); el.setSelectionRange(1, 1); }")
        await page.keyboard.insert_text("1")
        await expect(income).to_have_value("610,000,000")
        check("middle editing preserves digit-relative cursor", await income.evaluate("el => el.selectionStart") == 2)
        await income.fill("60,000,000")
        await income.evaluate("el => { el.focus(); el.setSelectionRange(3, 3); }")
        await page.keyboard.press("Backspace")
        await expect(income).to_have_value("60,000,000")
        check("comma-only deletion restores formatting while preserving caret", await income.evaluate("el => el.selectionStart") == 2)
        await income.fill("1,234,567")
        check("comma-separated pasted amount is integer in profile", (await stored(page))["annualIncomeKrw"] == "1234567")
        await income.fill("-100")
        await expect(income).to_have_attribute("aria-invalid", "true")
        await expect(dialog.get_by_role("alert")).to_contain_text("음수")
        check("negative amount produces explicit error and no negative stored value", (await stored(page))["annualIncomeKrw"] == "")
        await income.fill("12.5")
        await expect(income).to_have_attribute("aria-invalid", "true")
        check("fractional KRW input is rejected")
        await income.fill("60000000")
        await expect(income).to_have_attribute("aria-invalid", "false")
        check("valid amount correction clears error")
        check("monthly income is independently requested for relevant official conditions", await dialog.get_by_label("공고 기준 가구 월평균소득 (원)", exact=True).is_visible())
        await dialog.get_by_role("button", name=re.compile("특별공급")).click()
        check("special supply asks facts, not target self-assessment", await dialog.get_by_role("heading", name="특별공급 대상인가요?", exact=True).count() == 0 and await dialog.get_by_label("특별공급 유형", exact=True).count() == 0)
        await dialog.get_by_label(re.compile(r"^현재 혼인 상태")).select_option("married")
        await dialog.get_by_label("혼인신고일", exact=True).fill("2024-04-02")
        await dialog.get_by_role("group", name="현재 자녀가 있나요?", exact=True).get_by_role("button", name="예", exact=True).click()
        await dialog.get_by_role("button", name="자녀 정보 추가", exact=True).click()
        await dialog.get_by_label("자녀 1 생년월일", exact=True).fill("2025-06-01")
        await dialog.get_by_role("group", name="자녀 1은 입양한 자녀인가요?", exact=True).get_by_role("button", name="아니요", exact=True).click()
        await dialog.get_by_role("group", name="본인 또는 배우자가 임신 중인가요?", exact=True).get_by_role("button", name="예", exact=True).click()
        await dialog.get_by_label("임신 중 태아 수", exact=True).fill("1")
        check("marriage children adoption and pregnancy facts coexist", (await stored(page))["children"] == [{"dateOfBirth": "2025-06-01", "adopted": False}] and (await stored(page))["pregnant"] is True)
        check("relevant first-home parent institution and relocation follow-ups are shown", all([await locator.is_visible() for locator in [dialog.get_by_label("소득세 납부한 연수 (년)", exact=True), dialog.get_by_label("부양 중인 부모·조부모 생년월일", exact=True), dialog.get_by_label(re.compile(r"^추천 대상 사유")), dialog.get_by_role("group", name="공고에서 지정한 이전기관에 소속되어 근무하나요?", exact=True)]]))
        await dialog.get_by_role("button", name="닫기", exact=True).first.click()
        check("375px profile interactions cause no page overflow", await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        check("profile edits and extra questions never request API data", len(router.requests) == before)

        # Focus and visibility resume only adjust local time; regular polls are
        # tested independently so a legitimately due timer is not misclassified.
        focus_router = Router()
        focus_page = await create_page(browser, focus_router)
        private_card = focus_page.locator(".notice-card").filter(has=focus_page.get_by_role("heading", name=FIXTURES[0]["title"], exact=True))
        national_card = focus_page.locator(".notice-card").filter(has=focus_page.get_by_role("heading", name=FIXTURES[1]["title"], exact=True))
        await expect(private_card.locator(".rank-explanation")).to_contain_text("민영주택 1순위 조건 충족")
        await expect(national_card.locator(".rank-explanation")).to_contain_text("국민주택 1순위 요건 불일치")
        check("same profile produces separate private/national first-rank results")
        await private_card.get_by_role("button", name="유형별 근거", exact=True).click()
        await expect(private_card.locator(".qualification-details")).to_be_visible()
        offered_titles = await private_card.locator(".qualification-section h5").all_text_contents()
        check("multiple actual offered special supplies have separate details", all(any(name in title for title in offered_titles) for name in ["신혼부부", "신생아", "생애최초", "노부모부양", "기관추천", "이전기관 종사자"]))
        await private_card.get_by_role("button", name="근거 접기", exact=True).click()
        calls = len(focus_router.requests)
        await focus_page.evaluate("window.dispatchEvent(new Event('blur')); window.dispatchEvent(new Event('focus'))")
        await visibility(focus_page, "hidden")
        await focus_page.clock.fast_forward(2_000)
        await visibility(focus_page, "visible")
        await settle(focus_page)
        check("short focus/visibility change makes zero API requests", len(focus_router.requests) == calls)
        await visibility(focus_page, "hidden")
        await focus_page.clock.fast_forward(20 * 60_000)
        check("hidden long interval pauses public API polling", len(focus_router.requests) == calls)
        await visibility(focus_page, "visible")
        await focus_page.evaluate("window.dispatchEvent(new Event('focus'))")
        await settle(focus_page)
        check("long focus/visibility return does not immediately refresh", len(focus_router.requests) == calls)
        await focus_page.clock.fast_forward(30_001)
        await settle(focus_page)
        check("scheduled coverage polling resumes independently", len(focus_router.calls("/api/coverage")) > 1)
        before_notice = len(focus_router.calls("/api/notices"))
        await focus_page.get_by_role("button", name="새로고침", exact=True).click()
        await focus_page.wait_for_load_state("networkidle")
        check("manual refresh still fetches public list", len(focus_router.calls("/api/notices")) > before_notice)

        # A changed collection timestamp should refresh in place, preserving
        # card expansion and scroll even while responses are deliberately held.
        await private_card.get_by_role("button", name="유형별 근거", exact=True).click()
        await expect(private_card.locator(".qualification-details")).to_be_visible()
        detail_text = await private_card.locator(".qualification-details").inner_text()
        check("card details explain input requirement date reasoning and evidence", all(text in detail_text for text in ["내 입력", "요구", "기준일", "판단 이유"]) and await private_card.locator(".qualification-details a").count() > 0)
        await private_card.scroll_into_view_if_needed()
        await focus_page.get_by_role("button", name="내 조건 설정", exact=True).click()
        live_dialog = focus_page.get_by_role("dialog")
        await live_dialog.get_by_role("button", name=re.compile("소득·자산")).click()
        editing_income = live_dialog.get_by_label(re.compile(r"^가구 연 소득 합계 \(원\)"))
        await editing_income.fill("-120")
        card_top_before = (await private_card.bounding_box())["y"]
        focus_router.success = "2026-10-03T03:25:00Z"
        focus_router.delay = True
        await focus_page.clock.fast_forward(300_001)
        await asyncio.wait_for(focus_router.started.wait(), timeout=5)
        check("background refresh keeps both existing cards visible", await focus_page.locator(".notice-card").count() == 2)
        check("background refresh preserves open evidence", await private_card.get_by_role("button", name="근거 접기", exact=True).count() == 1)
        # Browser anchoring may change scrollY to compensate for a status line;
        # keeping the card's viewport position verifies the user's actual view.
        check("background refresh preserves viewport position while waiting", abs((await private_card.bounding_box())["y"] - card_top_before) <= 5)
        check("background refresh preserves input-in-progress and validation", await editing_income.input_value() == "-120" and await editing_income.get_attribute("aria-invalid") == "true")
        focus_router.delay = False
        focus_router.release.set()
        await focus_page.wait_for_load_state("networkidle")
        check("background response preserves evidence expansion after update", await private_card.get_by_role("button", name="근거 접기", exact=True).count() == 1)
        check("background response preserves active condition dialog and editing input", await live_dialog.count() == 1 and await editing_income.input_value() == "-120")
        await live_dialog.get_by_role("button", name="닫기", exact=True).first.click()
        check("background response preserves viewport position after update", abs((await private_card.bounding_box())["y"] - card_top_before) <= 5)

        midnight_router = Router()
        midnight_page = await create_page(browser, midnight_router, now=datetime(2026, 10, 3, 14, 59, 58, tzinfo=timezone.utc))
        midnight_calls = len(midnight_router.calls("/api/notices"))
        await midnight_page.clock.fast_forward(3_000)
        await settle(midnight_page)
        check("actual KST midnight changes query start and fetches new window", len(midnight_router.calls("/api/notices")) > midnight_calls and any(parse_qs(urlsplit(req["url"]).query).get("start") == ["2026-10-04"] for req in midnight_router.calls("/api/notices")))
        check("past calendar day disappears after KST midnight", await midnight_page.get_by_role("button", name=re.compile(r"^10월 3일")).count() == 0)
        check("all housing-type prices remain expanded without opening notice", await midnight_page.locator(".price-row").count() == 4)

        unknown_router = Router()
        unknown_page = await create_page(browser, unknown_router, profile={**LEGACY, "region": "인천광역시", "district": "중구"}, legacy=True)
        unknown = await stored(unknown_page)
        check("split or ambiguous legacy district requires re-selection", unknown["regionNeedsReview"] is True and unknown["districtCode"] == "" and unknown["district"] == "중구")

        all_requests = [req for current in [router, focus_router, midnight_router, unknown_router] for req in current.requests]
        serialized = json.dumps(all_requests, ensure_ascii=False)
        check("every API request is profile-free GET with no request body", all(req["method"] == "GET" and not req["body"] for req in all_requests) and not any(value in serialized for value in ["privateRankBaseDate", "nationalRankBaseDate", "marriageDate", "annualIncomeKrw", "districtCode", "2024-04-02", "2025-06-01", "60000000", "11740"]))
        check("only intended public endpoints were accessed", not any(current.errors for current in [router, focus_router, midnight_router, unknown_router]))
        await focus_page.screenshot(path="/tmp/cheongyak-profile-mobile.png", full_page=True)
        await browser.close()
    print(json.dumps({"passed": len(checks), "checks": checks, "screenshot": "/tmp/cheongyak-profile-mobile.png"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
