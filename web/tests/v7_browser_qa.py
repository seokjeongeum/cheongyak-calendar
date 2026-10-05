"""Public notices, fictional isolated profile: deadlines, opportunities, children."""
from __future__ import annotations

import asyncio
import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from playwright.async_api import async_playwright, expect
from v6_browser_qa import INSTRUMENTATION, PROFILE, snapshot, route_public, settled

ROOT = Path(__file__).resolve().parents[2]
TODAY = '2026-10-05'


def deadline(notice):
    dates=[]
    for event in notice['events']:
        if event['kind'] in {'announcement','result','winner','contract'}:
            continue
        end=event.get('end_date')
        if end is None and re.search(r'상시|마감\s*시|소진\s*시|종료일\s*미공개',event['label']):
            continue
        end=end or event['start_date']
        if end >= TODAY:
            dates.append(end)
    return min(dates) if dates else '9999-12-31'


async def cohort(browser, public, width):
    context=await browser.new_context(viewport={'width':width,'height':1000},timezone_id='Asia/Seoul')
    fake=copy.deepcopy(PROFILE)
    # A present-day "no" is deliberately not historical proof.
    fake['factChanges'].pop('children',None)
    fake['factChanges'].pop('pregnancy',None)
    fake['factChanges']['points']={'mode':'never_changed','date':''}
    await context.add_init_script("localStorage.setItem('cheongyak-profile-v5',"+json.dumps(json.dumps(fake))+" )")
    await context.add_init_script(INSTRUMENTATION)
    await context.route('**/api/**',lambda route:route_public(route,public))
    page=await context.new_page()
    requests,errors,checks=[],[],[]
    page.on('pageerror',lambda error:errors.append(type(error).__name__))
    page.on('request',lambda r:requests.append({'method':r.method,'path':urlsplit(r.url).path,'query':list(parse_qs(urlsplit(r.url).query)),'body':bool(r.post_data)}) if '/api/' in r.url else None)
    def check(label,value=True):
        assert value,label
        checks.append(label)
    await page.goto('http://localhost:8080',wait_until='domcontentloaded')
    await settled(page)
    panel=page.locator('#schedule-panel')
    cards=panel.locator('.notice-card')
    while await panel.locator('.load-more').count():
        await panel.locator('.load-more').click()
    await expect(cards).to_have_count(len(public['schedule']),timeout=30000)
    await settled(page)
    titles=await cards.locator('h4').all_text_contents()
    dates_by_title={n['title']:deadline(n) for n in public['schedule']}
    ordered=[dates_by_title[t] for t in titles]
    check('Every active public notice remains in deadline order',ordered==sorted(ordered))
    check('No separate ongoing group changes the deadline order',await page.locator('.current-group').count()==0)
    check('Date headings are reception deadlines',all('마감' in t for t in await panel.locator('.day-heading h3').all_text_contents()))
    prices_before=await cards.locator('.price-row').count()
    competition_before=await cards.locator('.competition-row').count()
    days_before=await page.locator('.calendar-day.has-events').count()
    check('Current reception is identified on the cards',await cards.get_by_text('현재 접수 중',exact=True).count()>0)
    check('Official opportunities are expanded without opening a notice',await panel.locator('.opportunity-panel').count()>0)
    check('Other-region limitation is separate from admission',await panel.get_by_text('해당지역 우선 · 기타지역 기회 제한',exact=True).count()>0)
    check('Unit-specific mixed and 100-percent lottery routes are displayed',await panel.get_by_text('가점 40% · 추첨 60%',exact=True).count()>0 and await panel.get_by_text('추첨제 100%',exact=True).count()>0)
    check('Confirmed own points and part scores are visible',await panel.locator('.my-points').count()>0 and await panel.get_by_text('부양가족',exact=False).count()>0)
    check('Separate regional quota is displayed without blanket disadvantage',await panel.get_by_text('기타지역 별도 배정',exact=True).count()>0)
    multi=panel.locator('.qualification-supply-brief').filter(has=page.get_by_text('다자녀가구 특별공급',exact=True))
    before_text=' '.join(await multi.all_text_contents())
    check('Present-only child answer still requires past proof','자녀 상태 변경일' in before_text)
    request_count=len(requests)
    await page.get_by_role('button',name='내 조건 설정',exact=True).click()
    dialog=page.get_by_role('dialog')
    await dialog.locator('.step-progress').get_by_role('button',name=re.compile('특별공급')).click()
    check('Child add and birth controls are hidden for current no',await dialog.get_by_role('button',name='자녀 정보 추가',exact=True).count()==0)
    check('Fetus count is hidden for current no',await dialog.locator('[data-profile-field="expectedChildren"]').count()==0)
    await dialog.get_by_role('button',name='계속 자녀·임신 없음',exact=True).click()
    check('Explicit common no is selected',await dialog.get_by_role('button',name='계속 자녀·임신 없음',exact=True).get_attribute('aria-pressed')=='true')
    await dialog.locator('.dialog-close').click()
    await settled(page)
    saved=await page.evaluate("JSON.parse(localStorage.getItem('cheongyak-profile-v5'))")
    check('Both independent timelines are stored only after explicit selection',saved['factChanges']['children']['mode']=='never_changed' and saved['factChanges']['pregnancy']['mode']=='never_changed')
    after_text=' '.join(await multi.all_text_contents())
    check('No repeated child or pregnancy change-date question remains',all(t not in after_text for t in ['자녀 상태 변경일','임신 상태 변경일','공고 기준일의 사실']))
    check('Zero children produces multi-child mismatch',await multi.count()>0 and await multi.locator('.qualification-brief-row').filter(has_text='0명').count()>0 and await multi.filter(has=page.locator('strong')).count()>0 and await panel.locator('.qualification-supply-brief.qualification-unavailable').filter(has=page.get_by_text('다자녀가구 특별공급',exact=True)).count()==await multi.count())
    check('No profile input reaches the public API',len(requests)==request_count)
    check('All gray and non-gray cards remain visible',await cards.count()==len(public['schedule']))
    check('Prices, competition rows and calendar dates are preserved',await cards.locator('.price-row').count()==prices_before and await cards.locator('.competition-row').count()==competition_before and await page.locator('.calendar-day.has-events').count()==days_before)
    evidence=cards.filter(has=page.get_by_role('heading',name='쌍용 더 플래티넘 한강',exact=True))
    await evidence.locator('.details-button').click()
    await expect(evidence.locator('.qualification-details')).to_be_visible()
    await page.get_by_role('button',name='내 조건 설정',exact=True).click()
    await page.get_by_role('dialog').locator('.dialog-close').click()
    check('Expanded evidence remains open after profile dialog',await evidence.locator('.details-button').get_attribute('aria-expanded')=='true')
    await evidence.scroll_into_view_if_needed()
    await page.add_style_tag(content='.site-header { visibility:hidden !important; }')
    if width==375:
        await page.screenshot(path=str(ROOT/'docs/screenshots/v7-opportunity-mobile.png'))
    check('No horizontal overflow',await page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'))
    before=len(requests)
    await page.evaluate("window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'))")
    await page.wait_for_timeout(150)
    check('Focus return alone does not fetch',len(requests)==before)
    allowed={'start','end','page','page_size','cap_only','application_only','exclude_public_rental','category','view'}
    check('Every public request is a GET with public filters only',all(r['method']=='GET' and not r['body'] and set(r['query'])<=allowed for r in requests))
    check('No runtime errors',not errors)
    result={'width':width,'passed':len(checks),'checks':checks,'cards':len(public['schedule']),'priceRows':prices_before,'competitionRows':competition_before,'calendarDays':days_before,'grayCards':await panel.locator('.notice-unavailable').count(),'profileValuesInReport':False}
    await context.close()
    return result


async def main():
    public=snapshot('http://localhost:8080')
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        results=[await cohort(browser,public,width) for width in [1280,375]]
        results.append(await published_score(browser,public))
        await browser.close()
    report={'date':TODAY,'passed':sum(r['passed'] for r in results),'cohorts':results,'profileValuesInReport':False}
    output=ROOT/'docs/qa/v7-browser-2026-10-05.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


async def published_score(browser,public):
    """A published official result, compared with an isolated fictional local applicant."""
    notice=next(n for n in public['results'] if n['id']=='5493b9ce-5ac5-4b9e-82cc-f4736b04d6b9')
    assert notice['winning_scores'] and notice['selection_methods']
    context=await browser.new_context(viewport={'width':375,'height':1000},timezone_id='Asia/Seoul')
    fake={**copy.deepcopy(PROFILE),'regionCode':'44','region':'충청남도','districtCode':'44130','district':'천안시'}
    await context.add_init_script("localStorage.setItem('cheongyak-profile-v5',"+json.dumps(json.dumps(fake))+" )")
    await context.add_init_script(INSTRUMENTATION)
    await context.route('**/api/**',lambda route:route_public(route,public))
    page=await context.new_page()
    errors=[]
    page.on('pageerror',lambda e:errors.append(type(e).__name__))
    await page.goto('http://localhost:8080',wait_until='domcontentloaded')
    await expect(page.locator('#schedule-panel .notice-card')).to_have_count(len(public['schedule']),timeout=30000)
    await settled(page)
    await page.get_by_role('tab',name='경쟁률·청약결과',exact=True).click()
    panel=page.locator('#results-panel')
    await expect(panel.locator('.notice-card')).to_have_count(min(20,len(public['results'])),timeout=30000)
    while await panel.locator('.load-more').count():
        await panel.locator('.load-more').click()
    card=panel.locator('.notice-card').filter(has=page.get_by_role('heading',name=notice['title'],exact=True))
    await expect(card).to_have_count(1)
    await expect(card).to_have_attribute('data-evaluation-ready','true',timeout=30000)
    # This older document has verified rates but no parsed admission-region
    # rule. The app must not guess local status from the notice's address.
    assert await card.locator('.points-benchmark').count()==0
    await card.get_by_role('combobox',name=notice['title']+' 청약 지역',exact=True).select_option('local')
    await expect(card.locator('.my-points')).to_contain_text('36 / 84점',timeout=30000)
    await expect(card.locator('.points-benchmark').first).to_be_visible()
    text=await card.locator('.opportunity-panel').inner_text()
    assert '과거 최저가점 미만' in text and '37점' in text and '내 가점 -1점' in text
    assert '36 / 84점' in text and '미래 당첨확률' in text
    assert await card.locator('.price-row').count()==len(notice['prices'])
    assert await card.locator('.competition-row').count()==len(notice['competitions'])
    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    assert not errors,errors
    assert '직접 선택한 청약 지역' in text
    result={'width':375,'passed':7,'checks':['Unknown automatic region does not guess a comparison','Explicit region selection is identified separately from admission','Same official project, unit and local area result is compared','36 fictional points is below the official 37-point minimum','No future probability is inferred','Prices and competitions remain visible','No overflow or runtime error'],'sourceNoticeId':notice['id'],'profileValuesInReport':False}
    await context.close()
    return result


if __name__=='__main__':
    asyncio.run(main())
