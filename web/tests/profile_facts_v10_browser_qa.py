"""Real Chromium checks for factual profile questions (isolated public fixtures).

CHEONGYAK_QA_BASE points to Vite or a web build. No API keys or user profiles
are read; synthetic facts stay in each fresh browser's local storage.
"""

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

BASE = os.environ.get("CHEONGYAK_QA_BASE", "http://127.0.0.1:5193")
OUT = Path(os.environ.get("CHEONGYAK_QA_OUT", "/tmp/cheongyak-profile-facts-v10-qa"))
PROFILE_KEY = "cheongyak-profile-v5"
NOW = datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc)
SOURCES = ["cheongyak_home", "myhome", "lh", "ih", "sh", "gh"]
HASH = "b5668bcd00f9606b110b21c9703fdce3994f5f690b43299fadeaf9ed2a73c61e"


def rule(kind, value, **extra):
    return {"kind": kind, "value": value, "verification": "official", "evidence_url": "https://example.org/qa-notice.pdf", "evidence_text": "브라우저 회귀 검증용 공개 조건", **extra}


def notice(*, selection=True, parent_only=False):
    rules = [rule(kind, value, supply_type="노부모부양 특별공급") for kind, value in [("parent_age_min", 65), ("parent_same_register", True), ("parent_support_months_min", 36), ("parent_owns_home", False), ("parent_spouse_owns_home", False)]]
    if not parent_only:
        rules += [rule("homeless", True), rule("never_owned_home", True, supply_type="생애최초 특별공급"), rule("private_rank_months", 12, purpose="first_rank", housing_kind="private", rank_rules_complete=True), rule("deposit_min_krw", 3_000_000, purpose="first_rank", housing_kind="private"), rule("monthly_income_max_krw", 5_000_000, supply_type="생애최초 특별공급", min_household_size=3, document_hash=HASH)]
    selections = [rule("selection_method", "points_lottery", supply_type="일반공급", unit_type="084", points_percent=40, lottery_percent=60)] if selection else []
    return {"id": "qa-factual-profile", "title": "회귀 검증용 민영주택", "category": "apt", "source": "cheongyak_home", "sources": ["cheongyak_home"], "provider": "공개 응답 브라우저 검증", "address": "서울특별시 강동구", "region_name": "서울특별시", "region_code": "11", "housing_kind": "private", "housing_kind_evidence": {"verification": "official", "source": "cheongyak_home", "evidence_url": "https://example.org/qa-notice.pdf", "evidence_text": "검증용 주택 구분"}, "qualification_context": {"speculation_zone": False, "subscription_overheated": False, "capital_region": True}, "announcement_date": "2026-09-30", "sort_date": "2026-10-12", "official_url": "https://example.org/qa-notice.pdf", "price_cap_status": "no", "events": [{"kind": "special", "label": "특별공급", "start_date": "2026-10-12", "end_date": "2026-10-12", "audience": None}], "prices": [], "rules": rules, "selection_methods": selections, "rules_complete": True, "offered_supplies": [{"supply_type": supply, "unit_type": "084", "supply_count": 1, "verification": "official"} for supply in (["노부모부양 특별공급"] if parent_only else ["일반공급", "노부모부양 특별공급", "생애최초 특별공급"])], "competitions": [], "competition": {"status": "pending", "complete": False, "unit_types": []}, "updated_at": "2026-10-09T00:55:00Z", "version": 1}


def parent(dob="1950-03-01", **extra):
    return {"id": "qa-parent", "relation": "applicant_parent", "register": "applicant", "dateOfBirth": dob, "ownsHome": False, "previouslyOwnedHome": False, **extra}


def profile(**extra):
    return {"version": 5, "region": "서울특별시", "district": "강동구", "regionCode": "11", "districtCode": "11740", "movedInDate": "2020-01-01", "districtMovedInDate": "2020-01-01", "dateOfBirth": "1990-01-01", "citizenship": "korean", "maritalStatus": "single", "hasSpouse": False, "applicantOnRegister": True, "isHouseholdHead": True, "applicantOwnsHome": False, "applicantPreviouslyOwnedHome": False, "additionalFamilyPresence": True, "householdMembersComplete": None, "pointsFamilyComplete": None, "ownershipFactsKnown": None, "householdMembers": [parent()], "pointsFamily": {"qa-parent": {"registeredSince": "2020-01-01", "spouseOwnsHome": False, "unmarried": None, "overseasExcluded": False, "grandchildrenParentsAbsent": None}}, "factChanges": {"household": {"mode": "known", "date": "2020-01-01"}, "points": {"mode": "known", "date": "2020-01-01"}, "ownership": {"mode": "known", "date": "2020-01-01"}}, "accountType": "comprehensive", "privateRankBaseDate": "2020-01-01", "nationalRankBaseDate": "2021-01-01", "privateDepositKrw": "6000000", "restrictedFromApplying": False, **extra}


