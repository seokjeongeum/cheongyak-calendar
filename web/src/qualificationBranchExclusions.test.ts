import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { conditionSourceStatus } from './eligibility'
import { setEvaluationToday } from './factTimeline'
import { evaluateQualification, evaluateRule, officialClauseApplicability } from './qualification'
import { createOwnershipFact, EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'

const today = '2026-10-09', cutoff = '2026-10-02', source = 'https://example.com/current-announcement.pdf'
const newlywed = '신혼부부 특별공급', firstHome = '생애최초 특별공급', institution = '기관추천 특별공급'
const rule = (kind: string, part: Partial<NoticeRule> = {}): NoticeRule => ({ kind, verification: 'official', evidence_url: source, criterion_date: cutoff, ...part })
const notice = (rules: NoticeRule[], part: Partial<Notice> = {}): Notice => ({ id: 'branch', title: '분기별 공식 조건', category: 'apt', source: 'cheongyak_home', provider: '청약홈', address: null, region_code: null, region_name: null, announcement_date: cutoff, official_url: source, price_cap_status: 'unknown', events: [], prices: [], rules, rules_complete: true, updated_at: null, version: 1, ...part })
const profile = (part: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, dateOfBirth: '1990-01-01', applicantOnRegister: true, additionalFamilyPresence: false, householdMembersComplete: true, householdSnapshotDate: cutoff, hasSpouse: false, maritalStatus: 'single', hasChildren: false, pregnant: false,
  factChanges: { marital: { mode: 'never_changed', date: '' }, children: { mode: 'never_changed', date: '' }, pregnancy: { mode: 'never_changed', date: '' }, ownership: { mode: 'never_changed', date: '' } }, ...part })
const remarriage = rule('unparsed', { label: '동일 배우자와 재혼한 경우 전체 혼인기간 합산 확인', text: '동일 배우자와 재혼한 경우 이전 혼인기간을 합산하는 공고의 요구가 있습니다.' })
const birth = rule('unparsed', { label: '출산특례 등 무주택 요건의 공식 예외 확인', text: '출산특례 적용의 1회 사용·처분 조건', evidence_text: '2026.10.02. 공고 · ’24.6.19. 이후 출생한 사람을 입양한 경우 포함' })
const home = { ...createOwnershipFact('home'), ownerMemberId: 'applicant', ownerRelation: 'applicant' as const, propertyKind: 'apartment' as const, areaSqm: '84', propertyRegionCode: '41', acquiredDate: '2020-01-01', acquisitionMethod: 'purchase' as const, abandonedOrDestroyedOrNonResidential: false, oldLawUnauthorized: false }
const owned = (part: Partial<LocalProfile> = {}) => profile({ applicantOwnsHome: true, ownershipFactsKnown: true, ownershipFacts: [home], ownershipPropertyCounts: { applicant: '1' }, ...part })
beforeEach(() => setEvaluationToday(today))
afterEach(() => setEvaluationToday(null))

