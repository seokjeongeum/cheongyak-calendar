import { describe, expect, it } from 'vitest'
import { applicantRegionEligibility, regionDecision } from './qualification'
import { EMPTY_PROFILE, type Notice, type NoticeRule } from './types'

const source = 'https://www.applyhome.co.kr/notice'
const provinces = [
  { region_code: '41', region_name: '경기도' },
  { region_code: '11', region_name: '서울특별시' },
  { region_code: '28', region_name: '인천광역시' },
]
const profile = {
  ...EMPTY_PROFILE, region: '경기도', regionCode: '41', district: '화성시',
  districtCode: '41590', movedInDate: '2020-01-01', districtMovedInDate: '2020-01-01',
}
const metadata = (supplyType: string, extra: Partial<NoticeRule> = {}): NoticeRule => ({
  kind: 'applicant_regions', effect: 'metadata', verification: 'official',
  supply_type: supplyType, regions: provinces, scope_complete: true,
  priority_applicable: false, exceptions: [], criterion_date: '2026-10-02',
  evidence_url: source, ...extra,
})
const notice = (rules: NoticeRule[]): Notice => ({
  id: 'regional-scope-equivalence', title: '새 모집공고', category: 'apt',
  source: 'cheongyak_home', provider: '공급기관', address: null, region_code: null,
  region_name: null, announcement_date: '2026-10-02', official_url: source,
  price_cap_status: 'unknown', events: [], prices: [], rules, updated_at: null, version: 1,
})
const scopedNotice = (second: Partial<NoticeRule> = {}) => notice([
  metadata('일반공급'),
  metadata('생애최초 특별공급', { regions: [...provinces].reverse(), ...second }),
])

describe('equivalent official regional OR scopes', () => {
  it('uses a shared notice scope regardless of printed province order without mutating its source', () => {
    const item = scopedNotice()
    const before = JSON.stringify(item.rules)
    expect(applicantRegionEligibility(item, profile)?.status).toBe('pass')
    expect(regionDecision(item, profile).status).toBe('not_divided')
    expect(JSON.stringify(item.rules)).toBe(before)
  })

  it('also compares unordered region alternatives inside a priority scope', () => {
    const first = metadata('일반공급', {
      priority_applicable: true,
      local_priority: { region_code: '41', region_name: '경기도', min_months: 12, regions: provinces },
    })
    const second = metadata('생애최초 특별공급', {
      priority_applicable: true,
      local_priority: { region_code: '41', region_name: '경기도', min_months: 12, regions: [...provinces].reverse() },
    })
    expect(regionDecision(notice([first, second]), profile).status).toBe('local')
  })

  it('keeps genuinely different offer scopes separate while allowing an explicit offer comparison', () => {
    const item = scopedNotice({ regions: [{ region_code: '11', region_name: '서울특별시' }] })
    expect(applicantRegionEligibility(item, profile)).toBeNull()
    expect(regionDecision(item, profile).status).toBe('source_gap')
    expect(regionDecision(item, profile, { supplyType: '일반공급' }).status).toBe('not_divided')
    expect(regionDecision(item, profile, { supplyType: '생애최초 특별공급' }).status).toBe('outside')
  })

  it.each([
    { criterion_date: '2026-10-03' },
    { criterion_basis: 'contract_date' },
    { priority_applicable: true },
    { scope_complete: false },
    { exceptions: [{ kind: 'military_service_years', min_years: 10 }] },
    { regions: [{ ...provinces[0], min_months: 12 }, ...provinces.slice(1)] },
  ] as Partial<NoticeRule>[])('does not normalize away a real condition difference: %j', (different) => {
    expect(regionDecision(scopedNotice(different), profile).status).toBe('source_gap')
  })

  it('preserves a different local priority duration', () => {
    const base = { priority_applicable: true, local_priority: { region_code: '41', region_name: '경기도', min_months: 12 } }
    const item = notice([
      metadata('일반공급', base),
      metadata('생애최초 특별공급', { ...base, local_priority: { ...base.local_priority, min_months: 24 } }),
    ])
    expect(regionDecision(item, profile).status).toBe('source_gap')
  })

  it('retains exception ordering rather than treating every array as an OR set', () => {
    const exceptions = [
      { kind: 'military_service_years', min_years: 10 },
      { kind: 'military_service_years', min_years: 25, recommendation_required: true },
    ]
    const item = notice([
      metadata('일반공급', { exceptions }),
      metadata('생애최초 특별공급', { exceptions: [...exceptions].reverse() }),
    ])
    expect(regionDecision(item, profile).status).toBe('source_gap')
  })
})
