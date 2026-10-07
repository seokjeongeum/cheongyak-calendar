"""Replay official Hangang allocation evidence with isolated fictional profiles.

Uses recorded public documents and fictional reception windows. No production
database writes or user browser storage are involved.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect
import v6_browser_qa
from v6_browser_qa import INSTRUMENTATION, PROFILE, route_public, settled

SOURCE_ID = 'qa-recorded-2026000468'
SOURCE_HASH = '90a4d4e7e50b205ae45ee27cd7b3b50b5b8e1b3a65f19580f156336308cc1c34'
SOURCE_URL = 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000468&pblancNo=2026000468&atchmnflSeqNo=1990183&atchmnflSn=2'
RESIDENCES = [
    ('gyeonggi', '41', '경기도', '41590', '화성시'),
    ('seoul', '11', '서울특별시', '11680', '강남구'),
    ('local', '41', '경기도', '41830', '양평군'),
]


async def cohort(browser, public, residence, width, args):
    name, region_code, region, district_code, district = residence
    fake = copy.deepcopy(PROFILE)
    fake.update(regionCode=region_code, region=region, districtCode=district_code, district=district)
    context = await browser.new_context(viewport={'width': width, 'height': 1000}, timezone_id='Asia/Seoul')
    await context.add_init_script("localStorage.setItem('cheongyak-profile-v5'," + json.dumps(json.dumps(fake)) + ")")
    await context.add_init_script(INSTRUMENTATION)
    await context.route('**/api/**', lambda route: route_public(route, public))
    page = await context.new_page()
    requests, errors, checks = [], [], []
    page.on('pageerror', lambda e: errors.append(type(e).__name__))
    page.on('request', lambda r: requests.append({'method': r.method, 'body': bool(r.post_data), 'queryNames': list(parse_qs(urlsplit(r.url).query))}) if '/api/' in r.url else None)

    def check(label, value=True):
        assert value, f'{name}/{width}: {label}'
        checks.append(label)

    await page.goto(args.base, wait_until='domcontentloaded')
    await settled(page)
    card = page.locator('#schedule-panel .notice-card')
    await expect(card).to_have_count(1)
    notice = public['schedule'][0]
    await expect(card.locator('h4')).to_have_text(notice['title'])
    panel = card.locator('.opportunity-panel')
    await expect(panel).to_be_visible()
    text = await panel.inner_text()
    check('Incorrect combined source-gap and qualification claim are absent', '자격은 확인' not in text and '배정 방식 확인 필요' not in text)
    check('Official Gyeonggi and Seoul/Incheon 50-percent quotas are visible', '경기도 50%' in text and any(s in text for s in ['서울·인천 50%', '서울/인천 50%', '서울특별시 및 인천광역시 50%']))
    check('Yangpyeong priority within Gyeonggi quota is named', '양평군' in text)
    check('First-stage losers can enter the remaining quota without local priority', '낙첨자' in text and '다시' in text and '우선을 적용하지 않습니다' in text)
    check('Institution nomination has its own selection method', '추천기관 우선순위로 선정' in text)
    check('Special selection order is shown', '선정 순서:' in text)
    check('Newlywed third-stage lottery overrides the basic rank order', '기본 선정 순서:' in text and '3단계 선정 순서: 지역 → 추첨' in text and '순위와 관계없이' in text)

    positive = {}
    for supply in notice['offered_supplies']:
        if supply['verification'] == 'official' and (supply['supply_count'] is None or supply['supply_count'] > 0):
            positive.setdefault(supply['supply_type'], set()).add(supply['unit_type'])
    seen = set()
    for row in await panel.locator('.opportunity-row').all():
        label = await row.locator(':scope > small').inner_text()
        supply_type, unit_label = label.split('\n', 1)
        units = unit_label.removeprefix('주택형 ').split(' · ')
        check('Displayed supply and units form only actual positive offers', supply_type in positive and set(units) <= positive[supply_type])
        seen.add(supply_type)
        for link in await row.locator(':scope > a').all():
            check('Allocation evidence links to the exact official attachment', (await link.get_attribute('href')).split('#', 1)[0] == SOURCE_URL)
    check('All six special supply methods remain separate', {s for s in positive if s != '일반공급'} <= seen)
    multi = card.locator('.qualification-supply-brief.qualification-unavailable').filter(has=page.get_by_text('다자녀가구 특별공급', exact=True))
    check('An opportunity explanation does not override child eligibility mismatch', await multi.count() > 0)
    check('Recorded prices and competitions are preserved', await card.locator('.price-row').count() == len(notice['prices']) and await card.locator('.competition-row').count() == len(notice['competitions']))
    check('No horizontal overflow', await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'))
    allowed = {'start', 'end', 'page', 'page_size', 'cap_only', 'application_only', 'exclude_public_rental', 'category', 'view'}
    check('Only public GET filters are sent', all(r['method'] == 'GET' and not r['body'] and set(r['queryNames']) <= allowed for r in requests))
    check('No browser runtime error', not errors)
    if name == 'gyeonggi' and width == 375 and args.screenshot:
        await page.add_style_tag(content='.site-header { visibility: hidden !important; }')
        await panel.screenshot(path=args.screenshot)
    result = {'fictionalResidenceCohort': name, 'width': width, 'passed': len(checks), 'checks': checks, 'supplyTypesDisplayed': sorted(seen)}
    await context.close()
    return result


async def main(args):
    v6_browser_qa.TODAY = v6_browser_qa.date.fromisoformat(args.today)
    public = json.loads(Path(args.snapshot).read_text())
    notice = next(n for n in public['schedule'] if n['id'] == SOURCE_ID)
    assert notice['document_hash'] == SOURCE_HASH
    public['schedule'] = [notice]
    public['results'] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        results = [await cohort(browser, public, residence, width, args) for residence in RESIDENCES for width in [1280, 375]]
        await browser.close()
    report = {'date': args.today, 'passed': sum(r['passed'] for r in results), 'cohorts': results,
        'sourceNoticeId': SOURCE_ID, 'sourceHash': SOURCE_HASH, 'profileValuesInReport': False,
        'dataProvenance': public['provenance']}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'cohorts': len(results), 'sourceHash': SOURCE_HASH}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8080')
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--today', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--screenshot')
    asyncio.run(main(parser.parse_args()))
