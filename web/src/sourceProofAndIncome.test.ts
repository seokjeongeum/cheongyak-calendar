import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setEvaluationToday } from './factTimeline'
import { conditionCoverage, evaluateQualification, evaluateRule } from './qualification'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'

const today = '2026-10-09', cutoff = '2026-10-02', source = 'https://example.com/current-attachment.pdf'
const rule = (kind: string, part: Partial<NoticeRule> = {}): NoticeRule => ({ kind, verification: 'official', criterion_date: cutoff, document_hash: 'old-reviewed-hash', evidence_url: source, ...part })
const notice = (rules: NoticeRule[]): Notice => ({ id: 'proof', title: '공식 조건 검증', category: 'apt', source: 'cheongyak_home', provider: '청약홈', address: null, region_code: null, region_name: null, announcement_date: cutoff, official_url: source, price_cap_status: 'unknown', events: [], prices: [], rules, rules_complete: true, updated_at: null, version: 1 })
const profile = (part: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, dateOfBirth: '1990-01-01', factChanges: { income: { mode: 'known', date: '2026-09-01' } }, ...part })
beforeEach(() => setEvaluationToday(today))
afterEach(() => setEvaluationToday(null))

describe('latest attachment identity proof', () => {
  const age = rule('age_min', { value: 19, supply_type: '일반공급' })
  const complete = rule('condition_coverage', { effect: 'metadata', scopes: [{ supply_type: '일반공급', complete: true, topics: [] }] })
  const mismatch = (status = 'unreadable') => rule('document_diagnostics', { effect: 'metadata', status, diagnostics: [{ stage: 'identity', code: 'current_document_mismatch', status: 'error', evidence_url: source, missing_items: ['해당 공고번호·공고일이 일치하는 모집공고 첨부'] }] })
  it('blocks old complete coverage when the same URL now has the wrong notice identity', () => {
    const n = notice([age, complete, mismatch()])
    expect(conditionCoverage(n, undefined, '일반공급')).toMatchObject({ complete: false, missingTopics: ['최신 모집공고 첨부의 신청 제한·면제 원문 미확보'] })
    expect(evaluateQualification(n, profile(), undefined, '일반공급')).toMatchObject({ status: 'review', reasons: [{ status: 'pass' }, { status: 'review', category: 'source_gap' }] })
  })
  it('also blocks an explicit identity failure without an attachment URL or hash', () => {
    const diagnostic = rule('document_diagnostics', { effect: 'metadata', status: 'error', diagnostics: [{ stage: 'identity', code: 'current_document_mismatch', status: 'error' }] })
    expect(conditionCoverage(notice([{ ...age, document_hash: undefined }, { ...complete, document_hash: undefined }, diagnostic]), undefined, '일반공급').complete).toBe(false)
  })
  it('allows a recovered matched attachment despite an earlier ancillary identity failure', () => {
    for (const status of ['partial', 'complete']) expect(conditionCoverage(notice([age, complete, mismatch(status)]), undefined, '일반공급').complete).toBe(true)
  })
  it('preserves an actual unresolved legal exception without inventing an applicant question', () => {
    const text = '현재 부모 소유 예외만으로 모든 과거 취득·처분의 예외 적용을 확정할 수 없습니다.'
    const unknown = rule('unparsed', { label: '제53조 과거 주택 소유 예외', text })
    const assessed = evaluateRule(unknown, profile(), notice([unknown]))
    expect(assessed).toMatchObject({ status: 'review', category: 'source_gap', label: '제53조 과거 주택 소유 예외', detail: text })
    expect(assessed.profileField).toBeUndefined()
  })
  it('reviews an unsupported confirmed nomination branch while retaining a known no-nomination failure', () => {
    const r = rule('recommendation', { require_confirmed: true, allowed_reasons: ['장애인'], unsupported_reason_label: '철거주택 소유자·도시재생 부지제공자 추천 분기' })
    const assessed = evaluateRule(r, profile({ recommendationStatus: 'confirmed', recommendationReason: '철거주택 소유자' }), notice([r]))
    expect(assessed).toMatchObject({ status: 'review', category: 'source_gap', label: '철거주택 소유자·도시재생 부지제공자 추천 분기' })
    expect(assessed.profileField).toBeUndefined()
    expect(evaluateRule(r, profile({ recommendationStatus: 'none', recommendationReason: '장애인' }), notice([r])).status).toBe('fail')
    expect(evaluateRule(r, profile({ recommendationStatus: 'confirmed', recommendationReason: '장애인' }), notice([r])).status).toBe('pass')
  })
})

describe('official excess-income branch and 9+ household footnote', () => {
  const income = (percent = 160, part: Partial<NoticeRule> = {}): NoticeRule => rule('monthly_income_max_krw', { value_basis: 'household_monthly_income', household_size_basis: 'official_income_household', income_table: [{ household_size: 8, max_krw: Math.round(11064819 * percent / 100) }], extra_person_krw: percent === 160 ? 926845 : 810989, extra_person_base_krw: 579278, extra_person_income_base_last_krw: 11064819, income_percent: percent, ...part })
  it('compares and displays > for the official income-excess branch', () => {
    const r = income(160, { operator: '>' }), p = profile({ incomeHouseholdSize: '8', monthlyIncomeKrw: '17703710' })
    expect(evaluateRule(r, p, notice([r]))).toMatchObject({ status: 'fail', requirement: '공식 소득 산정 8인 · > 17,703,710원' })
    expect(evaluateRule(r, { ...p, monthlyIncomeKrw: '17703711' }, notice([r])).status).toBe('pass')
  })
  it('rounds the unscaled official formula once for each 9+ household size', () => {
    for (const percent of [140, 160]) for (const size of [9, 13, 20]) {
      const r = income(percent), limit = Math.round((11064819 + (size - 8) * 579278) * percent / 100)
      const p = profile({ incomeHouseholdSize: String(size), monthlyIncomeKrw: String(limit) })
      expect(evaluateRule(r, p, notice([r]))).toMatchObject({ status: 'pass', requirement: `공식 소득 산정 ${size}인 · <= ${limit.toLocaleString('ko-KR')}원` })
      expect(evaluateRule(r, { ...p, monthlyIncomeKrw: String(limit + 1) }, notice([r])).status).toBe('fail')
    }
  })
  it('keeps the generic documented increment when the original unscaled metadata is absent', () => {
    const r = income(160, { income_percent: undefined, extra_person_base_krw: undefined, extra_person_income_base_last_krw: undefined })
    const limit = 17703710 + 5 * 926845
    expect(evaluateRule(r, profile({ incomeHouseholdSize: '13', monthlyIncomeKrw: String(limit) }), notice([r]))).toMatchObject({ status: 'pass', requirement: `공식 소득 산정 13인 · <= ${limit.toLocaleString('ko-KR')}원` })
  })
})
