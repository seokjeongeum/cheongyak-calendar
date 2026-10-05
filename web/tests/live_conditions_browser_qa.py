"""Read-only browser/engine checks against saved, real official notice rules.

Run with a Python environment containing Playwright. The only network calls are
public GETs to the locally deployed app. Invented test profiles are isolated in
browser storage; neither profiles nor credentials are printed or sent to an API.
The test deliberately retains partial diagnosis when source coverage is partial.
"""

import asyncio
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from playwright.async_api import async_playwright, expect


ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("CHEONGYAK_QA_BASE", "http://localhost:8080")
NODE = os.environ.get("CHEONGYAK_QA_NODE", "/home/seokj/.cache/ms-playwright-go/1.57.0/node")
NOTICES = {
    "private": "46bcf351-feda-4a60-ab2d-2c29cbd2bc16",
    "national_special": "5faf1ba8-7b13-47a3-9d08-7ae8fd2689a3",
    "national_general": "dabc205e-71fb-4ce9-b0c9-ac75e58f9872",
}
PROFILE = {
    "version": 2, "region": "인천광역시", "regionCode": "28", "district": "계양구", "districtCode": "28245",
    "movedInDate": "2010-01-01", "districtMovedInDate": "2010-01-01", "householdSize": "2",
    "dateOfBirth": "1990-01-01", "isHouseholdHead": True, "hasSpouse": True, "spouseSameRegister": True,
    "familyOnRegister": False, "householdScopeKnown": True, "applicantOwnsHome": False,
    "spouseOwnsHome": False, "ownershipException": False, "applicantPreviouslyOwnedHome": False,
    "spousePreviouslyOwnedHome": False, "accountType": "comprehensive", "accountConversionUnclear": False,
    "privateRankBaseDate": "2026-01-01", "nationalRankBaseDate": "2026-01-01", "privateDepositKrw": "20000000",
    "nationalRecognizedPayments": "9", "restrictedFromApplying": False, "previousWinning": False,
    "specialWinning": False, "maritalStatus": "married", "marriageDate": "2024-01-01", "children": [],
    "hasChildren": False, "pregnant": False,
}
ALLOWED_QUERY = {"start", "end", "page", "page_size", "exclude_public_rental", "application_only", "cap_only", "view"}


def public_documents():
    documents = {}
    for key, identifier in NOTICES.items():
        with urlopen(f"{BASE}/api/notices/{identifier}", timeout=30) as response:
            documents[key] = json.load(response)
    return documents


def engine_comparisons(documents):
    """Use exactly the public JSON, rather than restating rules in a fixture."""
    with tempfile.TemporaryDirectory(prefix="cheongyak-official-qa-") as temporary:
        bundle = str(Path(temporary) / "eligibility.cjs")
        build = (
            f"import {{ build }} from {json.dumps(str(ROOT / 'web/node_modules/esbuild/lib/main.js'))};"
            "await build({stdin:{contents:"
            + json.dumps(f"export {{ evaluateRule, evaluateEligibility, deriveRank, specialDiagnostics }} from {json.dumps(str(ROOT / 'web/src/eligibility.ts'))};")
            + ",resolveDir:" + json.dumps(str(ROOT / "web"))
            + "},bundle:true,platform:'node',format:'cjs',outfile:" + json.dumps(bundle) + "});"
        )
        subprocess.run([NODE, "--input-type=module", "-e", build], cwd=ROOT / "web", check=True, capture_output=True, text=True)
        comparison = r"""
const fs = require('fs');
const {evaluateRule,evaluateEligibility} = require(process.argv[1]);
const {documents,profile} = JSON.parse(fs.readFileSync(0,'utf8'));
function assess(key,kind,predicate=()=>true) {
  const notice=documents[key], rule=notice.rules.find(r=>r.kind===kind && r.verification==='official' && predicate(r));
  if(!rule) throw new Error(`${key}: missing verified ${kind}`);
  const result=evaluateRule(rule,profile,notice);
  return {status:result.status,requirement:rule.value,cutoff:result.criterionDate,source:rule.source,hasEvidence:!!result.evidenceUrl && !!result.evidenceText};
}
process.stdout.write(JSON.stringify({
 privatePeriod:assess('private','private_rank_months',r=>r.purpose==='first_rank'),
 nationalPeriod:assess('national_general','national_rank_months',r=>r.purpose==='first_rank'),
 nationalPayments:assess('national_general','recognized_payments_min',r=>r.purpose==='first_rank'),
 specialPeriod:assess('national_special','national_rank_months',r=>r.supply_type?.startsWith('신혼부부')),
 specialPayments:assess('national_special','recognized_payments_min',r=>r.supply_type?.startsWith('신혼부부')),
 privateOverall:evaluateEligibility(documents.private,profile).status,
 specialOverall:evaluateEligibility(documents.national_special,profile,undefined,'신혼부부(신혼희망타운)').status,
}));
"""
        result = subprocess.run([NODE, "-e", comparison, bundle], input=json.dumps({"documents": documents, "profile": PROFILE}),
                                cwd=ROOT / "web", check=True, capture_output=True, text=True)
        return json.loads(result.stdout)


