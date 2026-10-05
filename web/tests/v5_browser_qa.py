"""Isolated 375px/desktop checks of the deployed public API and current UI.

No existing browser storage is read. Fictional local facts are never sent to
an API, written to the report, or printed in request/debug logs.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from urllib.request import urlopen
from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
BASE = 'http://localhost:8080'

async def main():
    with urlopen(BASE+'/api/notices?start=2026-10-05&end=2026-12-31&page_size=100&exclude_public_rental=true&application_only=true') as response:
        public=json.load(response)
    cutoffs=sorted({r.get('criterion_date') for n in public['items'] for r in n['rules'] if r.get('criterion_date')})
    confirmations=[{'criterionDate':day,'unchanged':True} for day in cutoffs]
    profile={'version':4,'region':'경기도','regionCode':'41','district':'화성시','districtCode':'41590',
        'movedInDate':'2010-01-01','districtMovedInDate':'2010-01-01','cityMovedInDate':'2010-01-01',
        'dateOfBirth':'1990-01-01','militaryCurrentlyServing':False,'militaryFactsAsOfDate':'2026-10-05',
        'militaryFactsHistoryConfirmations':confirmations,'currentlyDomesticResident':True,
        'domesticResidenceFactsAsOfDate':'2026-10-05','domesticResidenceHistoryConfirmations':confirmations,
        'providerEmployeeOrRelatedFamily':False,'applicantOnRegister':True,'hasSpouse':False,
        'maritalStatus':'single','householdMembers':[],'householdMembersComplete':True,
        'householdSnapshotDate':'2026-10-05','householdHistoryConfirmations':confirmations,
        'ownershipFactsKnown':True,'ownershipFacts':[],'applicantOwnsHome':False,'applicantPreviouslyOwnedHome':False,
        'isHouseholdHead':True,'citizenship':'korean','hasChildren':False,'children':[],'pregnant':False,
        'accountType':'comprehensive','privateRankBaseDate':'2010-01-01','nationalRankBaseDate':'2010-01-01',
        'accountConversionUnclear':False,'privateDepositKrw':'6000000','privateDepositMaintained':True,
        'privateDepositAsOfDate':'2026-10-02','nationalRecognizedPayments':'12','nationalPaymentsAsOfDate':'2026-09-30'}
    requests=[];errors=[];checks=[];measurements={}
    def check(label,ok=True):
        assert ok,label
        checks.append(label)
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        context=await browser.new_context(viewport={'width':1280,'height':900},timezone_id='Asia/Seoul')
        await context.add_init_script("localStorage.setItem('cheongyak-profile-v4',"+json.dumps(json.dumps(profile))+")")
        page=await context.new_page()
        page.on('pageerror',lambda e:errors.append(type(e).__name__))
        page.on('request',lambda r:requests.append({'path':urlsplit(r.url).path,'query':parse_qs(urlsplit(r.url).query),'method':r.method,'hasBody':bool(r.post_data)}) if '/api/' in r.url else None)
        await page.goto(BASE,wait_until='networkidle')
        panel=page.locator('#schedule-panel')
        await expect(panel.locator('.notice-card')).to_have_count(public['total'],timeout=30000)
        check('Every returned active notice remains in the list, including personally unavailable notices')
        def card(title):return panel.locator('.notice-card').filter(has=page.get_by_role('heading',name=title,exact=True))
        for title in ['충정로역자이르네','고양 장항 아테라','탕정 푸르지오 리버파크','제주시 이도이동 아이린8차 아파트','천안 아이파크 시티 2단지(2회차)']:
            n=card(title)
            await expect(n.locator('.notice-region-decision').first).to_have_attribute('data-region-status','outside')
            await expect(n).to_have_class(__import__('re').compile('notice-unavailable'))
            check(title+': explicit region exclusion is gray and retains all prices',await n.locator('.price-row').count()>0)
        tang=card('탕정 푸르지오 리버파크')
        check('Tangjeong diagnoses first-home only, with no phantom general supply','일반공급' not in await tang.locator('.qualification-brief').inner_text())
        hyang=card('향남역 그로브 스위첸')
        await expect(hyang.locator('.notice-region-decision').first).to_have_attribute('data-region-status','local')
        check('Applicant city priority is distinct from permitted other-region residence')
        for n in await panel.locator('.qualification-supply-brief').all():
            check('A real supply summary does not repeat an empty condition-preparation placeholder','공고 조건 정리 중' not in await n.inner_text())
        await tang.get_by_role('button',name='유형별 근거',exact=True).click()
        details=tang.locator('.qualification-details')
        await expect(details).to_be_visible()
        detail_text=await details.inner_text()
        check('Official comparisons expose source and cutoff',all(v in detail_text for v in ['기준일','원문 근거','2026-10-02']))
        for width in [1280,375]:
            await page.set_viewport_size({'width':width,'height':900})
            widths=await details.locator('.qualification-reason-body').evaluate_all('(rows)=>rows.map(r=>r.getBoundingClientRect().width)')
            measurements[str(width)]={'minimumEvidenceBodyWidth':min(widths),'evidenceRows':len(widths)}
            check(f'{width}px: evidence text has readable width',min(widths)>180 if width==1280 else min(widths)>140)
            overflow=await page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
            check(f'{width}px: page has no horizontal overflow',not overflow)
        await tang.screenshot(path=str(ROOT/'docs/screenshots/v5-tangjeong-mobile.png'))
        await tang.evaluate('(el)=>el.scrollIntoView({block:"start"})')
        await page.screenshot(path=str(ROOT/'docs/screenshots/v5-tangjeong-mobile-top.png'))
        before=len(requests)
        for _ in range(2):
            await page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('blur'))")
            await page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('focus'))")
        await page.wait_for_timeout(300)
        check('Focus out/in itself causes no API requests',len(requests)==before)
        await panel.get_by_role('button',name='새로고침',exact=True).click()
        await page.wait_for_load_state('networkidle')
        await expect(details).to_be_visible()
        check('Manual background refresh retains expanded evidence and local filters',await page.get_by_label('현재 거주 시군구',exact=True).input_value()=='41590')
        # Follow a real missing fact link to the exact question without fetching.
        missing=tang.locator('.qualification-input-action').first
        if await missing.count():
            before=len(requests)
            await missing.click()
            await expect(page.get_by_role('dialog')).to_be_visible()
            check('Missing fact links open the local question without an API request',len(requests)==before)
            await page.get_by_role('button',name='닫기',exact=True).first.click()
        await page.get_by_role('button',name='내 조건 설정',exact=True).click()
        dialog=page.get_by_role('dialog')
        await dialog.get_by_role('button',name=__import__('re').compile('소득·자산')).click()
        net=dialog.locator('[data-profile-field="officialNetAssetsKrw"] input')
        await expect(net).to_be_visible()
        before=len(requests)
        await net.fill('397000000')
        await expect(net).to_have_value('397,000,000')
        check('Net assets are edited with commas and kept separate from total assets',await dialog.locator('[data-profile-field="assetsKrw"] input').input_value()=='')
        check('Changing personal monetary facts sends no API request',len(requests)==before)
        await page.get_by_role('button',name='닫기',exact=True).first.click()
        await page.get_by_role('tab',name='경쟁률·청약결과',exact=True).click()
        results=page.locator('#results-panel')
        await expect(results.locator('.notice-card').first).to_be_visible(timeout=30000)
        gw=results.locator('.notice-card').filter(has=page.get_by_role('heading',name='광명 시티프라디움 에듀하임',exact=True))
        await expect(gw).to_have_count(1)
        check('Historical competition keeps every price and every official row',await gw.locator('.price-row').count()==7 and await gw.locator('.competition-row').count()==28)
        check('59A rows are gray and 59B 1.10 is still visible',await gw.locator('.competition-row-unavailable').count()==4 and '1.10' in await gw.inner_text())
        allowed={'start','end','page','page_size','exclude_public_rental','application_only','cap_only','view'}
        check('API receives only public date/filter GETs, with no personal conditions',all(r['method']=='GET' and not r['hasBody'] and set(r['query'])<=allowed for r in requests))
        check('Browser has no JavaScript runtime errors',not errors)
        await browser.close()
    report={'passed':len(checks),'checks':checks,'measurements':measurements,'publicApiRequestCount':len(requests),'profileValuesInReport':False}
    (ROOT/'docs/qa/v5-browser-2026-10-05.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':len(checks),'report':'docs/qa/v5-browser-2026-10-05.json'}))

if __name__=='__main__':asyncio.run(main())
