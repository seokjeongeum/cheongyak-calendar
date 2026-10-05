"""Live official contract API and adult-path UI smoke, isolated fictional profile."""
import asyncio,json
from pathlib import Path
from urllib.request import urlopen
from playwright.async_api import async_playwright,expect
from v6_browser_qa import PROFILE,STORAGE_KEY,ROOT
BASE='http://localhost:8080'
NOTICE_ID='817add08-c732-4629-a702-847f677e20b7'
async def main():
 listing=json.load(urlopen(BASE+'/api/notices?start=2026-10-05&end=2026-12-31&page_size=100&application_only=true&exclude_public_rental=true'))
 row=next(n for n in listing['items'] if n.get('contract_schedule') and '67720873' in (n['contract_schedule'].get('evidence_url') or ''))
 detail=json.load(urlopen(BASE+'/api/notices/'+row['id']))
 assert row['contract_schedule']==detail['contract_schedule']
 assert row['contract_schedule']['status']=='ongoing' and row['rules_complete']
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True)
  context=await browser.new_context(viewport={'width':375,'height':1100},timezone_id='Asia/Seoul')
  await context.add_init_script('localStorage.setItem('+json.dumps(STORAGE_KEY)+','+json.dumps(json.dumps(PROFILE))+')')
  page=await context.new_page();requests=[]
  page.on('request',lambda r:requests.append((r.method,bool(r.post_data))) if '/api/' in r.url else None)
  await page.goto(BASE,wait_until='domcontentloaded')
  card=page.locator('.notice-card').filter(has=page.get_by_role('heading',name=row['title'],exact=True))
  await expect(card.locator('.eligibility-badge')).to_have_text('조건상 가능성 있음',timeout=30000)
  await expect(card.locator('.contract-comparison-note')).to_contain_text('오늘 계약한다면 (2026-10-05)')
  assert await card.locator('.qualification-gap-note').count()==0
  assert '기간 확인 필요' not in await card.locator('.qualification-candidate').inner_text()
  assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
  assert requests and all(method=='GET' and not body for method,body in requests)
  await card.screenshot(path=str(ROOT/'docs/screenshots/v6-cheongju-mobile.png'),style='.site-header {visibility:hidden!important;}')
  report={'date':'2026-10-05','passed':8,'notice':row['title'],'contract_schedule_list_detail_equal':True,'reviewed_document_hash':row['contract_schedule']['document_hash'],'adult_path':'possible','scenario':'today_contract','mobile_width':375,'horizontal_overflow':False,'api_requests_read_only_without_profile_body':True,'profileValuesInReport':False}
  (ROOT/'docs/qa/v6-live-smoke-2026-10-05.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
  print(json.dumps({'passed':8,'adult_path':'possible','contract_scenario':'today'},ensure_ascii=False))
  await browser.close()
asyncio.run(main())
