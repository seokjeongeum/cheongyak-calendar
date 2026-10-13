"""Current official-source DTOs with synthetic facts confined to Chromium.

The API routes are isolated public-response fixtures. No administrator token,
API key, actual applicant profile, or production mutation is used.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect
from profile_facts_v10_browser_qa import PROFILE_KEY, Router, profile

BASE = os.environ.get('CHEONGYAK_QA_BASE', 'http://127.0.0.1:5198')
ASSET = os.environ.get('CHEONGYAK_QA_EXPECTED_ASSET', 'index-CFl_3Xjf.js')
SOURCE = Path(os.environ.get('CHEONGYAK_QA_SOURCE', '/tmp/oct13-browser-notices.json'))
PLANS = Path(os.environ.get('CHEONGYAK_QA_PLANS', '/tmp/oct13-reviewed-plans.json'))
OUT = Path(os.environ.get('CHEONGYAK_QA_OUT', '/tmp/current-public-v19-browser'))
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
KST_TODAY = '2026-10-13'
CASES = [('uiwang', '의왕역 한신더휴'), ('eco18', '센터파크(18BL)'), ('eco19', '센터포인트(19BL)'),
         ('wonju', '원주무실'), ('gumi', '구미화성파크드림'), ('daegu', '대구노원한신더휴'),
         ('jungsun', '정선산수빌'), ('asan-corrected', '[정정공고]아산배방LH4단지'),
         ('asan-original', '아산배방LH4단지')]


def facts():
    restriction = {'ineligibleHistoryPresence': False, 'resaleViolationHistoryPresence': False,
                   'ineligibleRestrictionActive': False, 'resaleRestrictionActive': False,
                   'rewinningRestrictionActive': False, 'asOfDate': '2026-10-12', 'historyConfirmations': []}
    return profile(region='경기도', regionCode='41', district='화성시', districtCode='41590',
        movedInDate='2020-01-01', districtMovedInDate='2020-01-01', cityMovedInDate='2020-01-01',
        householdMembers=[], pointsFamily={}, additionalFamilyPresence=False,
        currentlyDomesticResident=True, domesticResidenceFactsAsOfDate='2020-01-01',
        providerEmployeeOrRelatedFamily=False, overseasContinuousDays='0', overseasFactsAsOfDate='2020-01-01',
        applicationHistoryPresence=False, applicationHistoryPeople=['applicant'],
        applicationHistoryAbsencePeople=['applicant'], applicationHistoryEvents=[],
        applicationRestrictionFacts={key: deepcopy(restriction) for key in ['applicant', 'household', 'applicant_spouse']},
        factChanges={group: {'mode': 'never_changed', 'date': ''} for group in
            ['bank_account', 'provider_employee', 'domestic_residence', 'citizenship', 'household',
             'ownership', 'restrictions', 'marital', 'overseas']})


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, plans = json.loads(SOURCE.read_text()), json.loads(PLANS.read_text())
    plan_by_id = {item['id']: item for item in plans}
    checks, errors, requests, assets, source_evidence = [], [], [], set(), []

    def check(label, result=True):
        assert result, label
        checks.append(label)
        print(label, flush=True)

    chosen = {}
    for case, fragment in CASES:
        matches = [row for row in rows if fragment in row['title']]
        if case == 'asan-original':
            matches = [row for row in matches if not row['title'].startswith('[정정공고]')]
        assert matches, f'current official DTO missing: {fragment}'
        chosen[case] = next((row for row in matches if row['title'].startswith('[정정공고]')), matches[0])
        row, plan = chosen[case], plan_by_id[chosen[case]['id']]
        check(f'{case}: DTO matches reviewed source identity, hash, date and new version', all(
            row.get(key) == plan.get(key) for key in ['id', 'official_url', 'announcement_date', 'document_hash'])
            and row['version'] == plan['new_version'] and plan['document_hash'] == plan['expected_hash'])
        source_evidence.append({key: row.get(key) for key in ['id', 'title', 'document_hash', 'announcement_date', 'version']})
    eco_plan = plan_by_id[chosen['eco19']['id']]
    check('eco19: repository revision retains both original source prices', eco_plan['expected_prices'] == 2
          and len(eco_plan['revision']['prices']) == 2)
    check('eco19: public DTO has one identical official price', len(chosen['eco19']['prices']) == 1
          and chosen['eco19']['prices'][0]['verification'] == 'official'
          and chosen['eco19']['prices'][0]['amount_krw'] == eco_plan['revision']['prices'][0]['amount_krw'])

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])

        async def create(row, *, midnight=False):
            context = await browser.new_context(viewport={'width': 375, 'height': 900}, timezone_id='Asia/Seoul')
            await context.add_init_script(f'localStorage.setItem({json.dumps(PROFILE_KEY)}, {json.dumps(json.dumps(facts()))})')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda req: assets.add(req.url) if '/assets/' in req.url else None)
            if midnight:
                await page.clock.install(time=datetime(2026, 10, 13, 14, 55, 0, tzinfo=timezone.utc))
            else:
                await page.clock.set_fixed_time(NOW)
            router = Router([deepcopy(row)])
            await page.route('**/api/**', router.handle)
            await page.route('https://fonts.googleapis.com/**', lambda route: route.fulfill(status=200, body=''))
            await page.goto(BASE, wait_until='domcontentloaded', timeout=60000)
            await expect(page.locator('.notice-card[data-evaluation-ready="true"]')).to_have_count(1, timeout=20000)
            return page, page.locator('.notice-card'), router

        async def finish(page, card, router, name):
            check(f'{name}: 375px no horizontal overflow', await page.evaluate(
                'document.documentElement.scrollWidth <= window.innerWidth'))
            before = len(router.requests)
            await page.evaluate("""() => {window.dispatchEvent(new Event('focus')); Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'}); document.dispatchEvent(new Event('visibilitychange')); Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'}); document.dispatchEvent(new Event('visibilitychange'));}""")
            await page.wait_for_timeout(300)
            check(f'{name}: focus does not refetch', before == len(router.requests) and not router.errors)
            requests.extend(router.requests)
            (OUT / f'{name}-text.txt').write_text(await card.inner_text())
            await card.scroll_into_view_if_needed()
            await page.screenshot(path=str(OUT / f'{name}-375.png'))
            await page.context.close()

        for case, row in chosen.items():
            page, card, router = await create(row)
            fold = card.locator('details.notice-content-fold')
            if case in {'eco18', 'eco19'}:
                await expect(fold).to_have_js_property('open', False)
                reason = card.get_by_label('신청 불가 이유', exact=True)
                await expect(reason).to_be_visible()
                await expect(reason).to_contain_text('신청 범위 밖')
                await expect(reason).to_contain_text('부산광역시')
                await expect(reason).to_contain_text('경기도 화성시')
                await expect(card.locator('.schedule-row')).to_be_hidden()
                check(f'{case}: Hwaseong outside Busan is closed with the official reason visible')
                await card.scroll_into_view_if_needed()
                await page.screenshot(path=str(OUT / f'{case}-collapsed-375.png'))
                await fold.locator(':scope > summary').click()
                await expect(fold).to_have_js_property('open', True)
                await expect(card.locator('[data-region-status="outside"]')).to_have_count(1)
                check(f'{case}: expansion shows the current official regional evidence')
                if case == 'eco19':
                    await expect(card.locator('.price-count')).to_contain_text('1개 주택형')
                    await expect(card.locator('.price-row')).to_have_count(1)
                    await expect(card.locator('.price-row')).to_contain_text('공식 자료')
                    await expect(card.locator('.price-row')).not_to_contain_text('자동 추출')
                    check('eco19: mobile table shows only the proven official unit price')
            else:
                await expect(fold).to_have_js_property('open', True)
                await expect(card.locator('.eligibility-summary')).to_contain_text('조건상 가능성 있음')
                await expect(card).not_to_contain_text('서비스 원문 검토 부족')
                check(f'{case}: fulfilled actual source criteria are possible without a fabricated gap')
                await card.get_by_role('button', name='유형별 근거', exact=True).click()
                details = card.locator('.qualification-details')
                await expect(details).to_be_visible()
                await expect(details).not_to_contain_text('미확보 공고 조항')
                await expect(details).not_to_contain_text('서비스 원문 검토 부족')
                check(f'{case}: detailed review does not invent missing source clauses')
                if case.startswith('asan-'):
                    await expect(card.locator('.notice-provider')).to_contain_text(f'자료 갱신 {row["version"]}판')
                    await expect(details).not_to_contain_text('HWP 문서를 로컬에서 변환하지 못했습니다')
                    await expect(details).not_to_contain_text('공식 모집공고문 파일을 내려받지 못했습니다')
                    coverage = [rule for rule in row['rules'] if rule.get('kind') == 'condition_coverage'
                                and rule.get('verification') == 'official' and rule.get('document_hash') == row['document_hash']]
                    check(f'{case}: current source hash has complete review and visible version without HWP/download failure',
                          row['rules_complete'] and coverage and all(rule.get('status') == 'complete' for rule in coverage))
                if case == 'uiwang':
                    await expect(card.get_by_role('region', name='내 지역 판정', exact=True)).to_contain_text('신청지역 충족')
                    await expect(card).not_to_contain_text('공식 지역 조건 확인 필요')
                    await expect(details).to_contain_text('2026-10-12')
                    check('uiwang: capital-region admission retains October 12 criterion')
                contract_rules = [rule for rule in row['rules'] if rule.get('criterion_basis') == 'contract_date']
                if contract_rules:
                    await expect(card.locator('.contract-comparison-note')).to_contain_text('오늘의 내 상태로 미리 비교')
                    await expect(card.locator('.contract-comparison-note')).to_contain_text(KST_TODAY)
                    await expect(details).to_contain_text('오늘 비교일 (한국 시간)')
                    await expect(details).to_contain_text(KST_TODAY)
                    check(f'{case}: contract facts compare October 13 in Korea without a personal contract date')
                announced = [rule for rule in row['rules'] if rule.get('criterion_basis') == 'announcement'
                             and rule.get('criterion_date') == row['announcement_date'] and rule.get('effect') != 'metadata']
                if announced:
                    await expect(details).to_contain_text(row['announcement_date'])
                    check(f'{case}: announcement facts retain their original official date')
            await finish(page, card, router, case)

        unavailable_source = next((row for row in rows if '선운지구다사로움' in row['title']), None)
        if unavailable_source is not None:
            page, card, router = await create(unavailable_source)
            await expect(card.locator('.eligibility-summary')).to_contain_text('조건 비교 자료 확인')
            await expect(card.get_by_role('region', name='내 지역 판정', exact=True)).to_contain_text('공식 지역 조건 확인 필요')
            await expect(card.locator('.qualification-account-summary')).to_contain_text('순위 적용 조건 정리 중')
            await expect(card).not_to_contain_text('조건상 가능성 있음')
            check('unavailable Seonun source stays unresolved without an inferred region or rank')
            await card.get_by_role('button', name='유형별 근거', exact=True).click()
            await expect(card.locator('.qualification-details')).to_contain_text('공고문 찾기')
            await expect(card.locator('.qualification-details')).to_contain_text('첨부 주소')
            check('unavailable Seonun source reports the actual attachment discovery stage')
            await finish(page, card, router, 'seonun-unavailable')

        # Time advances across the Korean midnight while the same browser is
        # open. Public notice dates stay official; contract prechecks use today.
        page, card, router = await create(chosen['wonju'], midnight=True)
        await expect(card.locator('.contract-comparison-note')).to_contain_text('2026-10-13')
        await card.get_by_role('button', name='유형별 근거', exact=True).click()
        before = len(router.requests)
        await page.clock.fast_forward(310000)
        await expect(card.locator('.contract-comparison-note')).to_contain_text('2026-10-14', timeout=10000)
        await expect(card.locator('.qualification-details')).to_contain_text('2026-09-28')
        check('Korean midnight updates contract comparison and preserves official announcement date')
        # A new day changes the public calendar query range. Those GETs may
        # refresh schedules, but must never contain the local applicant facts.
        check('Korean midnight requests contain only public schedule/status parameters', all(
            item['method'] == 'GET' and item['body'] is None
            and set(parse_qs(urlsplit(item['url']).query)) <=
                {'start', 'end', 'page', 'page_size', 'exclude_public_rental', 'application_only', 'price_cap_status'}
            for item in router.requests[before:]))
        await finish(page, card, router, 'wonju-midnight')

        check('served build matches expected asset', any(ASSET in url for url in assets))
        check('no JavaScript exceptions', not errors)
        check('synthetic applicant facts stay browser-only', all(item['method'] == 'GET' and item['body'] is None
            and set(parse_qs(urlsplit(item['url']).query)) <=
                {'start', 'end', 'page', 'page_size', 'exclude_public_rental', 'application_only', 'price_cap_status'}
            and not any(value in item['url'] for value in ['1990-01-01', '41590', '19300000']) for item in requests))
        await browser.close()
    result = {'checks_passed': len(checks), 'checks': checks, 'javascript_errors': errors,
              'synthetic_facts_only': True, 'api_routes_are_public_response_fixtures': True,
              'public_source_file': str(SOURCE), 'reviewed_source_plans': str(PLANS),
              'source_evidence': source_evidence, 'expected_asset': ASSET,
              'served_assets': sorted(assets), 'api_requests': requests, 'fixed_time': NOW.isoformat()}
    (OUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'checks_passed': len(checks), 'result': str(OUT / 'result.json')}))


if __name__ == '__main__':
    asyncio.run(main())
