import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setEvaluationToday } from './factTimeline'
import { conditionCoverage, evaluateQualification } from './qualification'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'

const today = '2026-10-12', cutoff = '2026-10-06', hash = 'a'.repeat(64)
const source = 'https://apply.lh.or.kr/current-public-notice.pdf', supply = '일반공급'
const rule = (id: string, kind: string, extra: Partial<NoticeRule> = {}): NoticeRule => ({
  id, kind, verification: 'official', supply_type: supply, criterion_date: cutoff,
  document_hash: hash, evidence_url: source, evidence_page: 3, evidence_text: '현재 모집공고의 개인 신청자격', ...extra,
})
const admission = [
  rule('adult-age', 'age_min', { value: 19 }),
  rule('domestic-address', 'domestic_residence', { value: true }),
  rule('applicant-citizenship', 'citizenship', { allowed_values: ['korean'] }),
]
const scope = (extra: Record<string, unknown> = {}): Record<string, unknown> => ({
  supply_type: supply, complete: true, verified_rule_count: admission.length, missing_topics: [],
  topics: [
    { topic: 'age', status: 'verified', required: true, rule_ids: ['adult-age'] },
    { topic: 'domestic_residence', status: 'verified', required: true, rule_ids: ['domestic-address'] },
    { topic: 'citizenship', status: 'verified', required: true, rule_ids: ['applicant-citizenship'] },
  ],
  source_gaps: [], reviewed_document_hash: hash, review_version: 'generic-admission-2026-10-12-public-v1',
  reviewed_pages: [1, 2, 3, 4], reviewed_section_pages: [3], completion_basis: 'current_document_clause_coverage',
  branches: [
    { branch_id: 'adult', label: '성년 개인 신청자', status: 'verified', required: true, rule_ids: admission.map((entry) => entry.id), requirements: ['age', 'domestic_residence', 'citizenship'] },
    { branch_id: 'corporate', label: '법인 계약의 대표·위임 서류', status: 'not_applicable', required: false, phase: 'application', reason: '개인 신청자격 비교 범위 밖의 법인 계약 절차' },
  ],
  ...extra,
})
const coverageRule = (review: Record<string, unknown>, extra: Partial<NoticeRule> = {}): NoticeRule => rule('clause-review', 'condition_coverage', {
  effect: 'metadata', status: 'complete', scopes: [review], completion_basis: 'current_document_clause_coverage', ...extra,
})
const notice = (review = scope(), extra: Partial<Notice> = {}): Notice => ({
  id: 'public-clauses-v18', title: '공공분양 현재 신청자격', category: 'public_sale', source: 'lh', provider: 'LH',
  address: null, region_code: null, region_name: null, announcement_date: cutoff, official_url: source,
  document_hash: hash, price_cap_status: 'unknown', events: [], prices: [], updated_at: null, version: 1,
  rules_complete: true, rules: [...admission, coverageRule(review)], ...extra,
})
const profile = (extra: Partial<LocalProfile> = {}): LocalProfile => ({
  ...EMPTY_PROFILE, dateOfBirth: '1990-01-01', currentlyDomesticResident: true,
  domesticResidenceFactsAsOfDate: cutoff, citizenship: 'korean', factChanges: { citizenship: { mode: 'never_changed', date: '' } }, ...extra,
})
const assertSourceReview = (item: Notice): void => {
  expect(conditionCoverage(item, undefined, supply).complete).toBe(false)
  const result = evaluateQualification(item, profile(), undefined, supply)
  expect(result.status).toBe('review')
  expect(result.reasons.some((reason) => reason.status === 'review' && reason.category === 'source_gap' && reason.label === '미확보 공고 조항')).toBe(true)
}
beforeEach(() => setEvaluationToday(today))
afterEach(() => setEvaluationToday(null))

