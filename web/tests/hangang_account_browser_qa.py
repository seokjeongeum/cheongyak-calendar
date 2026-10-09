"""375px Chromium QA from the exact Hangang official document.

Only saved source text and synthetic local facts are used. Public API responses
are intercepted; no user profile, administrator credential or API key is read.
"""

import asyncio
import copy
import json
import os
from pathlib import Path
import re
import sys

from playwright.async_api import async_playwright, expect
from profile_facts_v10_browser_qa import NOW, PROFILE_KEY, Router, parent, profile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
from app.extract.official_rules import parse_official_rules  # noqa: E402

BASE = os.environ.get("CHEONGYAK_QA_BASE", "http://127.0.0.1:5193")
OUT = Path(os.environ.get("CHEONGYAK_QA_OUT", "/tmp/cheongyak-hangang-account-qa"))
SOURCE = next(row for row in json.loads((ROOT / "api/tests/fixtures/current-private-v5.json").read_text()) if row["external_id"] == "2026000468")
PARSED = parse_official_rules(SOURCE["pages"], url=SOURCE["document_url"], digest=SOURCE["document_hash"], payload=SOURCE["payload"])
CUTOFF = SOURCE["payload"]["announcement_date"]
USAGE = "현재 사용할 청약통장이 당첨자 선정에 사용된 적이 있나요?"
FIRST = "현재 청약통장이 가장 먼저 당첨자 선정에 사용된 날"
RESOLVED_MESSAGE = "공식 공고 페이지를 가져오지 못했습니다."
RULES = copy.deepcopy(PARSED["rules"])
RULES.append({"kind": "document_diagnostics", "effect": "metadata", "verification": "official", "status": "partial", "document_hash": SOURCE["document_hash"], "diagnostics": [{"stage": "discovery", "code": "official_page_failed", "status": "resolved", "message": RESOLVED_MESSAGE, "evidence_url": SOURCE["document_url"]}]})
CLASSIFICATION = next(rule for rule in RULES if rule["kind"] == "housing_classification")
AREAS = next(rule for rule in RULES if rule["kind"] == "unit_exclusive_areas")["units"]
ROW = {**SOURCE["payload"], "id": "qa-official-hangang", "provider": "정확한 공식 원문 브라우저 검증", "address": None, "region_name": "경기도", "region_code": "41", "housing_kind": "private", "housing_kind_evidence": {key: CLASSIFICATION[key] for key in ["verification", "source", "document_hash", "evidence_url", "evidence_text"]}, "document_hash": SOURCE["document_hash"], "price_cap_status": "no", "events": [{"kind": "special", "label": "특별공급", "start_date": "2026-10-12", "end_date": "2026-10-12"}], "prices": [{**unit, "price_kind": "sale", "verification": "official", "evidence_url": SOURCE["document_url"], "evidence_text": "공식 모집표 전용면적", "document_hash": SOURCE["document_hash"]} for unit in AREAS], "rules": RULES, "rules_complete": False, "updated_at": "2026-10-09T00:55:00Z", "version": 1}


def account_control(rule, historical=False):
    if rule["kind"] == "account_unused_after_winning":
        return {**rule, "criterion_basis": "announcement", "criterion_date": CUTOFF, "evaluation_mode": None, "requires_maintained_until_application": False} if historical else None
    result = {**rule}
    for key in ["conditions", "exceptions"]:
        if isinstance(result.get(key), list):
            result[key] = [mapped for entry in result[key] if (mapped := account_control(entry, historical)) is not None]
    return result


# This control deliberately changes only the account condition's time basis.
# It tests the historical helper; it is not the Hangang application clause.
HISTORICAL = {**ROW, "id": "qa-historical-account-control", "title": "과거 기준일 통장 분기 검증용 공고", "rules": [account_control(rule, True) for rule in RULES]}


