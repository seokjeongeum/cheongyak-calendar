"""Isolated v6 UI, privacy, persistence and 40-notice responsiveness checks.

The public API is snapshotted before testing and served through browser routes.
Only fictional profiles are placed in a fresh context. Reports never include
profile values, request bodies, or actual user browser storage.
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
import json
import math
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

from playwright.async_api import async_playwright, expect


ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 10, 5)
STORAGE_KEY = "cheongyak-profile-v5"
GROUPS = "household household_head domestic_residence restrictions overseas military income_tax income assets bank_private bank_national citizenship employment parent_support marital children provider_employee ownership".split()
PROFILE = {
    "version": 5, "region": "경기도", "regionCode": "41", "district": "화성시", "districtCode": "41590",
    "movedInDate": "2010-01-01", "districtMovedInDate": "2010-01-01", "cityMovedInDate": "2010-01-01",
    "dateOfBirth": "1990-01-01", "militaryCurrentlyServing": False, "currentlyDomesticResident": True,
    "providerEmployeeOrRelatedFamily": False, "applicantOnRegister": True, "hasSpouse": False,
    "maritalStatus": "single", "householdMembers": [], "householdMembersComplete": True,
    "ownershipFactsKnown": True, "ownershipFacts": [], "applicantOwnsHome": False, "applicantPreviouslyOwnedHome": False,
    "isHouseholdHead": True, "citizenship": "korean", "hasChildren": False, "children": [], "pregnant": False,
    "accountType": "comprehensive", "privateRankBaseDate": "2010-01-01", "nationalRankBaseDate": "2010-01-01",
    "privateDepositKrw": "6000000", "privateDepositMaintained": True, "nationalRecognizedPayments": "12",
    "factChanges": {group: {"mode": "never_changed", "date": ""} for group in GROUPS},
    "applicationHistoryPresence": False, "applicationHistoryComplete": True, "applicationHistoryPeople": ["applicant"],
    "applicationHistoryEvents": [], "overseasContinuousDays": "0", "annualIncomeKrw": "", "assetsKrw": "",
}
INSTRUMENTATION = """(() => {
  window.__qaMetrics = { events: [], workers: [], posts: [], longTasks: [] };
  for (const event of ['click','input','change']) document.addEventListener(event, () => {
    const started = performance.now();
    const marker = {kind:event,started,paint:null}; window.__qaMetrics.events.push(marker);
    requestAnimationFrame(() => requestAnimationFrame(() => { marker.paint=performance.now(); }));
  }, true);
  const OriginalWorker = window.Worker;
  window.Worker = class extends OriginalWorker {
    constructor(...args) { super(...args); this.addEventListener('message', (event) => {
      if (window.__qaDelayWorker && !event.__qaReplayed) {
        event.stopImmediatePropagation();
        setTimeout(() => { const replay=new MessageEvent('message',{data:event.data}); replay.__qaReplayed=true; this.dispatchEvent(replay); },window.__qaDelayWorker);
        return;
      }
      const data=event.data;
      window.__qaMetrics.workers.push({at:performance.now(),revision:data.revision,elapsedMs:data.elapsedMs,error:!!data.error});
    }); }
    postMessage(data,...args) {
      window.__qaMetrics.posts.push({at:performance.now(),revision:data.revision});
      return super.postMessage(data,...args);
    }
  };
  new PerformanceObserver((entries) => {
    for (const task of entries.getEntries()) window.__qaMetrics.longTasks.push({start:task.startTime,duration:task.duration});
  }).observe({type:'longtask',buffered:true});
})();"""


def read_json(url):
    with urlopen(url, timeout=30) as response:
        return json.load(response)


def snapshot(source):
    def notices(start, end, view="schedule"):
        params = {"start":str(start),"end":str(end),"page_size":100,"application_only":"true","exclude_public_rental":"true"}
        if view == "results": params["view"] = "results"
        first = read_json(source + "/api/notices?" + urlencode(params))
        rows = list(first["items"])
        for page in range(2, math.ceil(first["total"] / first["page_size"]) + 1):
            rows.extend(read_json(source + "/api/notices?" + urlencode({**params,"page":page}))["items"])
        return rows
    end = date(TODAY.year, TODAY.month + 2, calendar.monthrange(TODAY.year, TODAY.month + 2)[1])
    return {"schedule":notices(TODAY,end),"results":notices(TODAY-timedelta(days=89),TODAY,"results"),"coverage":read_json(source+"/api/coverage")}


async def route_public(route, public):
    url = urlsplit(route.request.url)
    if url.path == "/api/coverage": body = public["coverage"]
    elif url.path == "/api/health": body = {"status":"ok"}
    elif url.path == "/api/notices":
        query = parse_qs(url.query)
        rows = public["results"] if query.get("view") == ["results"] else public["schedule"]
        start, end = query.get("start",[str(TODAY)])[0], query.get("end",["2026-12-31"])[0]
        if query.get("view") != ["results"]:
            rows = [n for n in rows if any(e["kind"] not in {"announcement","contract","result","winner"} and e["start_date"] <= end and (e.get("end_date") or e["start_date"]) >= start for e in n["events"])]
        if query.get("cap_only") == ["true"]: rows = [n for n in rows if n["price_cap_status"] == "yes"]
        offset, size = int(query.get("page",[1])[0]), int(query.get("page_size",[100])[0])
        body = {"items":rows[(offset-1)*size:offset*size],"total":len(rows),"page":offset,"page_size":size}
    else:
        ident = url.path.removeprefix("/api/notices/")
        body = next((n for n in public["schedule"] + public["results"] if n["id"] == ident), {})
    await route.fulfill(status=200,content_type="application/json",body=json.dumps(body,ensure_ascii=False))


async def settled(page):
    await page.wait_for_function("window.__qaMetrics.workers.length>0 && !document.querySelector('[data-evaluation-pending=true]') && [...document.querySelectorAll('.notice-card')].every(card=>card.dataset.evaluationReady==='true') && Number(document.querySelector('.app-shell')?.dataset.evaluationRevision)===window.__qaMetrics.posts.at(-1)?.revision",timeout=30000)
    await page.evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")


async def interaction(page, action, kind="click"):
    before = await page.evaluate("window.__qaMetrics.events.length")
    await action()
    await page.wait_for_function("([index,kind])=>window.__qaMetrics.events.slice(index).some(e=>e.kind===kind&&e.paint!==null)",arg=[before,kind])
    return await page.evaluate("([index,kind])=>{const e=window.__qaMetrics.events.slice(index).find(e=>e.kind===kind&&e.paint!==null);return e.paint-e.started}",[before,kind])


def stats(values):
    ordered = sorted(values)
    return {"samples":len(values),"medianMs":round(ordered[len(ordered)//2],1),"p95Ms":round(ordered[math.ceil(.95*len(ordered))-1],1),"maximumMs":round(max(ordered),1)}


async def cohort(browser, base, public, *, width, slowdown, functional, strict):
    context = await browser.new_context(viewport={"width":width,"height":900},timezone_id="Asia/Seoul")
    # Seed once. Reload must read the newly saved draft rather than re-seeding it.
    await context.add_init_script("if (!sessionStorage.getItem('v6-qa-seeded')) {localStorage.setItem('"+STORAGE_KEY+"',"+json.dumps(json.dumps(PROFILE))+");sessionStorage.setItem('v6-qa-seeded','yes')}")
    await context.add_init_script(INSTRUMENTATION)
    await context.route("**/api/**",lambda route:route_public(route,public))
    page = await context.new_page()
    requests, errors, checks = [], [], []
    results_snapshot = None
    page.on("pageerror",lambda e: errors.append(type(e).__name__))
    page.on("request",lambda r: requests.append({"path":urlsplit(r.url).path,"queryNames":sorted(parse_qs(urlsplit(r.url).query)),"method":r.method,"body":bool(r.post_data)}) if "/api/" in r.url else None)
    cdp = await context.new_cdp_session(page)
    await cdp.send("Emulation.setCPUThrottlingRate",{"rate":slowdown})
    await page.goto(base,wait_until="domcontentloaded")
    await settled(page)
    panel = page.locator("#schedule-panel")
    await expect(panel.locator(".notice-card")).to_have_count(len(public["schedule"]),timeout=30000)
    await settled(page)
    initial = {"cards":await panel.locator(".notice-card").count(),"prices":await panel.locator(".price-row").count(),"competitionRows":await panel.locator(".competition-row").count(),"grayCards":await panel.locator(".notice-unavailable").count(),"calendarDays":await page.locator(".calendar-day.has-events").count()}
    def check(label, condition=True):
        assert condition, label
        checks.append(label)
    check("Every public active notice remains visible, including gray mismatches")
    check("All public price rows remain available without opening notices",initial["prices"]==sum(len(n["prices"]) for n in public["schedule"]))
    check("No horizontal overflow",await page.evaluate("document.documentElement.scrollWidth<=innerWidth+2"))
    timings = {"openClose":[],"step":[],"input":[]}
    start_long = await page.evaluate("performance.now()")
    posts_before = await page.evaluate("window.__qaMetrics.posts.length")
    for _ in range(8):
        timings["openClose"].append(await interaction(page,lambda:page.get_by_role("button",name="내 조건 설정",exact=True).click()))
        timings["openClose"].append(await interaction(page,lambda:page.get_by_role("dialog").locator(".dialog-close").click()))
    check("Opening and closing unchanged conditions does not recalculate notices",await page.evaluate("window.__qaMetrics.posts.length")==posts_before)
    await page.get_by_role("button",name="내 조건 설정",exact=True).click()
    dialog = page.get_by_role("dialog")
    for name in ["세대·주택","청약통장","소득·자산","특별공급","거주지","청약통장","소득·자산"]:
        timings["step"].append(await interaction(page,lambda n=name:dialog.locator(".step-progress").get_by_role("button",name=re.compile(n)).click()))
    check("Step changes do not recalculate notices",await page.evaluate("window.__qaMetrics.posts.length")==posts_before)
    money = dialog.locator('[data-profile-field="annualIncomeKrw"] input')
    await money.fill("")
    await money.focus()
    for digit in "1234567890":
        timings["input"].append(await interaction(page,lambda d=digit:page.keyboard.insert_text(d),"input"))
    await expect(money).to_have_value("1,234,567,890")
    last_input = await page.evaluate("window.__qaMetrics.events.filter(e=>e.kind==='input').at(-1).started")
    await page.wait_for_function("started=>window.__qaMetrics.posts.some(p=>p.at>=started)",arg=last_input,timeout=30000)
    await settled(page)
    latest_ms = await page.evaluate("started=>window.__qaMetrics.workers.at(-1).at-started",last_input)
    check("Money values show commas")
    workers = await page.evaluate("window.__qaMetrics.workers.map(w=>({elapsedMs:w.elapsedMs,error:w.error}))")
    measured = {key:stats(values) for key,values in timings.items()}
    all_timings = [n for rows in timings.values() for n in rows]
    measured["overall"] = stats(all_timings)
    measured["latestResultAfterTypingMs"] = round(latest_ms,1)
    measured["workerExecutionMs"] = [round(w["elapsedMs"],1) for w in workers if isinstance(w.get("elapsedMs"),(int,float))]
    measured["mainThreadLongTasks"] = await page.evaluate("start=>window.__qaMetrics.longTasks.filter(t=>t.start>=start).map(t=>({durationMs:Math.round(t.duration),startMs:Math.round(t.start-start)}))",start_long)
    if strict:
        if measured["overall"]["p95Ms"]>100 or latest_ms>1000:
            print(json.dumps({"performanceFailure":{"width":width,"cpuSlowdown":slowdown,"measurements":measured,"eventTimings":timings}},ensure_ascii=False),flush=True)
        check("Input/click paint p95 is at most 100ms",measured["overall"]["p95Ms"]<=100)
        check("Latest full result follows final typing within 1 second",latest_ms<=1000)
    if functional:
        await dialog.locator(".step-progress").get_by_role("button",name=re.compile("거주지")).click()
        for name in ["거주지","세대·주택","청약통장","소득·자산","특별공급"]:
            await dialog.locator(".step-progress").get_by_role("button",name=re.compile(name)).click()
            text = await dialog.inner_text()
            check(name+": removed repeated date/address/account questions stay absent",all(term not in text for term in ["확인한 기준일","예정 계약일","공고 기준일에 다른 지역","통장 전환·미성년","최초 청약에서 당첨","이 사업의 주택 공급계약","이 사업에서 예비입주자"]))
            if name == "청약통장":
                check("Common history presence is asked once",await dialog.locator('[data-profile-field="applicationHistoryPresence"]').count()==1)
            if name == "특별공급":
                check("Unmarried profile is preserved",await dialog.locator('[data-profile-field="maritalStatus"] select').first.input_value()=="single")
                check("Unmarried profile does not ask marriage duration",await dialog.locator('[data-profile-field="marriageDate"] input').count()==0)
        await dialog.locator(".step-progress").get_by_role("button",name=re.compile("소득·자산")).click()
        # Browser-side synchronous events guarantee close precedes 300ms debounce.
        await page.evaluate("""() => {
          const input=document.querySelector('[data-profile-field="annualIncomeKrw"] input');
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'987654321');
          input.dispatchEvent(new Event('input',{bubbles:true}));
        }""")
        await dialog.locator(".dialog-close").click()
        saved = await page.evaluate("JSON.parse(localStorage.getItem('cheongyak-profile-v5'))")
        check("Close flushes the latest draft before debounce",saved["annualIncomeKrw"]=="987654321")
        await settled(page)
        before_requests = len(requests)
        for _ in range(3):
            await page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('blur'));Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('focus'))")
        await page.wait_for_timeout(250)
        check("Focus changes alone issue no API request",len(requests)==before_requests)
        await page.reload(wait_until="domcontentloaded")
        await settled(page)
        await page.get_by_role("button",name="내 조건 설정",exact=True).click()
        dialog = page.get_by_role("dialog")
        await dialog.locator(".step-progress").get_by_role("button",name=re.compile("소득·자산")).click()
        check("Reload preserves the last draft",await dialog.locator('[data-profile-field="annualIncomeKrw"] input').input_value()=="987,654,321")
        pagehide_saved = await page.evaluate("""() => {
          const started=performance.now();
          const input=document.querySelector('[data-profile-field="annualIncomeKrw"] input');
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'876543210');
          input.dispatchEvent(new Event('input',{bubbles:true}));
          window.dispatchEvent(new Event('pagehide'));
          return {elapsed:performance.now()-started,saved:JSON.parse(localStorage.getItem('cheongyak-profile-v5')).annualIncomeKrw};
        }""")
        check("Page termination flushes the latest draft before debounce",pagehide_saved["elapsed"]<300 and pagehide_saved["saved"]=="876543210")
        await settled(page)
        # Delay one worker reply across two newer committed drafts. The stale
        # reply must be discarded, then the coalesced latest revision applied.
        await page.evaluate("""() => {
          window.__qaDelayWorker=1200; window.__qaApplied=[];
          const shell=document.querySelector('.app-shell');
          window.__qaRevisionObserver=new MutationObserver(()=>window.__qaApplied.push(Number(shell.dataset.evaluationRevision)));
          window.__qaRevisionObserver.observe(shell,{attributes:true,attributeFilter:['data-evaluation-revision']});
        }""")
        first_posts = await page.evaluate("window.__qaMetrics.posts.length")
        race_money = dialog.locator('[data-profile-field="annualIncomeKrw"] input')
        await race_money.fill("111")
        await page.wait_for_function("count=>window.__qaMetrics.posts.length>count",arg=first_posts)
        first_revision = await page.evaluate("window.__qaMetrics.posts.at(-1).revision")
        await race_money.fill("222")
        await page.wait_for_timeout(330)
        await race_money.fill("333")
        await page.wait_for_timeout(330)
        await page.evaluate("window.__qaDelayWorker=0")
        await dialog.locator(".dialog-close").click()
        await settled(page)
        applied = await page.evaluate("window.__qaApplied")
        check("Delayed obsolete worker reply cannot replace a newer profile",first_revision not in applied)
        current = await page.evaluate("({applied:Number(document.querySelector('.app-shell').dataset.evaluationRevision),latest:window.__qaMetrics.posts.at(-1).revision,saved:JSON.parse(localStorage.getItem('cheongyak-profile-v5')).annualIncomeKrw})")
        check("Only the coalesced latest worker revision is applied",current["applied"]==current["latest"] and current["saved"]=="333")
        await page.evaluate("window.__qaRevisionObserver.disconnect()")
        final = {"cards":await panel.locator(".notice-card").count(),"prices":await panel.locator(".price-row").count(),"competitionRows":await panel.locator(".competition-row").count(),"grayCards":await panel.locator(".notice-unavailable").count(),"calendarDays":await page.locator(".calendar-day.has-events").count()}
        check("Personal changes retain all notices, prices and competition rows",all(initial[k]==final[k] for k in ["cards","prices","competitionRows","calendarDays"]))
        check("Personally unavailable notices remain gray",initial["grayCards"]>0 and final["grayCards"]>0)
        all_links = await panel.locator('.qualification-input-action').all_text_contents()
        check("Unmarried known state creates no marriage-duration missing-input action",not any("혼인 기간" in v for v in all_links))
        evidence_card = panel.locator(".notice-card").first
        await evidence_card.locator(".details-button").click()
        await expect(evidence_card.locator(".qualification-details")).to_be_visible()
        await evidence_card.locator(".notice-actions").get_by_role("button",name="내 조건 입력",exact=True).scroll_into_view_if_needed()
        scroll_before = await page.evaluate("window.scrollY")
        await evidence_card.locator(".notice-actions").get_by_role("button",name="내 조건 입력",exact=True).click()
        await page.get_by_role("dialog").locator(".dialog-close").click()
        scroll_after = await page.evaluate("window.scrollY")
        check("Opening conditions retains expanded evidence and scroll",await evidence_card.locator(".details-button").get_attribute("aria-expanded")=="true" and abs(scroll_after-scroll_before)<=2)
        if public["results"]:
            await page.get_by_role("tab",name="경쟁률·청약결과",exact=True).click()
            results_panel = page.locator("#results-panel")
            expected_results = [n for n in public["results"] if n["category"] != "public_rental" and any(r["verification"]=="official" for r in n.get("competitions",[]))]
            await expect(results_panel.locator(".notice-card")).to_have_count(min(20,len(expected_results)),timeout=30000)
            while await results_panel.locator(".load-more").count():
                await results_panel.locator(".load-more").click()
            await expect(results_panel.locator(".notice-card")).to_have_count(len(expected_results))
            await page.wait_for_function("!document.querySelector('#results-panel .background-refresh')",timeout=30000)
            results_snapshot = {"cards":await results_panel.locator(".notice-card").count(),"priceRows":await results_panel.locator(".price-row").count(),"competitionRows":await results_panel.locator(".competition-row").count(),"grayCompetitionRows":await results_panel.locator(".competition-row-unavailable").count()}
            check("Results keep every notice and every price",results_snapshot["cards"]==len(expected_results) and results_snapshot["priceRows"]==sum(len(n["prices"]) for n in expected_results))
            check("Results keep every official competition row",results_snapshot["competitionRows"]==sum(len(n["competitions"]) for n in expected_results))
            gray = results_panel.locator(".competition-row-unavailable")
            check("Unavailable competition rows stay gray rather than disappearing",await gray.count()>0)
            check("Results have no horizontal overflow",await page.evaluate("document.documentElement.scrollWidth<=innerWidth+2"))
    else:
        await dialog.locator(".dialog-close").click()
    allowed = {"start","end","page","page_size","exclude_public_rental","application_only","cap_only","view"}
    check("API gets only public GET parameters and no profile",all(r["method"]=="GET" and not r["body"] and set(r["queryNames"])<=allowed for r in requests))
    check("No JavaScript runtime errors",not errors)
    result = {"width":width,"cpuSlowdown":slowdown,"checks":checks,"passed":len(checks),"measurements":measured,"publicNoticeSnapshot":initial,"resultsSnapshot":results_snapshot,"profileValuesInReport":False}
    await context.close()
    return result


async def main(args):
    if args.snapshot:
        raw = json.loads(Path(args.snapshot).read_text())
        public = raw if "schedule" in raw else {"schedule":raw["items"],"results":[],"coverage":{"sources":[]}}
    else:
        public = snapshot(args.source)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        cohorts = []
        scenarios = {"desktop":(1280,1,not args.performance_only),"mobile":(375,1,not args.performance_only),"slow":(375,4,False)}
        for width, slowdown, functional in ([scenarios[args.cohort]] if args.cohort else scenarios.values()):
            result = await cohort(browser,args.base,public,width=width,slowdown=slowdown,functional=functional,strict=args.strict_performance)
            cohorts.append(result)
            print(json.dumps({"width":width,"cpu":slowdown,"passed":result["passed"],"timing":result["measurements"]},ensure_ascii=False),flush=True)
        await browser.close()
    report = {"date":str(TODAY),"base":args.base,"publicFixtureCount":len(public["schedule"]),"passed":sum(c["passed"] for c in cohorts),"cohorts":cohorts,"profileValuesInReport":False,"strictPerformance":args.strict_performance}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"passed":report["passed"],"report":args.output},ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base",default="http://127.0.0.1:5174")
    parser.add_argument("--source",default="http://localhost:8080")
    parser.add_argument("--snapshot",help="Previously fetched public notices; contains no personal profile")
    parser.add_argument("--output",default=str(ROOT/"docs/qa/v6-browser-2026-10-05.json"))
    parser.add_argument("--strict-performance",action="store_true")
    parser.add_argument("--performance-only",action="store_true")
    parser.add_argument("--cohort",choices=["desktop","mobile","slow"])
    asyncio.run(main(parser.parse_args()))
