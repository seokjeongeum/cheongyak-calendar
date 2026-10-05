import { describe, expect, it } from 'vitest'
import { criterionDate, deriveRank, evaluateQualification, evaluateRule } from './qualification'
import { createHouseholdMember, EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'
const currentDate = '2026-10-01'
const source = 'https://www.applyhome.co.kr/official-v4'
const rule = (kind: string, extra: Partial<NoticeRule> = {}): NoticeRule => ({ kind, value: false, verification: 'official', evidence_url: source, criterion_date: currentDate, ...extra })
const item = (rules: NoticeRule[], extra: Partial<Notice> = {}): Notice => ({ id: 'v4-unranked', title: '공식 조건 인터페이스 비교', category: 'unranked', application_method: 'unranked_after', application_method_evidence: { verification: 'official', criterion_date: currentDate }, housing_kind: 'private', rank_applicability: { status: 'not_applicable', verification: 'official', account_required: false }, source: 'cheongyak_home', provider: '사업자', address: null, region_code: '36', region_name: '세종특별자치시', announcement_date: currentDate, official_url: source, price_cap_status: 'no', events: [], prices: [], rules, rules_complete: true, updated_at: null, version: 1, qualification_context: { public_housing: false, speculation_zone: false, subscription_overheated: false, weakened_area: false, capital_region: false, original_announcement_date: '2020-07-24', application_criterion_date: currentDate }, ...extra })
const facts = (extra: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, factChanges: { citizenship: { mode: 'known', date: currentDate } }, dateOfBirth: '1990-03-01', applicantOnRegister: true, hasSpouse: false, applicantOwnsHome: false, householdMembersComplete: true, householdSnapshotDate: currentDate, citizenship: 'korean', overseasContinuousDays: '0', overseasFactsAsOfDate: currentDate, ...extra })
const restriction = (restriction: string, scope = 'applicant', extra: Partial<NoticeRule> = {}): NoticeRule => rule('application_restriction', { restriction, scope, ...extra })
describe('unranked conditions remain independent from apartment rank', () => {
  it('evaluates real residence and homeless requirements after rank is not applicable', () => {
    const notice = item([rule('residence_region', { region_code: '36', region_name: '세종특별자치시', value: null }), rule('homeless', { value: true })])
    const applicant = facts({ region: '경기도', regionCode: '41', movedInDate: '2010-01-01' })
    expect(deriveRank(notice, applicant).rank).toBe('not_applicable')
    expect(evaluateQualification(notice, applicant, undefined, '일반공급').status).toBe('mismatch')
    expect(evaluateQualification(notice, { ...applicant, region: '세종특별자치시', regionCode: '36' }, undefined, '일반공급').status).toBe('possible')
  })
  it('defaults unranked qualification to its current date while preserving original criteria explicitly', () => {
    const notice = item([])
    expect(criterionDate({ kind: 'baseline' }, notice)).toBe(currentDate)
    expect(criterionDate({ kind: 'baseline', criterion_basis: 'original_announcement' }, notice)).toBe('2020-07-24')
    expect(evaluateRule(rule('age_min', { value: 19 }), facts({ dateOfBirth: '2004-09-30' }), notice).status).toBe('pass')
  })
  it('does not mistake minor exceptions not yet parsed for definite adult exclusion', () => {
    const adult = rule('any', { value: null, conditions: [rule('age_min', { value: 19 }), rule('unparsed', { label: '미성년자의 공식 성년·세대주 예외', text: '법정 예외 원문' })] })
    expect(evaluateRule(adult, facts(), item([adult])).status).toBe('pass')
    expect(evaluateRule(adult, facts({ dateOfBirth: '2010-01-01' }), item([adult])).status).toBe('review')
  })
  it('requires all supported mandatory input instead of granting possibility from no account requirement', () => {
    const citizenship = rule('citizenship', { value: null, allowed_values: ['korean'] })
    const notice = item([citizenship, rule('homeless', { value: true })])
    expect(evaluateQualification(notice, EMPTY_PROFILE, undefined, '일반공급').status).toBe('review')
    expect(evaluateQualification(notice, facts(), undefined, '일반공급').status).toBe('possible')
    expect(evaluateRule(citizenship, facts({ citizenship: 'foreign' }), notice).status).toBe('fail')
  })
  it('derives legal household size from the roster and ignores manual or income counts', () => {
    const minimum = rule('household_min', { value: 2 })
    const notice = item([minimum])
    expect(evaluateRule(minimum, facts({ householdSize: '99', incomeHouseholdSize: '7' }), notice).status).toBe('fail')
    const child = { ...createHouseholdMember('child'), relation: 'applicant_child' as const, register: 'applicant' as const, ownsHome: false }
    expect(evaluateRule(minimum, facts({ householdMembers: [child] }), notice).status).toBe('pass')
    expect(evaluateRule(minimum, facts({ householdMembersComplete: null }), notice)).toMatchObject({ status: 'review', profileField: 'householdMembersComplete' })
  })
  it('never asserts homeless status when the official criterion date is missing', () => {
    const homeless = { ...rule('homeless', { value: true }), criterion_date: undefined }
    const notice = item([homeless], { announcement_date: null, application_method_evidence: null, qualification_context: { public_housing: null, speculation_zone: null, subscription_overheated: null, weakened_area: null, capital_region: null } })
    expect(evaluateRule(homeless, facts(), notice)).toMatchObject({ status: 'review', category: 'source_gap' })
  })
})
describe('scoped project histories and cutoff-specific restriction queries', () => {
  const project = '2026000323'
  const prior = { winning: false, contract: false, additionalResident: false, winningScope: 'applicant' as const, contractScope: 'applicant' as const, asOfDate: currentDate, historyConfirmations: [] }
  const active = { ineligibleRestrictionActive: false, resaleRestrictionActive: false, rewinningRestrictionActive: false, asOfDate: currentDate, historyConfirmations: [] }
  it('applies an answer only to the exact original project and scope', () => {
    const condition = restriction('prior_project_winner', 'applicant', { project_id: project })
    const notice = item([condition])
    expect(evaluateRule(condition, facts({ projectApplicationHistory: { [project]: prior } }), notice).status).toBe('pass')
    expect(evaluateRule(condition, facts({ projectApplicationHistory: { '2021000515': prior } }), notice)).toMatchObject({ status: 'review', profileField: 'applicationHistoryEvents' })
    expect(evaluateRule(condition, facts({ projectApplicationHistory: { [project]: { ...prior, winningScope: 'household' } } }), notice).status).toBe('review')
    expect(evaluateRule(condition, facts({ projectApplicationHistory: { [project]: { ...prior, winning: true } } }), notice).status).toBe('fail')
  })
  it('treats completed additional resident contract as a real contract restriction', () => {
    const condition = restriction('prior_project_contract', 'applicant', { project_id: project })
    const notice = item([condition])
    expect(evaluateRule(condition, facts({ projectApplicationHistory: { [project]: { ...prior, additionalResident: true } } }), notice).status).toBe('fail')
    expect(evaluateRule(condition, facts({ projectApplicationHistory: { [project]: { ...prior, additionalResident: null } } }), notice).status).toBe('review')
  })
  it('does not apply current or a different-date query backwards without exact confirmation', () => {
    const condition = restriction('ineligible_restriction_active')
    const notice = item([condition])
    const current = { ...active, asOfDate: '2026-10-04' }
    expect(evaluateRule(condition, facts({ applicationRestrictionFacts: { applicant: current } }), notice).status).toBe('review')
    expect(evaluateRule(condition, facts({ applicationRestrictionFacts: { applicant: { ...current, historyConfirmations: [{ criterionDate: '2026-09-30', unchanged: true }] } } }), notice).status).toBe('review')
    expect(evaluateRule(condition, facts({ applicationRestrictionFacts: { applicant: { ...current, historyConfirmations: [{ criterionDate: currentDate, unchanged: true }] } } }), notice).status).toBe('pass')
  })
  it('keeps applicant, spouse and all household restriction facts separate and ignores former global answers', () => {
    const condition = restriction('rewinning_restriction_active', 'applicant_spouse')
    const notice = item([condition])
    const applicant = facts({ hasSpouse: true, spouseSameRegister: false, spouseOwnsHome: false })
    expect(evaluateRule(condition, { ...applicant, restrictedFromApplying: false, rewinningRestrictionActive: false }, notice).status).toBe('review')
    expect(evaluateRule(condition, { ...applicant, applicationRestrictionFacts: { applicant: active } }, notice).status).toBe('review')
    expect(evaluateRule(condition, { ...applicant, applicationRestrictionFacts: { applicant_spouse: active } }, notice).status).toBe('pass')
    expect(evaluateRule(condition, { ...applicant, applicationRestrictionFacts: { applicant_spouse: { ...active, rewinningRestrictionActive: true } } }, notice).status).toBe('fail')
  })
})
describe('overseas residence official threshold and factual exception', () => {
  const condition = rule('overseas_residence', { max_continuous_days: 90, value_basis: 'continuous_days_including_reentry_within_7_days', livelihood_exception: true })
  const notice = item([condition])
  it('passes up to90days and asks a concrete exception at91days', () => {
    expect(evaluateRule(condition, facts({ overseasContinuousDays: '90' }), notice).status).toBe('pass')
    expect(evaluateRule(condition, facts({ overseasContinuousDays: '91' }), notice)).toMatchObject({ status: 'review', profileField: 'overseasOnlyApplicantForLivelihood' })
    expect(evaluateRule(condition, facts({ overseasContinuousDays: '91', overseasOnlyApplicantForLivelihood: false }), notice).status).toBe('fail')
    expect(evaluateRule(condition, facts({ overseasContinuousDays: '91', overseasOnlyApplicantForLivelihood: true }), notice).status).toBe('pass')
  })
  it('requires the observed numeric fact to be valid at the exact cutoff', () => {
    expect(evaluateRule(condition, facts({ overseasContinuousDays: '0', overseasFactsAsOfDate: '2026-10-04' }), notice).status).toBe('review')
    expect(evaluateRule(condition, facts({ overseasContinuousDays: '0', overseasFactsAsOfDate: '2026-10-04', overseasFactsHistoryConfirmations: [{ criterionDate: currentDate, unchanged: true }] }), notice).status).toBe('pass')
  })
})

