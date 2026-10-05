import { describe, expect, it } from 'vitest'
import { deriveRank, evaluateEligibility, specialDiagnostics } from './eligibility'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'

const url = 'https://www.applyhome.co.kr/notice/official'
const rule = (kind: string, value: NoticeRule['value'], extra: Partial<NoticeRule> = {}): NoticeRule => ({ kind, value, verification: 'official', evidence_url: url, evidence_text: '공식 입주자 모집공고 조건', ...extra })
// These cases declare facts at the fixture's official criterion date.
const datedFacts = Object.fromEntries(['ownership', 'income', 'assets', 'bank_private', 'bank_national', 'marital', 'children', 'pregnancy', 'household_head'].map((group) => [group, { mode: 'known', date: '2026-09-25' }])) as LocalProfile['factChanges']
const profile = (extra: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, factChanges: datedFacts, ...extra })
const homeless: Partial<LocalProfile> = { applicantOnRegister: true, hasSpouse: false, applicantOwnsHome: false, householdMembersComplete: true, householdMembers: [], householdSnapshotDate: '2026-09-25', householdCompositionUnchanged: true }
const account = { accountType: 'comprehensive', accountConversionUnclear: false, privateRankBaseDate: '2024-09-25', nationalRankBaseDate: '2025-09-25', privateDepositKrw: '3000000', nationalRecognizedPayments: '11', restrictedFromApplying: false } as const
const housing = (rules: NoticeRule[], extra: Partial<Notice> = {}): Notice => ({
  id: 'sample', title: '공식 자격 사례', category: 'apt', source: 'cheongyak_home', provider: '사업자', address: '서울특별시', region_code: '11', region_name: '서울특별시', announcement_date: '2026-09-25', official_url: url, price_cap_status: 'unknown', events: [], prices: [], rules, rules_complete: true, updated_at: null, version: 1,
  housing_kind: 'private', housing_kind_evidence: { verification: 'official', source: 'cheongyak_home', evidence_url: url, evidence_text: 'HOUSE_DTL_SECD=01 민영' }, ...extra,
})
const rankRules = (kind: 'private' | 'national', extra: Partial<NoticeRule> = {}) => [
  rule(kind === 'private' ? 'private_rank_months' : 'national_rank_months', 12, { purpose: 'first_rank', rank_rules_complete: true, housing_kind: kind, ...extra }),
  rule(kind === 'private' ? 'deposit_min_krw' : 'recognized_payments_min', kind === 'private' ? 3_000_000 : 12, { purpose: 'first_rank', housing_kind: kind }),
  rule('account_type', 'comprehensive', { purpose: 'first_rank', housing_kind: kind }),
]

