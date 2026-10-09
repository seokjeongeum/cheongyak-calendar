import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApplicationFactsFields } from './ApplicationFactsFields'
import { applicationHistoryCoveredPeople, applicationHistoryEventComplete } from './applicationHistoryFacts'
import { setEvaluationToday } from './factTimeline'
import { migrateProfile, saveProfile, updateProfileFacts } from './profile'
import { evaluateRule } from './qualification'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'
const today = '2026-10-09'
const rules: NoticeRule[] = ['ineligible_restriction_active', 'resale_restriction_active'].map((restriction) => ({ kind: 'application_restriction', restriction, value: false, scope: 'applicant', verification: 'official', criterion_date: '2026-10-02', evidence_url: 'https://example.go.kr/current.pdf' }))
const notice: Notice = { id: 'test', title: '공고', category: 'apt', source: 'cheongyak_home', provider: '공식 기관', address: null, region_code: null, region_name: null, announcement_date: '2026-10-02', official_url: 'https://example.go.kr/current.pdf', price_cap_status: 'unknown', events: [], prices: [], rules, updated_at: null, version: 1 }
const profile = (part: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, hasSpouse: false, maritalStatus: 'single', additionalFamilyPresence: false, applicationRestrictionFacts: { applicant: { ineligibleRestrictionActive: false, resaleRestrictionActive: false, rewinningRestrictionActive: false, asOfDate: today, historyConfirmations: [] } }, ...part })
beforeEach(() => setEvaluationToday(today))
afterEach(() => { setEvaluationToday(null); vi.unstubAllGlobals() })
describe('reusable actual restriction history', () => {
  it('asks specific missing events rather than a duplicate coarse state-change date', () => {
    const results = rules.map((rule) => evaluateRule(rule, profile(), notice))
    expect(results.map((result) => result.label)).toEqual(['부적격 당첨 판정 이력', '공급질서 교란·전매 위반 적발 이력'])
    expect(results.every((result) => result.category === 'missing_input')).toBe(true)
    const html = renderToStaticMarkup(<ApplicationFactsFields profile={profile()} onChange={() => {}} today={today} notices={[notice]} section="restrictions" />)
    expect(html).toContain('부적격 당첨자로 판정된 이력')
    expect(html).not.toContain('마지막 변경일')
    expect(html).not.toContain('현재 청약홈에')
  })
  it('reuses lifetime event absence across original notice dates without changing their cutoffs', () => {
    const value = profile()
    value.applicationRestrictionFacts.applicant = { ...value.applicationRestrictionFacts.applicant!, ineligibleHistoryPresence: false, resaleViolationHistoryPresence: false }
    for (const cutoff of ['2026-10-02', '2026-10-06']) for (const rule of rules) {
      expect(evaluateRule({ ...rule, criterion_date: cutoff }, value, notice)).toMatchObject({ status: 'pass', criterionDate: cutoff })
    }
    const migrated = migrateProfile(value)
    expect(migrated.applicationRestrictionFacts.applicant?.ineligibleHistoryPresence).toBe(false)
    const setItem = vi.fn(), fetch = vi.fn()
    vi.stubGlobal('localStorage', { setItem }); vi.stubGlobal('fetch', fetch)
    saveProfile(migrated)
    expect(setItem).toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  })
  it('does not turn a current inactive answer or contradictory active restriction into historical absence', () => {
    expect(evaluateRule(rules[0], migrateProfile(profile()), notice).status).toBe('review')
    const value = profile()
    value.applicationRestrictionFacts.applicant = { ...value.applicationRestrictionFacts.applicant!, ineligibleHistoryPresence: false, ineligibleRestrictionActive: true }
    expect(evaluateRule(rules[0], value, notice).status).toBe('review')
    const current = profile()
    current.applicationRestrictionFacts.applicant!.ineligibleHistoryPresence = false
    current.factSnapshots = [{ group: 'restrictions', date: '2026-10-02', values: { applicationRestrictionFacts: { applicant: { ...current.applicationRestrictionFacts.applicant!, ineligibleRestrictionActive: true, asOfDate: '2026-10-02' } } } }]
    expect(evaluateRule(rules[0], current, notice)).toMatchObject({ status: 'review', category: 'missing_input', label: '부적격 당첨 판정 이력' })
  })
  it('does not add a lifetime-history question when saved facts already cover the visible cutoff', () => {
    const value = profile()
    value.applicationRestrictionFacts.applicant = { ...value.applicationRestrictionFacts.applicant!, asOfDate: '2026-10-02' }
    expect(rules.every((rule) => evaluateRule(rule, value, notice).status === 'pass')).toBe(true)
    const html = renderToStaticMarkup(<ApplicationFactsFields profile={value} onChange={() => {}} today={today} notices={[notice]} section="restrictions" />)
    expect(html).not.toContain('부적격 당첨자로 판정된 이력')
    expect(html).not.toContain('적발된 이력')
  })
  it('invalidates collective absence for changed household identities but retains applicant facts', () => {
    const value = profile()
    const absence = { ...value.applicationRestrictionFacts.applicant!, ineligibleHistoryPresence: false, resaleViolationHistoryPresence: false }
    value.applicationRestrictionFacts = { applicant: absence, household: absence, applicant_spouse: absence }
    const next = updateProfileFacts(value, { ...value, hasSpouse: true, maritalStatus: 'married' }, today)
    expect(next.applicationRestrictionFacts.applicant?.ineligibleHistoryPresence).toBe(false)
    expect(next.applicationRestrictionFacts.household?.ineligibleHistoryPresence).toBeNull()
    expect(next.applicationRestrictionFacts.applicant_spouse?.resaleViolationHistoryPresence).toBeNull()
  })
  it('uses actual generic special-winning dates without requiring project identity', () => {
    const value = profile({ applicationHistoryEvents: [{ id: 'actual-event', personId: 'applicant', projectId: '', eventKind: 'winning', eventDate: '2026-10-01', specialSupply: true }] })
    expect(applicationHistoryEventComplete(value.applicationHistoryEvents[0], today)).toBe(true)
    expect(applicationHistoryEventComplete(value.applicationHistoryEvents[0], today, true)).toBe(false)
    expect(applicationHistoryCoveredPeople(value).has('applicant')).toBe(true)
    expect(evaluateRule({ kind: 'special_winning', scope: 'applicant', value: false, verification: 'official', criterion_date: '2026-10-02' }, value, notice).status).toBe('fail')
    expect(evaluateRule({ kind: 'application_restriction', scope: 'applicant', restriction: 'prior_project_winner', project_id: '2026000468', value: false, verification: 'official', criterion_date: '2026-10-02' }, value, notice).status).toBe('review')
  })
})