describe('current public-v1 clause coverage and personal facts', () => {
  it('accepts current hash, reviewed pages and verified required branches for fulfilled facts', () => {
    const item = notice()
    expect(conditionCoverage(item, undefined, supply)).toMatchObject({ complete: true, verifiedCount: 3, missingTopics: [] })
    const result = evaluateQualification(item, profile(), undefined, supply)
    expect(result.status).toBe('possible')
    expect(result.reasons.map((reason) => [reason.ruleId, reason.status])).toEqual([
      ['adult-age', 'pass'], ['domestic-address', 'pass'], ['applicant-citizenship', 'pass'],
    ])
  })

  it('requires the public-v1 version and exact current-clause completion basis together', () => {
    for (const review of [
      scope({ completion_basis: null }),
      scope({ completion_basis: 'validated_residual_qualification_clauses' }),
      scope({ review_version: 'generic-admission-older-version' }),
    ]) assertSourceReview(notice(review))
  })

  it('rejects an absent review hash, a different review hash or rules from another document', () => {
    assertSourceReview(notice(scope({ reviewed_document_hash: undefined })))
    assertSourceReview(notice(scope({ reviewed_document_hash: 'b'.repeat(64) })))
    assertSourceReview(notice(scope(), { rules: [...admission, coverageRule(scope(), { document_hash: undefined })] }))
    assertSourceReview(notice(scope(), { rules: [...admission.map((entry, index) => index === 1 ? { ...entry, document_hash: 'b'.repeat(64) } : entry), coverageRule(scope())] }))
  })

  it('rejects missing, empty or malformed reviewed page records', () => {
    for (const reviewed_pages of [undefined, [], [0], [-1], [1.5], ['3'], [1, null]]) {
      assertSourceReview(notice(scope({ reviewed_pages })))
    }
  })

  it('keeps source gaps and missing topics unresolved even when the complete flag was retained', () => {
    for (const review of [
      scope({ source_gaps: [{ item: '신청자격 예외 조항', stage: 'clause_extraction', evidence_page: 3 }] }),
      scope({ source_gaps: undefined }),
      scope({ missing_topics: ['현재 신청자격의 예외'] }),
      scope({ missing_topics: undefined }),
    ]) assertSourceReview(notice(review))
  })

  it('requires every required branch to be verified while allowing a documented optional branch', () => {
    for (const branches of [
      undefined, [],
      [{ branch_id: 'adult', required: true, status: 'partial' }],
      [{ branch_id: 'adult', required: true, status: 'not_applicable' }],
      [{ branch_id: 'adult', status: 'missing' }],
      [{ branch_id: 'adult', required: 'yes', status: 'verified' }],
    ]) assertSourceReview(notice(scope({ branches })))
    expect(conditionCoverage(notice(), undefined, supply).complete).toBe(true)
  })

  it('requires a positive integer verified-rule count for the current review', () => {
    for (const verified_rule_count of [undefined, 0, -1, 1.5, '3']) {
      assertSourceReview(notice(scope({ verified_rule_count })))
    }
  })

  it('keeps a required incomplete topic open even when all branches and source records are complete', () => {
    for (const status of ['partial', 'missing']) {
      assertSourceReview(notice(scope({ topics: [{ topic: 'domestic_residence', status, required: true, rule_ids: ['domestic-address'], reason: '국내 거주 인정 범위 미확보' }] })))
    }
  })

  it('does not let a complete official scope supply an unanswered personal fact or its past provenance', () => {
    const item = notice()
    expect(conditionCoverage(item, undefined, supply).complete).toBe(true)
    const missing = evaluateQualification(item, profile({ currentlyDomesticResident: null }), undefined, supply)
    expect(missing.status).toBe('review')
    expect(missing.reasons.find((reason) => reason.ruleId === 'domestic-address')).toMatchObject({ status: 'review', category: 'missing_input', profileField: 'currentlyDomesticResident' })
    const past = evaluateQualification(item, profile({ domesticResidenceFactsAsOfDate: today }), undefined, supply)
    expect(past.status).toBe('review')
    expect(past.reasons.find((reason) => reason.ruleId === 'domestic-address')).toMatchObject({ status: 'review', category: 'past_fact', historyGroup: 'domestic_residence' })
  })

  it('does not let an earlier complete official review hide an incomplete current review or missing input', () => {
    const prior = coverageRule(scope()), current = coverageRule(scope({ source_gaps: [{ item: '현재 예외 원문', stage: 'clause_extraction' }] }), { id: 'current-clause-review' })
    const item = notice(scope(), { rules: [...admission, prior, current] })
    expect(conditionCoverage(item, undefined, supply).complete).toBe(false)
    const result = evaluateQualification(item, profile({ currentlyDomesticResident: null }), undefined, supply)
    expect(result.status).toBe('review')
    expect(result.reasons.find((reason) => reason.ruleId === 'domestic-address')).toMatchObject({ status: 'review', category: 'missing_input' })
    expect(result.reasons.some((reason) => reason.label === '미확보 공고 조항')).toBe(true)
  })

  it('does not complete a review after a referenced condition was deleted, including provider employee restrictions', () => {
    assertSourceReview(notice(scope(), { rules: [...admission.filter((entry) => entry.id !== 'domestic-address'), coverageRule(scope())] }))
    const employee = rule('provider-employee', 'provider_employee_restriction', { value: false })
    const review = scope({
      verified_rule_count: 4,
      topics: [...scope().topics as Record<string, unknown>[], { topic: 'provider_employee', status: 'verified', required: true, rule_ids: [employee.id] }],
      branches: [...scope().branches as Record<string, unknown>[], { branch_id: 'provider_employee', status: 'verified', required: true, rule_ids: [employee.id] }],
    })
    const full = notice(review, { rules: [...admission, employee, coverageRule(review)] })
    const facts = profile({ providerEmployeeOrRelatedFamily: false, factChanges: {
      citizenship: { mode: 'never_changed', date: '' }, provider_employee: { mode: 'never_changed', date: '' },
    } })
    expect(conditionCoverage(full, undefined, supply).complete).toBe(true)
    expect(evaluateQualification(full, facts, undefined, supply).status).toBe('possible')
    assertSourceReview({ ...full, rules: full.rules.filter((entry) => entry.id !== employee.id) })
  })

  it('requires referenced conditions and their review to belong to the notice current document', () => {
    assertSourceReview(notice(scope(), { rules: [
      ...admission.map((entry) => entry.id === 'domestic-address' ? { ...entry, document_hash: undefined } : entry), coverageRule(scope()),
    ] }))
    assertSourceReview(notice(scope(), { rules: [
      ...admission.map((entry) => entry.id === 'domestic-address' ? { ...entry, document_hash: 'b'.repeat(64) } : entry), coverageRule(scope()),
    ] }))
    const oldHash = 'b'.repeat(64), oldReview = scope({ reviewed_document_hash: oldHash })
    assertSourceReview(notice(oldReview, { rules: [
      ...admission.map((entry) => ({ ...entry, document_hash: oldHash })), coverageRule(oldReview, { document_hash: oldHash }),
    ] }))
  })

  it('requires nonempty valid rule references on every verified required topic', () => {
    for (const rule_ids of [undefined, null, [], [''], 'domestic-address']) {
      const topics = (scope().topics as Record<string, unknown>[]).map((topic) => topic.topic === 'domestic_residence' ? { ...topic, rule_ids } : topic)
      assertSourceReview(notice(scope({ topics })))
    }
  })

  it('requires the verified count to match the distinct referenced current conditions', () => {
    for (const verified_rule_count of [1, 2, 4, 20]) assertSourceReview(notice(scope({ verified_rule_count })))
    expect(conditionCoverage(notice(), undefined, supply)).toMatchObject({ complete: true, verifiedCount: 3 })
  })

  it('rejects nonexistent or empty references in a required verified branch', () => {
    for (const rule_ids of [[], [''], ['deleted-condition']]) {
      const review = scope({
        verified_rule_count: rule_ids[0] === 'deleted-condition' ? 4 : 3,
        branches: [{ branch_id: 'adult', required: true, status: 'verified', rule_ids }],
      })
      assertSourceReview(notice(review))
    }
  })
})