describe('fact based local qualification', () => {
  it('excludes classification metadata and keeps missing or incomplete conditions cautious', () => {
    expect(evaluateEligibility(housing([]), profile()).status).toBe('unpublished')
    expect(evaluateEligibility(housing([rule('housing_classification', null, { effect: 'metadata' })]), profile()).status).toBe('unpublished')
    const result = evaluateEligibility(housing([rule('homeless', true)], { rules_complete: false }), profile(homeless))
    expect(result.status).toBe('review')
    expect(result.reasons.some((r) => r.category === 'source_gap' && r.detail.includes('필수 요건'))).toBe(true)
  })
  it('shows inputs, requirement, criterion date and official evidence in reasons', () => {
    const result = evaluateEligibility(housing([rule('household_min', 3)]), profile({ ...homeless, householdMembers: Array.from({ length: 3 }, (_, index) => ({ id: `child-${index}`, relation: 'applicant_child', register: 'applicant', dateOfBirth: '2000-01-01', ownsHome: false, previouslyOwnedHome: false })) }))
    expect(result.status).toBe('possible')
    expect(result.reasons[0]).toMatchObject({ input: '4명', requirement: '>= 3명', criterionDate: '2026-09-25', evidenceUrl: url })
  })
  it('uses separate province and city residence start dates and parent city relationships', () => {
    const home = profile({ region: '경기도', regionCode: '41', district: '수원시 영통구', districtCode: '41117', movedInDate: '2020-01-01', districtMovedInDate: '2026-05-01', cityMovedInDate: '2026-05-01' })
    const provinceRule = rule('residence_months', 12, { region_name: '경기도' })
    const cityRule = rule('residence_months', 12, { region_name: '경기도 수원시' })
    expect(evaluateEligibility(housing([provinceRule]), home).status).toBe('possible')
    expect(evaluateEligibility(housing([cityRule]), home).status).toBe('mismatch')
    expect(evaluateEligibility(housing([cityRule]), { ...home, cityMovedInDate: '' }).status).toBe('review')
  })
  it('handles calendar month end anniversaries and invalid dates', () => {
    const notice = housing([rule('residence_months', 1, { region_name: '서울특별시' })], { announcement_date: '2024-02-29' })
    expect(evaluateEligibility(notice, profile({ region: '서울특별시', movedInDate: '2024-01-31' })).status).toBe('possible')
    expect(evaluateEligibility(notice, profile({ region: '서울특별시', movedInDate: '2024-02-30' })).status).toBe('review')
  })
  it('never substitutes legacy self assessments for ownership facts', () => {
    expect(evaluateEligibility(housing([rule('homeless', true)]), profile({ homeless: true })).status).toBe('review')
    expect(evaluateEligibility(housing([rule('homeless', true)]), profile(homeless)).status).toBe('possible')
    expect(evaluateEligibility(housing([rule('homeless', true)]), profile({ ...homeless, applicantOwnsHome: true, ownershipException: false })).status).toBe('review')
  })
  it('requires the separated spouse and legal household scope and preserves ownership exceptions for review', () => {
    const own = housing([rule('homeless', true)])
    expect(evaluateEligibility(own, profile({ ...homeless, hasSpouse: true, spouseSameRegister: false })).status).toBe('review')
    expect(evaluateEligibility(own, profile({ ...homeless, hasSpouse: true, spouseOwnsHome: false, spouseSameRegister: false })).status).toBe('possible')
    expect(evaluateEligibility(own, profile({ ...homeless, householdMembers: [{ id: 'parent', relation: 'applicant_parent', register: 'applicant', dateOfBirth: '1960-01-01', ownsHome: true, previouslyOwnedHome: true }], ownershipException: true })).status).toBe('review')
    expect(evaluateEligibility(own, profile({ ...homeless, householdMembersComplete: false })).status).toBe('review')
  })
  it('compares separately reported monthly income and each asset category without annual division', () => {
    const applicant = profile({ annualIncomeKrw: '60000000', assetsKrw: '200000000' })
    expect(evaluateEligibility(housing([rule('income_max_krw', 5_000_000, { period: 'monthly' })]), applicant).status).toBe('review')
    expect(evaluateEligibility(housing([rule('income_max_krw', 5_000_000, { period: 'monthly' })]), { ...applicant, monthlyIncomeKrw: '5100000' }).status).toBe('mismatch')
    expect(evaluateEligibility(housing([rule('income_max_krw', 60_000_000, { period: 'annual' })]), applicant).status).toBe('possible')
    expect(evaluateEligibility(housing([rule('assets_max_krw', 210_000_000)]), applicant).status).toBe('possible')
    expect(evaluateEligibility(housing([rule('assets_max_krw', 30_000_000, { asset_basis: 'automobile' })]), applicant).status).toBe('review')
    expect(evaluateEligibility(housing([rule('assets_max_krw', 30_000_000, { asset_basis: 'automobile' })]), { ...applicant, vehicleKrw: '20000000' }).status).toBe('possible')
  })
  it('requires verified conditions and does not turn a residence preference into application rejection', () => {
    expect(evaluateEligibility(housing([rule('homeless', true, { verification: 'ai_unverified' })]), profile(homeless)).status).toBe('review')
    expect(evaluateEligibility(housing([rule('unknown_requirement', 1)]), profile()).status).toBe('review')
    expect(evaluateEligibility(housing([rule('residence_months', 12, { effect: 'priority', region_name: '성남시' })]), profile({ region: '서울특별시' })).status).toBe('review')
  })
  it('uses the original official criterion date after a correction and preserves explicit different cutoff dates', () => {
    const metadata = { kind: 'qualification_context', effect: 'metadata', verification: 'official', value: { original_announcement_date: '2026-09-01' } } as unknown as NoticeRule
    const result = evaluateEligibility(housing([metadata, rule('private_rank_months', 12), rule('deposit_min_krw', 3000000, { criterion_date: '2026-09-24' })]), profile({ ...account, privateRankBaseDate: '2025-09-10' }))
    expect(result.status).toBe('mismatch')
    expect(result.reasons.map((r) => r.criterionDate)).toEqual(['2026-09-01', '2026-09-24'])
  })
  it('supports verified alternative branches, exception branches and validity periods', () => {
    const either = rule('any', null, { conditions: [rule('marital_status', 'married'), rule('children_min', 1, { child_age_max: 19 })] })
    expect(evaluateEligibility(housing([either]), profile({ maritalStatus: 'single', pregnant: false, hasChildren: false })).status).toBe('mismatch')
    expect(evaluateEligibility(housing([either]), profile({ maritalStatus: 'married' })).status).toBe('possible')
    const exception = rule('household_head', true, { exceptions: [rule('age_min', 65)] })
    expect(evaluateEligibility(housing([exception]), profile({ isHouseholdHead: false, dateOfBirth: '1940-01-01' })).status).toBe('possible')
    expect(evaluateEligibility(housing([exception]), profile({ isHouseholdHead: false })).status).toBe('review')
    expect(evaluateEligibility(housing([rule('household_head', true, { valid_from: '2027-01-01' })]), profile({ isHouseholdHead: true })).status).toBe('review')
  })
  it('uses a verified recent-winning window and keeps a missing winning date under review', () => {
    const restriction = housing([rule('previous_winning', false, { window_months: 60 })])
    expect(evaluateEligibility(restriction, profile({ previousWinning: true, previousWinningDate: '2020-09-24' })).status).toBe('possible')
    expect(evaluateEligibility(restriction, profile({ previousWinning: true, previousWinningDate: '2024-09-24' })).status).toBe('mismatch')
    expect(evaluateEligibility(restriction, profile({ previousWinning: true })).status).toBe('review')
  })
  it('does not apply general first-rank thresholds to an independently offered special supply', () => {
    const rules = [...rankRules('private'), rule('marital_status', 'married', { supply_type: '신혼부부 특별공급' }), rule('marriage_months_max', 84, { supply_type: '신혼부부 특별공급' })]
    const result = evaluateEligibility(housing(rules), profile({ ...account, privateRankBaseDate: '2026-08-01', privateDepositKrw: '0', maritalStatus: 'married', marriageDate: '2025-01-01' }), undefined, '신혼부부 특별공급')
    expect(result.status).toBe('possible')
    expect(result.reasons.some((r) => /예치금|순위/.test(r.label))).toBe(false)
  })
  it('keeps malformed branch children from creating a false possible result', () => {
    const branch = rule('all', null, { conditions: [rule('household_head', true), { value: true }] })
    expect(evaluateEligibility(housing([branch]), profile({ isHouseholdHead: true })).status).toBe('review')
  })
  it('compares newborn cutoff dates exactly, including the second birthday only when officially included', () => {
    const child = rule('newborn_children_min', 1, { child_months_max: 24, child_age_inclusive: true })
    const person = profile({ hasChildren: true, pregnant: false, children: [{ dateOfBirth: '2024-09-25', adopted: false }] })
    expect(evaluateEligibility(housing([child]), person).status).toBe('possible')
    expect(evaluateEligibility(housing([child]), { ...person, children: [{ dateOfBirth: '2024-09-24', adopted: false }] }).status).toBe('mismatch')
    expect(evaluateEligibility(housing([rule('newborn_children_min', 1)]), person).status).toBe('review')
    expect(evaluateEligibility(housing([child]), profile({ pregnant: false })).status).toBe('review')
  })
  it('does not use child-district residence as a parent-city clock', () => {
    const person = profile({ region: '경기도', district: '수원시 영통구', districtCode: '41117', movedInDate: '2010-01-01', districtMovedInDate: '2026-08-01', cityMovedInDate: '2020-01-01' })
    expect(evaluateEligibility(housing([rule('residence_months', 12, { region_name: '경기도 수원시' })]), person).status).toBe('possible')
    expect(evaluateEligibility(housing([rule('residence_months', 12, { region_name: '경기도 수원시 영통구' })]), person).status).toBe('mismatch')
    expect(evaluateEligibility(housing([rule('residence_months', 12, { region_name: '경기도 수원시' })]), { ...person, cityMovedInDate: '' }).status).toBe('review')
  })

})

