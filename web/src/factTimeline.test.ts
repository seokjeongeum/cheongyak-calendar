import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { contractEvaluationDate, factsAtDate, setEvaluationToday } from './factTimeline'
import { deriveHousehold } from './household'
import { criterionDate, deriveRank, evaluateQualification, evaluateRule } from './qualification'
import { EMPTY_PROFILE, type ContractSchedule, type LocalProfile, type Notice, type NoticeRule } from './types'

const today = '2026-10-05', past = '2026-09-25', source = 'https://apply.lh.or.kr/official'
const rule = (kind: string, extra: Partial<NoticeRule> = {}): NoticeRule => ({ kind, value: true, verification: 'official', evidence_url: source, criterion_date: today, ...extra })
const notice = (rules: NoticeRule[] = [], extra: Partial<Notice> = {}): Notice => ({ id: 'timeline', title: '자격 비교', category: 'public_sale', source: 'lh', provider: 'LH', address: null, region_code: '43', region_name: '충청북도', announcement_date: past, official_url: source, price_cap_status: 'unknown', events: [], prices: [], rules, rules_complete: true, updated_at: null, version: 1, ...extra })
const profile = (extra: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, applicantOnRegister: true, hasSpouse: false, maritalStatus: 'single', applicantOwnsHome: false, householdMembersComplete: true, householdMembers: [], dateOfBirth: '1990-01-01', currentlyDomesticResident: true, ...extra })
const schedule = (status: ContractSchedule['status'], start: string, end: string | null = null): ContractSchedule => ({ status, start_date: start, end_date: end, verification: 'official', source: 'official_document_parser', evidence_url: source, evidence_text: '공식 계약 일정', evidence_page: 8, document_hash: 'official-file' })
beforeEach(() => setEvaluationToday(today))
afterEach(() => setEvaluationToday(null))

describe('today facts and dated factual periods', () => {
  it('uses today facts without an observation-date question', () => {
    const domestic = rule('domestic_residence')
    expect(evaluateRule(domestic, profile(), notice([domestic])).status).toBe('pass')
    expect(deriveHousehold(profile(), today)).toMatchObject({ complete: true, legalCount: 1 })
  })
  it('requires the last actual change to cover a past cutoff', () => {
    const domestic = rule('domestic_residence', { criterion_date: past })
    const run = (extra: Partial<LocalProfile>) => evaluateRule(domestic, profile(extra), notice([domestic]))
    expect(run({}).status).toBe('review')
    expect(run({ factChanges: { domestic_residence: { mode: 'known', date: '2026-09-01' } } }).status).toBe('pass')
    expect(run({ factChanges: { domestic_residence: { mode: 'known', date: '2026-10-01' } } }).status).toBe('review')
    expect(run({ factChanges: { domestic_residence: { mode: 'never_changed', date: '' } } }).status).toBe('pass')
  })
  it('does not interpret a former observation date as the last change', () => {
    const p = profile({ domesticResidenceFactsAsOfDate: '2026-09-01' })
    expect(factsAtDate(p, 'domestic_residence', past, { date: p.domesticResidenceFactsAsOfDate! }).known).toBe(false)
    expect(factsAtDate(p, 'domestic_residence', '2026-09-01', { date: p.domesticResidenceFactsAsOfDate! }).source).toBe('legacy')
  })
  it('uses an exact stored old state and protects unrelated current fields', () => {
    const p = profile({ factSnapshots: [{ group: 'domestic_residence', date: past, values: { currentlyDomesticResident: false, citizenship: 'foreign' } }] })
    const old = factsAtDate(p, 'domestic_residence', past)
    expect(old.profile.currentlyDomesticResident).toBe(false)
    expect(old.profile.citizenship).toBe(p.citizenship)
    expect(evaluateRule(rule('domestic_residence', { criterion_date: past }), p, notice()).status).toBe('fail')
    expect(factsAtDate(p, 'domestic_residence', '2026-09-26').known).toBe(false)
  })
  it('does not reuse stale legacy confirmations after an explicit new change', () => {
    const p = profile({ domesticResidenceFactsAsOfDate: past, domesticResidenceHistoryConfirmations: [{ criterionDate: past, unchanged: true }], factChanges: { domestic_residence: { mode: 'known', date: '2026-10-01' } } })
    expect(evaluateRule(rule('domestic_residence', { criterion_date: past }), p, notice()).status).toBe('review')
  })
  it('uses the old roster instead of the current spouse for past family scope', () => {
    const p = profile({ hasSpouse: true, maritalStatus: 'married', spouseOwnsHome: false, factSnapshots: [{ group: 'household', date: past, values: { hasSpouse: false, maritalStatus: 'single', householdMembers: [], householdMembersComplete: true, applicantOnRegister: true } }] })
    expect(deriveHousehold(p, past)).toMatchObject({ complete: true, legalCount: 1 })
    expect(deriveHousehold(p, today).legalCount).toBe(2)
  })
})

