"""Focused competition UI/privacy checks using controlled public API responses.

Run with a Python environment containing Playwright. CHEONGYAK_QA_BASE defaults
to http://localhost:8080. This script never collects real data or reads .env.
"""
import asyncio
import copy
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect


BASE = os.environ.get("CHEONGYAK_QA_BASE", "http://localhost:8080")
NOW = datetime(2026, 10, 1, 3, 0, 0, tzinfo=timezone.utc)
FRESH = "2026-10-01T02:55:00Z"
PROFILE_KEY = "cheongyak-profile-v2"
OVERRIDE_KEY = "cheongyak-residence-overrides-v1"
SCREENSHOT = Path(__file__).resolve().parents[2] / "docs/screenshots/mobile-competition.png"
SOURCES = ["cheongyak_home", "myhome", "lh", "ih", "sh", "gh"]
PROFILE = {
    "version": 2, "region": "서울특별시", "regionCode": "11", "district": "강동구", "districtCode": "11740",
    "regionNeedsReview": False, "movedInDate": "2024-01-01", "districtMovedInDate": "2024-01-01",
    "householdSize": "2", "householdScopeKnown": True, "hasSpouse": True, "spouseSameRegister": False,
    "familyOnRegister": False, "applicantOwnsHome": False, "spouseOwnsHome": False, "ownershipException": False,
    "accountType": "comprehensive", "accountConversionUnclear": False, "privateRankBaseDate": "",
    "nationalRankBaseDate": "2010-01-01", "privateDepositKrw": "3000000", "nationalRecognizedPayments": "12",
    "annualIncomeKrw": "60000000", "assetsKrw": "300000000", "maritalStatus": "married", "marriageDate": "2024-01-01",
    "children": [], "hasChildren": False, "pregnant": False, "specialWinning": False, "restrictedFromApplying": False,
}


def rank_rules():
    """Synthetic verified per-notice requirements, not a default legal rule."""
    return [{"kind": "private_rank_months", "value": 12, "operator": ">=", "purpose": "first_rank",
             "housing_kind": "private", "rank_rules_complete": True, "verification": "official",
             "evidence_url": "https://www.applyhome.co.kr/", "evidence_text": "통제된 공고의 민영 순위 인정 12개월 조건"},
            {"kind": "deposit_min_krw", "value": 3000000, "operator": ">=", "purpose": "first_rank",
             "housing_kind": "private", "verification": "official", "evidence_url": "https://www.applyhome.co.kr/",
             "evidence_text": "통제된 공고의 해당 지역·면적 예치금 300만원 조건"}]



def event(day, kind="first_priority", label="1순위", audience="기타지역"):
    return {"kind": kind, "label": label, "start_date": f"2026-10-{day:02}",
            "end_date": f"2026-10-{day:02}", "audience": audience}


def competition(unit, status="local_first_closed", *, area="local", rate="5.00", verification="official", observed=FRESH):
    texts = {"local_first_closed": "1순위 해당지역 마감(청약 접수 종료)",
             "first_closed": "1순위 마감(청약 접수 종료)", "open": "청약 접수중", "unknown": "결과 미공개"}
    return {"source": "cheongyak_home", "unit_type": unit, "model_no": None,
            "rank": 1, "residence_area": area,
            "residence_area_label": {"local": "해당지역", "other": "기타지역", "other_gyeonggi": "기타경기"}.get(area, "미확인"),
            "supply_count": 60, "application_count": 3 if "△" in rate else 300,
            "competition_rate": rate, "result_status": status, "result_text": texts[status],
            "evidence_url": "https://www.applyhome.co.kr/ai/aia/selectAPTCompetitionPopup.do?houseManageNo=2026000399&pblancNo=2026000399",
            "verification": verification, "observed_at": observed}


