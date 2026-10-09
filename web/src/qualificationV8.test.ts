import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { contractEvaluationDate, setEvaluationToday } from './factTimeline'
import { conditionCoverage, criterionDate, evaluateQualification, evaluateRule, specialDiagnostics } from './qualification'
import { evaluateEligibility } from './eligibility'
import { createOwnershipFact, EMPTY_PROFILE, type ApplicationHistoryEvent, type LocalProfile, type Notice, type NoticeRule } from './types'

const today = '2026-10-07', cutoff = '2026-09-23', source = 'https://apply.lh.or.kr/lhapply/lhFile.do?fileid=68804506'
const project = 'LH-INCHEON-GAJEONG2-B2'
const rule = (kind: string, extra: Partial<NoticeRule> = {}): NoticeRule => ({ kind, verification: 'official', evidence_url: source, criterion_date: cutoff, ...extra })
const notice = (rules: NoticeRule[], extra: Partial<Notice> = {}): Notice => ({ id: 'v8', title: '공식 조건 비교', category: 'public_sale', source: 'lh', provider: 'LH', address: null, region_code: null, region_name: null, announcement_date: cutoff, official_url: source, price_cap_status: 'unknown', events: [], prices: [], rules, rules_complete: true, updated_at: null, version: 1, ...extra })
const profile = (extra: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, dateOfBirth: '1990-01-01', applicantOnRegister: true, hasSpouse: false, maritalStatus: 'single', applicantOwnsHome: false, householdMembersComplete: true, householdSnapshotDate: cutoff, currentlyDomesticResident: true, domesticResidenceFactsAsOfDate: cutoff, overseasContinuousDays: '0', overseasFactsAsOfDate: cutoff, applicationHistoryPresence: false, applicationHistoryComplete: true, applicationHistoryPeople: ['applicant'], ...extra })
beforeEach(() => setEvaluationToday(today))
afterEach(() => setEvaluationToday(null))

describe('contract conditions preview KST today and preserve announcement conditions', () => {
  const contract = rule('age_min', { value: 19, criterion_basis: 'contract_date', criterion_date: '2026-10-27' })
  it('does not grant a future birthday or query a personal contract date', () => {
    const n = notice([contract], { contract_schedule: { status: 'range', start_date: '2026-10-27', end_date: '2027-08-31', verification: 'official', evidence_url: source } })
    expect(contractEvaluationDate(n)).toBe(today)
    expect(criterionDate(contract, n)).toBe(today)
    expect(evaluateRule(contract, profile({ dateOfBirth: '2007-10-20', intendedContractDate: '2026-10-27' }), n)).toMatchObject({ status: 'fail', criterionDate: today, contractPreview: true })
    expect(n.contract_schedule?.start_date).toBe('2026-10-27')
  })
  it('compares today even if the official schedule has not been collected', () => {
    expect(evaluateRule(rule('household_head', { value: true, criterion_basis: 'contract_date' }), profile({ isHouseholdHead: true }), notice([]))).toMatchObject({ status: 'pass', criterionDate: today, contractPreview: true })
  })
  it('keeps a historical announcement cutoff and uses saved facts there', () => {
    const head = rule('household_head', { value: true, criterion_basis: 'announcement' })
    expect(evaluateRule(head, profile({ isHouseholdHead: true }), notice([head]))).toMatchObject({ status: 'review', category: 'past_fact', label: '세대주 상태 변경일', profileField: 'isHouseholdHead', historyGroup: 'household_head', criterionDate: cutoff })
    expect(evaluateRule(head, profile({ isHouseholdHead: true, factChanges: { household_head: { mode: 'known', date: '2026-09-01' } } }), notice([head]))).toMatchObject({ status: 'pass', criterionDate: cutoff })
  })
  it('reuses historical snapshots and changes the preview at the next Korean day', () => {
    const head = rule('household_head', { value: true, criterion_basis: 'announcement' })
    expect(evaluateRule(head, profile({ isHouseholdHead: false, factSnapshots: [{ group: 'household_head', date: cutoff, values: { isHouseholdHead: true } }] }), notice([])).status).toBe('pass')
    const p = profile({ dateOfBirth: '2007-10-08' })
    expect(evaluateRule(contract, p, notice([])).status).toBe('fail')
    setEvaluationToday('2026-10-08')
    expect(evaluateRule(contract, p, notice([]))).toMatchObject({ status: 'pass', criterionDate: '2026-10-08' })
  })
  it('does not reuse a previous-day preview for the same cached public notice and local profile', () => {
    const n = notice([contract]), p = profile({ dateOfBirth: '2007-10-08' })
    expect(evaluateEligibility(n, p).status).toBe('mismatch')
    setEvaluationToday('2026-10-08')
    expect(evaluateEligibility(n, p)).toMatchObject({ status: 'possible', reasons: [{ status: 'pass', criterionDate: '2026-10-08', contractPreview: true }] })
  })
})