def person(**extra):
    value = profile(
        region="경기도", regionCode="41", district="화성시", districtCode="41590",
        privateDepositKrw="15000000", privateDepositAsOfDate=CUTOFF,
        currentlyDomesticResident=True, domesticResidenceFactsAsOfDate=CUTOFF,
        applicationRestrictionsAsOfDate=CUTOFF,
        ineligibleRestrictionActive=False, resaleRestrictionActive=False,
        rewinningRestrictionActive=False, currentAccountUsedForWinning=False,
        currentAccountFactsAsOfDate=CUTOFF,
        householdMembers=[parent("1966-01-01")],
        applicationRestrictionFacts={"applicant": {"ineligibleRestrictionActive": False, "resaleRestrictionActive": False, "rewinningRestrictionActive": False, "asOfDate": CUTOFF, "historyConfirmations": []}},
    )
    return {**value, **extra}


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []

    def check(label, value=True):
        assert value, label
        checks.append(label)
        print(label, flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])

        async def create(value, row=ROW):
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
            await page.wait_for_timeout(350)
            return page, router

        async def bank(page):
            dialog = page.get_by_role("dialog")
            await dialog.locator(".step-progress").get_by_role("button", name=re.compile("청약통장")).click()
            return dialog

        async def no_requests(page, router, before, label):
            await page.evaluate("""() => {window.dispatchEvent(new Event('focus')); Object.defineProperty(document, 'visibilityState', {configurable:true,get:()=> 'hidden'}); document.dispatchEvent(new Event('visibilitychange')); Object.defineProperty(document, 'visibilityState', {configurable:true,get:()=> 'visible'}); document.dispatchEvent(new Event('visibilitychange'));}""")
            await page.wait_for_timeout(450)
            check(label, len(router.requests) == before and not router.errors and all(request["method"] == "GET" and request["body"] is None for request in router.requests))

        page, router = await create(person())
        before = len(router.requests)
        overview = page.locator(".qualification-supply-overview")
        general = overview.locator("section.qualification-supply-brief").filter(has=page.locator(".qualification-supply-title>strong", has_text="일반공급"))
        await expect(general).to_contain_text("조건상 가능성 있음")
        check("exact Hangang reviewed general branch and all common facts yield possible")
        parent_path = overview.locator("details.qualification-supply-collapse").filter(has=page.locator("summary", has_text="노부모부양 특별공급"))
        await expect(parent_path.first).to_be_visible()
        for path in await parent_path.all():
            await expect(path).to_have_js_property("open", False)
            await expect(path.locator("summary")).to_contain_text("내 조건으로 신청 불가")
        for reason in await page.get_by_text("불일치 · 부모 만 나이", exact=True).all():
            await expect(reason).to_be_hidden()
        check("actual Hangang 60-versus-65 parent failure starts collapsed without shared duplicate")
        await expect(page.locator("body")).not_to_contain_text(RESOLVED_MESSAGE)
        check("resolved discovery failure is absent from actual-source page")
        await general.scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "general-possible-parent-closed-375.png"))
        await page.get_by_role("button", name="유형별 근거", exact=True).click()
        topics = page.locator(".qualification-details .qualification-remaining-topics li")
        texts = await topics.all_text_contents()
        for scope in ["기관추천", "다자녀", "노부모"]:
            scoped_texts = [text for text in texts if scope in text]
            check(f"{scope} remaining topics have no fictitious income/assets requirement", all("소득·자산" not in text and "소득 기준" not in text and "자산 기준" not in text for text in scoped_texts))
        await expect(page.locator(".qualification-details")).not_to_contain_text(RESOLVED_MESSAGE)
        await page.get_by_role("button", name="내 조건 설정", exact=True).click()
        dialog = await bank(page)
        await expect(dialog.get_by_role("group", name=USAGE, exact=True)).to_have_count(1)
        await expect(dialog.locator(".step-fields:not([hidden])").get_by_role("group", name=USAGE, exact=True)).to_be_visible()
        check("current account winning-use question appears once in the bank step")
        await expect(dialog.get_by_label(FIRST, exact=True)).to_have_count(0)
        check("known unused current account asks no needless first-winning date")
        await dialog.get_by_role("group", name=USAGE, exact=True).scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "single-bank-fact-375.png"))
        await dialog.locator(".dialog-close").click()
        check("375px official source page has no horizontal overflow", await page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        await no_requests(page, router, before, "source toggles, profile opening and focus return add no API requests")
        await page.context.close()

        # An unknown current-account answer links to its one canonical bank field.
        page, router = await create(person(currentAccountUsedForWinning=None, currentAccountFactsAsOfDate=""))
        before = len(router.requests)
        await page.get_by_role("button", name="유형별 근거", exact=True).click()
        action = page.get_by_role("button", name="현재 청약통장 당첨 사용 이력 입력하기", exact=True).first
        await expect(action).to_be_visible()
        await action.click()
        dialog = page.get_by_role("dialog")
        group = dialog.get_by_role("group", name=USAGE, exact=True)
        await expect(group).to_be_visible()
        check("missing account fact link switches to bank and focuses canonical field", await page.evaluate("document.activeElement.closest('[data-profile-field]')?.dataset.profileField === 'currentAccountUsedForWinning'"))
        await group.get_by_role("button", name="예", exact=True).click()
        await expect(dialog.get_by_label(FIRST, exact=True)).to_have_count(0)
        check("actual Hangang application-date precheck asks no first-win date for today's known used account")
        await dialog.locator(".dialog-close").click()
        failed = page.locator(".qualification-supply-overview details.qualification-supply-collapse").filter(has=page.locator("summary", has_text="일반공급")).first
        await expect(failed).to_have_js_property("open", False)
        await failed.locator("summary").click()
        await expect(failed).to_contain_text("불일치 · 현재 청약통장 당첨 사용 이력")
        await expect(failed).to_contain_text("오늘의 통장 상태로 미리 비교")
        await expect(failed).to_contain_text("오늘 비교일 (한국 시간)")
        await expect(failed).to_contain_text("2026-10-09")
        check("currently used account blocks actual Hangang application independently of contract or announcement-date history")
        saved = json.loads(await page.evaluate(f"localStorage.getItem('{PROFILE_KEY}')"))
        check("actual Hangang current-account answer is dated and saved only in browser", saved["currentAccountUsedForWinning"] is True and saved["currentAccountFactsAsOfDate"] == "2026-10-09")
        await failed.scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "current-account-used-375.png"))
        await no_requests(page, router, before, "actual Hangang account input and focus return stay local without extra API requests")
        await page.context.close()

        # A separate, explicitly historical control checks actual event dates.
        page, router = await create(person(currentAccountUsedForWinning=None, currentAccountFactsAsOfDate=""), HISTORICAL)
        before = len(router.requests)
        await page.get_by_role("button", name="유형별 근거", exact=True).click()
        await page.get_by_role("button", name="현재 청약통장 당첨 사용 이력 입력하기", exact=True).first.click()
        dialog = page.get_by_role("dialog")
        await dialog.get_by_role("group", name=USAGE, exact=True).get_by_role("button", name="예", exact=True).click()
        date = dialog.get_by_label(FIRST, exact=True)
        await expect(date).to_be_visible()
        await date.fill("2026-10-05")
        await dialog.locator(".dialog-close").click()
        saved = json.loads(await page.evaluate(f"localStorage.getItem('{PROFILE_KEY}')"))
        check("bank winning-use and actual first-winning date save only in browser", saved["currentAccountUsedForWinning"] is True and saved["currentAccountFirstWinningDate"] == "2026-10-05")
        general = page.locator(".qualification-supply-overview section.qualification-supply-brief").filter(has=page.locator(".qualification-supply-title>strong", has_text="일반공급"))
        await expect(general).to_contain_text("조건상 가능성 있음")
        check("historical control: first win after October 2 leaves the October 2 branch possible")
        await expect(page.locator(".qualification-details")).to_contain_text("최초 당첨자 선정일 2026-10-05")
        await page.get_by_role("button", name="내 조건 설정", exact=True).click()
        dialog = await bank(page)
        await dialog.get_by_label(FIRST, exact=True).fill("2026-10-01")
        await dialog.locator(".dialog-close").click()
        failed = page.locator(".qualification-supply-overview details.qualification-supply-collapse").filter(has=page.locator("summary", has_text="일반공급")).first
        await expect(failed).to_have_js_property("open", False)
        await failed.locator("summary").click()
        await expect(failed).to_contain_text("불일치 · 현재 청약통장 당첨 사용 이력")
        await expect(failed).to_contain_text("2026-10-01")
        check("historical control: first win before October 2 blocks reuse independent of contract")
        await failed.scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "before-cutoff-account-used-375.png"))
        await no_requests(page, router, before, "historical control edits and first-winning dates stay local with no extra GET or POST")
        await page.context.close()

        # False today without a dated history must link to the account history,
        # rather than borrowing private/national rank dates.
        page, router = await create(person(currentAccountFactsAsOfDate=""), HISTORICAL)
        await page.get_by_role("button", name="유형별 근거", exact=True).click()
        await page.get_by_role("button", name="현재 청약통장 당첨 사용 이력 변경일 입력하기", exact=True).first.click()
        history = page.get_by_role("dialog").locator('[data-fact-group="bank_account"]')
        await expect(history).to_be_visible()
        check("historical control: past account gap links to its own history instead of rank dates", await page.evaluate("document.activeElement.closest('[data-fact-group]')?.dataset.factGroup === 'bank_account'"))
        await history.locator("select").select_option("known")
        await history.locator('input[type="date"]').fill("2026-09-01")
        await page.get_by_role("dialog").locator(".dialog-close").click()
        await expect(page.locator(".qualification-supply-overview section.qualification-supply-brief").filter(has=page.locator(".qualification-supply-title>strong", has_text="일반공급"))).to_contain_text("조건상 가능성 있음")
        check("historical control: explicit unchanged-since account date restores the general branch")
        await page.context.close()

        no_usage = {**ROW, "id": "qa-without-account-reuse-rule", "rules": [mapped for rule in RULES if (mapped := account_control(rule)) is not None]}
        page, router = await create(person(), no_usage)
        await page.get_by_role("button", name="내 조건 설정", exact=True).click()
        dialog = await bank(page)
        await expect(dialog.get_by_role("group", name=USAGE, exact=True)).to_have_count(0)
        check("notices without a current-account reuse condition show no account-use question")
        check("375px account dialog has no horizontal overflow", await page.evaluate("document.querySelector('.profile-dialog').scrollWidth <= document.querySelector('.profile-dialog').clientWidth"))
        await page.context.close()

        # Standard institution conditions use the full reviewed official source.
        value = person(recommendationStatus="confirmed", recommendationReason="중소기업 장기근속", applicationHistoryPresence=False, applicationHistoryPeople=["applicant", "qa-parent"])
        value["factChanges"] = {**value["factChanges"], "citizenship": {"mode": "never_changed", "date": ""}}
        page, router = await create(value)
        institution = page.locator(".qualification-supply-overview section.qualification-supply-brief").filter(has=page.locator(".qualification-supply-title>strong", has_text="기관추천 특별공급"))
        await expect(institution.first).to_be_visible()
        for scope in await institution.all():
            await expect(scope).to_contain_text("조건상 가능성 있음")
        check("actual reviewed standard institution nomination with fulfilled common facts is possible")
        await institution.first.scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "standard-institution-possible-375.png"))
        await page.context.close()

        # p38 is an unsupported legal exception, rather than a new confirmation.
        value = person(householdMembers=[parent("1966-01-01", previouslyOwnedHome=True)])
        page, router = await create(value)
        await page.get_by_role("button", name="유형별 근거", exact=True).click()
        exception = page.locator(".qualification-reason").filter(has=page.get_by_text("서비스 원문 검토 부족 · 생애최초의 제53조 과거 주택 소유 예외", exact=True))
        await expect(exception).to_be_visible()
        await expect(exception.locator(".qualification-input-action")).to_have_count(0)
        check("active p38 ownership exception stays precise source review without a confirmation input")
        await exception.scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "active-p38-source-review-375.png"))
        await page.context.close()

        # The public source's strict child condition still needs one canonical
        # input when general-points selection metadata has not arrived.
        child = {**parent("2010-01-01"), "id": "child", "relation": "applicant_child"}
        value = person(householdMembers=[child], hasChildren=True, pregnant=False, pointsFamily={"child": {"registeredSince": "2020-01-01", "unmarried": None, "overseasExcluded": False}})
        value["factChanges"] = {**value["factChanges"], "marital": {"mode": "known", "date": "2020-01-01"}, "pregnancy": {"mode": "never_changed", "date": ""}}
        child_row = {**ROW, "id": "qa-hangang-child-without-points-metadata", "rules": [rule for rule in RULES if rule["kind"] != "selection_method"]}
        page, router = await create(value, child_row)
        before = len(router.requests)
        await page.get_by_role("button", name="유형별 근거", exact=True).click()
        await page.get_by_role("button", name="생애최초 자녀 혼인 여부 입력하기", exact=True).first.click()
        canonical = page.get_by_role("dialog").locator('details[data-profile-field="pointsFamily"]')
        await expect(canonical).to_have_js_property("open", True)
        await expect(canonical.locator("summary")).to_have_text("생애최초 자녀 혼인 조건")
        await expect(canonical.locator("select")).to_have_count(1)
        await expect(canonical.locator("input")).to_have_count(0)
        check("strict child link focuses one missing marital select without repeating DOB/register", await page.evaluate("document.activeElement.closest('[data-child-member-id]')?.dataset.childMemberId === 'child'"))
        await canonical.scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "canonical-child-missing-marital-375.png"))
        await canonical.locator("select").select_option("true")
        await page.get_by_role("dialog").locator(".dialog-close").click()
        saved = json.loads(await page.evaluate(f"localStorage.getItem('{PROFILE_KEY}')"))
        check("scoped child marriage fact saves to the canonical family record", saved["pointsFamily"]["child"]["unmarried"] is True)
        await no_requests(page, router, before, "scoped child fact entry and focus return add no API requests")
        await page.context.close()
        check("all Hangang browser scenarios have no JavaScript exceptions", not errors)
        await browser.close()

    result = {"fixture_data_only": True, "official_source_hash": SOURCE["document_hash"], "backend_parser_version": PARSED["parser_version"], "historical_control_has_synthetic_time_basis": True, "checks_passed": len(checks), "checks": checks, "javascript_errors": errors}
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