describe('official contract dates without personal planned dates', () => {
  it('uses today for an ongoing contract and ignores former personal planned dates', () => {
    const n = notice([], { contract_schedule: schedule('ongoing', '2026-07-23') })
    expect(criterionDate(rule('age_min', { criterion_basis: 'contract_date', criterion_date: null }), n)).toBe(today)
    expect(evaluateRule(rule('age_min', { value: 19, criterion_basis: 'contract_date', criterion_date: null }), profile({ intendedContractDate: '2020-01-01' }), n)).toMatchObject({ status: 'pass', criterionDate: today })
  })
  it('previews today for fixed dates and future official periods', () => {
    expect(contractEvaluationDate(notice([], { contract_schedule: schedule('fixed', '2026-11-01', '2026-11-01') }))).toBe(today)
    expect(contractEvaluationDate(notice([], { contract_schedule: schedule('range', '2026-11-01', '2026-11-03') }))).toBe(today)
    expect(contractEvaluationDate(notice([], { contract_schedule: schedule('range', '2026-10-01', '2026-10-08') }))).toBe(today)
  })
  it('compares today separately from ended, unverified and future official schedules', () => {
    for (const contract_schedule of [schedule('range', '2026-09-01', '2026-09-03'), schedule('ongoing', '2026-11-01'), { ...schedule('fixed', today), verification: 'unknown' }]) {
      const n = notice([], { contract_schedule })
      expect(contractEvaluationDate(n)).toBe(today)
      expect(evaluateRule(rule('age_min', { value: 19, criterion_basis: 'contract_date', criterion_date: null }), profile(), n)).toMatchObject({ status: 'pass', contractPreview: true, criterionDate: today })
    }
  })
})

describe('common person and project application history', () => {
  const restriction = (kind = 'prior_project_winner', date = today) => rule('application_restriction', { value: false, scope: 'applicant', restriction: kind, project_id: '2026000323', criterion_date: date })
  const history = (extra: Partial<LocalProfile> = {}) => profile({ applicationHistoryPresence: false, applicationHistoryComplete: true, applicationHistoryPeople: ['applicant'], ...extra })
  it('reuses a complete no-history answer across multiple projects', () => {
    for (const project_id of ['2026000323', 'LH-SUWON-DANGSU-A3']) expect(evaluateRule({ ...restriction(), project_id }, history(), notice()).status).toBe('pass')
  })
  it('matches dates, people, original projects and reserve/additional event types', () => {
    const event = { id: 'event', personId: 'applicant', projectId: '2026000323', eventKind: 'reserve_winning' as const, eventDate: '2026-10-01' }
    const p = history({ applicationHistoryPresence: true, applicationHistoryEvents: [event] })
    expect(evaluateRule(restriction(), p, notice()).status).toBe('fail')
    expect(evaluateRule(restriction('prior_project_winner', past), p, notice()).status).toBe('pass')
    expect(evaluateRule({ ...restriction(), project_id: '2026000999' }, p, notice()).status).toBe('pass')
    expect(evaluateRule(restriction('prior_project_contract'), p, notice()).status).toBe('pass')
    expect(evaluateRule(restriction('prior_project_contract'), { ...p, applicationHistoryEvents: [{ ...event, eventKind: 'additional_resident_contract' }] }, notice()).status).toBe('fail')
  })
  it('does not conclude no history for an uncovered spouse or unanswered substantive history', () => {
    const p = history({ hasSpouse: true, maritalStatus: 'married', spouseOwnsHome: false })
    expect(evaluateRule({ ...restriction(), scope: 'applicant_spouse' }, p, notice())).toMatchObject({ status: 'review', profileField: 'applicationHistoryAbsencePeople' })
    expect(evaluateRule(restriction(), history({ applicationHistoryPresence: true, applicationHistoryComplete: false }), notice()).status).toBe('review')
  })
  it('reuses actual dated events and person-specific absence without asking for completeness', () => {
    const p = history({ applicationHistoryPresence: true, applicationHistoryComplete: false, applicationHistoryPeople: [], applicationHistoryEvents: [{ id: 'event', personId: 'applicant', projectId: '2026000999', eventKind: 'winning', eventDate: past }] })
    expect(evaluateRule(restriction(), p, notice()).status).toBe('pass')
    expect(evaluateRule(restriction(), profile({ applicationHistoryAbsencePeople: ['applicant'] }), notice()).status).toBe('pass')
    expect(evaluateRule(restriction(), { ...p, applicationHistoryEvents: [{ ...p.applicationHistoryEvents[0], eventDate: '' }] }, notice()).status).toBe('review')
  })
  it('can establish a known event before all other events are entered', () => {
    const p = history({ applicationHistoryPresence: true, applicationHistoryComplete: false, applicationHistoryEvents: [{ id: 'event', personId: 'applicant', projectId: '2026000323', eventKind: 'winning', eventDate: past }] })
    expect(evaluateRule(restriction(), p, notice()).status).toBe('fail')
  })
  it('does not treat a default winning row with an unknown project as a real general win', () => {
    const p = history({ applicationHistoryPresence: true, applicationHistoryComplete: false, applicationHistoryEvents: [{ id: 'event', personId: 'applicant', projectId: '', eventKind: 'winning', eventDate: past }] })
    expect(evaluateRule(rule('previous_winning', { value: false, scope: 'applicant' }), p, notice())).toMatchObject({ status: 'review', profileField: 'applicationHistoryEvents' })
  })
  it('does not turn a legacy project answer into a dated common event', () => {
    const p = profile({ projectApplicationHistory: { '2026000323': { winning: true, contract: false, additionalResident: false, winningScope: 'applicant', contractScope: 'applicant', asOfDate: past, historyConfirmations: [] } } })
    expect(evaluateRule(restriction('prior_project_winner', past), p, notice()).status).toBe('fail')
    expect(evaluateRule(restriction(), p, notice()).status).toBe('review')
    expect(p.applicationHistoryEvents).toEqual([])
  })
  it('filters special supply winners without treating a reserve as a general winner', () => {
    const p = history({ applicationHistoryPresence: true, applicationHistoryEvents: [{ id: 'a', personId: 'applicant', projectId: '2026000323', eventKind: 'winning', eventDate: past, specialSupply: false }] })
    expect(evaluateRule(rule('special_winning', { value: false, scope: 'applicant' }), p, notice()).status).toBe('pass')
    expect(evaluateRule(rule('special_winning', { value: false, scope: 'applicant' }), { ...p, applicationHistoryEvents: [{ ...p.applicationHistoryEvents[0], specialSupply: null }] }, notice()).status).toBe('review')
  })
})