describe('concrete institution ineligibility', () => {
  it('closes only the institution path with no source or no nomination reason', () => {
    const n = notice([rule('age_min', { value: 19, supply_type: '일반공급' })], { rules_complete: false, offered_supplies: [institution, '일반공급'].map((supply_type) => ({ supply_type, unit_type: '84', supply_count: 1, verification: 'official' })) })
    for (const p of [profile({ recommendationReason: 'none' }), profile({ recommendationStatus: 'none', recommendationReason: '' })]) {
      expect(evaluateQualification(n, p, '84', institution)).toMatchObject({ status: 'mismatch', reasons: [{ status: 'fail', category: 'condition' }] })
      expect(evaluateQualification(n, p, '84', '일반공급').status).toBe('review')
    }
  })
  it('keeps pending and genuinely unknown nomination facts unresolved', () => {
    for (const p of [profile(), profile({ recommendationReason: '장애인', recommendationStatus: 'pending' })]) expect(evaluateQualification(notice([]), p, undefined, institution).status).not.toBe('mismatch')
    const r = rule('recommendation', { allowed_reasons: ['장애인'] })
    expect(evaluateRule(r, profile({ recommendationStatus: 'none' }), notice([r])).status).toBe('fail')
    expect(evaluateRule(r, profile({ recommendationReason: 'none', recommendationStatus: 'confirmed' }), notice([r])).status).toBe('fail')
  })
  it('does not add an unoffered institution path', () => {
    expect(evaluateQualification(notice([], { offered_supplies: [] }), profile({ recommendationReason: 'none' }), '84', institution).status).toBe('unpublished')
  })
  it('uses exact nomination reasons to apply only a relevant bank waiver', () => {
    const knownWaiver = rule('recommendation', { allowed_reasons: ['장애인', '국가유공자·보훈'], allowed_recommendation_reasons: ['장애인', '국가유공자·보훈'], require_confirmed: true })
    const unparsedWaiver = rule('unparsed', { label: '철거주택 소유자·도시재생 부지제공자 통장 면제', allowed_recommendation_reasons: ['철거주택 소유자', '도시재생 부지제공자'] })
    const bank = rule('all', { supply_type: institution, conditions: [rule('account_type', { allowed_values: ['comprehensive', 'deposit', 'installment'], criterion_basis: 'application_date', evaluation_mode: 'today_precheck' })], exceptions: [knownWaiver, unparsedWaiver] })
    expect(evaluateRule(bank, profile({ accountType: 'none', recommendationReason: '중소기업 장기근속', recommendationStatus: 'confirmed' }), notice([bank])).status).toBe('fail')
    expect(evaluateRule(bank, profile({ accountType: 'none', recommendationReason: '장애인', recommendationStatus: 'confirmed' }), notice([bank])).status).toBe('pass')
    expect(evaluateRule(bank, profile({ accountType: 'none', recommendationReason: '철거주택 소유자', recommendationStatus: 'confirmed' }), notice([bank]))).toMatchObject({ status: 'review', category: 'source_gap', label: unparsedWaiver.label })
    expect(evaluateRule(bank, profile({ accountType: 'none', recommendationReason: '장애인', recommendationStatus: 'pending' }), notice([bank])).status).toBe('review')
    expect(evaluateRule(bank, profile({ accountType: 'none' }), notice([bank])).status).toBe('review')
  })
  it('separates exact Yongin exclusions from its genuinely unmodeled nomination subsets', () => {
    const nomination = rule('recommendation', { supply_type: institution, allowed_reasons: ['장애인', '국가유공자·보훈'], unsupported_reasons: ['장기복무 군인', '기타'], unsupported_reason_label: '공고에 열거된 장기복무 제대군인·철거주택 소유자의 별도 추천 분기', require_confirmed: true })
    const bank = rule('account_type', { supply_type: institution, allowed_values: ['comprehensive', 'deposit', 'installment'] })
    const n = notice([nomination, bank])
    const p = profile({ accountType: 'comprehensive', recommendationStatus: 'confirmed' })
    for (const recommendationStatus of ['confirmed', 'pending', 'unknown'] as const) expect(evaluateQualification(n, { ...p, recommendationReason: '중소기업 장기근속', recommendationStatus }, undefined, institution)).toMatchObject({ status: 'mismatch', reasons: [{ status: 'fail', category: 'condition', label: '기관추천 대상 사유' }, { status: 'pass' }] })
    expect(evaluateQualification(n, { ...p, recommendationReason: '장애인' }, undefined, institution).status).toBe('possible')
    for (const recommendationReason of ['장기복무 군인', '기타']) expect(evaluateQualification(n, { ...p, recommendationReason }, undefined, institution)).toMatchObject({ status: 'review', reasons: [{ status: 'review', category: 'source_gap', label: nomination.unsupported_reason_label }, { status: 'pass' }] })
    for (const recommendationReason of ['', 'unknown']) expect(evaluateRule(nomination, { ...p, recommendationReason }, n)).toMatchObject({ status: 'review', category: 'missing_input', profileField: 'recommendationReason' })
  })
  it('retains conservative review for old sources without an explicit unsupported subset', () => {
    const r = rule('recommendation', { allowed_reasons: ['장애인'], unsupported_reason_label: '추천 사유의 별도 공식 분기' })
    expect(evaluateRule(r, profile({ recommendationReason: '중소기업 장기근속', recommendationStatus: 'confirmed' }), notice([r]))).toMatchObject({ status: 'review', category: 'source_gap', label: r.unsupported_reason_label })
  })
})