def notice(identifier, title, day, *, statuses=("local_first_closed", "local_first_closed"), rates=("5.00", "2.00"), meta_status="ok", complete=True, observed=FRESH, verification="official", special=False):
    units = ["059.9442A", "084.8481A"]
    rows = [competition(unit, status, rate=rate, observed=observed, verification=verification)
            for unit, status, rate in zip(units, statuses, rates)]
    rows += [competition(unit, status, area="other", rate="-", observed=observed, verification=verification)
             for unit, status in zip(units, statuses)]
    events = [event(day)]
    if special:
        events.append(event(day + 1, "special", "신혼부부 특별공급", "신혼부부"))
    return {
        "id": identifier, "title": title, "category": "apt", "source": "cheongyak_home",
        "housing_kind": "private", "housing_kind_evidence": {"verification": "official", "source": "cheongyak_home", "evidence_url": "https://www.applyhome.co.kr/", "evidence_text": "민영주택"},
        "sources": ["cheongyak_home"], "provider": "통제된 브라우저 검증",
        "address": "서울특별시 강동구", "region_code": "11", "region_name": "서울특별시",
        "announcement_date": "2026-09-20", "sort_date": f"2026-10-{day:02}",
        "official_url": "https://www.applyhome.co.kr/", "price_cap_status": "yes",
        "events": events, "prices": [{"unit_type": unit, "area_sqm": 59.9 if index == 0 else 84.8,
            "price_kind": "sale_max", "amount_krw": 512000000 + index * 100000000,
            "monthly_krw": None, "basis_label": "주택형별 최고 분양금액", "verification": "official",
            "source": "cheongyak_home", "evidence_url": "https://www.applyhome.co.kr/", "evidence_text": "브라우저 검증용 공식 가격"}
            for index, unit in enumerate(units)],
        "rules": rank_rules(), "rules_complete": False, "competitions": rows,
        "competition": {"status": meta_status, "last_attempt_at": observed if meta_status == "ok" else FRESH,
            "last_success_at": observed, "complete": complete, "unit_types": units,
            "evidence_url": rows[0]["evidence_url"], "message": "통제된 공식 경쟁률 결과"},
        "updated_at": FRESH, "version": 1,
    }


FIXTURES = [
    notice("qa-all-closed", "검증 전 주택형 해당지역 마감", 2),
    notice("qa-partial", "검증 일부 주택형 신청 가능", 5, statuses=("local_first_closed", "open"), rates=("68.71", "(△57)")),
    notice("qa-ratio", "검증 경쟁률 1.10 접수 중", 6, statuses=("open", "open"), rates=("1.10", "(△57)")),
    notice("qa-generic", "검증 일반 1순위 마감", 7, statuses=("first_closed", "first_closed")),
    notice("qa-stale", "검증 6시간 경과 결과", 8, observed="2026-09-30T20:59:59Z"),
    notice("qa-failed", "검증 최신 수집 실패", 9, meta_status="error"),
    notice("qa-unverified", "검증 미검증 결과", 10, verification="auto_unverified"),
    notice("qa-incomplete", "검증 전체 주택형 미확인", 11, complete=False),
    notice("qa-missing-type", "검증 일부 주택형 결과 누락", 12),
    notice("qa-unknown", "검증 청약 지역 미확인", 13),
    notice("qa-local", "검증 해당지역 신청자", 14),
    notice("qa-gyeonggi", "검증 기타경기 신청자", 15),
    notice("qa-special", "검증 앞으로의 특별공급", 16, special=True),
]
FIXTURES[8]["competitions"] = [row for row in FIXTURES[8]["competitions"] if row["unit_type"] == "059.9442A"]
for row in FIXTURES[:2]:
    row.update({"address": "경기도 수원시", "region_name": "경기도", "region_code": "41"})
simple_rule = {"kind": "homeless", "value": True, "verification": "official",
               "evidence_url": "https://www.applyhome.co.kr/", "evidence_text": "통제된 공식 무주택 조건"}
first_rank_rule = {"kind": "first_rank", "value": True, "verification": "official", "evidence_url": "https://www.applyhome.co.kr/", "evidence_text": "통제된 공고 일반공급 1순위 요건"}
FIXTURES[0].update({"rules": [*rank_rules(), copy.deepcopy(simple_rule), copy.deepcopy(first_rank_rule)], "rules_complete": True})
FIXTURES[1].update({"rules": [*rank_rules(), {**simple_rule, "supply_type": "일반공급"},
                              {**first_rank_rule, "supply_type": "일반공급"},
                              {**simple_rule, "supply_type": "신혼부부"},
                              {**simple_rule, "kind": "marital_status", "value": "married", "supply_type": "신혼부부"},
                              {**simple_rule, "kind": "marriage_months_max", "operator": "<=", "value": 84, "supply_type": "신혼부부"},
                              {**simple_rule, "kind": "special_winning", "value": False, "supply_type": "신혼부부"}], "rules_complete": True})
OVERRIDES = {row["id"]: "other" for row in FIXTURES}
OVERRIDES.update({"qa-unknown": "unknown", "qa-local": "local", "qa-gyeonggi": "other_gyeonggi"})


