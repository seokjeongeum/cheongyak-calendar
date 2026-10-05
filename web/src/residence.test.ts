import { describe, expect, it } from 'vitest'
import { applicationDatesInMonth, briefReasons, candidateExplanation, candidateLabel, eventCandidate, hasResidenceCandidate, msUntilNextKstMidnight } from './App'
import { EMPTY_PROFILE, type Notice, type NoticeRule } from './types'

const localDay = { kind: 'first_priority', label: '1순위', start_date: '2026-10-01', end_date: '2026-10-01', audience: '해당지역' }
const otherDay = { kind: 'first_priority', label: '1순위', start_date: '2026-10-02', end_date: '2026-10-02', audience: '기타지역' }

function notice(rule: NoticeRule): Notice {
  return {
    id: 'priority-notice', title: '성남 공공주택', category: 'public_rental', source: 'lh', provider: 'LH',
    address: '경기도 성남시', region_code: '41', region_name: '경기도 성남시',
    announcement_date: '2026-09-25', official_url: 'https://www.lh.or.kr/notice', price_cap_status: 'not_applicable',
    events: [localDay, otherDay], prices: [], rules: [rule], rules_complete: false, updated_at: null, version: 1,
  }
}

describe('residence-based reception date hints', () => {
  it('does not infer an other-region audience from a city priority condition alone', () => {
    const housing = notice({
      kind: 'residence_months', value: 12, operator: '>=', region_name: '성남시',
      supply_type: '일반공급', effect: 'priority', verification: 'official',
    })
    const profile = { ...EMPTY_PROFILE, region: '경기도', district: '성남시', movedInDate: '2026-07-01' }
    expect(eventCandidate(localDay, housing, profile)).toBe(true)
    expect(eventCandidate(otherDay, housing, profile)).toBe(false)
    expect(candidateLabel(housing, profile)).toContain('확인 필요')
  })

  it('distinguishes an explicit province priority duration from an eligibility condition', () => {
    const profile = { ...EMPTY_PROFILE, region: '경기도', district: '성남시', movedInDate: '2026-07-01' }
    const priority = notice({
      kind: 'residence_months', value: 12, region_name: '경기도',
      effect: 'priority', verification: 'official',
    })
    expect(eventCandidate(otherDay, priority, profile)).toBe(false)
    expect(candidateLabel(priority, profile)).toContain('우선순위 미충족')

    const requirement = notice({
      kind: 'residence_months', value: 12, region_name: '경기도', verification: 'official',
    })
    expect(eventCandidate(localDay, requirement, profile)).toBe(false)
    expect(eventCandidate(otherDay, requirement, profile)).toBe(false)
  })

  it('uses the official applicant scope and city residence cutoff to identify an admitted other-region candidate', () => {
    const housing = notice({ kind: 'applicant_regions', effect: 'metadata', verification: 'official', evidence_url: 'https://www.lh.or.kr/notice',
      regions: [{ region_code: '41', region_name: '경기도' }, { region_code: '11', region_name: '서울특별시' }],
      local_priority: { region_code: '41130', region_name: '성남시', min_months: 12 },
    })
    housing.rules.push({ kind: 'residence_months', value: 12, effect: 'priority', region_code: '41130', region_name: '성남시', verification: 'official' })
    const profile = { ...EMPTY_PROFILE, region: '경기도', regionCode: '41', district: '성남시', districtCode: '41130', movedInDate: '2020-01-01', districtMovedInDate: '2026-07-01' }
    expect(eventCandidate(otherDay, housing, profile)).toBe(true)
    expect(eventCandidate(localDay, housing, profile)).toBe(false)
    const outside = { ...profile, region: '부산광역시', regionCode: '26', district: '중구', districtCode: '26110' }
    expect(eventCandidate(otherDay, housing, outside)).toBe(false)
  })
})

