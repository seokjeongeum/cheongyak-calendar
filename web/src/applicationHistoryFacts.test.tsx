import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApplicationFactsFields } from './ApplicationFactsFields'
import { applicationHistoryCoveredPeople, applicationHistoryEventComplete, applicationHistoryPersonPresence } from './applicationHistoryFacts'
import { setEvaluationToday } from './factTimeline'
import { migrateProfile, PROFILE_STORAGE_KEY, saveProfile } from './profile'
import { ProfileDialog } from './ProfileDialog'
import { EMPTY_PROFILE, type ApplicationHistoryEvent, type LocalProfile, type Notice, type NoticeRule } from './types'

const today = '2026-10-09'
const event = (part: Partial<ApplicationHistoryEvent> = {}): ApplicationHistoryEvent => ({ id: 'event', personId: 'applicant', projectId: '2026000468', eventKind: 'winning', eventDate: '2026-10-01', ...part })
const profile = (part: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, hasSpouse: false, maritalStatus: 'single', additionalFamilyPresence: false, applicationHistoryComplete: null, ...part })
const rule: NoticeRule = { kind: 'previous_winning', value: false, scope: 'household', verification: 'official', criterion_date: '2026-10-02', evidence_url: 'https://example.com/official.pdf' }
const notice: Notice = { id: 'test', title: '공식 이력 조건', category: 'apt', source: 'cheongyak_home', provider: '청약홈', address: null, region_code: null, region_name: null, announcement_date: '2026-10-02', official_url: 'https://example.com/official.pdf', price_cap_status: 'unknown', events: [], prices: [], rules: [rule], updated_at: null, version: 1 }
const render = (value: LocalProfile) => renderToStaticMarkup(<ApplicationFactsFields profile={value} onChange={() => {}} today={today} notices={[notice]} section="restrictions" />)
beforeEach(() => setEvaluationToday(today))
afterEach(() => { setEvaluationToday(null); vi.unstubAllGlobals() })