class FixtureRouter:
    def __init__(self, fixtures=FIXTURES):
        self.fixtures = copy.deepcopy(fixtures)
        self.requests = []
        self.errors = []

    async def handle(self, route):
        req = route.request
        parsed = urlsplit(req.url)
        self.requests.append({"url": req.url, "method": req.method, "body": req.post_data, "headers": req.headers})
        if parsed.path == "/api/coverage":
            payload = {"sources": [{"source": source, "status": "ok", "message": "수집 완료",
                "last_attempt_at": FRESH, "last_success_at": FRESH, "record_count": len(self.fixtures)} for source in SOURCES]}
        elif parsed.path == "/api/notices":
            q = parse_qs(parsed.query)
            start, end = q["start"][0], q["end"][0]
            rows = [row for row in self.fixtures if any(e["start_date"] <= end and e["end_date"] >= start for e in row["events"])]
            page, size = int(q.get("page", ["1"])[0]), int(q.get("page_size", ["100"])[0])
            payload = {"items": rows[(page - 1) * size:page * size], "total": len(rows), "page": page, "page_size": size}
        else:
            self.errors.append(parsed.path)
            await route.fulfill(status=404, json={"detail": "unexpected public endpoint"})
            return
        await route.fulfill(status=200, json=payload)


def card(page, title):
    return page.locator(".notice-card").filter(has=page.get_by_role("heading", name=title, exact=True))


async def create_page(browser, router, profile=PROFILE, overrides=OVERRIDES):
    context = await browser.new_context(viewport={"width": 375, "height": 812}, timezone_id="Asia/Seoul")
    await context.add_init_script(f"localStorage.setItem({json.dumps(PROFILE_KEY)}, {json.dumps(json.dumps(profile))}); localStorage.setItem({json.dumps(OVERRIDE_KEY)}, {json.dumps(json.dumps(overrides))});")
    page = await context.new_page()
    await page.clock.install(time=NOW)
    await page.route("**/api/**", router.handle)
    await page.goto(BASE, wait_until="networkidle")
    return page


async def set_private_base_date(page, value):
    await page.get_by_role("button", name="내 조건 설정", exact=True).click()
    await page.get_by_role("button", name="청약통장", exact=False).click()
    await page.get_by_label("민영주택 순위기산일", exact=True).fill(value)
    await page.get_by_role("button", name="닫기", exact=True).click()


