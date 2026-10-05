import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { applicationAvailabilityInMonth, applicationDatesInMonth, hasResidenceCandidate, MiniCalendar, NoticeCard, officialApplicationMethodLabel } from './App'
import { applicationEventAvailability, noticeEligibilitySummary } from './eligibility'
import { competitionDecision, resultCompetitionDecision } from './competition'
import { EMPTY_PROFILE, type Notice, type NoticeRule } from './types'
const unchangedFacts = { bank_private: { mode: 'never_changed' as const, date: '' }, bank_national: { mode: 'never_changed' as const, date: '' }, children: { mode: 'never_changed' as const, date: '' }, military: { mode: 'never_changed' as const, date: '' } }

const now = Date.parse('2026-10-04T03:00:00Z')
const home = { ...EMPTY_PROFILE, factChanges: unchangedFacts, region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590', movedInDate: '2020-01-01', dateOfBirth: '1990-01-01', hasChildren: false, pregnant: false }
function rule(kind: string, value: unknown, extra: Partial<NoticeRule> = {}): NoticeRule {
  return { kind, value: value as NoticeRule['value'], verification: 'official', evidence_url: 'https://www.applyhome.co.kr/official', evidence_text: '검증된 공식 조건', ...extra }
}
function housing(rules: NoticeRule[] = [], extra: Partial<Notice> = {}): Notice {
  return { id: 'official', title: '공식 실제 접수 방식 공고', category: 'apt', housing_kind: 'private', source: 'cheongyak_home', provider: '공식 사업자', address: '대구광역시 중구', region_code: '27', region_name: '대구광역시', announcement_date: '2026-10-02', official_url: 'https://www.applyhome.co.kr/official', price_cap_status: 'no', updated_at: null, version: 1,
    events: [{ kind: 'first_priority', label: '1순위', audience: '기타지역', start_date: '2026-10-13', end_date: '2026-10-13' }],
    prices: [{ unit_type: '59A', price_kind: 'sale', amount_krw: 588000000, verification: 'official' }, { unit_type: '59B', price_kind: 'sale', amount_krw: 819800000, verification: 'official' }], rules, rules_complete: true, ...extra }
}
function card(notice: Notice, resultsMode = false, decision = competitionDecision(notice, home, '2026-10-04', undefined, now)) {
  return renderToStaticMarkup(<NoticeCard notice={notice} profile={home} demoMode={false} today="2026-10-04" viewStart="2026-10-04" viewEnd="2026-10-31" decision={decision} now={now} onOverride={() => undefined} onProfile={() => undefined} resultsMode={resultsMode} />)
}
const regionRules = [rule('applicant_regions', null, { effect: 'metadata', regions: [{ region_code: '27', region_name: '대구광역시' }, { region_code: '47', region_name: '경상북도' }], exceptions: [] })]

describe('v4 personal display keeps all public entries', () => {
  it('mutes a confirmed outside-region notice and its event without deleting prices or links', () => {
    const notice = housing(regionRules)
    expect(noticeEligibilitySummary(notice, home).status).toBe('mismatch')
    const html = card(notice)
    expect(html).toContain('notice-unavailable')
    expect(html).toContain('data-unavailable="true"')
    expect(html).toContain('내 조건으로 신청 불가')
    expect(html).toContain('event-unavailable')
    expect(html).toContain('59A')
    expect(html).toContain('59B')
    expect(html).toContain('5억 8,800만원')
    expect(html).toContain('https://www.applyhome.co.kr/official')
    expect(html).toContain('내 조건 입력')
    expect(applicationDatesInMonth([notice], '2026-10', '2026-10-04').has('2026-10-13')).toBe(true)
    expect(hasResidenceCandidate(notice, home, '2026-10-04', '2026-10-31')).toBe(false)
  })
  it('never mutes a card or date because criteria or personal input are missing', () => {
    const notice = housing([rule('age_min', 19)], { rules_complete: false })
    const html = renderToStaticMarkup(<NoticeCard notice={notice} profile={EMPTY_PROFILE} demoMode={false} today="2026-10-04" viewStart="2026-10-04" viewEnd="2026-10-31" decision={{ area: 'unknown', closedUnits: [], reason: null }} now={now} onOverride={() => undefined} onProfile={() => undefined} />)
    expect(html).not.toContain('notice-unavailable')
    expect(html).not.toContain('event-unavailable')
    expect(applicationAvailabilityInMonth([notice], '2026-10', '2026-10-04', EMPTY_PROFILE).get('2026-10-13')).toEqual({ unavailable: false, events: 1 })
  })
  it('marks only a failing special supply and keeps a valid general reception normal', () => {
    const notice = housing([rule('age_min', 19, { supply_type: '일반공급' }), rule('children_min', 2, { supply_type: '다자녀 특별공급', child_age_max: 19 })], { events: [
      { kind: 'first_priority', label: '1순위', start_date: '2026-10-13', end_date: '2026-10-13' }, { kind: 'special', label: '다자녀 특별공급', start_date: '2026-10-12', end_date: '2026-10-12' },
    ] })
    const html = card(notice)
    expect(html).not.toContain('notice-unavailable')
    expect(html).toContain('qualification-mismatch qualification-unavailable')
    expect(applicationEventAvailability(notice.events[0], notice, home).unavailable).toBe(false)
    expect(applicationEventAvailability(notice.events[1], notice, home).unavailable).toBe(true)
    expect(html).not.toContain('순위 적용 조건 정리 중</strong>')
    expect(html).toContain('이 공고의 신청 조건')
  })
  it('keeps a general offering in review when only an incomplete failing special condition was collected', () => {
    const notice = housing([rule('children_min', 2, { supply_type: '다자녀 특별공급', child_age_max: 19 })], { rules_complete: false, events: [
      { kind: 'first_priority', label: '1순위', start_date: '2026-10-13', end_date: '2026-10-13' },
      { kind: 'special', label: '특별공급', start_date: '2026-10-12', end_date: '2026-10-12' },
    ] })
    expect(noticeEligibilitySummary(notice, home).status).toBe('review')
    expect(card(notice)).not.toContain('notice-unavailable')
    expect(applicationEventAvailability(notice.events[1], notice, home).unavailable).toBe(false)
  })
  it('uses a muted calendar dot only when every event for that date is unavailable', () => {
    const closed = housing(regionRules)
    const unknown = housing([], { id: 'unknown' })
    const all = applicationAvailabilityInMonth([closed], '2026-10', '2026-10-04', home, {}, now)
    const mixed = applicationAvailabilityInMonth([closed, unknown], '2026-10', '2026-10-04', home, {}, now)
    expect(all.get('2026-10-13')).toEqual({ unavailable: true, events: 1 })
    expect(mixed.get('2026-10-13')).toEqual({ unavailable: false, events: 2 })
    const html = renderToStaticMarkup(<MiniCalendar month="2026-10" today="2026-10-04" selectedDate={null} notices={[closed]} profile={home} now={now} onMonth={() => undefined} onSelect={() => undefined} />)
    expect(html).toContain('calendar-day unavailable-dot')
    expect(html).toContain('접수 일정 있음 · 내 조건으로 모든 접수 신청 불가')
    expect(html).not.toContain('opacity:')
    expect(html).not.toContain('pointer-events:')
  })
  it('retains every historical competition row and all prices when one unit is closed', () => {
    const observed = '2026-10-01T12:07:21Z'
    const base = { source: 'cheongyak_competition', rank: 1, residence_area: 'local' as const, residence_area_label: '해당지역', supply_type: 'general', supply_count: 10, application_count: 36, verification: 'official', evidence_url: 'https://www.applyhome.co.kr/result', observed_at: observed }
    const notice = housing([], { competitions: [
      { ...base, unit_type: '59A', result_status: 'local_first_closed', competition_rate: '3.60', result_text: '1순위 해당지역 마감(청약 접수 종료)' },
      { ...base, unit_type: '59B', result_status: 'open', competition_rate: '1.10', result_text: '청약 접수중' },
    ], competition: { status: 'error', complete: true, unit_types: ['59A', '59B'], last_attempt_at: '2026-10-04T02:00:00Z', last_success_at: observed, proof_invalidated: false } })
    const decision = resultCompetitionDecision(notice, home, 'other', now)
    const html = card(notice, true, decision)
    expect(decision.closedUnits).toEqual(['59A'])
    expect((html.match(/class="competition-row[^"]*"/g) || [])).toHaveLength(2)
    expect((html.match(/class="price-row"/g) || [])).toHaveLength(2)
    expect(html).toContain('competition-row competition-row-unavailable')
    expect(html).toContain('1.10')
    expect(html).not.toContain('숨겼습니다')
    const corrected = card({ ...notice, competition: { ...notice.competition!, proof_invalidated: true } }, true, resultCompetitionDecision({ ...notice, competition: { ...notice.competition!, proof_invalidated: true } }, home, 'other', now))
    expect(corrected).not.toContain('competition-row-unavailable')
  })
  it('keeps the whole result card under review when all general units close but special types are not collected', () => {
    const observed = '2026-10-01T12:07:21Z'
    const notice = housing([], { events: [{ kind: 'special', label: '특별공급', start_date: '2026-09-29', end_date: '2026-09-29' }],
      competitions: ['59A', '59B'].map((unit_type) => ({ source: 'cheongyak_competition', unit_type, rank: 1, residence_area: 'local', residence_area_label: '해당지역', supply_type: 'general', supply_count: 10, application_count: 36, competition_rate: '3.60', result_status: 'local_first_closed', result_text: '1순위 해당지역 마감(청약 접수 종료)', verification: 'official', evidence_url: 'https://www.applyhome.co.kr/result', observed_at: observed })),
      competition: { status: 'ok', complete: true, unit_types: ['59A', '59B'], last_attempt_at: observed, last_success_at: observed, proof_invalidated: false } })
    const decision = resultCompetitionDecision(notice, home, 'other', now)
    expect(decision.allGeneralUnavailable).toBe(true)
    expect(decision.allApplicationsUnavailable).toBe(false)
    expect(noticeEligibilitySummary(notice, home, decision).status).toBe('review')
    const html = card(notice, true, decision)
    expect(html).not.toContain('notice-unavailable')
    expect((html.match(/class="competition-row competition-row-unavailable"/g) || [])).toHaveLength(2)
    expect((html.match(/class="price-row"/g) || [])).toHaveLength(2)
  })
  it('shows a reception-method badge only with official classification evidence', () => {
    const notice = housing([], { application_method: 'cancelled_resupply', application_method_evidence: { verification: 'official', evidence_text: '계약취소주택 재공급 입주자모집공고' } })
    expect(officialApplicationMethodLabel(notice)).toBe('계약취소 후 재공급')
    expect(card(notice)).toContain('application-method-tag')
    expect(officialApplicationMethodLabel({ ...notice, application_method_evidence: { verification: 'ai_unverified' } })).toBeNull()
  })
})