describe('applicability of exact unresolved legal exceptions', () => {
  const marriage = rule('marriage_months_max', { value: 84, supply_type: newlywed, exceptions: [remarriage] })
  const homeless = rule('homeless', { value: true, supply_type: newlywed, exceptions: [birth] })
  it('keeps dated unmarried failure even when remarriage summation is unparsed', () => {
    expect(evaluateRule(marriage, profile(), notice([marriage]))).toMatchObject({ status: 'fail', label: '혼인 필수 조건', category: 'condition' })
    expect(evaluateRule(marriage, profile({ factChanges: {} }), notice([marriage]))).toMatchObject({ status: 'review', category: 'past_fact' })
  })
  it('retains a real or unknown remarriage branch for married facts', () => {
    expect(evaluateRule(marriage, profile({ maritalStatus: 'married', hasSpouse: true, marriageDate: '2010-01-01' }), notice([marriage]))).toMatchObject({ status: 'review', category: 'source_gap', label: remarriage.label })
    expect(officialClauseApplicability(remarriage, profile({ hasSpouse: true }), notice([]))).toBeNull()
  })
  it('does not let a birth waiver rescue owned housing with dated no-child and no-pregnancy facts', () => {
    expect(evaluateRule({ ...homeless, exceptions: [] }, owned(), notice([homeless])).status).toBe('fail')
    expect(evaluateRule(homeless, owned(), notice([homeless]))).toMatchObject({ status: 'fail', category: 'condition' })
  })
  it('retains unknown historical birth facts and genuine pregnancy/qualifying children', () => {
    for (const p of [owned({ factChanges: { ownership: { mode: 'never_changed', date: '' } } }), owned({ pregnant: true }), owned({ hasChildren: true, children: [{ dateOfBirth: '2025-01-01', adopted: false }] })]) expect(evaluateRule(homeless, p, notice([homeless]))).toMatchObject({ status: 'review', category: 'source_gap', label: birth.label })
  })
  it('uses the birth-bound source date to exclude older children, preserving missing source dates', () => {
    const p = owned({ hasChildren: true, children: [{ dateOfBirth: '2010-01-01', adopted: null }] })
    expect(evaluateRule(homeless, p, notice([homeless])).status).toBe('fail')
    const noBirthBound = { ...birth, evidence_text: '공고일 2026.10.02. 출산특례' }
    expect(evaluateRule({ ...homeless, exceptions: [noBirthBound] }, p, notice([homeless])).status).toBe('review')
  })
  it('does not invent child absence from a contradictory roster or unknown adoption', () => {
    for (const p of [owned({ children: [{ dateOfBirth: '2025-01-01', adopted: false }] }), owned({ hasChildren: true, children: [{ dateOfBirth: '2025-01-01', adopted: null }] })]) expect(evaluateRule(homeless, p, notice([homeless])).status).toBe('review')
  })
  it('keeps mixed spouse/marriage/birth waivers until every possible alternative is excluded', () => {
    const mixed = rule('unparsed', { label: '배우자 혼인 전 당첨·혼인특례·출산특례의 1회 사용 조건' })
    const winning = rule('special_winning', { value: false, supply_type: newlywed, scope: 'applicant', exceptions: [mixed] })
    const won = { applicationHistoryEvents: [{ id: 'win', personId: 'applicant', projectId: '2026000468', eventKind: 'winning' as const, eventDate: '2026-01-01', specialSupply: true }] }
    expect(evaluateRule(winning, profile(won), notice([winning])).status).toBe('fail')
    expect(evaluateRule(winning, profile({ ...won, maritalStatus: 'married', hasSpouse: true }), notice([winning])).status).toBe('review')
    expect(evaluateRule(winning, profile({ ...won, factChanges: { children: { mode: 'never_changed', date: '' }, pregnancy: { mode: 'never_changed', date: '' } } }), notice([winning])).status).toBe('review')
  })
  it('retains first-home historical section 53 ownership review', () => {
    const exception = rule('unparsed', { label: '생애최초의 제53조 과거 주택 소유 예외', text: '60세 이상 직계존속 등의 공식 소유 예외를 원시 과거 소유 사실만으로 제외하지 않습니다.' })
    const r = rule('never_owned_home', { value: true, supply_type: firstHome, scope: 'household', exclude_spouse_pre_marriage_disposed: true, exceptions: [exception] })
    expect(evaluateRule(r, profile({ applicantPreviouslyOwnedHome: true }), notice([r]))).toMatchObject({ status: 'review', category: 'source_gap', label: exception.label })
  })
  it('excludes explicitly conflicting supply/unit exceptions before they can rescue a failure', () => {
    for (const exception of [{ ...remarriage, supply_type: firstHome }, { ...remarriage, supply_types: [firstHome] }, { ...remarriage, unit_type: '59' }, { ...remarriage, unit_types: ['59'] }, rule('age_min', { value: 19, supply_type: firstHome })]) expect(evaluateRule({ ...marriage, unit_type: '84', exceptions: [exception] }, profile(), notice([marriage]), '84').status).toBe('fail')
  })
})

describe('profile-aware remaining source topics', () => {
  it('hides nonapplicable remarriage/birth overviews while preserving section 53 and unknown facts', () => {
    const coverage = rule('condition_coverage', { effect: 'metadata', scopes: [
      { supply_type: newlywed, complete: false, topics: [{ topic: remarriage.label, status: 'missing', required: true }] },
      { supply_type: firstHome, complete: true, topics: [{ topic: birth.label, status: 'missing', required: true }, { topic: '생애최초의 제53조 과거 주택 소유 예외', status: 'missing', required: true }] },
    ] })
    expect(conditionSourceStatus(notice([coverage]), profile()).topics.map((item) => item.label)).toEqual(['생애최초의 제53조 과거 주택 소유 예외'])
    expect(conditionSourceStatus(notice([coverage]), profile({ factChanges: {} })).topics.map((item) => item.label)).toContain(remarriage.label)
    expect(conditionSourceStatus(notice([coverage])).topics).toHaveLength(3)
  })
})