async def main():
    checks = []

    def check(label, condition=True):
        assert condition, label
        checks.append(label)

    router = FixtureRouter()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await create_page(browser, router)
        await expect(page.locator(".notice-card")).to_have_count(len(FIXTURES))
        check("unconfirmed rank base date never hides an officially closed notice")
        partial = card(page, "검증 일부 주택형 신청 가능")
        check("competition rows visible at375px without opening details", await partial.locator(".competition-row").count() == 4)
        await expect(partial).to_contain_text("68.71")
        await expect(partial).to_contain_text("미달 57")
        await expect(partial).to_contain_text("미공개")
        check("raw numeric ratio, undersubscription count and unpublished dash distinguished")
        check("all26 price rows visible before any detail click", await page.locator(".price-row").count() == len(FIXTURES) * 2)
        check("375px page has no horizontal overflow", await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        check("closed unit preserves its price row", await partial.locator(".price-row").count() == 2)
        await expect(card(page, "검증 전 주택형 해당지역 마감").locator(".eligibility-summary .eligibility-badge")).to_have_text("추가 확인 필요")
        check("missing factual rank date remains review despite verified complete rules")
        await partial.get_by_role("button", name="유형별 근거", exact=True).click()
        await expect(partial.locator(".qualification-details")).to_be_visible()
        supply_sections = partial.locator(".qualification-section").filter(has=page.locator("h5").filter(has_text=re.compile(r"^(일반공급|신혼부부)")))
        check("general supply requires missing rank date and special supply is assessed once for all units", await supply_sections.locator(".qualification-badge").all_text_contents() == ["추가 확인 필요", "조건상 가능성 있음"])
        await partial.get_by_role("button", name="근거 접기", exact=True).click()

        before = len(router.requests)
        await set_private_base_date(page, "2010-01-01")
        await expect(page.locator(".notice-card")).to_have_count(len(FIXTURES) - 1)
        check("other-region first rank excludes only complete fresh officially local-first-closed notice")
        check("rank-base date edit makes no API request", len(router.requests) == before)
        check("rank facts are saved only in the browser profile without a self-assessed rank", json.loads(await page.evaluate(f"localStorage.getItem('{PROFILE_KEY}')"))["privateRankBaseDate"] == "2010-01-01" and "subscriptionRank" not in json.loads(await page.evaluate(f"localStorage.getItem('{PROFILE_KEY}')")))
        check("excluded notice absent from agenda", await card(page, "검증 전 주택형 해당지역 마감").count() == 0)
        titles = await page.locator(".notice-card h4").all_text_contents()
        check("partial closure, high ratio, generic first closure and future special all remain", all(title in titles for title in ["검증 일부 주택형 신청 가능", "검증 경쟁률 1.10 접수 중", "검증 일반 1순위 마감", "검증 앞으로의 특별공급"]))
        check("stale/error/unverified/incomplete/missingtype outcomes cannot hide", all(title in titles for title in ["검증 6시간 경과 결과", "검증 최신 수집 실패", "검증 미검증 결과", "검증 전체 주택형 미확인", "검증 일부 주택형 결과 누락"]))
        check("unknown/local/othergyeonggi applicant regions cannot hide", all(title in titles for title in ["검증 청약 지역 미확인", "검증 해당지역 신청자", "검증 기타경기 신청자"]))
        await partial.get_by_role("button", name="유형별 근거", exact=True).click()
        closed_general = partial.locator(".qualification-supply").filter(has_text="일반공급").filter(has_text="059.9442A")
        open_general = partial.locator(".qualification-supply").filter(has_text="일반공급").filter(has_text="084.8481A")
        closed_special = partial.locator(".qualification-supply").filter(has_text="신혼부부")
        await expect(closed_general.locator(".qualification-badge")).to_have_text("명확한 불일치")
        await expect(closed_general).to_contain_text("기타지역 1순위 접수 마감")
        await expect(closed_general).to_contain_text("1순위 해당지역 마감(청약 접수 종료)")
        check("closed general unit cannot show possible eligibility and displays explicit official closure reason")
        check("closed general diagnosis links official competition evidence", FIXTURES[1]["competitions"][0]["evidence_url"] in await closed_general.locator("a").evaluate_all("els => els.map(el => el.href)"))
        await expect(open_general.locator(".qualification-badge")).to_have_text("조건상 가능성 있음")
        check("open general unit retains its qualifying diagnosis")
        await expect(closed_special.locator(".qualification-badge")).to_have_text("조건상 가능성 있음")
        check("special supply diagnosis unaffected by general closure", "기타지역 1순위 접수 마감" not in await closed_special.inner_text())
        await partial.get_by_role("button", name="근거 접기", exact=True).click()
        summary = page.locator(".intro-stats > div").first
        await expect(summary.locator("strong")).to_have_text(f"{len(FIXTURES) - 1}건")
        check("display count agrees with visible notices after exclusion")
        await expect(page.locator(".intro-stats > div").nth(1).locator("strong")).to_have_text("2건")
        check("residence candidate count excludes closed notice while keeping partial and eligible special supply")
        day_two = page.get_by_role("button", name=re.compile(r"^10월 2일.*접수 일정 없음"))
        await expect(day_two).to_be_visible()
        check("hidden-only application date has no calendar point", await day_two.locator(".calendar-dot").count() == 0 and "접수 일정 있음" not in (await day_two.get_attribute("aria-label") or ""))
        await expect(page.get_by_role("button", name=re.compile(r"^10월 16일.*접수 일정 없음"))).to_be_visible()
        await expect(page.get_by_role("button", name=re.compile(r"^10월 17일.*접수 일정 있음"))).to_be_visible()
        special_group = page.locator(".day-group").filter(has=page.get_by_role("heading", name="검증 앞으로의 특별공급", exact=True))
        await expect(special_group.locator(".day-heading h3")).to_contain_text("10월 17일")
        check("retained special supply groups and calendar points use its open day rather than closed general day")
        SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
        await partial.screenshot(path=str(SCREENSHOT), style=".site-header { visibility: hidden !important; }")
        await day_two.click()
        await expect(page.locator(".notice-card")).to_have_count(0)
        check("selected hidden-only date remains excluded")
        await page.get_by_role("button", name="다가오는 일정", exact=True).click()
        await expect(page.locator(".notice-card")).to_have_count(len(FIXTURES) - 1)

        restore = page.get_by_role("checkbox", name=re.compile(r"^마감으로 숨긴 공고 보기"))
        await restore.check()
        hidden = card(page, "검증 전 주택형 해당지역 마감")
        await expect(hidden).to_be_visible()
        await expect(hidden.locator(".competition-exclusion-reason")).to_contain_text("해당지역")
        check("restore control reveals hidden notice with official closure reason")
        check("restored closed notice retains both visible original prices", await hidden.locator(".price-row").count() == 2)
        await expect(hidden.locator(".eligibility-summary .eligibility-badge")).to_have_text("명확한 불일치")
        check("restored fully closed notice summary cannot retain its earlier possible eligibility")
        await restore.uncheck()
        await expect(page.locator(".notice-card")).to_have_count(len(FIXTURES) - 1)

        before = len(router.requests)
        await page.get_by_label("검증 청약 지역 미확인 청약 지역", exact=True).select_option("other")
        await expect(card(page, "검증 청약 지역 미확인")).to_have_count(0)
        check("explicit per-notice other-region choice immediately applies exclusion")
        check("region override makes no API request", len(router.requests) == before)
        check("region override persists locally", json.loads(await page.evaluate(f"localStorage.getItem('{OVERRIDE_KEY}')"))["qa-unknown"] == "other")

        for row in router.fixtures[0]["competitions"]:
            row["result_status"] = "open"
            row["result_text"] = "청약 접수중"
        await page.get_by_role("button", name="새로고침", exact=True).click()
        await expect(card(page, "검증 전 주택형 해당지역 마감")).to_be_visible()
        check("official correction reopening applications restores a previously hidden notice")
        await expect(page.get_by_role("button", name=re.compile(r"^10월 2일.*접수 일정 있음"))).to_be_visible()
        check("official reopening correction restores calendar point consistently")
        await set_private_base_date(page, "2026-09-19")
        await expect(page.locator(".notice-card")).to_have_count(len(FIXTURES))
        check("insufficient first-rank period stops exclusion without assuming second rank")

        # A complete first100row API page can be locally excluded. The UI must
        # continue loading so that an application-open result on page2 appears.
        hidden_rows = [notice(f"qa-paging-{index:03}", f"페이지 제외 검증 {index:03}", 2) for index in range(100)]
        open_row = notice("qa-paging-open", "두 번째 페이지 신청 가능", 19, statuses=("open", "open"))
        paging_router = FixtureRouter(hidden_rows + [open_row])
        paging_profile = {**PROFILE, "privateRankBaseDate": "2010-01-01"}
        paging_overrides = {row["id"]: "other" for row in hidden_rows + [open_row]}
        paging_page = await create_page(browser, paging_router, paging_profile, paging_overrides)
        await expect(card(paging_page, "두 번째 페이지 신청 가능")).to_be_visible()
        await expect(paging_page.locator(".notice-card")).to_have_count(1)
        check("fully excluded first API page advances automatically to visible page2 result")
        check("paging aggregate count contains only one visible result", (await paging_page.locator(".intro-stats > div").first.locator("strong").inner_text()).strip() == "1건")
        check("paging loaded page2", any(parse_qs(urlsplit(req["url"]).query).get("page") == ["2"] for req in paging_router.requests))

        before_return = len(paging_router.requests)
        await paging_page.evaluate("Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' }); document.dispatchEvent(new Event('visibilitychange'))")
        await paging_page.clock.fast_forward(6 * 60 * 60 * 1000 + 1000)
        await expect(paging_page.locator(".intro-stats > div").first.locator("strong")).to_have_text("1건")
        check("hidden tab pauses local freshness checks and periodic API requests", len(paging_router.requests) == before_return)
        await paging_page.evaluate("Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' }); document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('focus'))")
        await expect(paging_page.locator(".intro-stats > div").first.locator("strong")).to_have_text("101건")
        check("six-hour evidence expiry is recalculated on tab return and restores excluded notices")
        check("tab return recomputes expired competition locally without a refresh request", len(paging_router.requests) == before_return)

        all_requests = router.requests + paging_router.requests
        serialized = json.dumps(all_requests, ensure_ascii=False)
        check("API calls stay GET without profile or override body", all(req["method"] == "GET" and req["body"] is None for req in all_requests))
        check("profile rank and override values never enter request URLs,headers,bodies", not any(value in serialized for value in ["서울특별시", "강동구", "2024-01-01", "subscriptionRank", "privateRankBaseDate", "nationalRankBaseDate", "privateDepositKrw", "accountType", "movedInDate", "annualIncomeKrw", "residenceOverrides", "qa-unknown"]))
        check("no unexpected API endpoints", not router.errors and not paging_router.errors)
        await browser.close()
    print(json.dumps({"passed": len(checks), "checks": checks, "requests": len(router.requests),
        "paging_requests": len(paging_router.requests), "screenshot": str(SCREENSHOT)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