describe('mandatory marriage and alternative routes', () => {
  const married = rule('marital_status', { allowed_values: ['married'], value: null })
  const period = rule('marriage_months_max', { value: 84 })
  const path = rule('all', { value: null, conditions: [married, period, rule('homeless')] })
  it('fails a mandatory marriage path without asking for a duration or spouse', () => {
    const result = evaluateRule(path, profile(), notice())
    expect(result.status).toBe('fail')
    expect(result.profileField).toBeUndefined()
    expect(result.detail).not.toContain('혼인 기간 정보를 입력')
    expect(evaluateRule(period, profile(), notice()).status).toBe('fail')
  })
  it('retains a passing OR alternative when the marriage route fails', () => {
    const alternative = rule('any', { conditions: [path, rule('age_min', { value: 19 })], value: null })
    expect(evaluateQualification(notice([alternative]), profile()).status).toBe('possible')
  })
  it('asks for a historical status change instead of an impossible marriage period', () => {
    const result = evaluateRule({ ...period, criterion_date: past }, profile(), notice())
    expect(result).toMatchObject({ status: 'review', profileField: 'maritalStatus' })
    expect(result).toMatchObject({ category: 'past_fact', historyGroup: 'marital', label: '혼인 상태 변경일' })
  })
  it('does not link an unavailable old-address form after a later move', () => {
    const r = rule('residence_region', { region_code: '11', criterion_date: past })
    const result = evaluateRule(r, profile({ regionCode: '11', region: '서울특별시', movedInDate: '2026-10-01' }), notice())
    expect(result).toMatchObject({ status: 'review', category: 'past_fact' })
    expect(result.profileField).toBeUndefined()
  })
  it('assumes entered bank rank values have been confirmed', () => {
    const rankRules = [rule('account_type', { purpose: 'first_rank', allowed_values: ['comprehensive'] }), rule('private_rank_months', { purpose: 'first_rank', value: 12 }), rule('deposit_min_krw', { purpose: 'first_rank', value: 3000000, require_as_of_date: true }), rule('rank_requirements', { effect: 'metadata', complete: true, housing_kind: 'private', required_kinds: ['account_type', 'private_rank_months', 'deposit_min_krw'] })]
    const n = notice(rankRules, { housing_kind: 'private', housing_kind_evidence: { verification: 'official' } })
    expect(deriveRank(n, profile({ accountType: 'comprehensive', privateRankBaseDate: '2020-01-01', privateDepositKrw: '3000000', accountConversionUnclear: true }))).toMatchObject({ rank: 'first', status: 'possible' })
  })
})
