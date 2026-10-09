import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { EligibilityBrief, EligibilityDetails, ReasonList } from './EligibilityDetails'
import { conditionCoverage, eligibilityCombinations, evaluateEligibility, evaluateRule, deriveRank, noticeEligibilitySummary } from './eligibility'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'
const unchangedFacts = { bank_private: { mode: 'never_changed' as const, date: '' }, bank_national: { mode: 'never_changed' as const, date: '' }, household_head: { mode: 'never_changed' as const, date: '' }, marital: { mode: 'never_changed' as const, date: '' }, children: { mode: 'never_changed' as const, date: '' }, military: { mode: 'never_changed' as const, date: '' } }

const evidence = 'https://www.applyhome.co.kr/public/notice.pdf'
function rule(kind: string, value: NoticeRule['value'] = null, patch: Partial<NoticeRule> = {}): NoticeRule {
  return { kind, value, verification: 'official', evidence_url: evidence, evidence_text: '공식 공고 원문', ...patch }
}
const profile = (patch: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, factChanges: unchangedFacts, ...patch })
function family(count: number, hasSpouse = false): Partial<LocalProfile> {
  return { applicantOnRegister: true, hasSpouse, spouseSameRegister: hasSpouse ? false : null, householdMembersComplete: true,
    householdSnapshotDate: '2026-10-03', householdCompositionUnchanged: true,
    householdMembers: Array.from({ length: count - 1 - Number(hasSpouse) }, (_, index) => ({
      id: `family-${index}`, relation: 'applicant_child', register: 'applicant', dateOfBirth: '2000-01-01', ownsHome: false, previouslyOwnedHome: false,
    })) }
}
function notice(rules: NoticeRule[], patch: Partial<Notice> = {}): Notice {
  return { id: 'layout', title: '공식 모집공고', category: 'apt', source: 'cheongyak_home', provider: '', address: null, region_code: null, region_name: null, announcement_date: '2026-10-03', official_url: evidence, price_cap_status: 'no', events: [], prices: [{ unit_type: '59A', price_kind: 'sale_max', exclusive_area_sqm: 59.9 }, { unit_type: '104A', price_kind: 'sale_max', exclusive_area_sqm: 104 }], rules, rules_complete: true, updated_at: null, version: 1, housing_kind: 'private', housing_kind_evidence: { verification: 'official', evidence_url: evidence }, ...patch }
}
const deposit = rule('deposit_min_krw', null, { deposit_table: [
  { max_area_sqm: 85, amounts_krw: { seoul_busan: 3000000, other_metropolitan: 2500000, other: 2000000 } },
  { max_area_sqm: 102, amounts_krw: { seoul_busan: 6000000, other_metropolitan: 4000000, other: 3000000 } },
  { max_area_sqm: 135, amounts_krw: { seoul_busan: 10000000, other_metropolitan: 7000000, other: 4000000 } },
  { max_area_sqm: null, amounts_krw: { seoul_busan: 15000000, other_metropolitan: 10000000, other: 5000000 } },
] })

it('does not turn an unscoped selection into a service gap after every offered scope is verified', () => {
  const item = notice([
    rule('age_min', 19, { supply_type: '일반공급' }),
    rule('condition_coverage', null, { effect: 'metadata', scopes: [{ supply_type: '일반공급', complete: true }] }),
  ], { rules_complete: false })
  const person = profile({ dateOfBirth: '1990-01-01' })
  const result = noticeEligibilitySummary(item, person)
  expect(result.status).toBe('possible')
  const html = renderToStaticMarkup(<EligibilityBrief result={result} notice={item} profile={person} onProfile={() => {}} />)
  expect(html).not.toContain('qualification-gap-note')
  expect(html).toContain('조건상 가능성 있음')
})