describe('Gajeong current continuous overseas stay and actual livelihood exception', () => {
  const overseas = rule('overseas_residence', { supply_type: '일반공급', max_continuous_days: 90, value_basis: 'continuous_days_including_reentry_within_7_days', currently_abroad_only: true, reentry_same_country: true, livelihood_exception: true, livelihood_exception_requires_family: true })
  const domestic = rule('domestic_residence', { value: true, supply_type: '일반공급', overseas_residence_equivalence: true })
  const n = notice([overseas, domestic])
  it('accepts a returned resident without making a completed 120 day trip a failure', () => {
    expect(evaluateQualification(n, profile({ overseasContinuousDays: '120' }), undefined, '일반공급').status).toBe('possible')
  })
  it('accepts 90 days abroad as the official domestic-residence equivalent', () => {
    const p = profile({ currentlyDomesticResident: false, overseasContinuousDays: '90' })
    expect(evaluateQualification(n, p, undefined, '일반공급').status).toBe('possible')
    expect(evaluateRule(overseas, p, n).detail).toContain('같은 국가로')
  })
  it('fails 91 days for a one-person household even when livelihood is claimed', () => {
    expect(evaluateRule(overseas, profile({ currentlyDomesticResident: false, overseasContinuousDays: '91', overseasOnlyApplicantForLivelihood: true }), n)).toMatchObject({ status: 'fail', label: '해외 거주 생업 예외' })
  })
  it('allows only the documented family livelihood exception and reuses its cutoff', () => {
    const p = profile({ currentlyDomesticResident: false, overseasContinuousDays: '91', hasSpouse: true, maritalStatus: 'married', spouseOwnsHome: false, overseasOnlyApplicantForLivelihood: true })
    expect(evaluateQualification(n, p, undefined, '일반공급').status).toBe('possible')
    expect(evaluateRule(overseas, { ...p, overseasOnlyApplicantForLivelihood: null }, n)).toMatchObject({ status: 'review', category: 'missing_input', profileField: 'overseasOnlyApplicantForLivelihood' })
    expect(evaluateRule(overseas, { ...p, domesticResidenceFactsAsOfDate: today }, n)).toMatchObject({ status: 'review', category: 'past_fact', historyGroup: 'domestic_residence' })
  })
})

