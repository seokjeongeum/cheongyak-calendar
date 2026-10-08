"""API settings browser regression with fictional credentials and mocked APIs."""
import asyncio,json,os
from pathlib import Path
from playwright.async_api import async_playwright,expect
ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / 'docs' / 'qa'
BASE_URL = os.getenv('QA_BASE_URL', 'http://127.0.0.1:5176')
SERVICES=[('DATA_GO_KR_API_KEY','공공데이터 공통 키 · 청약홈','https://www.data.go.kr/data/15098547/openapi.do'),('MYHOME_API_KEY','마이홈','https://www.data.go.kr/data/15108420/openapi.do'),('LH_API_KEY','LH','https://www.data.go.kr/data/15058530/openapi.do'),('IH_API_KEY','iH 인천도시공사','https://www.data.go.kr/data/15149725/openapi.do'),('CHEONGYAK_COMPETITION_API_KEY','청약 경쟁률','https://www.data.go.kr/data/15098905/openapi.do'),('GEMINI_API_KEY','Gemini 문서 추출 · 선택','https://aistudio.google.com/apikey')]
async def main():
 checks=[]
 async with async_playwright() as pw:
  browser=await pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  for width in [1280,375]:
   context=await browser.new_context(viewport={'width':width,'height':900})
   page=await context.new_page()
   state={'admin_initialized':True,'services':[{'name':n,'label':l,'key_url':u,'configured':False,'storage':'server','uses_shared_key':False} for n,l,u in SERVICES],'gemini_unbilled_confirmed':False}
   writes=[]
   request_urls=[]
   console_text=[]
   page.on('request',lambda request:request_urls.append(request.url))
   page.on('console',lambda message:console_text.append(message.text))
   async def route(r):
    if '/api/integrations' in r.request.url:
     if r.request.method=='PUT':
      writes.append(r.request.post_data_json)
      if r.request.headers.get('authorization')!='Bearer fictional-admin':
       await r.fulfill(status=401,json={'detail':'invalid'});return
      for service in state['services']:
       if service['name'] in writes[-1]['keys']:service['configured']=bool(writes[-1]['keys'][service['name']])
      state['gemini_unbilled_confirmed']=writes[-1]['gemini_unbilled_confirmed']
     await r.fulfill(json=state)
    elif '/api/coverage' in r.request.url: await r.fulfill(json={'sources':[]})
    else: await r.fulfill(json={'items':[],'total':0,'page':1,'page_size':100})
   await page.route('**/api/**',route)
   await page.goto(BASE_URL)
   await page.get_by_role('button',name='API 연결 설정').click()
   await expect(page.get_by_role('form',name='API 연결 설정')).to_be_visible()
   checks.append(f'{width}: opens on request')
   for name,label,url in SERVICES:
    await expect(page.locator('.integration-service').filter(has=page.locator(f'#key-{name}')).get_by_role('link')).to_have_attribute('href',url)
   checks.append(f'{width}: six direct key links')
   await page.locator('#key-LH_API_KEY').fill('fictional-key')
   await page.locator('#integration-admin-token').fill('wrong')
   await page.get_by_role('button',name='연결 설정 저장').click()
   await expect(page.get_by_role('alert')).to_contain_text('관리자 인증키')
   checks.append(f'{width}: unauthorized error')
   await page.locator('#integration-admin-token').fill('fictional-admin')
   await page.get_by_role('button',name='연결 설정 저장').click()
   await expect(page.get_by_role('status').filter(has_text='저장했습니다')).to_be_visible()
   await expect(page.locator('#key-LH_API_KEY')).to_have_value('')
   await expect(page.locator('#integration-admin-token')).to_have_value('fictional-admin')
   checks.append(f'{width}: save clears API keys and retains in-memory administrator authentication')
   assert writes[-1]['keys']=={'LH_API_KEY':'fictional-key'}
   checks.append(f'{width}: only changed keys submitted')
   await page.locator('.integration-service').filter(has=page.locator('#key-LH_API_KEY')).get_by_role('button',name='삭제').click()
   await page.get_by_role('button',name='연결 설정 저장').click()
   await expect(page.get_by_role('status').filter(has_text='저장했습니다')).to_be_visible()
   assert writes[-1]['keys']=={'LH_API_KEY':''}
   checks.append(f'{width}: explicit delete')
   await page.get_by_role('checkbox',name='Gemini 키가 청구를 사용하지 않는 Google 프로젝트의 키임을 확인했습니다.').check()
   await page.locator('#key-GEMINI_API_KEY').fill('fictional-gemini')
   await expect(page.get_by_role('checkbox',name='Gemini 키가 청구를 사용하지 않는 Google 프로젝트의 키임을 확인했습니다.')).not_to_be_checked()
   checks.append(f'{width}: new Gemini key resets consent')
   assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
   checks.append(f'{width}: no horizontal overflow')
   assert not await page.evaluate("JSON.stringify({...localStorage,...sessionStorage}).includes('fictional-')")
   checks.append(f'{width}: secrets absent from browser storage')
   await page.get_by_role('button',name='API 연결 설정').click()
   await expect(page.locator('#integration-form')).to_have_count(0)
   await page.get_by_role('button',name='API 연결 설정').click()
   await expect(page.locator('#key-GEMINI_API_KEY')).to_have_value('')
   await expect(page.locator('#integration-admin-token')).to_have_value('')
   checks.append(f'{width}: close clears pending secrets')

   await page.goto(BASE_URL+'/#api-settings&admin=fictional-admin')
   await expect(page.get_by_role('form',name='API 연결 설정')).to_be_visible()
   await expect(page.locator('#integration-admin-token')).to_have_value('fictional-admin')
   assert page.url.endswith('/#api-settings')
   assert not await page.evaluate("JSON.stringify(history.state).includes('fictional-admin')")
   checks.append(f'{width}: private owner link auto-opens and immediately scrubs credential')
   assert await page.locator('#integration-form h3').evaluate("element => element.getBoundingClientRect().top >= document.querySelector('.site-header').getBoundingClientRect().bottom")
   checks.append(f'{width}: hosted form heading stays below the sticky header')
   assert not any('fictional-admin' in url for url in request_urls)
   assert not any('fictional-admin' in line for line in console_text)
   checks.append(f'{width}: owner credential absent from request URLs and console')
   text=await page.locator('#integration-form').inner_text()
   assert 'docker compose' not in text and 'git pull' not in text and '.env' not in text
   checks.append(f'{width}: hosted connection has no local setup commands')
   for key,name in [('fictional-key-one','LH_API_KEY'),('fictional-key-two','MYHOME_API_KEY')]:
    await page.locator(f'#key-{name}').fill(key)
    await page.get_by_role('button',name='연결 설정 저장').click()
    await expect(page.get_by_role('status').filter(has_text='저장했습니다')).to_be_visible()
    assert writes[-1]['keys']=={name:key}
    await expect(page.locator(f'#key-{name}')).to_have_value('')
    await expect(page.locator('#integration-admin-token')).to_have_value('fictional-admin')
   checks.append(f'{width}: consecutive hosted saves need no token re-entry and clear only API key fields')
   assert not await page.evaluate("JSON.stringify({...localStorage,...sessionStorage}).includes('fictional-')")
   checks.append(f'{width}: hosted credentials remain absent from persistent browser storage')
   await page.get_by_role('button',name='API 연결 설정').click()
   await page.get_by_role('button',name='API 연결 설정').click()
   await expect(page.locator('#integration-admin-token')).to_have_value('')
   await expect(page.get_by_role('button',name='연결 설정 저장')).to_be_disabled()
   checks.append(f'{width}: closing the hosted form discards owner authentication')

   await page.goto(BASE_URL+'/#api-settings')
   await expect(page.get_by_role('form',name='API 연결 설정')).to_be_visible()
   await expect(page.locator('#integration-admin-token')).to_have_value('')
   await expect(page.get_by_role('button',name='연결 설정 저장')).to_be_disabled()
   checks.append(f'{width}: plain public settings link auto-opens without write access')
   assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
   checks.append(f'{width}: hosted entry has no horizontal overflow')
   if width==375:
    await page.locator('#integration-form').screenshot(path=str(QA/'hosted-integration-settings-mobile-2026-10-08.png'))
   await context.close()
  await browser.close()
 (QA / 'hosted-integration-settings-ui-2026-10-08.json').write_text(json.dumps({'checks':checks,'passed':len(checks),'fictional_keys_only':True},ensure_ascii=False,indent=2))
 print(f'{len(checks)} browser checks passed')
asyncio.run(main())