describe('monthly calendar application dates', () => {
  it('marks every displayed day of a reception period that began more than 32 days earlier', () => {
    const housing = notice({ kind: 'homeless', value: true, verification: 'official' })
    housing.category = 'public_sale'
    housing.events = [
      { kind: 'general', label: '접수', start_date: '2026-07-01', end_date: '2026-10-15' },
      { kind: 'announcement', label: '당첨자 발표', start_date: '2026-09-30', end_date: null },
    ]
    const dates = applicationDatesInMonth([housing], '2026-09')
    expect(dates.size).toBe(30)
    expect(dates.has('2026-09-01')).toBe(true)
    expect(dates.has('2026-09-30')).toBe(true)
  })

  it('shows only today and later and excludes public rental while retaining private rental', () => {
    const publicRental = notice({ kind: 'homeless', value: true, verification: 'official' })
    publicRental.events = [{ kind: 'application', label: '접수', start_date: '2026-09-29', end_date: '2026-10-03' }]
    const privateRental = { ...publicRental, id: 'private-rental', category: 'private_rental' }
    const dates = applicationDatesInMonth([publicRental, privateRental], '2026-09', '2026-09-30')
    expect([...dates]).toEqual(['2026-09-30'])
    expect(applicationDatesInMonth([publicRental], '2026-09', '2026-09-30').size).toBe(0)
  })
})

describe('current reception window', () => {
  it('does not count an expired local reception as a residence candidate', () => {
    const housing = notice({ kind: 'homeless', value: true, verification: 'official' })
    housing.category = 'public_sale'
    housing.events = [
      { kind: 'first_priority', label: '해당지역', start_date: '2026-09-20', end_date: '2026-09-20', audience: '해당지역' },
      { kind: 'first_priority', label: '다른 권역', start_date: '2026-10-03', end_date: '2026-10-03', audience: '기타지역 · 부산' },
    ]
    const profile = { ...EMPTY_PROFILE, region: '경기도', district: '성남시' }
    expect(hasResidenceCandidate(housing, profile, '2026-09-30', '2026-10-31')).toBe(false)
  })

  it('schedules the next refresh at Korean midnight even when UTC is on the previous date', () => {
    expect(msUntilNextKstMidnight(Date.parse('2026-09-30T14:59:00Z'))).toBe(61_000)
    expect(msUntilNextKstMidnight(Date.parse('2026-09-30T15:00:00Z'))).toBe(86_401_000)
  })
})


describe('candidate evidence consistency', () => {
  it('uses the original qualification date for a corrected notice', () => {
    const housing = notice({ kind: 'residence_months', value: 12, region_name: '경기도', effect: 'priority', verification: 'official' })
    housing.announcement_date = '2027-09-25'
    housing.qualification_context = { public_housing: null, speculation_zone: null, subscription_overheated: null, weakened_area: null, capital_region: true, original_announcement_date: '2026-09-25' }
    expect(candidateLabel(housing, { ...EMPTY_PROFILE, region: '경기도', district: '성남시', movedInDate: '2026-01-01' })).toContain('미충족')
  })
  it('explains a failed priority duration even when the ordinary residence requirement passed', () => {
    const housing = notice({ kind: 'residence_months', value: 3, region_name: '경기도', verification: 'official' })
    housing.rules.push({ kind: 'residence_months', value: 12, region_name: '경기도', effect: 'priority', verification: 'official', criterion_date: '2026-09-25' })
    const person = { ...EMPTY_PROFILE, region: '경기도', district: '성남시', movedInDate: '2026-01-01' }
    expect(candidateExplanation(housing, person)).toContain('우선공급 기간은 충족하지 않습니다')
  })
  it('keeps a missing condition visible alongside several satisfied conditions', () => {
    const reasons = [1, 2, 3].map((i) => ({ status: 'pass' as const, label: `충족 ${i}`, detail: '' }))
    const missing = { status: 'review' as const, label: '미입력', detail: '' }
    expect(briefReasons([...reasons, missing])).toContain(missing)
    expect(briefReasons([...reasons, missing]).some((reason) => reason.status === 'pass')).toBe(true)
  })
})