async def main():
    documents = public_documents()
    checks, measurements, screenshots = [], {}, []

    def check(label, value=True):
        assert value, label
        checks.append(label)

    engine = engine_comparisons(documents)
    check("real private first-rank document requires six months and the test date meets it",
          engine["privatePeriod"]["requirement"] == 6 and engine["privatePeriod"]["status"] == "pass")
    check("real national general document requires twelve months and the same date fails it",
          engine["nationalPeriod"]["requirement"] == 12 and engine["nationalPeriod"]["status"] == "fail")
    check("real national general twelve-payment requirement fails independently of months",
          engine["nationalPayments"]["requirement"] == 12 and engine["nationalPayments"]["status"] == "fail")
    check("real offered national special supply uses six months and six payments",
          all(engine[key]["requirement"] == 6 and engine[key]["status"] == "pass" for key in ["specialPeriod", "specialPayments"]))
    check("each real comparison has a cutoff and original source evidence",
          all(engine[key]["cutoff"] and engine[key]["hasEvidence"] and engine[key]["source"] == "official_document_parser"
              for key in ["privatePeriod", "nationalPeriod", "nationalPayments", "specialPeriod", "specialPayments"]))
    check("partial official coverage is retained without claiming overall eligibility",
          engine["privateOverall"] != "possible" and engine["specialOverall"] != "possible")

    requests, page_errors = [], []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        async def scenario(profile):
            context = await browser.new_context(viewport={"width": 1280, "height": 900}, timezone_id="Asia/Seoul")
            await context.add_init_script("localStorage.setItem('cheongyak-profile-v2', " + json.dumps(json.dumps(profile)) + ")")
            page = await context.new_page()
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on("request", lambda request: requests.append({"url": request.url, "method": request.method, "body": request.post_data})
                    if urlsplit(request.url).path.startswith("/api/") else None)
            await page.goto(BASE, wait_until="networkidle")
            await expect(page.locator("#schedule-panel .notice-card").first).to_be_visible(timeout=30_000)
            return context, page

        context, page = await scenario(PROFILE)
        for key in ["private", "national_special"]:
            notice = documents[key]
            card = page.locator("#schedule-panel .notice-card").filter(has=page.get_by_role("heading", name=notice["title"], exact=True))
            await expect(card).to_have_count(1)
            await card.get_by_role("button", name="유형별 근거", exact=True).click()
            details = card.locator(".qualification-details")
            text = await details.inner_text()
            check(f"{key} real details show populated comparison values, cutoff and reasons",
                  all(label in text for label in ["내 입력", "공고 요구값", "기준일", "판단 이유:", notice["announcement_date"]]))
            check(f"{key} exact six-month official comparison is visibly satisfied",
                  await details.locator(".qualification-reason-body > strong").filter(has_text=re.compile(r"충족 · (민영|국민) 순위 인정기간")).count() > 0
                  and ">= 6개월" in text)
            evidence_links = await details.get_by_role("link", name="원문 근거", exact=True).evaluate_all("links => links.map(link => link.href)")
            check(f"{key} real document evidence is linked to the original public PDF",
                  bool(evidence_links) and all(url.startswith("https://") and ("applyhome.co.kr" in url or "apply.lh.or.kr" in url) for url in evidence_links))
            check(f"{key} renderer does not expose old repetitive internal placeholders",
                  not any(label in text for label in ["조건 범위", "미검증 조건", "미입력 또는 범위 확인 필요", "조건 미공개"]))
            if key == "national_special":
                headings = details.locator(".qualification-reason-body > strong")
                check("real national shared six-month and six-payment requirements render once across offered supplies",
                      await headings.filter(has_text="충족 · 국민 순위 인정기간").count() == 1
                      and await headings.filter(has_text="충족 · 국민주택 납입인정횟수").count() == 1)
                accepted_regions = details.locator(".qualification-reason-body").filter(has_text="충족 · 신청 가능한 거주지역")
                check("real accepted residence alternative explains acceptance without other-region failure language",
                      await accepted_regions.count() == 1
                      and "조건이 다릅니다" not in await accepted_regions.locator(".qualification-reason-detail").inner_text())
            for width, name in [(1280, "desktop"), (375, "mobile")]:
                await page.set_viewport_size({"width": width, "height": 900 if width == 1280 else 812})
                await page.wait_for_timeout(100)
                metrics = await details.locator(".qualification-reason-body").evaluate_all("""bodies => bodies.map(body => {
                  const b=body.getBoundingClientRect(), r=body.parentElement.getBoundingClientRect(),
                        i=body.parentElement.querySelector('.qualification-icon').getBoundingClientRect();
                  return {bodyWidth:b.width,iconWidth:i.width,bodyRight:b.right,rowRight:r.right};
                })""")
                measurements[f"{key}_{name}"] = {"rows": len(metrics), "minimumBodyWidth": min(row["bodyWidth"] for row in metrics)}
                check(f"{key} {name} has readable evidence body and fixed-width icon",
                      bool(metrics) and all(row["bodyWidth"] >= (350 if width == 1280 else 200) and 0 < row["iconWidth"] <= 20
                                            and row["bodyRight"] <= row["rowRight"] + 2 for row in metrics))
                check(f"{key} {name} long real evidence has no horizontal page overflow",
                      await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
                await details.locator(".qualification-reason-body").first.scroll_into_view_if_needed()
                path = f"/tmp/cheongyak-live-{key}-{name}.png"
                await page.screenshot(path=path)
                screenshots.append(path)
            await page.set_viewport_size({"width": 1280, "height": 900})
        await context.close()

        failed = {**PROFILE, "privateRankBaseDate": "2026-09-01", "privateDepositKrw": "1", "nationalRecognizedPayments": "1"}
        context, page = await scenario(failed)
        for key in ["private", "national_special"]:
            card = page.locator("#schedule-panel .notice-card").filter(has=page.get_by_role("heading", name=documents[key]["title"], exact=True))
            await card.get_by_role("button", name="유형별 근거", exact=True).click()
            check(f"{key} fact mismatch appears as a concrete official condition failure",
                  await card.locator(".qualification-details .qualification-reason-body > strong").filter(has_text="불일치").count() > 0)
        await context.close()

        missing = {**PROFILE, "privateRankBaseDate": "", "nationalRecognizedPayments": ""}
        context, page = await scenario(missing)
        for key, field, button_label in [("private", "privateRankBaseDate", "민영 순위 인정기간 입력하기"),
                                          ("national_special", "nationalRecognizedPayments", "국민주택 납입인정횟수 입력하기")]:
            card = page.locator("#schedule-panel .notice-card").filter(has=page.get_by_role("heading", name=documents[key]["title"], exact=True))
            await card.get_by_role("button", name="유형별 근거", exact=True).click()
            before = len(requests)
            await card.locator(".qualification-details").get_by_role("button", name=button_label, exact=True).first.click()
            dialog = page.get_by_role("dialog")
            target = dialog.locator(f"[data-profile-field='{field}'] input")
            await expect(target).to_be_visible()
            await expect(target).to_be_focused()
            check(f"{key} missing fact links directly to the correct profile question")
            check(f"{key} opening the missing fact question sends no API request", len(requests) == before)
            await dialog.get_by_role("button", name="닫기", exact=True).first.click()
            check(f"{key} expanded reasons remain open after closing the linked question",
                  await card.get_by_role("button", name="근거 접기", exact=True).count() == 1)
        await context.close()
        await browser.close()

    check("all observed public API requests are GETs without private request bodies",
          bool(requests) and all(request["method"] == "GET" and request["body"] is None for request in requests))
    check("API query parameters contain only public period/filter/pagination fields",
          all(set(parse_qs(urlsplit(request["url"]).query)) <= ALLOWED_QUERY for request in requests))
    check("real evidence rendering produces no JavaScript exception", not page_errors)
    print(json.dumps({"passed": len(checks), "checks": checks, "measurements": measurements,
                      "screenshots": screenshots, "official_comparisons": engine,
                      "public_get_count": len(requests)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
