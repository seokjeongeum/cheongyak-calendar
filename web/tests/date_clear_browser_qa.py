"""Date deletion, autosave and shared bank dates with synthetic local facts."""
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright, expect
from profile_facts_v10_browser_qa import PROFILE_KEY, Router, notice, profile

BASE = os.environ.get('CHEONGYAK_QA_BASE', 'http://127.0.0.1:5198')
OUT = Path(os.environ.get('CHEONGYAK_QA_OUT', '/tmp/date-clear-browser'))
DISPOSED = '처분 완료일 (현재 보유하면 비워두세요)'
HOMELESS = '본인·배우자가 마지막으로 무주택이 된 날 (기존 처분 이력으로 확인되지 않을 때)'
COMMON = '순위기산일 (민영·국민주택 공통)'

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
        for width in [375, 1280]:
            person = profile(privateRankBaseDate='2009-01-01', nationalRankBaseDate='2009-01-01',
                pointsHomelessSince='2020-01-01', ownershipFacts=[{'id':'qa-home', 'ownerMemberId':'applicant',
                'ownerRelation':'applicant', 'propertyKind':'apartment', 'acquiredDate':'2015-01-01',
                'disposedDate':'2020-01-01'}])
            context = await browser.new_context(viewport={'width':width, 'height':900}, timezone_id='Asia/Seoul')
            await context.add_init_script(f'if (!localStorage.getItem({json.dumps(PROFILE_KEY)})) localStorage.setItem({json.dumps(PROFILE_KEY)}, {json.dumps(json.dumps(person))})')
            page = await context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            await page.clock.set_fixed_time(datetime(2026,10,13,4,0,tzinfo=timezone.utc))
            router = Router([notice()])
            await page.route('**/api/**', router.handle)
            await page.route('https://fonts.googleapis.com/**', lambda route: route.fulfill(status=200, body=''))
            await page.goto(BASE, wait_until='domcontentloaded')
            async def step(name):
                dialog = page.get_by_role('dialog')
                await dialog.locator('.step-progress').get_by_role('button', name=re.compile(name)).click()
                return dialog
            async def close():
                await page.get_by_role('dialog').get_by_role('button', name='닫기', exact=True).first.click()
            async def open_dialog():
                await page.get_by_role('button', name='내 조건 설정', exact=True).click()
            def check(label):
                checks.append(f'{width}px {label}')
            await open_dialog()
            dialog = await step('세대·주택')
            await dialog.get_by_role('button', name=f'{DISPOSED} 지우기', exact=True).click()
            await expect(dialog.get_by_label(DISPOSED, exact=True)).to_have_value('')
            check('disposal date clears without removing the property')
            dialog = await step('청약통장')
            await dialog.locator('[data-profile-field="pointsFamily"] summary').click()
            await dialog.get_by_role('button', name=f'{HOMELESS} 지우기', exact=True).click()
            await expect(dialog.get_by_label(HOMELESS, exact=True)).to_have_value('')
            await expect(dialog.get_by_label(COMMON, exact=True)).to_have_count(1)
            await expect(dialog.get_by_label('민영주택 순위기산일', exact=True)).to_have_count(0)
            await expect(dialog.get_by_label('국민주택 순위기산일', exact=True)).to_have_count(0)
            check('equal rank dates have one common input')
            # Direct native clearing and the clear button both persist.
            await dialog.get_by_label(COMMON, exact=True).fill('')
            await expect(dialog.get_by_label(COMMON, exact=True)).to_have_value('')
            await close()
            saved = await page.evaluate(f'JSON.parse(localStorage.getItem({json.dumps(PROFILE_KEY)}))')
            assert saved['ownershipFacts'][0]['disposedDate'] == '' and saved['pointsHomelessSince'] == ''
            assert saved['privateRankBaseDate'] == saved['nationalRankBaseDate'] == ''
            check('all cleared dates flush as empty strings')
            await page.reload(wait_until='domcontentloaded')
            await open_dialog()
            dialog = await step('세대·주택')
            await expect(dialog.get_by_label(DISPOSED, exact=True)).to_have_value('')
            # Also exercise native emptying in the two reported controls.
            await dialog.get_by_label(DISPOSED, exact=True).fill('2020-01-01')
            await dialog.get_by_label(DISPOSED, exact=True).fill('')
            await expect(dialog.get_by_label(DISPOSED, exact=True)).to_have_value('')
            dialog = await step('청약통장')
            await dialog.locator('[data-profile-field="pointsFamily"] summary').click()
            await expect(dialog.get_by_label(HOMELESS, exact=True)).to_have_value('')
            await dialog.get_by_label(HOMELESS, exact=True).fill('2020-01-01')
            await dialog.get_by_label(HOMELESS, exact=True).fill('')
            await expect(dialog.get_by_label(HOMELESS, exact=True)).to_have_value('')
            check('reload and native deletion preserve blank optional dates')
            await dialog.get_by_label(COMMON, exact=True).fill('2009-01-01')
            await close()
            saved = await page.evaluate(f'JSON.parse(localStorage.getItem({json.dumps(PROFILE_KEY)}))')
            assert saved['privateRankBaseDate'] == saved['nationalRankBaseDate'] == '2009-01-01'
            check('one entry supplies both bank comparisons')
            await open_dialog()
            dialog = await step('청약통장')
            await dialog.get_by_role('checkbox', name='민영·국민주택 기산일 따로 입력').check()
            await dialog.get_by_label('국민주택 순위기산일', exact=True).fill('2010-01-01')
            await close()
            await page.reload(wait_until='domcontentloaded')
            await open_dialog()
            dialog = await step('청약통장')
            await expect(dialog.get_by_label('민영주택 순위기산일', exact=True)).to_have_value('2009-01-01')
            await expect(dialog.get_by_label('국민주택 순위기산일', exact=True)).to_have_value('2010-01-01')
            await dialog.get_by_role('button', name='국민주택 순위기산일 지우기', exact=True).click()
            await expect(dialog.get_by_label('국민주택 순위기산일', exact=True)).to_have_value('')
            await close()
            await open_dialog()
            dialog = await step('청약통장')
            await expect(dialog.get_by_label('국민주택 순위기산일', exact=True)).to_have_value('')
            await expect(dialog.get_by_label('민영주택 순위기산일', exact=True)).to_have_value('2009-01-01')
            check('different recognition dates and a separate blank are preserved')
            assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert await dialog.evaluate('(d) => d.scrollWidth <= d.clientWidth')
            assert all(r['method']=='GET' and r['body'] is None for r in router.requests) and not router.errors
            check('no overflow or private-data requests')
            await page.screenshot(path=str(OUT/f'rank-dates-{width}.png'))
            await context.close()
        assert not errors
        await browser.close()
    (OUT/'result.json').write_text(json.dumps({'checks':checks,'javascript_errors':errors},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'checks_passed':len(checks),'result':str(OUT/'result.json')}))

if __name__ == '__main__':
    asyncio.run(main())