describe('different private and national first ranks', () => {
  it('derives different rank results from the same facts using period plus money or recognized payments', () => {
    const home = profile(account)
    expect(deriveRank(housing(rankRules('private')), home).rank).toBe('first')
    const national = housing(rankRules('national'), { housing_kind: 'national', housing_kind_evidence: { verification: 'official', evidence_url: url, evidence_text: '국민' } })
    expect(deriveRank(national, home)).toMatchObject({ rank: 'unknown', status: 'mismatch' })
    expect(deriveRank(national, { ...home, nationalRecognizedPayments: '12' }).rank).toBe('first')
  })
  it('never derives first from the base date alone or second from failing first', () => {
    expect(deriveRank(housing([rankRules('private')[0]]), profile(account)).rank).toBe('unknown')
    expect(deriveRank(housing(rankRules('private')), profile({ ...account, privateDepositKrw: '2000000' }))).toMatchObject({ rank: 'unknown', status: 'mismatch' })
  })
  it('requires classification, applicable date and complete official conditions after bank confirmation', () => {
    const notice = housing(rankRules('private'))
    expect(deriveRank(notice, profile({ ...account, accountConversionUnclear: true })).rank).toBe('first')
    for (const [n, p] of [[{ ...notice, housing_kind: 'unknown' }, profile(account)], [{ ...notice, housing_kind_evidence: null }, profile(account)], [notice, profile({ ...account, privateRankBaseDate: '' })], [housing(rankRules('private').map((r) => ({ ...r, rank_rules_complete: false }))), profile(account)]] as const) {
      expect(deriveRank(n as Notice, p).rank).toBe('unknown')
    }
  })
  it('ignores old subscriptionRank and subscriptionMonths and protects unit-specific deposit coverage', () => {
    expect(deriveRank(housing(rankRules('private')), profile({ subscriptionRank: 'first', subscriptionMonths: '60' })).rank).toBe('unknown')
    expect(deriveRank(housing(rankRules('private').map((r) => r.kind === 'deposit_min_krw' ? { ...r, unit_type: '59A' } : r)), profile(account)).rank).toBe('unknown')
  })
  it('provides distinct verified statutory baseline guidance for real notices even without a complete extracted rule set', () => {
    const context = { public_housing: false, speculation_zone: false, subscription_overheated: false, weakened_area: false, capital_region: true }
    const person = profile(account)
    const privateResult = deriveRank(housing([], { qualification_context: context }), person)
    expect(privateResult.rank).toBe('unknown')
    expect(privateResult.reasons.find((r) => r.label === '민영 순위 인정기간')?.detail).toContain('24개월')
    expect(privateResult.reasons.find((r) => r.label === '민영주택 예치금')?.input).toBe('3,000,000원')
    const national = deriveRank(housing([], { housing_kind: 'national', qualification_context: context }), person)
    expect(national.rank).toBe('unknown')
    expect(national.reasons.find((r) => r.label === '국민주택 납입인정횟수')).toMatchObject({ status: 'fail', input: '11회' })
    expect(national.reasons.find((r) => r.label === '국민 순위 인정기간')?.input).toBe('12개월')
  })

})

