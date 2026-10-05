"""Browser verification for classification, profile facts and results interest.

Uses isolated fictional browser profiles and controlled public API responses.
CHEONGYAK_QA_BASE defaults to localhost:8080. Set CHEONGYAK_QA_SKIP_LIVE=1
for a source preview; the final run additionally checks real public notices.
No service keys, .env, shared profiles, or server writes are used.
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
NOW = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)
OLD = "2026-10-01T12:07:21Z"
PROFILE_KEY = "cheongyak-profile-v3"
V2_KEY = "cheongyak-profile-v2"
SOURCES = ["cheongyak_home", "myhome", "lh", "ih", "sh", "gh", "cheongyak_competition"]
PROFILE = {
    "version": 3, "region": "경기도", "district": "화성시", "regionCode": "41", "districtCode": "41590",
    "regionNeedsReview": False, "movedInDate": "2010-01-01", "districtMovedInDate": "2010-01-01",
    "dateOfBirth": "1990-01-01", "householdSize": "1", "isHouseholdHead": True,
    "hasSpouse": False, "familyOnRegister": False, "householdScopeKnown": True,
    "applicantOwnsHome": False, "applicantPreviouslyOwnedHome": False,
    "ownershipFactsKnown": True, "ownershipFacts": [], "accountType": "comprehensive",
    "privateRankBaseDate": "2010-01-01", "privateDepositKrw": "6000000", "privateDepositAsOfDate": "2026-09-01", "privateDepositMaintained": True,
    "nationalRankBaseDate": "2010-01-01", "nationalRecognizedPayments": "12", "nationalPaymentsAsOfDate": "2026-09-01",
    "nationalRecognizedAmountKrw": "3000000", "accountConversionUnclear": False,
    "previousWinning": False, "restrictedFromApplying": False, "specialWinning": False,
    "maritalStatus": "single", "hasChildren": False, "children": [], "pregnant": False,
    "annualIncomeKrw": "60000000", "assetsKrw": "300000000", "militaryCurrentlyServing": False,
}
V2_PROFILE = {**PROFILE, "version": 2, "ownershipException": True}
for key in ["ownershipFactsKnown", "ownershipFacts", "privateDepositAsOfDate", "privateDepositMaintained", "nationalPaymentsAsOfDate"]:
    V2_PROFILE.pop(key, None)


def rule(kind, value=None, **extra):
    return {"kind": kind, "value": value, "verification": "official", "evidence_url": "https://www.applyhome.co.kr/official-notice",
            "evidence_text": "브라우저 회귀 검증용 공개 공식 조건", **extra}


def applicants(local_name="경기도 광명시", local_code="41210", months=24):
    return rule("applicant_regions", effect="metadata", regions=[
        {"region_code": "11", "region_name": "서울특별시"}, {"region_code": "28", "region_name": "인천광역시"},
        {"region_code": "41", "region_name": "경기도"}],
        local_priority={"region_code": local_code, "region_name": local_name, "min_months": months}, document_hash="qa-current-document")


def rank_rules():
    return [rule("private_rank_months", 6, purpose="first_rank", housing_kind="private"),
            rule("account_type", purpose="first_rank", allowed_values=["comprehensive", "deposit", "installment"]),
            rule("deposit_min_krw", 3_000_000, purpose="first_rank", require_as_of_date=True),
            rule("rank_requirements", effect="metadata", complete=True, required_kinds=["private_rank_months", "account_type", "deposit_min_krw"], housing_kind="private")]


def base_notice(identifier, title):
    return {"id": identifier, "title": title, "category": "apt", "housing_kind": "private", "source": "cheongyak_home",
            "provider": "공개 조건 검증", "address": "경기도 광명시", "region_code": "41", "region_name": "경기도 광명시",
            "housing_kind_evidence": {"verification": "official", "evidence_url": "https://www.applyhome.co.kr/official-notice", "evidence_text": "민영주택"},
            "announcement_date": "2026-10-02", "sort_date": "2026-10-07", "application_end_date": "2026-10-08",
            "official_url": "https://www.applyhome.co.kr/official-notice", "price_cap_status": "no",
            "rank_applicability": {"status": "applicable", "verification": "official", "account_required": True},
            "events": [{"kind": "first_priority", "label": "1순위", "audience": "기타지역", "start_date": "2026-10-07", "end_date": "2026-10-08"}],
            "prices": [{"unit_type": "59A", "area_sqm": 59.9, "exclusive_area_sqm": 59.9, "area_basis": "exclusive", "price_kind": "sale_max", "amount_krw": 588_000_000,
                        "basis_label": "주택형별 최고 분양금액", "source": "cheongyak_home", "verification": "official"}],
            "rules": [applicants(), *rank_rules()], "rules_complete": False, "competitions": [],
            "competition": {"status": "pending", "last_attempt_at": None, "last_success_at": None, "complete": False, "unit_types": [], "proof_invalidated": False},
            "updated_at": "2026-10-04T02:55:00Z", "version": 3}


def jamsil():
    row = base_notice("qa-jamsil", "검증 잠실에떼르넬비욘드")
    row.update(category="officetel", housing_kind="not_applicable", price_cap_status="not_applicable")
    row["rank_applicability"] = {"status": "not_applicable", "account_required": False, "verification": "official",
                                 "evidence_url": row["official_url"], "evidence_text": "오피스텔 청약통장 가입 여부 무관", "reason": "오피스텔에는 아파트 1·2순위가 적용되지 않습니다."}
    row["events"] = [{"kind": "application", "label": "청약 접수", "start_date": "2026-10-07", "end_date": "2026-10-08"}]
    row["prices"] = [{"unit_type": unit, "area_sqm": area, "exclusive_area_sqm": area, "area_basis": "exclusive", "amount_krw": amount, "price_kind": "sale_max",
                      "source": "cheongyak_home", "basis_label": "타입별 최고 공급금액 · 부가세 포함", "verification": "official"}
                     for unit, area, amount in [("28D", 28.43, 588_000_000), ("36A", 35.81, 819_800_000), ("40B", 39.23, 913_810_000), ("40C", 39.94, 937_560_000)]]
    row["rules"] = [rule("supply_financial_terms", effect="metadata", units=[{"unit_type": price["unit_type"], "application_fee_krw": 3_000_000} for price in row["prices"]])]
    return row


def supplies():
    row = base_notice("qa-supplies", "검증 유형별 신청 가능성")
    row["events"].append({"kind": "special", "label": "다자녀 특별공급", "start_date": "2026-10-06", "end_date": "2026-10-06"})
    row["rules"] += [rule("homeless", True, supply_type="일반공급"), rule("first_rank", True, supply_type="일반공급"),
                     rule("children_min", 2, supply_type="다자녀 특별공급", child_age_max=19),
                     rule("condition_coverage", effect="metadata", status="reviewed", offered_supply_types=["일반공급", "다자녀 특별공급"],
                          scopes=[{"supply_type": "일반공급", "complete": True}, {"supply_type": "다자녀 특별공급", "complete": True}])]
    return row


def dongin():
    row = base_notice("qa-dongin", "검증 동인센트리체 신청 지역")
    row["rules"] = [rule("applicant_regions", effect="metadata", regions=[{"region_code": "27", "region_name": "대구광역시"},
        {"region_code": "47", "region_name": "경상북도"}], exceptions=[{"kind": "military_service_years", "min_years": 10}],
        local_priority={"region_code": "27", "region_name": "대구광역시", "min_months": 6}), *rank_rules(),
        rule("homeless", True, supply_type="일반공급")]
    row.update(region_name="대구광역시", region_code="27", address="대구광역시 중구")
    return row


def comp(unit, closed=True, area="local"):
    return {"source": "cheongyak_competition", "unit_type": unit, "rank": 1, "residence_area": area,
            "residence_area_label": "해당지역" if area == "local" else "기타지역", "supply_type": "general", "supply_type_label": "일반공급",
            "supply_count": 10 if unit == "059.9742A" else 42, "application_count": 36 if unit == "059.9742A" else 46,
            "competition_rate": "3.60" if unit == "059.9742A" else "1.10", "result_status": "first_closed" if closed else "open",
            "result_text": "1순위 마감(청약 접수 종료)" if closed else "청약 접수중", "verification": "official",
            "evidence_url": "https://www.applyhome.co.kr/official-competition", "observed_at": OLD}


def result(identifier="qa-result", partial=True, invalidated=False):
    row = base_notice(identifier, "검증 광명 공식 결과" if identifier == "qa-result" else f"검증 결과 {identifier}")
    row.update(announcement_date="2026-09-18", application_end_date="2026-10-02", sort_date="2026-10-02")
    row["events"] = [{"kind": "first_priority", "label": "1순위", "start_date": "2026-09-30", "end_date": "2026-10-02", "audience": "기타지역"}]
    units = ["059.9742A", "059.7421B", "084.8481A", "084.9149E", "084.9558C", "084.9648B", "084.9796D"]
    row["prices"] = [{"unit_type": unit, "area_sqm": 78.5 if unit.startswith("059") else 109.5, "exclusive_area_sqm": 59.9 if unit.startswith("059") else 84.9, "area_basis": "supply",
                      "price_kind": "sale_max", "amount_krw": 879_000_000 + index * 1_000_000,
                      "basis_label": "주택형별 최고 분양금액", "verification": "official", "source": "cheongyak_home"} for index, unit in enumerate(units)]
    row["competitions"] = [comp("059.9742A"), comp("059.9742A", area="other"), comp("059.7421B", closed=not partial), comp("059.7421B", closed=not partial, area="other")]
    row["rules"] = [applicants(), rule("regional_allocation", effect="metadata", supply_type="일반공급", allocation_method="all_local_first",
        local_share_percent=100, local_region={"region_code": "41210", "region_name": "경기도 광명시", "min_months": 24}, document_hash="qa-current-document",
        evidence_text="일반공급 전량 해당지역 우선배정 후 잔여세대 기타지역 공급")]
    row["competition"] = {"status": "error" if not invalidated else "running", "last_attempt_at": "2026-10-04T02:55:00Z", "last_success_at": OLD,
                          "unit_types": units[:2], "complete": False, "proof_invalidated": invalidated, "message": "최근 재조회 실패" if not invalidated else "공고 변경 후 경쟁률 재확인 대기"}
    return row


class Router:
    def __init__(self, schedule=None, results=None):
        self.schedule = copy.deepcopy(schedule if schedule is not None else [jamsil(), supplies(), dongin()])
        self.results = copy.deepcopy(results if results is not None else [result()])
        self.requests = []
        self.errors = []

    async def handle(self, route):
        req = route.request
        parsed = urlsplit(req.url)
        self.requests.append({"url": req.url, "method": req.method, "body": req.post_data})
        if parsed.path == "/api/coverage":
            payload = {"sources": [{"source": source, "status": "ok", "record_count": 3,
                                   "last_attempt_at": "2026-10-04T02:55:00Z", "last_success_at": "2026-10-04T02:55:00Z"} for source in SOURCES]}
        elif parsed.path == "/api/notices":
            q = parse_qs(parsed.query)
            selected = self.results if q.get("view") == ["results"] else self.schedule
            selected = [row for row in selected if any(e["start_date"] <= q["end"][0] and (e.get("end_date") or e["start_date"]) >= q["start"][0] for e in row["events"])]
            page, size = int(q.get("page", ["1"])[0]), int(q.get("page_size", ["100"])[0])
            payload = {"items": selected[(page - 1) * size:page * size], "total": len(selected), "page": page, "page_size": size}
        else:
            self.errors.append(parsed.path)
            await route.fulfill(status=404, json={"detail": "unexpected public endpoint"})
            return
        await route.fulfill(status=200, json=payload)


async def create_page(browser, router, profile=PROFILE, legacy=False, width=375):
    context = await browser.new_context(viewport={"width": width, "height": 812}, timezone_id="Asia/Seoul")
    await context.add_init_script(f"localStorage.setItem({json.dumps(V2_KEY if legacy else PROFILE_KEY)}, {json.dumps(json.dumps(profile))});")
    page = await context.new_page()
    await page.clock.install(time=NOW)
    page.on("pageerror", lambda error: router.errors.append(str(error)))
    await page.route("**/api/**", router.handle)
    await page.goto(BASE, wait_until="networkidle")
    await expect(page.locator("#schedule-panel .notice-card")).to_have_count(len(router.schedule))
    return context, page


def card(page, title):
    return page.locator(".notice-card").filter(has=page.get_by_role("heading", name=title, exact=True))


async def stored(page):
    raw = await page.evaluate(f"localStorage.getItem('{PROFILE_KEY}')")
    return json.loads(raw)


async def focus_cycle(page):
    await page.evaluate("""() => { window.dispatchEvent(new Event('blur')); Object.defineProperty(document, 'visibilityState', { configurable:true, get:()=> 'hidden' }); document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('focus')); Object.defineProperty(document, 'visibilityState', { configurable:true, get:()=> 'visible' }); document.dispatchEvent(new Event('visibilitychange')); }""")
    await page.wait_for_timeout(120)


async def overflow(page, selector):
    return await page.locator(selector).evaluate("el => ({scroll:el.scrollWidth,width:el.clientWidth})")


async def main():
    checks = []
    snapshots = {}

    def check(label, condition=True):
        assert condition, label
        checks.append(label)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        router = Router()
        context, page = await create_page(browser, router, profile=V2_PROFILE, legacy=True)
        migrated = await stored(page)
        check("v2 migrates to v3 while preserving residence and book values", migrated["version"] == 3 and all(migrated[k] == V2_PROFILE[k] for k in ["region", "district", "movedInDate", "privateRankBaseDate", "nationalRankBaseDate", "privateDepositKrw", "annualIncomeKrw", "assetsKrw"]))
        check("self-assessed ownership exception does not become a verified exception", migrated["ownershipException"] is None and migrated["ownershipFacts"] == [] and migrated["ownershipFactsKnown"] is None)
        check("migration does not invent past balance dates", migrated["privateDepositAsOfDate"] == "" and migrated["privateDepositMaintained"] is None and migrated["nationalPaymentsAsOfDate"] == "")
        before = len(router.requests)
        await focus_cycle(page)
        await page.clock.fast_forward(61_000)
        await focus_cycle(page)
        check("short and minute-long focus transitions make no API requests", len(router.requests) == before)
        await context.close()

        context, page = await create_page(browser, router)
        j = card(page, jamsil()["title"])
        for amount in ["5억 8,800만원", "8억 1,980만원", "9억 1,381만원", "9억 3,756만원"]:
            await expect(j).to_contain_text(amount)
        check("Jamsil four supply prices are expanded without opening a notice", await j.locator(".price-row").count() == 4)
        check("application fee is separate from the supply price", await j.locator(".price-main").filter(has_text="청약신청금 300만원").count() == 4)
        text = await j.inner_text()
        check("officetel has no rent or nonexistent rank-base requirement", not any(word in text for word in ["보증금 미공개", "월 임대료 미공개", "주택 구분 미확인", "순위기산일"]))
        check("officetel explicitly states no account and no apartment rank", "청약통장 불필요" in text and "아파트 1·2순위 적용 없음" in text)
        s = card(page, supplies()["title"])
        general = s.locator(".qualification-supply-brief").filter(has=page.get_by_text("일반공급", exact=True))
        child = s.locator(".qualification-supply-brief").filter(has=page.get_by_text("다자녀 특별공급", exact=True))
        await expect(general).to_contain_text("조건상 가능성 있음")
        await expect(child).to_contain_text("명확한 불일치")
        check("child-count failure stays in the actual multichild supply", "자녀" not in await general.inner_text() and "0명" in await child.inner_text())
        await expect(s.locator(".qualification-account-summary")).to_contain_text("1순위 조건 충족")
        check("actual confirmed first rank is displayed independently of special mismatch")
        d = card(page, dongin()["title"])
        await expect(d).to_contain_text("신청 범위 밖")
        check("Hwaseong is not a Dongin other-region schedule candidate", await d.locator(".candidate-badge").count() == 0 and "접수일 후보" not in await d.inner_text())
        await s.get_by_role("button", name="유형별 근거", exact=True).click()
        widths = await s.locator(".qualification-reason-body").evaluate_all("els=>els.map(el=>el.getBoundingClientRect().width)")
        check("375px evidence bodies remain readable", bool(widths) and min(widths) > 150)
        await page.screenshot(path="/tmp/cheongyak-v3-supply-mobile.png", full_page=True)
        before_profile_edits = len(router.requests)
        await page.get_by_role("button", name="내 조건 설정", exact=True).click()
        dialog = page.get_by_role("dialog")
        await dialog.get_by_role("button", name=re.compile("세대·주택")).click()
        await dialog.get_by_role("group", name="본인이 현재 주택·분양권·입주권·공유지분을 보유하나요?", exact=True).get_by_role("button", name="예", exact=True).click()
        await dialog.get_by_role("button", name="주택·권리 추가", exact=True).click()
        await expect(dialog.get_by_label(re.compile("^소유자와 본인의 관계"))).to_have_count(1)
        check("ownership asks concrete property facts rather than a self-judged exemption", await dialog.get_by_label(re.compile("^소유자와 본인의 관계")).count() == 1 and await dialog.get_by_text("무주택 예외에 해당하나요?", exact=True).count() == 0)
        await dialog.get_by_label(re.compile("^소유자와 본인의 관계")).select_option("applicant")
        await dialog.get_by_label(re.compile("^주택·권리 종류")).select_option("multi_family")
        await dialog.get_by_label("주거 전용면적 (㎡)", exact=True).fill("59.5")
        await dialog.get_by_label(re.compile("^주택이 있는 시도")).select_option("41")
        await dialog.get_by_text("공식 가격과 취득가격", exact=True).click()
        money = dialog.get_by_label("공식 주택 평가가격 (원)", exact=True)
        await money.fill("170000000")
        await expect(money).to_have_value("170,000,000")
        check("property official value stores integer KRW", (await stored(page))["ownershipFacts"][0]["officialValueKrw"] == "170000000")
        await money.evaluate("el=>{el.focus();el.setSelectionRange(2,2)}")
        await money.press("8")
        caret = await money.evaluate("el=>el.selectionStart")
        check("property money editing retains a middle cursor", caret < len(await money.input_value()) - 2)
        await money.fill("-1")
        await expect(money).to_have_attribute("aria-invalid", "true")
        check("negative property amount displays a validation error", await dialog.get_by_role("alert").count() == 1)
        await money.fill("170000000")
        layout = await overflow(page, ".profile-dialog")
        check("375px ownership questionnaire has no horizontal overflow", layout["scroll"] <= layout["width"] + 2)
        await page.screenshot(path="/tmp/cheongyak-v3-ownership-mobile.png", full_page=True)
        await dialog.get_by_role("button", name=re.compile("청약통장")).click()
        deposit = dialog.get_by_label("민영주택 예치금 (원)", exact=True)
        balance_date = dialog.get_by_label("위 예치금이 충족되어 있던 기준일", exact=True)
        await deposit.fill("7000000")
        await expect(deposit).to_have_value("7,000,000")
        await expect(balance_date).to_have_value("")
        changed = await stored(page)
        check("changing private deposit clears historical balance date and maintenance fact", changed["privateDepositKrw"] == "7000000" and changed["privateDepositAsOfDate"] == "" and changed["privateDepositMaintained"] is None)
        await balance_date.fill("2026-09-02")
        maintenance = dialog.get_by_role("group", name="입력한 기준일부터 현재까지 위 예치금 이상을 계속 유지했나요?", exact=True)
        await maintenance.get_by_role("button", name="예", exact=True).click()
        check("new private balance maintenance answer is stored only as an explicit fact", (await stored(page))["privateDepositMaintained"] is True)
        await balance_date.fill("2026-09-03")
        await expect(maintenance.get_by_role("button", name="모름", exact=True)).to_have_attribute("aria-pressed", "true")
        changed = await stored(page)
        check("changing historical deposit date clears the old maintenance answer", changed["privateDepositAsOfDate"] == "2026-09-03" and changed["privateDepositMaintained"] is None)
        await dialog.get_by_role("button", name="닫기", exact=True).click()
        check("profile edits and local diagnostic changes send no extra request", len(router.requests) == before_profile_edits)
        await context.close()

        result_router = Router()
        context, page = await create_page(browser, result_router)
        await page.get_by_role("tab", name="경쟁률·청약결과", exact=True).click()
        panel = page.locator("#results-panel")
        r = panel.locator(".notice-card")
        await expect(r).to_have_count(1)
        await expect(r.locator(".competition-row")).to_have_count(2)
        check("known other-region historical results default to hiding 59A", "059.9742A" not in " ".join(await r.locator(".competition-row").all_text_contents()))
        await expect(r.locator(".competition-table")).to_contain_text("1.10")
        check("59B stays despite 1.10 and every price row remains", await r.locator(".price-row").count() == 7)
        await expect(panel.locator(".results-explanation")).to_contain_text("1건 · 경쟁률 2행")
        check("visible result counts exclude hidden unit rows")
        check("results never show a past monthly calendar", not await page.locator(".calendar-card").is_visible())
        result_layout = await overflow(page, "#results-panel")
        check("375px result controls and price rows have no horizontal overflow", result_layout["scroll"] <= result_layout["width"] + 2)
        await page.screenshot(path="/tmp/cheongyak-v3-results-hidden-mobile.png", full_page=True)
        await r.locator(".competition-proof-details summary").click()
        await expect(r.locator(".competition-proof-details")).to_contain_text("모집 10세대·접수 36건")
        check("derived closure exposes both allocation and official result links", await r.locator(".competition-proof-details a").count() == 2)
        await panel.get_by_role("button", name=re.compile("숨긴 결과 보기")).click()
        await expect(r.locator(".competition-row")).to_have_count(4)
        await expect(panel.locator(".results-explanation")).to_contain_text("경쟁률 4행")
        check("show hidden restores exact source rows and counters")
        await panel.get_by_role("button", name=re.compile("다시 숨기기")).click()
        await expect(r.locator(".competition-row")).to_have_count(2)
        await r.get_by_label("검증 광명 공식 결과 청약 지역", exact=True).select_option("unknown")
        await expect(r.locator(".competition-row")).to_have_count(4)
        check("unknown region explicitly retains every result")
        await r.get_by_label("검증 광명 공식 결과 청약 지역", exact=True).select_option("automatic")
        await expect(r.locator(".competition-row")).to_have_count(2)
        before_results = len(result_router.requests)
        await focus_cycle(page)
        check("result interest changes and focus never send profile requests", len(result_router.requests) == before_results)
        result_router.results[0]["competition"].update(proof_invalidated=True, status="running", message="공고 변경 후 경쟁률 재확인 대기")
        await panel.get_by_role("button", name="새로고침", exact=True).click()
        await expect(r.locator(".competition-row")).to_have_count(4)
        check("correction invalidation restores historical rows through a running retry")
        result_router.results[0]["competition"].update(status="error", message="재조회 실패")
        await panel.get_by_role("button", name="새로고침", exact=True).click()
        await expect(r.locator(".competition-row")).to_have_count(4)
        check("a failed correction retry does not resurrect old exclusion proofs")
        await page.screenshot(path="/tmp/cheongyak-v3-results-mobile.png", full_page=True)
        await context.close()

        paginated = Router(results=[result(f"closed-{index:03}", partial=False) for index in range(100)] + [result(f"remaining-{index:03}") for index in range(25)])
        context, page = await create_page(browser, paginated)
        await page.get_by_role("tab", name="경쟁률·청약결과", exact=True).click()
        panel = page.locator("#results-panel")
        await expect(panel.locator(".notice-card")).to_have_count(20)
        await expect(panel.locator(".results-explanation")).to_contain_text("25건 · 경쟁률 50행")
        await expect(panel.get_by_role("button", name=re.compile("결과 더 보기"))).to_contain_text("5건 남음")
        check("entire hidden first API page is skipped before result cards and totals")
        await panel.get_by_role("button", name=re.compile("결과 더 보기")).click()
        await expect(panel.locator(".notice-card")).to_have_count(25)
        check("load more fills with displayable later-page results")
        await panel.get_by_role("button", name=re.compile("숨긴 결과 보기")).click()
        await expect(panel.locator(".notice-card")).to_have_count(20)
        await expect(panel.locator(".results-explanation")).to_contain_text("125건 · 경쟁률 500행")
        check("restoration also corrects fully hidden notice counts and pagination")
        query_pages = [parse_qs(urlsplit(req["url"]).query).get("page") for req in paginated.requests if parse_qs(urlsplit(req["url"]).query).get("view") == ["results"]]
        check("public results fetch crosses the 100-row API boundary", ["1"] in query_pages and ["2"] in query_pages)
        await context.close()

        if os.environ.get("CHEONGYAK_QA_SKIP_LIVE") != "1":
            api = await p.request.new_context(base_url=BASE)
            schedule = (await (await api.get("/api/notices?start=2026-10-04&end=2027-01-02&exclude_public_rental=true&application_only=true&page_size=100")).json())["items"]
            results = (await (await api.get("/api/notices?start=2026-07-07&end=2026-10-04&exclude_public_rental=true&application_only=true&view=results&page_size=100")).json())["items"]
            real_j = next(row for row in schedule if row["title"] == "잠실에떼르넬비욘드")
            expected = {"28D": 588000000, "36A": 819800000, "40B": 913810000, "40C": 937560000}
            check("live Jamsil API has exact supply prices in KRW", {row["unit_type"]: row["amount_krw"] for row in real_j["prices"]} == expected)
            check("live Jamsil is non-rental and has official non-rank applicability", real_j["category"] == "officetel" and real_j["rank_applicability"]["status"] == "not_applicable" and real_j["rank_applicability"]["account_required"] is False)
            real_d = next(row for row in schedule if "동인센트리체" in row["title"])
            real_r = next(row for row in results if "광명 시티프라디움" in row["title"])
            live_router = Router(schedule=[real_j, real_d], results=[real_r])
            context, page = await create_page(browser, live_router, width=1280)
            await expect(card(page, real_j["title"])).to_contain_text("9억 3,756만원")
            await expect(card(page, real_d["title"])).to_contain_text("신청 범위 밖")
            check("real official notices render corrected supply values and Hwaseong scope mismatch")
            real_general = card(page, real_d["title"]).locator(".qualification-supply-brief").filter(has=page.get_by_text("일반공급", exact=True))
            await expect(real_general).to_contain_text("명확한 불일치")
            await expect(real_general).to_contain_text("신청 범위 밖")
            check("live Dongin general supply shows its official region mismatch despite missing other conditions")
            await card(page, real_d["title"]).get_by_role("button", name="유형별 근거", exact=True).click()
            desktop_widths = await card(page, real_d["title"]).locator(".qualification-reason-body").evaluate_all("els=>els.map(el=>el.getBoundingClientRect().width)")
            check("desktop real-document reason text occupies the available body width", bool(desktop_widths) and min(desktop_widths) > 350)
            await page.get_by_role("tab", name="경쟁률·청약결과", exact=True).click()
            live_card = page.locator("#results-panel .notice-card")
            await expect(live_card).to_have_count(1)
            await expect(live_card.locator(".competition-table")).to_contain_text("059.7421B")
            await expect(live_card.locator(".competition-table")).to_contain_text("1.10")
            check("live Gwangmyeong preserves the 1.10 open result and all seven prices", await live_card.locator(".price-row").count() == 7)
            actual_units = " ".join(await live_card.locator(".competition-row").all_text_contents())
            invalidated = real_r.get("competition", {}).get("proof_invalidated", False)
            check("live Gwangmyeong 59A respects current official revision proof validity", ("059.9742A" in actual_units) == bool(invalidated))
            live_rows = await live_card.locator(".competition-row").count()
            await page.screenshot(path="/tmp/cheongyak-v3-live-desktop.png", full_page=True)
            await page.set_viewport_size({"width": 375, "height": 812})
            live_layout = await overflow(page, "#results-panel")
            check("real Gwangmyeong results and seven prices fit a 375px viewport", live_layout["scroll"] <= live_layout["width"] + 2)
            await page.screenshot(path="/tmp/cheongyak-v3-live-results-mobile.png", full_page=True)
            await page.get_by_role("tab", name="접수 일정", exact=True).click()
            await expect(card(page, real_j["title"])).to_contain_text("청약신청금 300만원")
            await expect(card(page, real_j["title"])).to_contain_text("청약통장 불필요")
            check("real Jamsil mobile card displays account applicability and the separate fee")
            await page.screenshot(path="/tmp/cheongyak-v3-live-schedule-mobile.png", full_page=True)
            await card(page, real_d["title"]).locator(".qualification-brief").screenshot(path="docs/screenshots/v3-live-eligibility-mobile.png", style=".site-header { visibility: hidden !important; }")
            snapshots["live_result_counts"] = {"notice_count": len(results), "official_rows": sum(sum(competition.get("verification") == "official" for competition in row.get("competitions", [])) for row in results), "gwangmyeong_visible_rows": live_rows, "gwangmyeong_prices": len(real_r["prices"])}
            snapshots["live_notices"] = {"jamsil": real_j["version"], "dongin": real_d["version"], "gwangmyeong": real_r["version"], "proof_invalidated": invalidated}
            await context.close()
            await api.dispose()
        allowed = {"start", "end", "page", "page_size", "exclude_public_rental", "application_only", "cap_only", "view"}
        routers = [router, result_router, paginated] + ([live_router] if os.environ.get("CHEONGYAK_QA_SKIP_LIVE") != "1" else [])
        for current in routers:
            check("no browser errors or unexpected API endpoints", not current.errors)
            for req in current.requests:
                check("every public request excludes profile fields and body", req["method"] == "GET" and req["body"] is None and set(parse_qs(urlsplit(req["url"]).query)).issubset(allowed))
        await browser.close()
    print(json.dumps({"passed": len(checks), "checks": checks, "snapshots": snapshots}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