describe('original winner contracts are property facts, not a blanket win ban', () => {
  const ownership = rule('original_project_contract_ownership', { supply_type: '일반공급', project_id: project, scope: 'applicant', original_announcement_date: '2026-04-15', requires_original_winning: true, ownership_effect: 'contract_date' })
  const event = (eventKind: ApplicationHistoryEvent['eventKind'], eventDate: string, projectId = project): ApplicationHistoryEvent => ({ id: `${eventKind}-${eventDate}`, personId: 'applicant', projectId, eventKind, eventDate })
  const winner = event('winning', '2026-04-20'), contract = event('contract', '2026-05-01')
  const p = (applicationHistoryEvents: ApplicationHistoryEvent[], extra: Partial<LocalProfile> = {}) => profile({ applicationHistoryPresence: true, applicationHistoryEvents, ...extra })
  const fact = { ...createOwnershipFact('contract-right'), projectId: project, ownerMemberId: 'applicant', ownerRelation: 'applicant' as const, propertyKind: 'presale_right' as const, underlyingPropertyKind: 'apartment' as const, acquiredDate: contract.eventDate, acquisitionMethod: 'purchase' as const, areaSqm: '74', propertyRegionCode: '28' }
  it('does not exclude a first winner or an ineligible history alone', () => {
    expect(evaluateRule(ownership, p([winner], { ineligibleRestrictionActive: true }), notice([])).status).toBe('pass')
  })
  it('requires a factual association of the contract property to the exact project', () => {
    const unlinked = { ...fact, projectId: 'LH-OTHER-PROJECT', disposedDate: '2026-08-01' }
    expect(evaluateRule(ownership, p([winner, contract], { ownershipFactsKnown: true, ownershipFacts: [unlinked] }), notice([]))).toMatchObject({ status: 'review', category: 'missing_input', profileField: 'ownershipFacts' })
  })
  it('assesses the contracted right and reuses its actual disposition', () => {
    expect(evaluateRule(ownership, p([winner, contract], { ownershipFactsKnown: true, ownershipFacts: [fact] }), notice([])).status).toBe('fail')
    expect(evaluateRule(ownership, p([winner, contract], { ownershipFactsKnown: true, ownershipFacts: [{ ...fact, disposedDate: '2026-09-01' }] }), notice([])).status).toBe('pass')
  })
  it('does not confuse another project, a reserve nomination, or later contract with original ownership', () => {
    for (const events of [[winner, event('contract', '2026-05-01', 'LH-OTHER-PROJECT')], [event('reserve_winning', '2026-04-20'), contract], [winner, event('contract', '2026-10-01')]]) expect(evaluateRule(ownership, p(events), notice([])).status).toBe('pass')
  })
  it('reuses dated events without requiring a completion confirmation and asks substantive missing dates', () => {
    expect(evaluateRule(ownership, p([winner], { applicationHistoryComplete: false }), notice([])).status).toBe('pass')
    expect(evaluateRule(ownership, p([{ ...winner, eventDate: '' }], { applicationHistoryComplete: false }), notice([]))).toMatchObject({ status: 'review', profileField: 'applicationHistoryEvents' })
  })
})