describe('multiple offered special supply fact comparisons', () => {
  const newlywed = [rule('marital_status', 'married', { supply_type: '신혼부부 특별공급' }), rule('marriage_months_max', 84, { supply_type: '신혼부부 특별공급' })]
  const children = [rule('children_min', 2, { supply_type: '다자녀 특별공급', include_pregnancy: true, child_age_max: 19 })]
  it('diagnoses several offered types concurrently from facts', () => {
    const person = profile({ maritalStatus: 'married', marriageDate: '2025-01-01', hasChildren: true, pregnant: true, expectedChildren: '1', children: [{ dateOfBirth: '2023-01-01', adopted: false }] })
    const results = specialDiagnostics(housing([...newlywed, ...children]), person)
    expect(results.map((d) => [d.type, d.result.status])).toEqual([['newlywed', 'possible'], ['multi_child', 'possible']])
    expect(results.some((d) => d.type === 'institution')).toBe(false)
  })
  it('keeps type-specific mismatches separate and leaves unrevealed types uncertain', () => {
    const results = specialDiagnostics(housing([...newlywed, ...children, rule('special_eligibility', '기관추천', { supply_type: '기관추천 특별공급' })]), profile({ maritalStatus: 'single', pregnant: false, hasChildren: false }))
    expect(results.map((d) => d.result.status)).toEqual(['mismatch', 'mismatch', 'review'])
  })
  it('does not use prior special eligibility self-assessments or spouse prior-home exceptions as definitive rejection', () => {
    expect(specialDiagnostics(housing(newlywed), profile({ specialEligibility: true, specialCategory: '신혼부부' }))[0].result.status).toBe('review')
    const firstHome = housing([rule('never_owned_home', true, { supply_type: '생애최초 특별공급' })])
    expect(specialDiagnostics(firstHome, profile({ ...homeless, applicantPreviouslyOwnedHome: true }))[0].result.status).toBe('review')
  })
})
