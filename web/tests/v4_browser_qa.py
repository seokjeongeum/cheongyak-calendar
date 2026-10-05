"""Isolated browser QA for v4 household facts and retained unavailable rows.

Public notice responses are controlled; real notices are fetched by read-only
GET for final source/UI verification. No shared profile or credentials are read.
"""

import asyncio
import copy
import importlib.util
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("v3_harness", ROOT / "web/tests/v3_browser_qa.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)
qa.PROFILE_KEY = "cheongyak-profile-v4"
NOW_TEXT = "2026-10-04T03:00:00Z"
CUTOFFS = ["2026-09-18", "2026-09-23", "2026-09-30", "2026-10-01", "2026-10-02"]
CONFIRMATIONS = [{"criterionDate": day, "unchanged": True} for day in CUTOFFS]
PROFILE = {
    **qa.PROFILE, "version": 4, "applicantOnRegister": True,
    "militaryCurrentlyServing": False, "militaryFactsAsOfDate": "2026-10-04",
    "militaryFactsHistoryConfirmations": CONFIRMATIONS,
    "householdMembers": [], "householdMembersComplete": True,
    "householdSnapshotDate": "2026-10-04", "householdCompositionUnchanged": True,
    "householdHistoryConfirmations": CONFIRMATIONS, "citizenship": "korean",
    "overseasContinuousDays": "0", "overseasFactsAsOfDate": "2026-10-04",
    "overseasFactsHistoryConfirmations": CONFIRMATIONS,
    "overseasOnlyApplicantForLivelihood": False,
    "applicationRestrictionFacts": {
        scope: {"ineligibleRestrictionActive": False, "resaleRestrictionActive": False,
                "rewinningRestrictionActive": False, "asOfDate": "2026-10-04",
                "historyConfirmations": CONFIRMATIONS}
        for scope in ["applicant", "household", "applicant_spouse"]
    },
    "projectApplicationHistory": {
        project: {"winning": False, "contract": False, "additionalResident": False,
                  "winningScope": "applicant", "contractScope": "applicant",
                  "asOfDate": "2026-10-04", "historyConfirmations": CONFIRMATIONS}
        for project in ["2026000323", "2021000515"]
    },
}


def current_closed():
    row = qa.result("qa-v4-closed", partial=False)
    row["title"] = "검증 전체 기타지역 기회 종료"
    row["events"] = [{"kind": "first_priority", "label": "1순위", "audience": "기타지역",
                      "start_date": "2026-10-09", "end_date": "2026-10-09"}]
    row["application_end_date"] = "2026-10-09"
    row["prices"] = row["prices"][:2]
    row["rules"] += qa.rank_rules()
    row["competition"].update(status="ok", complete=True, proof_invalidated=False,
                              last_success_at=NOW_TEXT, last_attempt_at=NOW_TEXT)
    for competition in row["competitions"]:
        competition["observed_at"] = NOW_TEXT
    return row


def region_ineligible():
    row = qa.base_notice("qa-v4-unranked", "검증 무순위 신청 지역")
    row.update(category="unsold", application_method="unranked_after",
               announcement_date="2026-10-01", housing_kind="private")
    row["application_method_evidence"] = {"verification": "official",
                                         "evidence_url": row["official_url"],
                                         "evidence_text": "무순위 사후접수"}
    row["rank_applicability"] = {"status": "not_applicable", "account_required": False,
                                 "verification": "official", "reason": "무순위 사후접수"}
    row["events"] = [{"kind": "general", "label": "무순위 접수", "start_date": "2026-10-08",
                      "end_date": "2026-10-08"}]
    row["rules"] = [
        qa.rule("age_min", 19, supply_type="일반공급", criterion_date="2026-10-01"),
        qa.rule("residence_region", region_code="36", region_name="세종특별자치시",
                supply_type="일반공급", criterion_date="2026-10-01"),
        qa.rule("homeless", True, supply_type="일반공급", criterion_date="2026-10-01"),
        qa.rule("condition_coverage", effect="metadata", status="complete",
                offered_supply_types=["일반공급"],
                scopes=[{"supply_type": "일반공급", "complete": True}]),
    ]
    return row


async def main():
    checks, snapshots, errors = [], {}, []

    def check(label, condition=True):
        assert condition, label
        checks.append(label)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        schedule = [qa.jamsil(), qa.supplies(), current_closed(), region_ineligible()]
        router = qa.Router(schedule=schedule, results=[qa.result()])
        context, page = await qa.create_page(browser, router, profile=PROFILE)
        page.on("pageerror", lambda error: errors.append(str(error)))
        check("all personally unavailable notices stay in the schedule",
              await page.locator("#schedule-panel .notice-card").count() == 4)
        closed = qa.card(page, current_closed()["title"])
        await expect(closed).to_have_class(re.compile("notice-unavailable"))
        await expect(closed).to_contain_text("내 조건으로 신청 불가")
        check("fully closed notice is retained with explicit unavailable presentation")
        denied = qa.card(page, region_ineligible()["title"])
        await expect(denied).to_have_class(re.compile("notice-unavailable"))
        await expect(denied).to_contain_text("거주지역")
        check("unranked no-rank status never bypasses its actual region criterion")
        check("price rows and original links remain usable on unavailable cards",
              await closed.locator(".price-row").count() == 2 and
              await closed.locator("a.official-link[href]").count() == 1)
        partial = qa.card(page, qa.supplies()["title"])
        check("a multichild mismatch does not mute a possible general supply card",
              "notice-unavailable" not in (await partial.get_attribute("class") or ""))
        await expect(partial.locator(".qualification-supply-brief").filter(
            has=page.get_by_text("다자녀 특별공급", exact=True)
        )).to_have_class(re.compile("qualification-unavailable"))
        check("only the failed special supply gets unavailable presentation")
        day = page.locator(".calendar-day").filter(has=page.locator("span").get_by_text("9", exact=True))
        await expect(day).to_have_class(re.compile("unavailable-dot"))
        await expect(day).to_have_attribute("aria-label", re.compile("接收|접수"))
        check("a fully unavailable future reception date remains selectable with a muted dot")
        await day.click()
        await expect(page.locator("#schedule-panel .notice-card")).to_have_count(1)
        await expect(page.locator("#schedule-panel .notice-card")).to_contain_text(current_closed()["title"])
        check("selecting an unavailable calendar date retains its notice")
        await page.locator(".calendar-card").get_by_role("button", name="오늘", exact=True).click()
        await page.wait_for_load_state("networkidle")

        before = len(router.requests)
        await qa.focus_cycle(page)
        await page.clock.fast_forward(61_000)
        await qa.focus_cycle(page)
        check("focus transitions alone do not query data", len(router.requests) == before)
        await page.get_by_role("tab", name="경쟁률·청약결과", exact=True).click()
        panel = page.locator("#results-panel")
        await expect(panel.locator(".notice-card")).to_have_count(1)
        result_card = panel.locator(".notice-card")
        await expect(result_card.locator(".competition-row")).to_have_count(4)
        await expect(result_card.locator(".competition-row-unavailable")).to_have_count(2)
        await expect(panel.locator(".results-explanation")).to_contain_text("1건")
        await expect(panel.locator(".results-explanation")).to_contain_text("4행")
        check("historical closed unit rows stay visible and result counters include them")
        check("open 1.10 result and every price are retained",
              "1.10" in await result_card.inner_text() and
              await result_card.locator(".price-row").count() == 7)
        check("obsolete hide and restore controls are absent",
              await panel.get_by_text("기타지역 배정 기회가 끝난 주택형 숨김", exact=True).count() == 0 and
              await page.get_by_text("마감으로 숨긴 공고 보기", exact=True).count() == 0)
        layout = await qa.overflow(page, "#results-panel")
        check("375px results have no horizontal overflow", layout["scroll"] <= layout["width"] + 2)
        await page.screenshot(path=str(ROOT / "docs/screenshots/v4-results-mobile.png"), full_page=True)
        await context.close()

        # Legacy facts remain facts; a former legal-scope answer is no roster.
        qa.V2_KEY = "cheongyak-profile-v3"
        former = {**qa.PROFILE, "version": 3, "householdScopeKnown": True,
                  "familyOnRegister": False, "householdSize": "3"}
        family_router = qa.Router(schedule=[region_ineligible()], results=[])
        context, page = await qa.create_page(browser, family_router, profile=former, legacy=True)
        migrated = await qa.stored(page)
        check("v3 migrates without losing residence, money or bank facts",
              migrated["version"] == 4 and all(migrated[key] == former[key]
              for key in ["regionCode", "districtCode", "privateRankBaseDate", "privateDepositKrw", "annualIncomeKrw"]))
        check("former household self-confirmation never invents a complete family roster",
              migrated["householdMembers"] == [] and migrated["householdMembersComplete"] is None
              and migrated["applicantOnRegister"] is None)
        await page.get_by_role("button", name="내 조건 설정", exact=True).click()
        dialog = page.get_by_role("dialog")
        await dialog.get_by_role("button", name=re.compile("세대·주택")).click()
        check("opaque scope question and manually entered legal household count are removed",
              "본인·배우자 등본의 가족 관계와 확인 대상 범위를 확인했나요?" not in await dialog.inner_text()
              and await dialog.locator('[data-profile-field="householdSize"]').count() == 0)
        async def fact(label, answer):
            await dialog.get_by_text(label, exact=True).locator("..").get_by_role("button", name=answer, exact=True).click()
        await fact("본인이 주민등록등본에 등재되어 있나요?", "예")
        await fact("현재 법률상 배우자가 있나요?", "예")
        await fact("배우자가 본인과 같은 주민등록등본에 있나요?", "아니요")
        before_edits = len(family_router.requests)
        await dialog.get_by_role("button", name="가족 추가", exact=True).click()
        member = dialog.locator(".household-member").first
        await member.get_by_label("본인과의 가족 관계", exact=True).select_option("spouse_child")
        await member.get_by_label("어느 주민등록등본에 함께 있나요?", exact=True).select_option("spouse")
        await expect(member.locator(".household-member-reason")).to_contain_text("확인 대상에서 제외")
        check("a spouse child on a separate spouse register is excluded with a readable reason")
        await member.get_by_label("어느 주민등록등본에 함께 있나요?", exact=True).select_option("applicant")
        await expect(member.locator(".household-member-reason")).to_contain_text("주택 보유 함께 확인")
        check("the same spouse child on the applicant register is included")
        await dialog.get_by_role("button", name="가족 추가", exact=True).click()
        sibling = dialog.locator(".household-member").nth(1)
        await sibling.get_by_label("본인과의 가족 관계", exact=True).select_option("sibling")
        await sibling.get_by_label("어느 주민등록등본에 함께 있나요?", exact=True).select_option("applicant")
        await expect(sibling.locator(".household-member-reason")).to_contain_text("확인 대상에서 제외")
        check("a sibling on the applicant register is excluded")
        await expect(dialog.locator(".household-fields")).to_contain_text("주소·등본이 달라도")
        check("a separate-address legal spouse remains included")
        current = await qa.stored(page)
        check("family edits clear old cutoff confirmations instead of certifying historical composition",
              current["householdHistoryConfirmations"] == [] and current["householdMembersComplete"] is None)
        layout = await qa.overflow(page, ".profile-dialog")
        check("family questions fit 375px without horizontal overflow", layout["scroll"] <= layout["width"] + 2)
        check("family edits never send API requests", len(family_router.requests) == before_edits)
        await dialog.screenshot(path=str(ROOT / "docs/screenshots/v4-family-mobile.png"))
        await context.close()

        paginated = qa.Router(results=[qa.result(f"closed-{i:03}", partial=False) for i in range(100)] +
                                      [qa.result(f"remaining-{i:03}") for i in range(25)])
        context, page = await qa.create_page(browser, paginated, profile=PROFILE)
        await page.get_by_role("tab", name="경쟁률·청약결과", exact=True).click()
        panel = page.locator("#results-panel")
        await expect(panel.locator(".notice-card")).to_have_count(20)
        await expect(panel.locator(".notice-card").first).to_contain_text("closed-000")
        await expect(panel.locator(".results-explanation")).to_contain_text("125건")
        await expect(panel.locator(".results-explanation")).to_contain_text("500행")
        check("an entirely unavailable first API page is displayed rather than skipped")
        await panel.get_by_role("button", name=re.compile("결과 더 보기")).click()
        await expect(panel.locator(".notice-card")).to_have_count(40)
        check("load more and visible totals include unavailable notices")
        await context.close()

        api = await p.request.new_context(base_url=qa.BASE)
        ids = ["0f434f69-2838-4e6f-a186-445940910a13", "ede290da-b467-42b9-a944-eae51d0fa705",
               "1706ac8d-4c6a-4472-88fa-9a43dbdbf8da", "0458dfae-6269-4b94-b1fa-9e7034e805ee",
               "342f3968-02fd-4d2a-aa79-71baecedf9c4", "46bcf351-feda-4a60-ab2d-2c29cbd2bc16"]
        real = [await (await api.get("/api/notices/" + ident)).json() for ident in ids]
        methods = [n.get("application_method") for n in real[:3]]
        check("real notices distinguish two post-reception cases and cancellation resupply",
              methods == ["unranked_after", "unranked_after", "cancelled_resupply"])
        check("real unranked eligibility rules use the new reception notice dates",
              all(n.get("application_method_evidence", {}).get("criterion_date") == day
                  for n, day in zip(real[:3], ["2026-10-01", "2026-10-01", "2026-09-23"])))
        live_router = qa.Router(schedule=real[:4] + [real[5]], results=[real[4]])
        # Real records may have been collected after the controlled 03:00 UTC
        # fixture clock. Use the current clock for these public snapshots.
        qa.NOW = datetime.now(timezone.utc)
        context, page = await qa.create_page(browser, live_router, profile=PROFILE)
        for notice in real[:3]:
            row = qa.card(page, notice["title"])
            await expect(row).to_have_class(re.compile("notice-unavailable"))
            check("actual outside-region unranked case remains with its official eligibility failure")
            check("actual no-rank card does not ask an apartment rank-base date",
                  "순위기산일" not in await row.inner_text())
        jamsil_card = qa.card(page, real[3]["title"])
        await expect(jamsil_card).to_contain_text("9억 3,756만원")
        await expect(jamsil_card).to_contain_text("청약신청금 300만원")
        check("Jamsil sale price and separate application fee survive v4")
        await expect(qa.card(page, real[5]["title"])).to_have_class(re.compile("notice-unavailable"))
        check("the actual Dongin notice remains gray with its outside-region reason")
        await page.screenshot(path=str(ROOT / "docs/screenshots/v4-live-schedule-mobile.png"), full_page=True)
        await page.get_by_role("tab", name="경쟁률·청약결과", exact=True).click()
        gw = qa.card(page, real[4]["title"])
        await expect(gw.locator(".competition-row")).to_have_count(28)
        await expect(gw.locator(".competition-row-unavailable")).to_have_count(4)
        await expect(gw.locator(".price-row")).to_have_count(7)
        check("actual Gwangmyeong shows all 28 official rows, four gray 59A rows and seven prices")
        await expect(gw).to_contain_text("1.10")
        check("actual 59B result at 1.10 stays readable")
        layout = await qa.overflow(page, "#results-panel")
        check("actual 375px result evidence has no horizontal overflow", layout["scroll"] <= layout["width"] + 2)
        row_style = await gw.locator(".competition-row-unavailable").first.evaluate(
            "el => ({opacity:getComputedStyle(el).opacity,events:getComputedStyle(el).pointerEvents})")
        check("gray rows remain readable and interactive", row_style["opacity"] == "1" and row_style["events"] != "none")
        await gw.locator(".competition-row-unavailable").first.screenshot(
            path=str(ROOT / "docs/screenshots/v4-live-59a-mobile.png"), style=".site-header{visibility:hidden!important}")
        await page.set_viewport_size({"width": 1440, "height": 1100})
        await page.screenshot(path=str(ROOT / "docs/screenshots/v4-live-results-desktop.png"), full_page=True)
        snapshots["live_notices"] = [{"title": n["title"], "version": n["version"],
                                      "application_method": n.get("application_method"),
                                      "verified_criteria": len([r for r in n["rules"] if r.get("effect") != "metadata" and r.get("verification") == "official"])}
                                     for n in real]
        await context.close()
        await api.dispose()

        allowed = {"start", "end", "page", "page_size", "exclude_public_rental", "application_only", "cap_only", "view"}
        from urllib.parse import parse_qs, urlsplit
        for current in [router, family_router, paginated, live_router]:
            check("no browser error or unexpected API endpoint", not current.errors)
            check("all browser API calls are public GET with no profile in query or body",
                  all(request["method"] == "GET" and request["body"] is None and
                      set(parse_qs(urlsplit(request["url"]).query)).issubset(allowed)
                      for request in current.requests))
        check("no JavaScript errors", not errors)
        await browser.close()
    result = {"passed": len(checks), "checks": checks, "snapshots": snapshots}
    (ROOT / "docs/qa/v4-browser-2026-10-04.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"passed": len(checks), "snapshots": snapshots}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