describe('scoped official comparisons and actionable input', () => {
  it('links a missing value to the actual profile question while retaining its official requirement', () => {
    const result = evaluateEligibility(notice([rule('income_max_krw', 5000000, { period: 'monthly' })]), profile({ annualIncomeKrw: '60000000' }))
    expect(result.reasons[0]).toMatchObject({ category: 'missing_input', profileField: 'monthlyIncomeKrw', requirement: '<= 5,000,000원' })
    expect(result.reasons[0].input).toBeUndefined()
    const html = renderToStaticMarkup(<ReasonList reasons={result.reasons} onProfile={() => {}} />)
    expect(html).toContain('공고 기준 월평균소득 입력하기')
    expect(html).not.toContain('미입력 또는 범위 확인 필요')
    expect(html).not.toContain('<dt>내 입력</dt>')
  })
  it('does not blame profile input when the service has not parsed the official condition', () => {
    const result = evaluateEligibility(notice([], { rules_complete: false }), profile())
    expect(result.status).toBe('unpublished')
    expect(result.reasons[0]).toMatchObject({ category: 'source_gap', label: '공고 조건 정리 중' })
    expect(result.reasons[0].detail).not.toContain('공개되지')
  })
  it('keeps confirmed comparisons useful while explicit incomplete coverage prevents a possible status', () => {
    const coverage = rule('condition_coverage', null, { effect: 'metadata', scopes: [{ supply_type: '일반공급', complete: false, verified_rule_count: 1, missing_topics: ['당첨 제한'] }] })
    const item = notice([rule('household_min', 2, { supply_type: '일반공급' }), coverage])
    const result = evaluateEligibility(item, profile({ ...family(3) }), undefined, '일반공급')
    expect(result.status).toBe('review')
    expect(result.reasons[0]).toMatchObject({ status: 'pass', input: '3명' })
    expect(conditionCoverage(item, undefined, '일반공급')).toMatchObject({ complete: false, verifiedCount: 1, missingTopics: ['당첨 제한'] })
  })
  it('applies reviewed complete coverage only to its actual unit/supply scope', () => {
    const coverage = rule('condition_coverage', null, { effect: 'metadata', scopes: [{ supply_type: '일반공급', unit_type: '59A', complete: true }] })
    const item = notice([rule('household_min', 2, { supply_type: '일반공급' }), coverage], { rules_complete: false })
    expect(evaluateEligibility(item, profile({ ...family(3) }), '59A', '일반공급').status).toBe('possible')
    expect(evaluateEligibility(item, profile({ ...family(3) }), '104A', '일반공급').status).toBe('review')
    expect(evaluateEligibility(item, profile({ ...family(3) }), undefined, '일반공급').status).toBe('review')
    expect(evaluateEligibility(notice([{ ...coverage, verification: 'ai_unverified' }, rule('household_min', 2)], { rules_complete: false }), profile({ ...family(3) })).status).toBe('review')
  })
  it('compares official deposit tiers by real residence and selected unit area', () => {
    const home = profile({ regionCode: '41', movedInDate: '2020-01-01', privateDepositKrw: '3000000' })
    expect(evaluateRule(deposit, home, notice([deposit]), '59A')).toMatchObject({ status: 'pass', input: '3,000,000원' })
    expect(evaluateRule(deposit, home, notice([deposit]), '104A')).toMatchObject({ status: 'fail' })
    expect(evaluateRule(deposit, home, notice([deposit]))).toMatchObject({ status: 'review', category: 'selection' })
    expect(evaluateRule(deposit, profile({ regionCode: '11', movedInDate: '2020-01-01', privateDepositKrw: '2500000' }), notice([deposit]), '59A').status).toBe('fail')
    expect(evaluateRule(deposit, profile({ regionCode: '28', movedInDate: '2020-01-01', privateDepositKrw: '2500000' }), notice([deposit]), '59A').status).toBe('pass')
    expect(evaluateRule(deposit, profile({ privateDepositKrw: '999999999' }), notice([deposit]), '59A')).toMatchObject({ status: 'review', category: 'missing_input', profileField: 'regionCode' })
    expect(evaluateRule({ ...deposit, verification: 'ai_unverified' }, home, notice([deposit]), '59A')).toMatchObject({ status: 'review', category: 'unverified' })
    expect(evaluateRule(deposit, home, notice([deposit], { prices: [{ unit_type: '59A', price_kind: 'sale_max', area_sqm: null }] }), '59A').status).toBe('review')
  })
  it('checks official exception branches before rejecting a grouped residence condition', () => {
    const geography = rule('any', null, { label: '신청 가능한 거주지역', conditions: [rule('residence_region', null, { region_name: '서울특별시', region_code: '11' }), rule('residence_region', null, { region_name: '경기도', region_code: '41' })] })
    const outside = profile({ regionCode: '26', region: '부산광역시', movedInDate: '2020-01-01' })
    const inside = profile({ regionCode: '11', region: '서울특별시', movedInDate: '2020-01-01' })
    const militaryException = rule('unparsed', null, { text: '장기복무 군인의 거주지역 예외는 추가 증빙 확인이 필요합니다.' })
    expect(evaluateRule(geography, outside, notice([geography])).status).toBe('fail')
    expect(evaluateRule({ ...geography, exceptions: [militaryException] }, outside, notice([geography])).status).toBe('review')
    expect(evaluateRule({ ...geography, exceptions: [militaryException] }, inside, notice([geography])).status).toBe('pass')
    const knownException = rule('household_head', true)
    expect(evaluateRule({ ...geography, exceptions: [knownException] }, { ...outside, isHouseholdHead: true }, notice([geography])).status).toBe('pass')
    expect(evaluateRule({ ...geography, exceptions: [{ ...knownException, verification: 'ai_unverified' }] }, { ...outside, isHouseholdHead: true }, notice([geography])).status).toBe('review')
  })
  it('explains the successful alternative without presenting other allowed regions as failures', () => {
    const geography = rule('any', null, { label: '신청 가능한 거주지역', conditions: [
      rule('residence_region', null, { region_name: '서울특별시', region_code: '11' }),
      rule('residence_region', null, { region_name: '인천광역시', region_code: '28' }),
      rule('residence_region', null, { region_name: '경기도', region_code: '41' }),
    ] })
    const met = evaluateRule(geography, profile({ regionCode: '28', region: '인천광역시', movedInDate: '2020-01-01' }), notice([geography]))
    expect(met).toMatchObject({ status: 'pass', input: '인천광역시 ', requirement: '서울특별시 또는 인천광역시 또는 경기도' })
    expect(met.detail).toContain('공식 신청 지역에 포함됩니다')
    expect(met.detail).not.toContain('조건이 다릅니다')
    const outside = evaluateRule(geography, profile({ regionCode: '26', region: '부산광역시', movedInDate: '2020-01-01' }), notice([geography]))
    expect(outside.status).toBe('fail')
    expect(outside.detail.match(/조건이 다릅니다/g)).toHaveLength(3)
  })
  it('keeps the official 85㎡ installment-account limit separate from other account types', () => {
    const account = rule('account_type', null, { allowed_values: ['comprehensive', 'deposit', 'installment'], area_limit_for_installment: 85 })
    const item = notice([account])
    expect(evaluateRule(account, profile({ accountType: 'installment' }), item, '59A').status).toBe('pass')
    expect(evaluateRule(account, profile({ accountType: 'installment' }), item, '104A').status).toBe('fail')
    expect(evaluateRule(account, profile({ accountType: 'installment' }), item)).toMatchObject({ status: 'review', category: 'selection' })
    expect(evaluateRule(account, profile({ accountType: 'comprehensive' }), item, '104A').status).toBe('pass')
  })
  it('checks an exact marriage anniversary rather than granting the rest of the 84th month', () => {
    const item = notice([rule('marriage_months_max', 84, { anniversary_limit: true })])
    expect(evaluateEligibility(item, profile({ marriageDate: '2019-10-03' })).status).toBe('possible')
    expect(evaluateEligibility(item, profile({ marriageDate: '2019-10-02' })).status).toBe('mismatch')
  })
})

