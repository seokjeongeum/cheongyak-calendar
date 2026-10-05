import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ResultsPane, resultInterestItems } from './ResultsPane'
import { EMPTY_PROFILE, type Notice, type NoticeCompetition, type NoticeRule } from './types'

const now = Date.parse('2026-10-04T03:00:00Z')
const old = '2026-10-01T12:07:21Z'
const allocation: NoticeRule = { kind: 'regional_allocation', effect: 'metadata', supply_type: '일반공급',
  allocation_method: 'all_local_first', local_share_percent: 100,
  local_region: { region_code: '41210', region_name: '경기도 광명시', min_months: 24 },
  verification: 'official', evidence_url: 'https://static.applyhome.co.kr/official.pdf', evidence_text: '일반공급 전량 해당지역 우선' }
const applicant: NoticeRule = { kind: 'applicant_regions', effect: 'metadata', verification: 'official',
  regions: [{ region_code: '11', region_name: '서울특별시' }, { region_code: '28', region_name: '인천광역시' }, { region_code: '41', region_name: '경기도' }],
  local_priority: { region_code: '41210', region_name: '경기도 광명시', min_months: 24 },
  evidence_url: 'https://static.applyhome.co.kr/official.pdf', evidence_text: '수도권 신청자 대상' }
const profile = { ...EMPTY_PROFILE, region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590', movedInDate: '2020-01-01' }
function row(unit: string, closed = true): NoticeCompetition {
  return { source: 'cheongyak_competition', unit_type: unit, rank: 1, residence_area: 'local', residence_area_label: '해당지역',
    supply_type: 'general', supply_count: 10, application_count: 36, competition_rate: '3.60',
    result_status: closed ? 'first_closed' : 'open', result_text: closed ? '1순위 마감(청약 접수 종료)' : '청약 접수중',
    verification: 'official', evidence_url: 'https://www.applyhome.co.kr/official', observed_at: old }
}
function notice(id: string, partial = false): Notice {
  return { id, title: id, category: 'apt', housing_kind: 'private', source: 'cheongyak_home', provider: '공식 사업자',
    address: '경기도 광명시', region_code: '41', region_name: '경기도 광명시', announcement_date: '2026-09-18',
    application_end_date: '2026-10-02', official_url: 'https://www.applyhome.co.kr/official',
    price_cap_status: 'no', events: [], prices: [{ unit_type: '59A', price_kind: 'sale', amount_krw: 879000000 },
      { unit_type: '59B', price_kind: 'sale', amount_krw: 877000000 }], rules: [allocation, applicant],
    updated_at: old, version: 1, competitions: [row('59A'), row('59B', !partial)],
    competition: { status: 'error', last_attempt_at: '2026-10-04T02:00:00Z', last_success_at: old,
      complete: false, unit_types: ['59A', '59B'], proof_invalidated: false } }
}

describe('all results retained before display pagination and counts', () => {
  it('retains an entirely unavailable first API page and every later result', () => {
    const notices = [...Array.from({ length: 100 }, (_, i) => notice(`hidden-${i}`)), notice('after-first-page', true)]
    const visible = resultInterestItems(notices, profile, {}, now, true)
    expect(visible).toHaveLength(101)
    expect(visible[0].notice.id).toBe('hidden-0')
    expect(visible[0].decision.allApplicationsUnavailable).toBe(true)
    expect(visible.at(-1)?.notice.id).toBe('after-first-page')
    expect(visible.reduce((sum, item) => sum + item.rows, 0)).toBe(202)
    expect(visible.at(-1)?.decision.closedUnits).toEqual(['59A'])
  })
  it('preserves source prices and competition rows while exposing accurate full row counts', () => {
    const housing = notice('partial', true)
    const before = JSON.stringify(housing)
    const filtered = resultInterestItems([housing], profile, {}, now, true)
    expect(filtered[0].rows).toBe(2)
    expect(filtered[0].notice.prices.map((price) => price.unit_type)).toEqual(['59A', '59B'])
    expect(JSON.stringify(housing)).toBe(before)
    expect(resultInterestItems([housing], profile, {}, now, false)[0].rows).toBe(2)
  })
  it('ignores legacy hiding choices and always retains all notices and rows', () => {
    const notices = [notice('closed'), notice('partial', true)]
    expect(resultInterestItems(notices, profile, {}, now, true)).toHaveLength(2)
    const restored = resultInterestItems(notices, profile, {}, now, false)
    expect(restored).toHaveLength(2)
    expect(restored.reduce((sum, item) => sum + item.rows, 0)).toBe(4)
    expect(restored[0].decision.allApplicationsUnavailable).toBe(true)
    expect(restored[0].decision.hidden).toBe(false)
    expect(restored[0].decision.closureProofs?.[0].allocationEvidenceText).toBe(allocation.evidence_text)
  })
  it('keeps unknown geography and explicit unknown override; rank need not be known for historical interest', () => {
    expect(resultInterestItems([notice('closed')], EMPTY_PROFILE, {}, now, true)).toHaveLength(1)
    expect(resultInterestItems([notice('closed')], { ...profile, movedInDate: '' }, {}, now, true)).toHaveLength(1)
    expect(resultInterestItems([notice('closed')], profile, { closed: 'unknown' }, now, true)).toHaveLength(1)
    expect(profile.accountType).toBe('unknown')
    expect(resultInterestItems([notice('closed')], profile, {}, now, true)[0].decision.closedUnits).toEqual(['59A', '59B'])
  })
  it('retains correction-pending results even if old rows would otherwise be hidden', () => {
    const housing = notice('invalid')
    housing.competition!.proof_invalidated = true
    expect(resultInterestItems([housing], profile, {}, now, true)[0].rows).toBe(2)
  })
})

describe('results controls', () => {
  it('explains muted retention without an interest switch, rank question or past calendar', () => {
    const html = renderToStaticMarkup(<ResultsPane active today="2026-10-04" refreshVersion={0} capOnly={false}
      category="all" categoryGroup={() => 'private'} profile={EMPTY_PROFILE} residenceOverrides={{}} now={now}
      onSummary={() => undefined} onRefresh={() => undefined} renderCard={() => null} />)
    expect(html).toContain('회색으로 표시')
    expect(html).not.toContain('주택형 숨김')
    expect(html).not.toContain('숨긴 결과 보기')
    expect(html).not.toContain('type="checkbox"')
    expect(html).toContain('경쟁률 0행')
    expect(html).not.toContain('순위기산일')
    expect(html).not.toContain('월간 달력')
  })
})