class Router:
    def __init__(self, rows):
        self.rows, self.requests, self.errors = rows, [], []

    async def handle(self, route):
        req = route.request
        path = urlsplit(req.url).path
        self.requests.append({"path": path, "url": req.url, "method": req.method, "body": req.post_data})
        if path == "/api/notices":
            result = {"items": self.rows, "total": len(self.rows), "page": 1, "page_size": 100}
        elif path == "/api/coverage":
            result = {"sources": [{"source": source, "status": "ok", "last_attempt_at": "2026-10-09T00:55:00Z", "last_success_at": "2026-10-09T00:55:00Z", "record_count": len(self.rows)} for source in SOURCES]}
        elif path == "/api/collection":
            result = {"job_id": None, "status": "idle", "trigger": None, "started_at": None, "finished_at": None, "message": "검증용 수집 대기"}
        else:
            self.errors.append(path)
            await route.fulfill(status=404, json={"detail": "unexpected fixture endpoint"})
            return
        await route.fulfill(status=200, json=result)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors, input_times = [], [], []

    def check(label, value=True):
        assert value, label
        checks.append(label)
        print(label, flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])

        async def create(width, value, rows=None):
            context = await browser.new_context(viewport={"width": width, "height": 900}, timezone_id="Asia/Seoul")
            if value is not None:
                await context.add_init_script(f"localStorage.setItem({json.dumps(PROFILE_KEY)}, {json.dumps(json.dumps(value))})")
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            # Fix only Date. Keep performance.now and animation frames native
            # so the input latency measurement is a real browser measurement.
            await page.clock.set_fixed_time(NOW)
            router = Router(rows or [notice()])
            await page.route("**/api/**", router.handle)
            await page.route("https://fonts.googleapis.com/**", lambda route: route.fulfill(status=200, body=""))
            await page.goto(BASE, wait_until="domcontentloaded")
            try:
                await expect(page.locator(".notice-card")).to_have_count(1, timeout=15000)
            except Exception:
                print(json.dumps({"errors": errors, "fixture_requests": router.requests, "page_text": (await page.locator("body").inner_text())[:2000]}, ensure_ascii=False), flush=True)
                raise
            await page.get_by_role("button", name="내 조건 설정", exact=True).click()
            return page, router

        async def step(page, name):
            dialog = page.get_by_role("dialog")
            await dialog.locator(".step-progress").get_by_role("button", name=re.compile(name)).click()
            return dialog

        async def geometry(page, label):
            state = await page.evaluate("""() => ({page: document.documentElement.scrollWidth <= window.innerWidth, dialog: document.querySelector('.profile-dialog').scrollWidth <= document.querySelector('.profile-dialog').clientWidth, visible: [...document.querySelectorAll('.step-fields:not([hidden]) input,.step-fields:not([hidden]) select')].filter(el=>el.getClientRects().length).every(el=>el.getBoundingClientRect().right<=window.innerWidth)})""")
            check(label, all(state.values()))

        async def no_requests(page, router, before, label):
            await page.evaluate("""() => {window.dispatchEvent(new Event('focus')); Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'}); document.dispatchEvent(new Event('visibilitychange')); Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'visible'}); document.dispatchEvent(new Event('visibilitychange'));}""")
            await page.wait_for_timeout(450)
            check(label, len(router.requests) == before and not router.errors and all(r["method"] == "GET" and r["body"] is None for r in router.requests))

        for width in [375, 1280]:
            page, router = await create(width, profile())
            before = len(router.requests)
            dialog = await step(page, "세대·주택")
            html = await dialog.inner_text()
            check(f"{width}px valid roster has no completeness gate", "빠진 가족이 없는지" not in html and "빠진 내용이 없나요" not in html and "빠짐없이 추가했나요" not in html)
            await expect(dialog.locator(".household-scope-summary")).to_contain_text("2명")
            dialog = await step(page, "청약통장")
            text = await dialog.locator(".step-fields:not([hidden])").inner_text()
            check(f"{width}px separate bank dates explained", all(t in text for t in ["같은 날짜일 수", "지역·면적별 예치금", "월 납입인정횟수·금액", "순위확인서"]))
            check(f"{width}px points family confirmation removed", "위 가점용 가족 사실에 빠진 내용이 없나요" not in text)
            dialog = await step(page, "소득·자산")
            text = await dialog.locator(".step-fields:not([hidden])").inner_text()
            check(f"{width}px actual income scope is displayed", all(t in text for t in ["2인 가구는 2명", "최근 1년 이상 계속하여", "태아 수만큼", "만19세 이상", "주택 보유 확인 가족 수"]))
            field = dialog.get_by_label("공고 기준 소득 산정 가구원 수 (명)", exact=True)
            await field.fill("2")
            await expect(field).to_have_value("2")
            await geometry(page, f"{width}px income explanations have no overflow")
            await page.screenshot(path=str(OUT / f"income-scope-{width}.png"))
            dialog = await step(page, "특별공급")
            section = dialog.locator('[data-profile-field="parentSupportMemberId"]')
            await expect(section).to_contain_text("기존 입력 재사용")
            await expect(section).to_contain_text("1950-03-01")
            await expect(section).to_contain_text("2020-01-01")
            check(f"{width}px known parent DOB/register/ownership/spouse are reused", await section.locator("input,select,fieldset").count() == 0 and "부모 부양·소유 상태 마지막 변경일" not in await section.inner_text())
            await section.scroll_into_view_if_needed()
            await geometry(page, f"{width}px known parent section has no overflow")
            await page.screenshot(path=str(OUT / f"parent-reuse-{width}.png"))
            await dialog.locator(".dialog-close").click()
            saved = json.loads(await page.evaluate(f"localStorage.getItem('{PROFILE_KEY}')"))
            check(f"{width}px facts autosave with separate bank dates", saved["incomeHouseholdSize"] == "2" and saved["privateRankBaseDate"] == "2020-01-01" and saved["nationalRankBaseDate"] == "2021-01-01")
            await page.get_by_role("button", name="내 조건 설정", exact=True).click()
            dialog = await step(page, "소득·자산")
            await expect(dialog.get_by_label("공고 기준 소득 산정 가구원 수 (명)", exact=True)).to_have_value("2")
            await no_requests(page, router, before, f"{width}px edits/reopen/focus never transmit profile or fetch")
            await page.context.close()

        # Fresh browser starts with no saved profile and asks an actual roster fact.
        page, router = await create(375, None)
        before = len(router.requests)
        dialog = await step(page, "세대·주택")
        await dialog.get_by_role("group", name="본인이 주민등록등본에 등재되어 있나요?", exact=True).get_by_role("button", name="예", exact=True).click()
        await dialog.get_by_role("group", name="현재 법률상 배우자가 있나요?", exact=True).get_by_role("button", name="아니요", exact=True).click()
        await dialog.get_by_role("group", name="본인·배우자 외 등본에 함께 있는 가족이 있나요?", exact=True).get_by_role("button", name="아니요", exact=True).click()
        await expect(dialog.locator(".household-scope-summary")).to_contain_text("1명")
        check("empty isolated profile needs real family presence, no blanket confirmation", "빠진 가족이 없는지" not in await dialog.inner_text())
        await no_requests(page, router, before, "initial roster answers stay in browser")
        await page.context.close()

        # A confirmed 60 < 65 mismatch stops this supply path's remaining questions.
        page, router = await create(375, profile(householdMembers=[parent("1966-01-01", ownsHome=None)], pointsFamily={}, factChanges={}))
        dialog = await step(page, "특별공급")
        section = dialog.locator('[data-profile-field="parentSupportMemberId"]')
        await expect(section).to_contain_text("노부모부양의 추가 질문을 멈췄습니다")
        check("age 60 below 65 stops this parent path including history navigation", await section.locator("input,fieldset,button").count() == 0)
        await section.scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "parent-age-stop-375.png"))
        await page.context.close()

        value = profile(pointsFamily={"qa-parent": {"registeredSince": "", "spouseOwnsHome": False, "overseasExcluded": False}})
        page, router = await create(375, value)
        dialog = await step(page, "특별공급")
        section = dialog.locator('[data-profile-field="parentSupportMemberId"]')
        check("parent section asks only the missing actual support start", await section.locator('input[type="date"]').count() == 1 and await section.locator("fieldset").count() == 0)
        await section.get_by_label("부양 시작일 · 본인과 같은 등본에 연속 등재된 날", exact=True).fill("2020-01-01")
        await dialog.locator(".dialog-close").click()
        saved = json.loads(await page.evaluate(f"localStorage.getItem('{PROFILE_KEY}')"))
        check("new support start writes canonical family points fact", saved["pointsFamily"]["qa-parent"]["registeredSince"] == "2020-01-01" and saved["parentSupportSince"] == "")
        await page.context.close()

        value = profile(householdMembers=[parent(), parent("1966-01-01", id="qa-other-parent", ownsHome=True)], pointsFamily={"qa-parent": {"registeredSince": "2020-01-01", "spouseOwnsHome": False}, "qa-other-parent": {"registeredSince": "2022-01-01", "spouseOwnsHome": True}})
        page, router = await create(375, value)
        dialog = await step(page, "특별공급")
        section = dialog.locator('[data-profile-field="parentSupportMemberId"]')
        choice = section.get_by_role("combobox", name="부양 대상 부모·조부모", exact=True)
        await expect(choice).to_have_value("")
        await choice.select_option("qa-other-parent")
        await expect(section).to_contain_text("1966-01-01")
        await expect(section).to_contain_text("노부모부양의 추가 질문을 멈췄습니다")
        await choice.select_option("qa-parent")
        await expect(section).to_contain_text("1950-03-01")
        await expect(section).to_contain_text("이 부모의 배우자 주택 보유: 아니요")
        check("multiple parents require identity selection and reuse that person's facts", "노부모부양의 추가 질문을 멈췄습니다" not in await section.inner_text())
        await page.context.close()

        # Missing historical facts route to original canonical inputs, even with
        # no selection-method rule that would normally show PointsFields.
        for group, expected_step in [("household", "세대·주택"), ("points", "청약통장")]:
            value = profile(factChanges={}, pointsFamily={"qa-parent": {"registeredSince": "", "spouseOwnsHome": False, "overseasExcluded": False}})
            page, router = await create(375, value, [notice(selection=False, parent_only=True)])
            dialog = await step(page, "특별공급")
            section = dialog.locator('[data-profile-field="parentSupportMemberId"]')
            target_text = "가족 구성·등본 관계 변경일" if group == "household" else "가점 가족 소유 사실 변경일"
            await section.locator("p", has_text=target_text).get_by_role("button", name="기존 입력에서 보완", exact=True).click()
            await expect(dialog.locator(".step-progress button.active")).to_contain_text(expected_step)
            target = dialog.locator(f'[data-fact-group="{group}"]')
            await expect(target).to_be_visible()
            await expect(target.locator("select")).to_be_focused()
            check(f"parent {group} history link switches and focuses original input", await dialog.locator(f'[data-fact-group="{group}"]').count() == 1)
            await geometry(page, f"parent {group} history navigation at 375px has no overflow")
            await page.screenshot(path=str(OUT / f"parent-history-{group}-375.png"))
            await target.locator("select").select_option("known")
            await target.locator('input[type="date"]').fill("2020-01-01")
            await page.context.close()

        # Price explanation is reachable from an actual holding, not a new
        # all-added confirmation. Typing updates are timed to the next paint.
        value = profile(applicantOwnsHome=True, ownershipFacts=[{"id": "qa-property", "ownerMemberId": "applicant", "ownerRelation": "applicant", "propertyKind": "apartment", "areaSqm": "59", "acquiredDate": "2020-01-01", "disposedDate": "", "valueBasis": "annex1_official"}])
        page, router = await create(375, value)
        before = len(router.requests)
        dialog = await step(page, "세대·주택")
        await dialog.locator('[data-profile-field="ownershipPropertyCounts"] input').fill("1")
        await dialog.get_by_text("공식 가격과 취득가격", exact=True).click()
        text = await dialog.locator(".ownership-facts").inner_text()
        check("official value explains actual public price timing and separate purchase price", all(t in text for t in ["공동주택가격", "개별주택가격", "처분일 전에 공시된 가격", "2007년 9월 1일", "매매가·KB시세", "취득 신고가격"]))
        await dialog.get_by_role("combobox", name="주택·권리 종류", exact=True).select_option("presale_right")
        text = await dialog.locator(".ownership-facts").inner_text()
        check("rights price uses original supply contract and excludes options/premium", all(t in text for t in ["원래 공급계약서의 공급가격", "선택품목 가격과 전매 프리미엄", "해당 공급계약일"]))
        await geometry(page, "375px official price explanation has no overflow")
        await page.screenshot(path=str(OUT / "official-price-375.png"))
        dialog = await step(page, "소득·자산")
        amount = dialog.get_by_label("가구 연 소득 합계 (원)", exact=True)
        await amount.fill("")
        await amount.focus()
        await page.evaluate("""() => { window.__qa_input_times=[]; const field=document.activeElement; field.addEventListener('input',()=>{const started=performance.now(); requestAnimationFrame(()=>window.__qa_input_times.push(performance.now()-started));}); }""")
        await amount.press_sequentially("60000000", delay=70)
        await expect(amount).to_have_value("60,000,000")
        await page.wait_for_timeout(450)
        input_times = await page.evaluate("window.__qa_input_times")
        print(json.dumps({"input_to_paint_samples_ms": input_times}), flush=True)
        check("input to next paint stays below 100ms at 375px", len(input_times) == 8 and max(input_times) < 100)
        await no_requests(page, router, before, "ownership/count/price/income edits and focus remain browser-only")
        await page.context.close()
        check("all real Chromium pages have no JavaScript exceptions", not errors)
        await browser.close()
    result = {"base": BASE, "fixture_data_only": True, "checks": checks, "checks_passed": len(checks), "input_to_paint_ms": {"samples": len(input_times), "max": round(max(input_times), 2), "mean": round(sum(input_times) / len(input_times), 2)}, "javascript_errors": errors}
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
