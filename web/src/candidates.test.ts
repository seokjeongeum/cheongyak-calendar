import { describe, expect, it } from 'vitest'
import { candidateExplanation, candidateLabel } from './candidates'
import { regionDecision } from './qualification'
import { EMPTY_PROFILE, type Notice, type NoticeRule } from './types'

const source = 'https://www.applyhome.co.kr/notice'
const profile = {
  ...EMPTY_PROFILE, region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590',
  movedInDate: '2026-10-01', districtMovedInDate: '',
}
const scope = (extra: Partial<NoticeRule> = {}): NoticeRule => ({
  kind: 'applicant_regions', effect: 'metadata', verification: 'official',
  regions: [{ region_code: '41', region_name: '경기도' }, { region_code: '11', region_name: '서울특별시' }],
  scope_complete: true, priority_applicable: false, criterion_date: '2026-10-06',
  evidence_url: source, ...extra,
})
const duration = (extra: Partial<NoticeRule> = {}): NoticeRule => ({
  kind: 'residence_months', value: 12, region_code: '41', region_name: '경기도',
  verification: 'official', evidence_url: source, ...extra,
})
const notice = (rules: NoticeRule[] = [scope()]): Notice => ({
  id: 'synthetic-reception', title: '새 모집공고', category: 'apt', source: 'cheongyak_home', provider: '공급기관',
  address: '경기도 성남시', region_code: '41130', region_name: '성남시', announcement_date: '2026-10-06',
  official_url: source, price_cap_status: 'unknown', events: [], prices: [], rules,
  updated_at: null, version: 1,
})
const admittedLabel = '신청지역 충족 · 접수일 후보'

describe('candidate copy for official scopes without a duration requirement', () => {
  it('uses satisfied applicant scope even with a short province stay and no city residence start', () => {
    const item = notice()
    expect(regionDecision(item, profile).status).toBe('not_divided')
    expect(candidateLabel(item, profile)).toBe(admittedLabel)
    expect(candidateExplanation(item, profile)).toContain('공식 신청 지역 범위에 포함됩니다')
    expect(candidateExplanation(item, profile)).toContain('나머지 신청 자격은 아래에서 별도로 비교합니다')
    expect(candidateExplanation(item, profile)).not.toContain('확인이 필요')
  })

  it('also handles an explicit undivided scope and equivalent scopes shared by offers', () => {
    const item = notice([
      scope({ supply_type: '일반공급', priority_applicable: undefined, priority_division: 'none' }),
      scope({ supply_type: '생애최초 특별공급', priority_applicable: undefined, priority_division: 'none' }),
    ])
    expect(regionDecision(item, profile).status).toBe('not_divided')
    expect(candidateLabel(item, profile)).toBe(admittedLabel)
  })

  it.each([
    duration({ value: null }),
    duration({ region_code: '41590', region_name: '화성시' }),
    duration({ supply_type: '일반공급' }),
    duration({ unit_type: '84' }),
    duration({ verification: 'ai_unverified' }),
    { kind: 'all', verification: 'official', conditions: [duration({ verification: undefined })] },
    { kind: 'any', verification: 'official', conditions: [{ kind: 'all', conditions: [duration({ value: null })] }] },
    { kind: 'age_min', value: 19, verification: 'official', exceptions: [duration()] },
  ] as NoticeRule[])('preserves review when an actual duration is unresolved or separately scoped: %j', (rule) => {
    const item = notice([scope(), rule])
    expect(regionDecision(item, profile).status).toBe('not_divided')
    expect(candidateLabel(item, profile)).toBe('지역 일치 · 기간 확인 필요')
    expect(candidateExplanation(item, profile)).toContain('기간은 확인이 필요합니다')
  })

  it.each([
    { regions: [{ region_code: '41', region_name: '경기도', min_months: 12 }] },
    { local_priority: { region_code: '41', region_name: '경기도', min_months: 12 } },
    { other_gyeonggi: { regions: [{ region_code: '41', region_name: '경기도', min_months: 12 }] } },
  ])('does not treat regional duration metadata as an absent requirement: %j', (extra) => {
    const item = notice([scope(extra)])
    expect(candidateLabel(item, profile)).toBe('지역 일치 · 기간 확인 필요')
    expect(candidateExplanation(item, profile)).toContain('기간은 확인이 필요합니다')
  })

  it('keeps fulfilled duration and failed priority copy', () => {
    const longStay = { ...profile, movedInDate: '2020-01-01' }
    expect(candidateLabel(notice([scope(), duration()]), longStay)).toBe('거주기간 충족 후보')
    const priority = notice([scope(), duration({ effect: 'priority' })])
    expect(candidateLabel(priority, profile)).toBe('지역 우선순위 미충족 · 접수일 확인')
    expect(candidateExplanation(priority, profile)).toContain('지역 우선공급 기간은 충족하지 않습니다')
  })

  it.each([
    { verification: 'ai_unverified' },
    { scope_complete: false },
    { priority_applicable: undefined },
    { regions: [{ region_code: '11', region_name: '서울특별시' }] },
  ] as Partial<NoticeRule>[])('does not assert satisfaction for an unverified, incomplete or outside scope: %j', (extra) => {
    const item = notice([scope(extra)])
    expect(candidateLabel(item, profile)).toBe('지역 일치 · 기간 확인 필요')
    expect(candidateExplanation(item, profile)).toContain('기간은 확인이 필요합니다')
  })
})