describe('conclusive path failure and source review scope', () => {
  it('stops elder-parent questions on 60 < 65 and keeps other offered paths open', () => {
    const elder = '노부모부양 특별공급', institution = '기관추천 특별공급'
    const rules = [rule('parent_age_min', { value: 65, supply_type: elder }), rule('parent_support_months_min', { value: 36, supply_type: elder }), rule('household_head', { value: true, supply_type: elder }), rule('recognized_payments_min', { value: 12, supply_type: elder }), rule('recommendation', { value: true, supply_type: institution })]
    const n = notice(rules, { offered_supplies: [elder, institution].map((supply_type) => ({ supply_type, unit_type: '74', supply_count: 1, verification: 'official' })) })
    const results = specialDiagnostics(n, profile({ parentDateOfBirth: '1966-09-23', isHouseholdHead: true }))
    const stopped = results.find((entry) => entry.supplyType === elder)!.result
    expect(stopped.status).toBe('mismatch')
    expect(stopped.reasons.find((entry) => entry.status === 'fail')?.detail).toContain('60세')
    expect(stopped.reasons.some((entry) => ['missing_input', 'past_fact'].includes(entry.category || ''))).toBe(false)
    expect(results.find((entry) => entry.supplyType === institution)?.result.reasons.some((entry) => entry.category === 'missing_input')).toBe(true)
  })
  it('removes the remaining questions from a failed mandatory condition group', () => {
    const group = rule('all', { conditions: [rule('parent_age_min', { value: 65 }), rule('parent_support_months_min', { value: 36 })] })
    expect(evaluateRule(group, profile({ parentDateOfBirth: '1966-09-23' }), notice([]))).toMatchObject({ status: 'fail', profileField: undefined })
    expect(evaluateRule(group, profile({ parentDateOfBirth: '1966-09-23' }), notice([])).detail).not.toContain('입력하면')
  })
  it('reuses the support start for duration and same-register continuity', () => {
    const p = profile({ parentSupportSince: '2020-01-01', parentSameRegister: true })
    for (const r of [rule('parent_support_months_min', { value: 36 }), rule('parent_same_register', { value: true })]) expect(evaluateRule(r, p, notice([])).status).toBe('pass')
  })
  it('asks for the actual support start date and reuses it at the 35/36-month boundary', () => {
    const duration = rule('parent_support_months_min', { value: 36 }), n = notice([duration])
    const missing = evaluateRule(duration, profile({ parentSupportSince: '' }), n)
    expect(missing).toMatchObject({ status: 'review', category: 'missing_input', label: '부양 시작일', profileField: 'parentSupportSince', requirement: '>= 36개월' })
    expect(missing.detail).toContain('부양하기 시작한 날짜')
    for (const [start, input, status] of [['2023-09-24', '35개월', 'fail'], ['2023-09-23', '36개월', 'pass']] as const) {
      const p = profile({ parentSupportSince: start, parentSameRegister: true })
      expect(evaluateRule(duration, p, n)).toMatchObject({ status, input, label: '부모 연속 부양 기간' })
      expect(evaluateRule(rule('parent_same_register', { value: true }), p, n).status).toBe('pass')
    }
  })
  it('counts specific required clauses and excludes paperwork and application instructions', () => {
    const coverage = rule('condition_coverage', { effect: 'metadata', scopes: [{ supply_type: '일반공급', complete: true, topics: [{ topic: '동일 블록 중복 신청', status: 'missing', phase: 'application' }, { topic: '서류 제출·계약금', status: 'missing', phase: 'post_selection' }, { topic: '소득 면제', status: 'not_applicable', required: true }], missing_topics: ['문서의 나머지 신청 제한·예외 검토'] }] })
    const age = rule('age_min', { value: 19, supply_type: '일반공급' })
    const n = notice([age, rule('document_submission', { effect: 'procedure' }), coverage])
    expect(conditionCoverage(n, undefined, '일반공급')).toMatchObject({ complete: true, missingTopics: [] })
    expect(evaluateQualification(n, profile(), undefined, '일반공급').status).toBe('possible')
    coverage.scopes = [{ supply_type: '일반공급', complete: false, topics: [{ topic: '해외 체류', status: 'partial', reason: '귀국 후 같은 국가 재출국 합산 기준 미확보' }] }]
    expect(conditionCoverage(n, undefined, '일반공급').missingTopics).toEqual(['귀국 후 같은 국가 재출국 합산 기준 미확보'])
  })
  it('does not certify coverage against a different document hash', () => {
    const age = rule('age_min', { value: 19, supply_type: '일반공급', document_hash: 'corrected' })
    const coverage = rule('condition_coverage', { effect: 'metadata', document_hash: 'original', scopes: [{ supply_type: '일반공급', complete: true, topics: [] }] })
    expect(evaluateQualification(notice([age, coverage]), profile(), undefined, '일반공급').status).toBe('review')
    expect(conditionCoverage(notice([age, coverage]), undefined, '일반공급').missingTopics).toEqual(['신청 조건과 분기별 검토 기록의 문서 해시 불일치'])
  })
  it('keeps reviewed comparisons but requires the newer unreadable attachment before complete certification', () => {
    const hash = 'old-reviewed-pdf', oldUrl = 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000463&atchmnflSeqNo=10'
    const age = rule('age_min', { value: 19, supply_type: '일반공급', document_hash: hash, evidence_url: oldUrl })
    const coverage = rule('condition_coverage', { effect: 'metadata', document_hash: hash, evidence_url: oldUrl, scopes: [{ supply_type: '일반공급', complete: true, topics: [] }] })
    const diagnostic = (url: string, stage = 'decode', code = 'unexpected_response') => rule('document_diagnostics', { effect: 'metadata', document_hash: hash, status: 'unreadable', diagnostics: [{ stage, code, status: 'error', evidence_url: url, missing_items: ['신청자격·지역 조건의 원문 텍스트'] }] })
    for (const failure of [diagnostic(oldUrl.replace('SeqNo=10', 'SeqNo=11')), diagnostic(oldUrl.replace('SeqNo=10', 'SeqNo=11'), 'download', 'document_download_failed')]) {
      const n = notice([age, coverage, failure])
      expect(evaluateQualification(n, profile(), undefined, '일반공급')).toMatchObject({ status: 'review', reasons: [{ status: 'pass', label: '공고 기준 만 나이' }, { status: 'review', category: 'source_gap' }] })
      expect(conditionCoverage(n, undefined, '일반공급')).toMatchObject({ complete: false, missingTopics: ['최신 모집공고 첨부의 신청 제한·면제 원문 미확보'] })
    }
    for (const url of [oldUrl, 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?atchmnflSeqNo=10&houseManageNo=2026000463']) expect(evaluateQualification(notice([age, coverage, diagnostic(url)]), profile(), undefined, '일반공급').status).toBe('possible')
  })
})
