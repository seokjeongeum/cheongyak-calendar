"""Verify real document rules with synthetic browser-only applicant facts."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect
from profile_facts_v10_browser_qa import PROFILE_KEY, Router, profile

BASE = os.environ.get('CHEONGYAK_QA_BASE', 'http://127.0.0.1:5194')
ASSET = os.environ.get('CHEONGYAK_QA_EXPECTED_ASSET', 'index-ibn9qA6B.js')
SOURCE = Path(os.environ.get('CHEONGYAK_QA_SOURCE', '/tmp/v18-browser-notices.json'))
OUT = Path(os.environ.get('CHEONGYAK_QA_OUT', '/tmp/v18-browser'))
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def facts(**extra):
    return profile(region='경기도', regionCode='41', district='화성시', districtCode='41590',
        movedInDate='2020-01-01', districtMovedInDate='2020-01-01', cityMovedInDate='2020-01-01',
        householdMembers=[], pointsFamily={}, additionalFamilyPresence=False,
        currentlyDomesticResident=True, domesticResidenceFactsAsOfDate='2026-01-01',
        providerEmployeeOrRelatedFamily=False, privateDepositKrw='19300000',
        factChanges={group: {'mode': 'never_changed', 'date': ''} for group in
            ['bank_private', 'bank_account', 'provider_employee', 'domestic_residence', 'citizenship', 'household', 'ownership', 'restrictions', 'marital']},
        **extra)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = json.loads(SOURCE.read_text())
    checks, errors, requests, assets = [], [], [], set()
    def check(label, result=True):
        assert result, label
        checks.append(label)
        print(label, flush=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
        async def create(row, person):
            context = await browser.new_context(viewport={'width': 375, 'height': 900}, timezone_id='Asia/Seoul')
            await context.add_init_script(f'localStorage.setItem({json.dumps(PROFILE_KEY)}, {json.dumps(json.dumps(person))})')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda req: assets.add(req.url) if '/assets/' in req.url else None)
            await page.clock.set_fixed_time(NOW)
            router = Router([row])
            await page.route('**/api/**', router.handle)
            await page.route('https://fonts.googleapis.com/**', lambda route: route.fulfill(status=200, body=''))
            await page.goto(BASE, wait_until='domcontentloaded', timeout=60000)
            await expect(page.locator('.notice-card[data-evaluation-ready="true"]')).to_have_count(1, timeout=20000)
            card = page.locator('.notice-card')
            return page, card, router
        async def finish(page, card, router, name):
            check(f'{name}: 375px no horizontal overflow', await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
            before = len(router.requests)
            await page.evaluate("""() => {window.dispatchEvent(new Event('focus')); Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'}); document.dispatchEvent(new Event('visibilitychange')); Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'}); document.dispatchEvent(new Event('visibilitychange'));}""")
            await page.wait_for_timeout(300)
            check(f'{name}: focus does not refetch', before == len(router.requests) and not router.errors)
            requests.extend(router.requests)
            await card.scroll_into_view_if_needed()
            await page.screenshot(path=str(OUT / f'{name}-375.png'))
            await page.context.close()
        for i, row in enumerate(rows[:4]):
            page, card, router = await create(row, facts())
            (OUT / f'official-{i+1}-text.txt').write_text(await card.inner_text())
            await expect(card.locator('.eligibility-details')).to_have_count(0)
            await expect(card.locator('.eligibility-summary')).to_contain_text('조건상 가능성 있음')
            check(f'official source {i+1}: fulfilled personal branch is possible')
            await card.get_by_role('button', name='유형별 근거', exact=True).click()
            await expect(card.locator('.qualification-details')).to_be_visible()
            await expect(card.locator('.qualification-details')).not_to_contain_text('미확보 공고 조항')
            await expect(card).not_to_contain_text('서비스 원문 검토 부족')
            check(f'official source {i+1}: no fabricated coverage gap')
            if i in [0, 1, 2]:
                await expect(card.locator('.qualification-details')).to_contain_text('오늘 비교일 (한국 시간)')
                await expect(card.locator('.qualification-details')).to_contain_text('2026-10-12')
                check(f'official source {i+1}: contract facts compare today')
            await finish(page, card, router, f'official-{i+1}')
        row = rows[4]
        page, card, router = await create(row, facts())
        await expect(card.locator('.qualification-account-summary')).to_contain_text('민영주택 1순위 조건 충족')
        await expect(card.locator('.qualification-account-summary')).to_contain_text('민영주택 예치금 충족')
        await expect(card).not_to_contain_text('주택형의 전용면적별 예치금 기준이 다릅니다')
        check('19300000: all real area tiers pass without a pending deposit warning')
        await finish(page, card, router, 'all-deposit-tiers')
        unknown = facts()
        unknown['factChanges']['bank_private'] = {'mode': 'unknown', 'date': ''}
        page, card, router = await create(row, unknown)
        await expect(card.locator('.qualification-account-summary')).to_contain_text('민영주택 1순위 확인 필요')
        await expect(card).to_contain_text('과거 사실 미확인')
        check('unknown deposit history: current large amount cannot establish a past balance')
        await finish(page, card, router, 'deposit-history-unknown')
        check('served build matches expected asset', any(ASSET in url for url in assets))
        check('no JavaScript exceptions', not errors)
        check('profile facts remain browser-only', all(item['method'] == 'GET' and item['body'] is None
            and set(parse_qs(urlsplit(item['url']).query)) <= {'start','end','page','page_size','exclude_public_rental','application_only','price_cap_status'}
            and not any(value in item['url'] for value in ['19300000','1990-01-01','41590']) for item in requests))
        await browser.close()
    result = {'checks_passed': len(checks), 'checks': checks, 'javascript_errors': errors,
        'personal_data_included': False, 'public_fixture_source': str(SOURCE), 'expected_asset': ASSET,
        'served_assets': sorted(assets), 'api_requests': requests, 'fixed_time': NOW.isoformat()}
    (OUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'checks_passed': len(checks), 'result': str(OUT / 'result.json')}))


if __name__ == '__main__':
    asyncio.run(main())