describe('complete official conditions and retained automatic extraction candidates', () => {
  const candidate = rule('unparsed', { verification: 'ai_unverified', value: null, text: '자동 추출한 미검증 거주·세대 조건', document_hash: 'current-official-hash' })
  const verified = rule('citizenship', { value: null, allowed_values: ['korean'], supply_type: '일반공급', document_hash: 'current-official-hash' })
  const coverage = (complete: boolean): NoticeRule => rule('condition_coverage', { effect: 'metadata', value: null, document_hash: 'current-official-hash', scopes: [{ supply_type: '일반공급', complete, verified_rule_count: 1, missing_topics: complete ? [] : ['기타 공식 조건'] }] })
  it('does not let an AI placeholder permanently downgrade a complete verified scope', () => {
    const notice = item([candidate, verified, coverage(true)], { rules_complete: false })
    const result = evaluateQualification(notice, facts(), undefined, '일반공급')
    expect(result.status).toBe('possible')
    expect(result.reasons.some((reason) => reason.category === 'unverified')).toBe(false)
    expect(notice.rules).toContain(candidate)
  })
  it('keeps incomplete official coverage unresolved and retains the candidate source state', () => {
    const result = evaluateQualification(item([candidate, verified, coverage(false)], { rules_complete: false }), facts(), undefined, '일반공급')
    expect(result.status).toBe('review')
    expect(result.reasons).toEqual(expect.arrayContaining([expect.objectContaining({ category: 'source_gap' }), expect.objectContaining({ category: 'unverified' })]))
  })
  it('never grants eligibility from an AI-only candidate even with a completeness flag', () => {
    expect(evaluateQualification(item([candidate, coverage(true)], { rules_complete: true }), facts(), undefined, '일반공급').status).toBe('review')
    expect(evaluateQualification(item([candidate], { rules_complete: true }), facts(), undefined, '일반공급').status).toBe('review')
  })
})
