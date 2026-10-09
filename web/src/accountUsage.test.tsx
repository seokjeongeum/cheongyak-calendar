import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProfileDialog } from './ProfileDialog'
import { accountWinningUsageAtDate } from './accountUsage'
import { factsAtDate, setEvaluationToday } from './factTimeline'
import { migrateProfile, PROFILE_STORAGE_KEY, saveProfile, updateProfileFacts } from './profile'
import { getProfileHistoryTarget, getProfileQuestionModel } from './profileQuestionModel'
import { evaluateRule } from './qualification'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'

const today = '2026-10-09', past = '2026-10-02'
const rule = (date = past): NoticeRule => ({ kind: 'account_unused_after_winning', value: false, verification: 'official', criterion_date: date, evidence_url: 'https://example.com/exact-attachment.pdf', evidence_text: '당첨된 청약통장은 계약여부와 관계없이 재사용이 불가합니다' })
const notice = (rules = [rule()]): Notice => ({ id: 'account', title: '공식 공고', category: 'apt', source: 'cheongyak_home', provider: '청약홈', address: null, region_code: null, region_name: null, announcement_date: past, official_url: 'https://example.com/exact-attachment.pdf', price_cap_status: 'unknown', events: [], prices: [], rules, updated_at: null, version: 1 })
const profile = (part: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, accountType: 'comprehensive', privateRankBaseDate: '2010-01-01', nationalRankBaseDate: '2010-01-01', ...part })
beforeEach(() => setEvaluationToday(today))
afterEach(() => { setEvaluationToday(null); vi.unstubAllGlobals() })