describe('grouped eligibility evidence renderer', () => {
  it('does not invent special-unit Cartesian pairs from a list of prices', () => {
    const item = notice([rule('marital_status', 'married', { supply_type: '신혼부부 특별공급' }), rule('marriage_months_max', 84, { supply_type: '신혼부부 특별공급' })])
    expect(eligibilityCombinations(item)).toHaveLength(1)
    expect(eligibilityCombinations(item)[0]).toMatchObject({ unitType: '전체 주택형', supplyType: '신혼부부 특별공급' })
    expect(eligibilityCombinations(notice([rule('marital_status', 'married', { supply_type: '신혼부부 특별공급', unit_type: '59A' })]))).toHaveLength(1)
    expect(eligibilityCombinations(notice([rule('marital_status', 'married', { supply_type: '신혼부부 특별공급', verification: 'ai_unverified' })]))).toHaveLength(0)
  })
  it('renders common official evidence once and keeps candidates in one collapsed group', () => {
    const item = notice([rule('household_min', 2), rule('marital_status', 'married', { supply_type: '신혼부부 특별공급' }), rule('marriage_months_max', 84, { supply_type: '신혼부부 특별공급' }), rule('unparsed', null, { verification: 'ai_unverified', evidence_text: '자동 추출한 공개 문구' })], { rules_complete: false })
    const html = renderToStaticMarkup(<EligibilityDetails notice={item} profile={profile({ ...family(3, true), maritalStatus: 'married', marriageDate: '2025-01-01' })} onProfile={() => {}} />)
    expect(html.match(/충족 · 계산된 주택 보유 확인 가족 수/g)).toHaveLength(1)
    expect(html.match(/자동 추출한 공개 문구/g)).toHaveLength(1)
    expect(html).toContain('qualification-reason-body')
    expect(html).toContain('qualification-icon')
    expect(html).not.toContain('미검증 조건')
    expect(html).not.toContain('조건 범위')
    expect(html).not.toContain('미입력 또는 범위 확인 필요')
  })
  it('renders identical scoped conditions once with only their actual applicable supplies', () => {
    const shared = { source: 'official_document_parser', criterion_date: '2026-10-03', evidence_text: '가입 후 6개월 및 월납입금 6회 이상' }
    const supplies = ['신혼부부(신혼희망타운)', '예비신혼부부(신혼희망타운)', '한부모가족(신혼희망타운)']
    const item = notice(supplies.flatMap((supply_type) => [
      rule('national_rank_months', 6, { ...shared, supply_type }),
      rule('recognized_payments_min', supply_type === supplies[2] ? 12 : 6, { ...shared, supply_type }),
    ]), { housing_kind: 'national', rules_complete: false })
    const html = renderToStaticMarkup(<EligibilityDetails notice={item} profile={profile({ accountConversionUnclear: false, nationalRankBaseDate: '2024-01-01', nationalRecognizedPayments: '9' })} onProfile={() => {}} />)
    expect(html.match(/충족 · 국민 순위 인정기간/g)).toHaveLength(1)
    expect(html.match(/충족 · 국민주택 납입인정횟수/g)).toHaveLength(1)
    expect(html.match(/불일치 · 국민주택 납입인정횟수/g)).toHaveLength(1)
    expect(html).toContain('유형 간 공통 조건')
    expect(html).toContain(`적용: ${supplies.join(' · ')}`)
    expect(html).toContain(`적용: ${supplies.slice(0, 2).join(' · ')}`)
    expect(html).not.toContain('기관추천')
    expect(html).not.toContain('59A')
  })
  it('preserves different supply outcomes after their only actionable evidence becomes shared', () => {
    const item = notice([
      rule('private_rank_months', 6, { purpose: 'first_rank', rank_rules_complete: true }),
      rule('deposit_min_krw', 3000000, { purpose: 'first_rank' }),
      rule('household_min', 2, { supply_type: '일반공급' }),
      rule('first_rank', true, { supply_type: '일반공급' }),
      rule('household_min', 2, { supply_type: '신혼부부 특별공급' }),
      rule('marital_status', 'married', { supply_type: '신혼부부 특별공급' }),
    ])
    const facts = profile({ ...family(3, true), accountType: 'comprehensive', accountConversionUnclear: false, privateDepositKrw: '4000000', restrictedFromApplying: false, specialWinning: false, maritalStatus: 'married' })
    expect(eligibilityCombinations(item, facts).map((combo) => combo.result.status)).toEqual(['review', 'possible'])
    const html = renderToStaticMarkup(<EligibilityDetails notice={item} profile={facts} onProfile={() => {}} />)
    expect(html.match(/충족 · 계산된 주택 보유 확인 가족 수/g)).toHaveLength(1)
    const general = html.split('<h5>일반공급<small>')[1].split('</section>')[0]
    const special = html.split('<h5>신혼부부 특별공급<small>')[1].split('</section>')[0]
    expect(general).toContain('추가 확인 필요')
    expect(special).toContain('조건상 가능성 있음')
    expect(general).not.toContain('qualification-reasons')
  })
  it('does not create repetitive empty supply sections when all shared comparisons remain incomplete', () => {
    const item = notice([rule('household_min', 2, { supply_type: '일반공급' }), rule('household_min', 2, { supply_type: '신혼부부 특별공급' })], { rules_complete: false })
    const facts = profile({ ...family(3), specialWinning: false })
    expect(eligibilityCombinations(item, facts).map((combo) => combo.result.status)).toEqual(['review', 'review'])
    const html = renderToStaticMarkup(<EligibilityDetails notice={item} profile={facts} onProfile={() => {}} />)
    expect(html.match(/충족 · 계산된 주택 보유 확인 가족 수/g)).toHaveLength(1)
    expect(html).toContain('적용: 일반공급 · 신혼부부 특별공급')
    expect(html).not.toContain('<h5>일반공급<small>')
    expect(html).not.toContain('<h5>신혼부부 특별공급<small>')
  })
  it('shows actual area tiers for general rank without cross-joining special supply', () => {
    const item = notice([{ ...deposit, purpose: 'first_rank' }], { rules_complete: false })
    const html = renderToStaticMarkup(<EligibilityDetails notice={item} profile={profile({ regionCode: '41', movedInDate: '2020-01-01', privateDepositKrw: '3000000' })} onProfile={() => {}} />)
    expect(html).toContain('면적별 청약통장 조건')
    expect(html).toContain('59A')
    expect(html).toContain('104A')
    expect(html).toContain('&gt;= 2,000,000원')
    expect(html).toContain('&gt;= 4,000,000원')
    expect(html).not.toContain('1순위 조건 충족')
  })
  it('surfaces verified rank comparisons in the brief without claiming completed first-rank diagnosis', () => {
    const item = notice([rule('private_rank_months', 12, { purpose: 'first_rank' }), rule('deposit_min_krw', 3000000, { purpose: 'first_rank' })], { rules_complete: false })
    const facts = profile({ accountType: 'comprehensive', accountConversionUnclear: false, privateRankBaseDate: '2024-10-03', privateDepositKrw: '4000000', restrictedFromApplying: false })
    expect(deriveRank(item, facts).rank).toBe('unknown')
    const html = renderToStaticMarkup(<EligibilityBrief notice={item} profile={facts} result={evaluateEligibility(item, facts)} onProfile={() => {}} />)
    expect(html).toContain('민영 순위 인정기간 충족')
    expect(html).not.toContain('1순위 조건 충족')
  })

  it('explains a child-count failure only under its offered special supply and keeps general supply possible', () => {
    const item = notice([
      rule('household_min', 1, { supply_type: '일반공급' }),
      rule('children_min', 2, { supply_type: '다자녀 특별공급', child_age_max: 19 }),
    ])
    const facts = profile({ ...family(1), hasChildren: false, children: [], pregnant: false, specialWinning: false })
    const result = noticeEligibilitySummary(item, facts)
    expect(result.status).toBe('possible')
    const html = renderToStaticMarkup(<EligibilityBrief notice={item} profile={facts} result={result} onProfile={() => {}} />)
    const general = html.match(/<section class="qualification-supply-brief[^\"]*">[\s\S]*?<\/section>/g) || []
    const failed = html.match(/<details class="qualification-supply-brief[^\"]*">[\s\S]*?<\/details>/g) || []
    expect(general).toHaveLength(1)
    expect(failed).toHaveLength(1)
    expect(general[0]).toContain('일반공급')
    expect(general[0]).toContain('조건상 가능성 있음')
    expect(general[0]).not.toContain('자녀')
    expect(failed[0]).toContain('다자녀 특별공급')
    expect(failed[0]).toContain('내 조건으로 신청 불가')
    expect(failed[0]).toContain('qualification-unavailable')
    expect(failed[0]).toContain('0명')
    expect(html).not.toContain('신혼부부 특별공급')
  })

  it('keeps the notice possible when another offered general unit remains possible after closure', () => {
    const item = notice([rule('household_min', 1, { supply_type: '일반공급' })], {
      competition: { status: 'ok', complete: true, unit_types: ['59A', '104A'], last_attempt_at: null, last_success_at: null },
    })
    const decision = { hidden: false, closedUnits: ['59A'], rank: 'first' as const, area: 'other' as const, reason: '59A 마감', fresh: true }
    const facts = profile({ ...family(1) })
    const summaries = eligibilityCombinations(item, facts, decision)
    expect(summaries.map((combo) => [combo.unitType, combo.result.status])).toEqual([['59A', 'mismatch'], ['104A', 'possible']])
    expect(noticeEligibilitySummary(item, facts, decision).status).toBe('possible')
  })
})