describe('concrete common application history', () => {
  it('covers a person from a dated event without requiring a completion affirmation', () => {
    const value = profile({ applicationHistoryPresence: true, applicationHistoryComplete: false, applicationHistoryEvents: [event()] })
    expect(applicationHistoryPersonPresence(value, 'applicant')).toBe(true)
    expect([...applicationHistoryCoveredPeople(value)]).toEqual(['applicant'])
    const html = render(value)
    expect(html).toContain('실제 사건 날짜')
    expect(html).not.toContain('위 확인 대상의 당첨·계약 이력을 모두 입력했나요?')
    expect(html).not.toContain('위 사람 중 당첨·예비당첨')
  })
  it('keeps genuinely missing event facts unresolved instead of asking for completeness', () => {
    for (const part of [{ projectId: '' }, { personId: '' }, { eventDate: '' }, { eventDate: '2026-02-30' }, { eventDate: '2026-10-10' }]) {
      const value = profile({ applicationHistoryEvents: [event(part)], applicationHistoryAbsencePeople: ['applicant'] })
      expect(applicationHistoryEventComplete(value.applicationHistoryEvents[0], today)).toBe(false)
      expect(applicationHistoryCoveredPeople(value).has('applicant')).toBe(false)
    }
    const html = render(profile({ applicationHistoryPresence: true, applicationHistoryEvents: [event({ projectId: '', eventDate: '' })] }))
    expect(html).toContain('최초 사업번호')
    expect(html).toContain('실제 사건 날짜')
    expect(html).not.toContain('입력을 모두')
  })
  it('records absence for exact people and asks only a newly added person’s substantive history', () => {
    const value = profile({ hasSpouse: true, maritalStatus: 'married', applicationHistoryPresence: true, applicationHistoryEvents: [event()], applicationHistoryAbsencePeople: [] })
    expect(applicationHistoryCoveredPeople(value).has('spouse')).toBe(false)
    expect(applicationHistoryPersonPresence(value, 'spouse')).toBeNull()
    const html = render(value)
    expect(html).toContain('배우자에게 당첨·예비당첨 또는 주택 공급계약 이력이 있나요?')
    expect(html).not.toContain('본인에게 당첨·예비당첨')
    expect(html).not.toContain('위 확인 대상의 당첨·계약 이력을 모두 입력했나요?')
    const answered = { ...value, applicationHistoryAbsencePeople: ['spouse'] }
    expect([...applicationHistoryCoveredPeople(answered)].sort()).toEqual(['applicant', 'spouse'])
    expect(render(answered)).toContain('배우자 · 당첨·예비당첨·공급계약 이력 없음')
    expect(render(answered)).not.toContain('배우자에게 당첨·예비당첨')
    expect(applicationHistoryCoveredPeople(answered).has('new-parent')).toBe(false)
  })
  it('preserves stored no-history answers and exact legacy scope without adding new people', () => {
    const old = profile({ applicationHistoryPresence: false, applicationHistoryComplete: true, applicationHistoryPeople: ['applicant'] })
    const migrated = migrateProfile(old)
    expect(migrated.applicationHistoryAbsencePeople).toEqual(['applicant'])
    expect(applicationHistoryPersonPresence(migrated, 'applicant')).toBe(false)
    expect(applicationHistoryPersonPresence(migrated, 'spouse')).toBeNull()
    expect(render(migrated)).not.toContain('위 사람 중 당첨·예비당첨')
    const mixed = migrateProfile(profile({ applicationHistoryPresence: true, applicationHistoryComplete: true, applicationHistoryPeople: ['applicant', 'spouse'], applicationHistoryEvents: [event()] }))
    expect(mixed.applicationHistoryAbsencePeople).toEqual(['spouse'])
    expect([...applicationHistoryCoveredPeople(mixed)].sort()).toEqual(['applicant', 'spouse'])
  })
  it('does not promote a contradictory legacy positive answer with an empty list into absence', () => {
    const value = profile({ applicationHistoryPresence: true, applicationHistoryComplete: true, applicationHistoryPeople: ['applicant'] })
    expect(applicationHistoryPersonPresence(value, 'applicant')).toBeNull()
    expect(applicationHistoryCoveredPeople(value).has('applicant')).toBe(false)
    expect(migrateProfile(value).applicationHistoryAbsencePeople).toEqual([])
    expect(render(value)).toContain('이력 추가')
  })
  it('keeps incomplete extra events from certifying negative facts despite a valid known event', () => {
    const value = profile({ applicationHistoryEvents: [event(), event({ id: 'incomplete', eventKind: 'contract', eventDate: '' })] })
    expect(applicationHistoryPersonPresence(value, 'applicant')).toBe(true)
    expect(applicationHistoryCoveredPeople(value).has('applicant')).toBe(false)
  })
  it('saves new absence facts only in the existing browser profile', () => {
    const value = migrateProfile(profile({ applicationHistoryAbsencePeople: ['applicant', 'applicant', 'spouse'] }))
    expect(value.applicationHistoryAbsencePeople).toEqual(['applicant', 'spouse'])
    const setItem = vi.fn(), fetch = vi.fn()
    vi.stubGlobal('localStorage', { setItem }); vi.stubGlobal('fetch', fetch)
    saveProfile(value)
    expect(setItem).toHaveBeenCalledWith(PROFILE_STORAGE_KEY, expect.any(String))
    expect(JSON.parse(setItem.mock.calls[0][1]).applicationHistoryAbsencePeople).toEqual(['applicant', 'spouse'])
    expect(fetch).not.toHaveBeenCalled()
  })
  it('offers explicit institution inapplicability separately from unknown', () => {
    const html = renderToStaticMarkup(<ProfileDialog profile={profile({ recommendationReason: 'none' })} onChange={() => {}} onClose={() => {}} today={today} notices={[notice]} initialField="recommendationReason" />)
    expect(html).toContain('value="none" selected="">해당 없음')
    expect(html).toContain('value="">미확인')
    expect(html).not.toContain('본인이 주민등록등본에 등재되어 있나요?')
  })
})