describe('the current account’s own winning use', () => {
  it('compares today without a contract or first-winning-date confirmation', () => {
    expect(evaluateRule(rule(today), profile({ currentAccountUsedForWinning: true }), notice())).toMatchObject({ status: 'fail', category: 'condition' })
    expect(evaluateRule(rule(today), profile({ currentAccountUsedForWinning: false }), notice())).toMatchObject({ status: 'pass', category: 'condition' })
    expect(evaluateRule(rule(today), profile(), notice())).toMatchObject({ status: 'review', profileField: 'currentAccountUsedForWinning' })
  })
  it('keeps the application-time reuse prohibition current after an announcement', () => {
    const application: NoticeRule = { ...rule(), criterion_basis: 'application_date', criterion_date: null, original_announcement_date: past, evaluation_mode: 'today_precheck', requires_maintained_until_application: true }
    const value = profile({ currentAccountUsedForWinning: true, currentAccountFirstWinningDate: '2026-10-05' })
    const assessed = evaluateRule(application, value, notice([application]))
    expect(assessed).toMatchObject({ status: 'fail', criterionDate: today, todayPreview: true })
    expect(assessed.detail).toContain('오늘의 통장 상태로 미리 비교하며, 접수일까지 유효한 통장을 유지해야 합니다.')
    expect(evaluateRule(application, profile({ currentAccountUsedForWinning: false }), notice([application]))).toMatchObject({ status: 'pass', criterionDate: today, todayPreview: true })
    const html = renderToStaticMarkup(<ProfileDialog profile={value} onChange={() => {}} onClose={() => {}} today={today} notices={[notice([application])]} initialField="currentAccountUsedForWinning" />)
    expect(html).not.toContain('현재 청약통장이 가장 먼저 당첨자 선정에 사용된 날')
    expect(html).not.toContain('data-fact-group="bank_account"')
    expect(getProfileHistoryTarget('currentAccountUsedForWinning', value, getProfileQuestionModel([notice([application])], today))).toBeUndefined()
  })
  it('does not infer which account won from common person or project events', () => {
    const oldWin = { id: 'old-win', personId: 'applicant', projectId: '2026000123', eventKind: 'winning' as const, eventDate: '2020-01-01' }
    const value = profile({ applicationHistoryPresence: true, applicationHistoryComplete: true, applicationHistoryEvents: [oldWin], previousWinning: true })
    expect(evaluateRule(rule(today), value, notice())).toMatchObject({ status: 'review', profileField: 'currentAccountUsedForWinning' })
    expect(evaluateRule(rule(today), { ...value, currentAccountUsedForWinning: false }, notice())).toMatchObject({ status: 'pass' })
  })
  it('reconstructs before and after the actual first win of THIS account regardless of contract', () => {
    const value = profile({ currentAccountUsedForWinning: true, currentAccountFirstWinningDate: '2026-10-05' })
    expect(evaluateRule(rule(past), value, notice())).toMatchObject({ status: 'pass' })
    expect(evaluateRule(rule('2026-10-05'), value, notice())).toMatchObject({ status: 'fail' })
    expect(evaluateRule(rule('2026-10-08'), value, notice())).toMatchObject({ status: 'fail' })
    expect(evaluateRule(rule(past), profile({ currentAccountUsedForWinning: true }), notice())).toMatchObject({ category: 'missing_input', profileField: 'currentAccountFirstWinningDate' })
    expect(evaluateRule(rule(past), profile({ currentAccountUsedForWinning: true, currentAccountFirstWinningDate: '2026-11-01' }), notice())).toMatchObject({ category: 'missing_input', profileField: 'currentAccountFirstWinningDate' })
  })
  it('does not use private/national recognition dates as proof of this account’s past unused state', () => {
    const value = profile({ currentAccountUsedForWinning: false, factChanges: { bank_private: { mode: 'never_changed', date: '' }, bank_national: { mode: 'never_changed', date: '' } } })
    expect(evaluateRule(rule(), value, notice())).toMatchObject({ category: 'past_fact', historyGroup: 'bank_account', profileField: 'currentAccountUsedForWinning' })
    const known = { ...value, factChanges: { ...value.factChanges, bank_account: { mode: 'known' as const, date: '2026-09-01' } } }
    expect(evaluateRule(rule(), known, notice())).toMatchObject({ status: 'pass' })
  })
  it('uses exact recorded account facts despite unknown today and does not borrow into old partial snapshots', () => {
    const recorded = profile({ factSnapshots: [{ group: 'bank_account', date: past, values: { currentAccountUsedForWinning: false, accountType: 'comprehensive' } }] })
    expect(evaluateRule(rule(), recorded, notice())).toMatchObject({ status: 'pass' })
    const partial = { ...recorded, currentAccountUsedForWinning: false, currentAccountFirstWinningDate: '2020-01-01', factSnapshots: [{ group: 'bank_account' as const, date: past, values: { accountType: 'comprehensive' } }] }
    expect(factsAtDate(partial, 'bank_account', past).profile.currentAccountUsedForWinning).toBeNull()
    expect(factsAtDate(partial, 'bank_account', past).profile.currentAccountFirstWinningDate).toBe('')
    expect(evaluateRule(rule(), partial, notice())).toMatchObject({ status: 'review', category: 'past_fact' })
  })
  it('preserves the local dated answer when account kind changes and resets the new current account fact', () => {
    const before = profile({ currentAccountUsedForWinning: true, currentAccountFirstWinningDate: '2020-01-01', currentAccountFactsAsOfDate: past })
    const changed = updateProfileFacts(before, { accountType: 'deposit' }, today)
    expect(changed.currentAccountUsedForWinning).toBeNull()
    expect(changed.currentAccountFirstWinningDate).toBe('')
    expect(accountWinningUsageAtDate(changed, past)).toMatchObject({ status: 'known', value: true })
    const migrated = migrateProfile(changed)
    expect(migrated.factSnapshots?.find((entry) => entry.group === 'bank_account')?.values.currentAccountUsedForWinning).toBe(true)
    const setItem = vi.fn(); vi.stubGlobal('localStorage', { setItem })
    saveProfile(migrated)
    expect(setItem).toHaveBeenCalledWith(PROFILE_STORAGE_KEY, expect.any(String))
    expect(JSON.parse(setItem.mock.calls[0][1]).currentAccountUsedForWinning).toBeNull()
  })
  it('links a genuine historical gap to the common dated input and an actual win-date gap to its date', () => {
    const model = getProfileQuestionModel([notice()], today)
    expect(getProfileHistoryTarget('currentAccountUsedForWinning', profile({ currentAccountUsedForWinning: false }), model)).toBe('bank_account')
    expect(getProfileHistoryTarget('currentAccountUsedForWinning', profile({ currentAccountUsedForWinning: true }), model)).toBeUndefined()
    expect(getProfileHistoryTarget('currentAccountFirstWinningDate', profile({ currentAccountUsedForWinning: true }), model)).toBeUndefined()
  })
  it('asks the common account question once only for notices requiring it and no extra date for today', () => {
    const rows = ['일반공급', '신혼부부 특별공급', '생애최초 특별공급'].map((supply_type) => ({ ...rule(), supply_type }))
    const render = (value: LocalProfile, notices: Notice[]) => renderToStaticMarkup(<ProfileDialog profile={value} onChange={() => {}} onClose={() => {}} today={today} notices={notices} initialField="currentAccountUsedForWinning" />)
    const html = render(profile(), [notice(rows), { ...notice(rows), id: 'second-notice' }])
    expect(html.match(/현재 사용할 청약통장이 당첨자 선정에 사용된 적이 있나요\?/g)).toHaveLength(1)
    expect(render(profile(), [notice([])])).not.toContain('현재 사용할 청약통장이 당첨자 선정에 사용된 적이 있나요?')
    expect(render(profile({ currentAccountUsedForWinning: true }), [notice([rule(today)])])).not.toContain('현재 청약통장이 가장 먼저 당첨자 선정에 사용된 날')
    expect(render(profile({ currentAccountUsedForWinning: true }), [notice()])).toContain('data-profile-field="currentAccountFirstWinningDate"')
  })
})
