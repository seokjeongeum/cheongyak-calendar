"""V9 source-replay browser QA with fictional profiles kept in fresh contexts.

Recorded public rules are routed locally. No production database or real user
storage is used. Reports contain checks and timings, never profile values.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect
import v6_browser_qa
from v6_browser_qa import INSTRUMENTATION, PROFILE, route_public, settled

TARGETS = ['0000061183', '2026000463', '2026950085', '2026930033', '2026910256', '2026950087', '2015122300020823']
PROJECT = 'LH-INCHEON-GAJEONG2-B2'


def fictional_profile() -> dict:
    fake = copy.deepcopy(PROFILE)
    fake.update(parentDateOfBirth='1966-01-01', parentOwnsHome=False,
        parentSpouseOwnsHome=False, spouseOwnsHome=False, familyOwnsHome=False,
        ineligibleRestrictionActive=False, resaleRestrictionActive=False,
        rewinningRestrictionActive=False)
    fake['factChanges'].update({group: {'mode': 'never_changed', 'date': ''}
        for group in ['pregnancy', 'points']})
    entry = {'ineligibleRestrictionActive': False, 'resaleRestrictionActive': False,
        'rewinningRestrictionActive': False, 'asOfDate': '2026-09-01', 'historyConfirmations': []}
    fake['applicationRestrictionFacts'] = {scope: copy.deepcopy(entry)
        for scope in ['applicant', 'applicant_spouse', 'household']}
    return fake


def find_notice(public: dict, number: str) -> dict:
    return next(n for n in public['schedule'] if n['id'] == 'qa-recorded-' + number)


def card_for(page, notice):
    return page.locator('#schedule-panel .notice-card').filter(
        has=page.get_by_role('heading', name=notice['title'], exact=True))


def deadline(notice: dict, today: str) -> str:
    dates = []
    for event in notice['events']:
        if event['kind'] in {'announcement', 'result', 'winner', 'contract'}:
            continue
        if not event.get('end_date') and re.search(r'상시|마감\s*시|소진\s*시|종료일\s*미공개', event['label']):
            continue
        ending = event.get('end_date') or event['start_date']
        if ending >= today:
            dates.append(ending)
    return min(dates) if dates else '9999-12-31'


async def setup(browser, public, args, *, width=375, fake=None, midnight=False):
    context = await browser.new_context(viewport={'width': width, 'height': 1000}, timezone_id='Asia/Seoul')
    fake = fake if fake is not None else fictional_profile()
    await context.add_init_script("localStorage.setItem('cheongyak-profile-v5'," + json.dumps(json.dumps(fake)) + ")")
    await context.add_init_script(INSTRUMENTATION)
    await context.route('**/api/**', lambda route: route_public(route, public))
    page = await context.new_page()
    errors, requests = [], []
    page.on('pageerror', lambda error: errors.append(type(error).__name__))
    page.on('request', lambda r: requests.append({'method': r.method, 'body': bool(r.post_data),
        'path': urlsplit(r.url).path, 'queryNames': sorted(parse_qs(urlsplit(r.url).query))}) if '/api/' in r.url else None)
    if midnight:
        await page.clock.install(time=datetime(2026, 10, 7, 14, 59, 58, tzinfo=timezone.utc))
    else:
        # Pin the documented test date even if the host crosses midnight.
        await page.clock.set_fixed_time(datetime.fromisoformat(args.today + 'T03:00:00+00:00'))
    await page.goto(args.base, wait_until='domcontentloaded')
    await settled(page)
    while await page.locator('#schedule-panel .load-more').count():
        await page.locator('#schedule-panel .load-more').click()
    await settled(page)
    return context, page, errors, requests


def check_log(cohort):
    checks = []
    def check(label, condition=True):
        assert condition, f'{cohort}: {label}'
        checks.append(label)
    return checks, check


async def functional_cohort(browser, public, args, width):
    context, page, errors, requests = await setup(browser, public, args, width=width)
    checks, check = check_log(f'functional/{width}')
    panel = page.locator('#schedule-panel')
    cards = panel.locator('.notice-card')
    await expect(cards).to_have_count(len(public['schedule']))
    check('All recorded notices remain visible, including confirmed mismatches')
    titles = await cards.locator('h4').all_text_contents()
    by_title = {n['title']: deadline(n, args.today) for n in public['schedule']}
    ordered = [by_title[title] for title in titles]
    check('Cards remain sorted by reception deadline', ordered == sorted(ordered))
    check('No separate ongoing section changes ordering', await panel.locator('.current-group').count() == 0)
    check('Unavailable cards remain gray', await panel.locator('.notice-unavailable').count() > 0)
    check('All price rows are retained', await cards.locator('.price-row').count() == sum(len(n['prices']) for n in public['schedule']))
    check('All competition rows are retained', await cards.locator('.competition-row').count() == sum(len(n.get('competitions') or []) for n in public['schedule']))
    check('Reception dates remain marked in the calendar', await page.locator('.calendar-day:has(i)').count() > 0)
    check('No horizontal overflow on the schedule', await page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'))

    gajeong = card_for(page, find_notice(public, '0000061183'))
    await gajeong.scroll_into_view_if_needed()
    text = await gajeong.text_content()
    check('Gajeong separates 308 total homes from 252 offered homes', '단지 전체 308세대' in text and '금회 모집 252세대' in text)
    check('Gajeong displays the four actual offer rows', all(x in text for x in ['74.9500A · 모집 18세대', '84.0000A · 모집 154세대', '84.0000B · 모집 58세대', '84.9800C · 모집 22세대']))
    check('A satisfied reviewed Gajeong branch is conditionally possible', '조건상 가능성 있음' in text)
    check('Gajeong has no generic remaining-document unknown', '문서의 나머지 신청 제한·예외 검토' not in text and '서비스 원문 검토 부족' not in text)
    check('Duplicate applications and the spouse exception are application instructions', '신청 시 지켜야 할 조건' in text and '동일 블록 중복 신청·부부 예외' in text)
    await gajeong.locator('.details-button').click()
    details = gajeong.locator('.qualification-details')
    await expect(details).to_be_visible()
    detail_text = await details.text_content()
    check('Gajeong keeps the official September 23 cutoff', '2026-09-23' in detail_text)
    check('Paperwork/payment are not counted as missing admission conditions', await details.locator('.qualification-source-gap').count() == 0)
    await gajeong.locator('.details-button').click()

    hyangnam = card_for(page, find_notice(public, '2026000463'))
    await hyangnam.scroll_into_view_if_needed()
    check('Hyangnam restores Hwaseong applicant priority', await hyangnam.locator('.notice-region-decision[data-region-status="local"]').count() > 0)
    hyangnam_text = await hyangnam.text_content()
    check('Hyangnam preserves its separate special-supply quota', '화성시 및 경기도 50%' in hyangnam_text and '서울특별시, 인천광역시 50%' in hyangnam_text)
    check('Hyangnam remains within the viewport at this width', await page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'))
    check('Service review reasons appear once in the notice summary', await hyangnam.locator('[aria-label="서비스 원문 검토 부족"]').count() == 1)
    check('The service reason lists concrete missing clauses', '재당첨·청약 제한 및 법령 예외' in hyangnam_text and '문서의 나머지 신청 제한·예외 검토' not in hyangnam_text)
    elder = hyangnam.locator('.qualification-supply-brief').filter(has=page.get_by_text('노부모부양 특별공급', exact=True))
    check('A definite 60 below 65 comparison fails the elder-parent path', '내 입력 60세 · 공고 요구 >= 65세' in (await elder.text_content()) and await elder.locator('.qualification-input-action').count() == 0)
    check('Other supply paths continue to request their own missing facts', await hyangnam.locator('.qualification-supply-brief').filter(has=page.get_by_text('생애최초 특별공급', exact=True)).locator('.qualification-input-action').count() > 0)
    await hyangnam.locator('.details-button').click()
    check('Expanding details keeps one service review section', await hyangnam.locator('[aria-label="서비스 원문 검토 부족"]').count() == 1)
    check('Failed elder-parent details have no extra required questions', await hyangnam.locator('.qualification-supply').filter(has=page.get_by_role('heading', name=re.compile('노부모부양 특별공급'))).locator('.qualification-input-action').count() == 0)
    await hyangnam.locator('.details-button').click()

    for number in ['2026950085', '2026930033', '2026910256', '2026950087']:
        notice = find_notice(public, number)
        card = card_for(page, notice)
        await card.scroll_into_view_if_needed()
        check(f'{number}: exact latest attachment has a region comparison', await card.locator('.notice-region-decision[data-region-status="source_gap"]').count() == 0)
        check(f'{number}: announcement cutoff is preserved', notice['announcement_date'] in (await card.locator('.notice-region-decisions').text_content()))
        check(f'{number}: no horizontal overflow', await page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'))
        if number in ['2026950085', '2026950087']:
            await card.locator('.details-button').click()
            check(f'{number}: a completely reviewed PRMO has no false service review gap', await card.locator('.qualification-source-gap').count() == 0)
            await card.locator('.details-button').click()
    check('Doan evaluates its Daejeon restriction instead of guessing from an address', await card_for(page, find_notice(public, '2026930033')).locator('.notice-region-decision[data-region-status="outside"]').count() > 0)

    gyeongsan = card_for(page, find_notice(public, '2015122300020823'))
    await gyeongsan.scroll_into_view_if_needed()
    text = await gyeongsan.text_content()
    check('Gyeongsan previews current facts on the Korean date', f'오늘의 내 상태로 미리 비교 · 한국 시간 {args.today}' in text)
    check('Gyeongsan retains its future official contract period', '공식 계약기간 2026-10-27 – 2027-08-31' in text)
    check('Future contract comparison states the continuation assumption', '실제 계약일까지 현재 상태가 유지된다는 전제로' in text)
    check('Contract facts compare today without a personal contract input', '공식 계약일을 확인하지 못해' not in text and '조건상 가능성 있음' in text)
    await gyeongsan.locator('.details-button').click()
    text = await gyeongsan.locator('.qualification-details').text_content()
    check('Contract reasons explicitly label today as the comparison day', '오늘 비교일 (한국 시간)' in text and args.today in text)
    await gyeongsan.locator('.details-button').click()

    before = len(requests)
    await page.get_by_role('button', name='내 조건 설정', exact=True).click()
    dialog = page.get_by_role('dialog')
    await dialog.locator('.step-progress').get_by_role('button', name=re.compile('소득·자산')).click()
    await dialog.locator('[data-profile-field="annualIncomeKrw"] input').fill('80000000')
    await dialog.locator('.dialog-close').click()
    await settled(page)
    check('Editing and evaluating a fictional profile sends no API request', len(requests) == before)
    check('Profile changes retain every notice and gray mismatch', await cards.count() == len(public['schedule']) and await panel.locator('.notice-unavailable').count() > 0)
    await page.evaluate("window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'))")
    await page.wait_for_timeout(100)
    check('Focus return alone does not fetch', len(requests) == before)
    allowed = {'start', 'end', 'page', 'page_size', 'cap_only', 'application_only', 'exclude_public_rental', 'category', 'view'}
    check('API requests contain public GET filters only', all(r['method'] == 'GET' and not r['body'] and set(r['queryNames']) <= allowed for r in requests))
    check('No JavaScript runtime errors', not errors)
    if width == 375 and args.screenshots:
        folder = Path(args.screenshots)
        folder.mkdir(parents=True, exist_ok=True)
        await page.add_style_tag(content='.site-header { visibility:hidden !important; }')
        await gajeong.locator('.qualification-brief').screenshot(path=str(folder / ('v9-gajeong-mobile-' + args.today + '.png')))
        await gyeongsan.scroll_into_view_if_needed()
        await gyeongsan.screenshot(path=str(folder / ('v9-contract-mobile-' + args.today + '.png')))
    result = {'width': width, 'passed': len(checks), 'checks': checks,
        'noticeCount': len(public['schedule']), 'profileValuesInReport': False}
    await context.close()
    return result


async def gajeong_cases(browser, public, args):
    checks, check = check_log('gajeong')
    subset = {**public, 'schedule': [find_notice(public, '0000061183')], 'results': []}
    def event(kind, day):
        return {'id': kind, 'personId': 'applicant', 'projectId': PROJECT, 'eventKind': kind, 'eventDate': day}
    variants = [('returned_resident', {'currentlyDomesticResident': True, 'overseasContinuousDays': '120'}, 'possible'),
        ('90_days_abroad', {'currentlyDomesticResident': False, 'overseasContinuousDays': '90'}, 'possible'),
        ('91_days_single_household', {'currentlyDomesticResident': False, 'overseasContinuousDays': '91', 'overseasOnlyApplicantForLivelihood': True}, 'mismatch'),
        ('original_winner_only', {'applicationHistoryPresence': True, 'applicationHistoryEvents': [event('winning', '2026-04-20')]}, 'possible'),
        ('ineligible_history_without_contract', {'ineligibleRestrictionActive': True}, 'possible')]
    right = {'id': 'qa-original-right', 'projectId': PROJECT, 'ownerMemberId': 'applicant',
        'ownerRelation': 'applicant', 'propertyKind': 'presale_right', 'underlyingPropertyKind': 'apartment',
        'acquiredDate': '2026-05-01', 'acquisitionMethod': 'purchase', 'areaSqm': '74', 'propertyRegionCode': '28'}
    variants.extend([
        ('original_winner_and_current_contract', {'applicationHistoryPresence': True,
            'applicationHistoryEvents': [event('winning', '2026-04-20'), event('contract', '2026-05-01')],
            'ownershipFacts': [right]}, 'mismatch'),
        ('original_contract_disposed_before_cutoff', {'applicationHistoryPresence': True,
            'applicationHistoryEvents': [event('winning', '2026-04-20'), event('contract', '2026-05-01')],
            'ownershipFacts': [{**right, 'disposedDate': '2026-09-01'}]}, 'possible')])
    for name, change, expected in variants:
        fake = fictional_profile()
        fake.update(change)
        if name == 'ineligible_history_without_contract':
            fake['applicationRestrictionFacts']['applicant']['ineligibleRestrictionActive'] = True
        context, page, errors, requests = await setup(browser, subset, args, fake=fake)
        card = page.locator('.notice-card')
        check(name + ': matches the source branch', await card.locator('.qualification-supply-brief.qualification-' + expected).count() == 1)
        check(name + ': no browser error', not errors)
        await context.close()
    # A parent-owned home uses the existing exact member/DOB ownership link.
    fake = fictional_profile()
    fake['householdMembers'] = [{'id': 'qa-parent', 'relation': 'applicant_parent', 'register': 'applicant',
        'dateOfBirth': '1966-01-01', 'ownsHome': True, 'previouslyOwnedHome': True}]
    fake['ownershipFacts'] = [{'id': 'qa-parent-home', 'ownerMemberId': 'qa-parent', 'ownerRelation': 'ascendant',
        'propertyKind': 'apartment', 'areaSqm': '84', 'acquiredDate': '2010-01-01', 'acquisitionMethod': 'purchase',
        'standardResidentialBuilding': True, 'ownedShare': False}]
    context, page, errors, requests = await setup(browser, subset, args, fake=fake)
    card = page.locator('.notice-card')
    await card.locator('.details-button').click()
    check('The 60-plus parent ownership exception remains valid', await card.locator('.qualification-supply-brief.qualification-possible').count() == 1 and '제53조 제6호' in (await card.text_content()))
    await context.close()
    return {'passed': len(checks), 'checks': checks, 'profileValuesInReport': False}


async def precise_history_cohort(browser, public, args):
    subset = {**public, 'schedule': [find_notice(public, '0000061183')], 'results': []}
    checks, check = check_log('precise_history')
    missing = fictional_profile()
    missing['applicationRestrictionFacts'] = {}
    context, page, errors, requests = await setup(browser, subset, args, fake=missing)
    check('A missing common current fact is explicitly labeled as missing input', '내 입력 부족 · 공급질서 교란·전매 위반 청약 제한' in (await page.locator('.notice-card').text_content()))
    await context.close()
    fake = fictional_profile()
    fake['factChanges'].pop('restrictions')
    fake['applicationRestrictionFacts']['applicant']['asOfDate'] = args.today
    context, page, errors, requests = await setup(browser, subset, args, fake=fake)
    card = page.locator('.notice-card')
    check('An unknown past restriction is separate from missing current input', '과거 사실 미확인 · 청약 제한 상태 변경일' in (await card.text_content()))
    action = card.locator('.qualification-input-action').filter(has_text='청약 제한 상태 변경일 입력하기').first
    await action.click()
    dialog = page.get_by_role('dialog')
    history = dialog.locator('[data-fact-group="restrictions"] select')
    await expect(history).to_be_focused()
    check('The precise past-fact action focuses its actual change-history control')
    await history.select_option('never_changed')
    await dialog.locator('.dialog-close').click()
    await settled(page)
    check('One saved common history resolves the repeated past-fact question', await card.locator('.qualification-supply-brief.qualification-possible').count() == 1 and '청약 제한 상태 변경일 입력하기' not in (await card.text_content()))
    check('Saving common history sends no profile request', all(r['method'] == 'GET' and not r['body'] for r in requests))
    await context.close()
    return {'passed': len(checks), 'checks': checks, 'profileValuesInReport': False}


async def failure_cohort(browser, public, args):
    """A marked fictional decode failure verifies failure-stage presentation."""
    notice = copy.deepcopy(find_notice(public, '2026950085'))
    notice.update(id='qa-fictional-v9-decode-failure', title='[QA 가상 문서 처리 실패] 원문 텍스트 미확보',
        document_hash=None, rules_complete=False, offered_supplies=None, selection_methods=None,
        qualification_context=None, rank_applicability=None)
    notice['rules'] = [{'kind': 'document_diagnostics', 'effect': 'metadata', 'verification': 'official',
        'status': 'unreadable', 'diagnostics': [{'stage': 'decode', 'code': 'document_no_text',
            'status': 'failed', 'message': '문서에서 신청 조건을 읽을 수 있는 텍스트를 확보하지 못했습니다.',
            'missing_items': ['공식 신청 지역', '필수 신청 제한·예외'], 'url': notice['official_url']}]}]
    subset = {**public, 'schedule': [notice], 'results': []}
    context, page, errors, requests = await setup(browser, subset, args)
    checks, check = check_log('marked_fictional_source_failure')
    card = page.locator('.notice-card')
    check('A source failure keeps the notice visible instead of guessing eligibility', await card.count() == 1 and await card.locator('.notice-region-decision[data-region-status="source_gap"]').count() == 1)
    check('A source failure is labeled separately from missing personal input', await card.locator('[aria-label="서비스 원문 검토 부족"]').count() == 1)
    await card.locator('.details-button').click()
    text = await card.locator('.qualification-source-gap').text_content()
    check('Failure details identify the decode stage and missing clauses', '문서 형식 변환·텍스트 추출' in text and '공식 신청 지역' in text and '필수 신청 제한·예외' in text)
    check('An expanded failed notice has one service review section', await card.locator('[aria-label="서비스 원문 검토 부족"]').count() == 1)
    check('The source failure is not converted into a profile input action', await card.locator('.qualification-source-gap .qualification-input-action').count() == 0)
    check('A failed source does not cause browser runtime errors', not errors)
    await context.close()
    return {'passed': len(checks), 'checks': checks, 'fictionalFailureScenario': True, 'profileValuesInReport': False}


async def support_date_cohort(browser, public, args):
    fake = fictional_profile()
    fake.update(parentDateOfBirth='1950-01-01', parentSameRegister=True, parentSupportSince='')
    fake['householdMembers'] = [{'id': 'qa-support-parent', 'relation': 'applicant_parent',
        'register': 'applicant', 'dateOfBirth': '1950-01-01', 'ownsHome': False, 'previouslyOwnedHome': False}]
    fake['applicationHistoryPeople'] = ['applicant', 'qa-support-parent']
    subset = {**public, 'schedule': [find_notice(public, '2026000463'), find_notice(public, '2026000468')], 'results': []}
    context, page, errors, requests = await setup(browser, subset, args, fake=fake)
    checks, check = check_log('specific_support_date')
    card = card_for(page, subset['schedule'][0])
    await card.locator('.details-button').click()
    elder = card.locator('.qualification-supply').filter(has=page.get_by_role('heading', name=re.compile('노부모부양 특별공급')))
    action = card.locator('.qualification-details .qualification-input-action').filter(has_text='부양 시작일 입력하기').first
    check('The remaining elder-parent question names the actual support start date', await action.count() == 1)
    before = len(requests)
    await action.click()
    dialog = page.get_by_role('dialog')
    start = dialog.locator('[data-profile-field="parentSupportSince"] input')
    await expect(start).to_be_focused()
    check('The support-start action focuses the actual common date field')
    await start.fill('2023-10-03')
    await dialog.locator('.dialog-close').click()
    await settled(page)
    check('The announcement cutoff rejects 35 completed support months', '내 입력 35개월 · 공고 요구 >= 36개월' in (await card.locator('.qualification-details').text_content()) and await elder.locator('.qualification-badge.qualification-mismatch').count() == 1)
    await page.get_by_role('button', name='내 조건 설정', exact=True).click()
    dialog = page.get_by_role('dialog')
    await dialog.locator('.step-progress').get_by_role('button', name=re.compile('특별공급')).click()
    await dialog.locator('[data-profile-field="parentSupportSince"] input').fill('2023-10-02')
    await dialog.locator('.dialog-close').click()
    await settled(page)
    check('The same announcement cutoff accepts exactly 36 completed months', '내 입력 36개월 · 공고 요구 >= 36개월' in (await card.locator('.qualification-details').text_content()))
    check('The saved support start is reused instead of asking the date again', await card.locator('.qualification-input-action').filter(has_text='부양 시작일 입력하기').count() == 0)
    other = card_for(page, subset['schedule'][1])
    await other.scroll_into_view_if_needed()
    await other.locator('.details-button').click()
    check('Another official elder-parent notice reuses the saved common support date', '충족 · 부모 연속 부양 기간' in (await other.locator('.qualification-details').text_content()) and await other.locator('.qualification-input-action').filter(has_text='부양 시작일 입력하기').count() == 0)
    check('Support-date input stays in the browser', len(requests) == before)
    check('Support-date routing has no runtime errors', not errors)
    await context.close()
    return {'passed': len(checks), 'checks': checks, 'profileValuesInReport': False}


async def midnight_cohort(browser, public, args):
    # The birth date is fictional and chosen to expose a real cutoff transition.
    subset = {**public, 'schedule': [find_notice(public, '2015122300020823'), find_notice(public, '0000061183')], 'results': []}
    fake = fictional_profile()
    fake['dateOfBirth'] = '2007-10-08'
    context, page, errors, requests = await setup(browser, subset, args, fake=fake, midnight=True)
    checks, check = check_log('midnight')
    contract = card_for(page, subset['schedule'][0])
    announcement = card_for(page, subset['schedule'][1])
    check('Before midnight the contract preview uses October 7 and age 18', '한국 시간 2026-10-07' in (await contract.text_content()) and await contract.locator('.qualification-supply-brief.qualification-mismatch').count() == 1)
    before = len(requests)
    await page.clock.fast_forward(3_000)
    await page.wait_for_function("document.querySelector('.contract-comparison-note')?.textContent?.includes('2026-10-08') || [...document.querySelectorAll('.notice-card')].some(c=>c.textContent.includes('오늘의 내 상태로 미리 비교 · 한국 시간 2026-10-08'))")
    await settled(page)
    check('Actual Korean midnight advances the preview date', '한국 시간 2026-10-08' in (await contract.text_content()))
    check('The birthday transition reevaluates eligibility using today', await contract.locator('.qualification-supply-brief.qualification-possible').count() == 1)
    check('Midnight keeps the future official contract period unchanged', '2026-10-27 – 2027-08-31' in (await contract.text_content()))
    check('Announcement-date requirements retain their original cutoff', '2026-09-23' in (await announcement.locator('.notice-region-decisions').text_content()))
    check('Midnight queries the new public calendar window', len(requests) > before)
    check('Midnight has no browser runtime errors', not errors)
    await context.close()
    return {'passed': len(checks), 'checks': checks, 'profileValuesInReport': False}


async def main(args):
    v6_browser_qa.TODAY = date.fromisoformat(args.today)
    public = json.loads(Path(args.snapshot).read_text())
    for number in TARGETS:
        find_notice(public, number)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        cohorts = []
        for width in [1280, 375]:
            result = await functional_cohort(browser, public, args, width)
            cohorts.append(result)
            print(json.dumps({'cohort': 'functional', 'width': width, 'passed': result['passed']}), flush=True)
        cohorts.append(await gajeong_cases(browser, public, args))
        cohorts.append(await precise_history_cohort(browser, public, args))
        cohorts.append(await failure_cohort(browser, public, args))
        cohorts.append(await support_date_cohort(browser, public, args))
        cohorts.append(await midnight_cohort(browser, public, args))
        await browser.close()
    report = {'date': args.today, 'base': args.base, 'passed': sum(c['passed'] for c in cohorts),
        'cohorts': cohorts, 'profileValuesInReport': False, 'productionDatabaseTouched': False,
        'dataProvenance': public['provenance']}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'cohorts': len(cohorts), 'output': args.output}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:5176')
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--today', default='2026-10-07')
    parser.add_argument('--output', required=True)
    parser.add_argument('--screenshots')
    asyncio.run(main(parser.parse_args()))
