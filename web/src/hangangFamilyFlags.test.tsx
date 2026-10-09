import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ProfileDialog } from './ProfileDialog'
import { getFirstHomeChildQuestionState, getProfileHistoryTarget, getProfileQuestionModel } from './profileQuestionModel'
import { evaluateRule } from './qualification'
import { setEvaluationToday } from './factTimeline'
import { createHouseholdMember, emptyPointsFamilyFact, EMPTY_PROFILE, type HouseholdMember, type LocalProfile, type Notice, type NoticeRule } from './types'

const today = '2026-10-09', cutoff = '2026-10-02'
const source = 'https://example.com/hangang-exact.pdf'
const rule: NoticeRule = { kind: 'first_home_family', supply_type: '생애최초 특별공급', verification: 'official', criterion_date: cutoff, evidence_url: source, unmarried_child_required: true, unmarried_applicant_child_same_register: true, non_solo_requires_ascendant: true, include_adoption: true, include_pregnancy: true, solo_max_area_sqm: 60 }
const notice = (area = 84, rules = [rule]): Notice => ({ id: 'hangang', title: '검증용 공식 공고', category: 'apt', source: 'cheongyak_home', provider: '청약홈', address: null, region_code: null, region_name: null, announcement_date: cutoff, official_url: source, price_cap_status: 'unknown', events: [], prices: [{ unit_type: 'test', exclusive_area_sqm: area, price_kind: 'sale' }], rules, updated_at: null, version: 1 })
const member = (id: string, relation: HouseholdMember['relation'] = 'applicant_child', register: HouseholdMember['register'] = 'applicant'): HouseholdMember => ({ ...createHouseholdMember(id), relation, register, dateOfBirth: '2010-01-01' })
const profile = (part: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, dateOfBirth: '1990-01-01', maritalStatus: 'single', hasSpouse: false, applicantOnRegister: true, additionalFamilyPresence: false, householdMembers: [], hasChildren: false, pregnant: false, factChanges: { household: { mode: 'known', date: '2026-09-01' }, marital: { mode: 'known', date: '2026-09-01' }, children: { mode: 'never_changed', date: '' }, pregnancy: { mode: 'never_changed', date: '' }, points: { mode: 'known', date: '2026-09-01' } }, ...part })
beforeEach(() => setEvaluationToday(today))
afterEach(() => setEvaluationToday(null))

describe('exact Hangang first-home family branches', () => {
  it('requires the canonical child to be unmarried and on the applicant register', () => {
    const child = member('child')
    const value = profile({ householdMembers: [child], pointsFamily: { child: { ...emptyPointsFamilyFact(), unmarried: true } } })
    expect(evaluateRule(rule, value, notice())).toMatchObject({ status: 'pass', category: 'condition' })
    expect(evaluateRule(rule, { ...value, pointsFamily: { child: { ...emptyPointsFamilyFact(), unmarried: false } } }, notice()).status).toBe('fail')
    expect(evaluateRule(rule, { ...value, householdMembers: [{ ...child, register: 'separate' }] }, notice()).status).toBe('fail')
  })
  it('does not borrow a today child-marital answer into the older cutoff', () => {
    const value = profile({ householdMembers: [member('child')], pointsFamily: { child: { ...emptyPointsFamilyFact(), unmarried: true } }, factChanges: { household: { mode: 'known', date: '2026-09-01' }, marital: { mode: 'known', date: '2026-09-01' }, pregnancy: { mode: 'never_changed', date: '' } } })
    expect(evaluateRule(rule, value, notice())).toMatchObject({ status: 'review', category: 'past_fact', historyGroup: 'points', profileField: 'pointsFamily', profileMemberId: 'child' })
    expect(evaluateRule(rule, { ...value, factSnapshots: [{ group: 'points', date: cutoff, values: { pointsFamily: { child: { ...emptyPointsFamilyFact(), unmarried: false } } } }] }, notice()).status).toBe('fail')
  })
  it('uses real parent or grandparent identity for the non-solo exception', () => {
    expect(evaluateRule(rule, profile({ householdMembers: [member('parent', 'applicant_parent')] }), notice()).status).toBe('pass')
    expect(evaluateRule(rule, profile({ householdMembers: [member('grandparent', 'applicant_grandparent')] }), notice()).status).toBe('pass')
    expect(evaluateRule(rule, profile({ householdMembers: [member('sibling', 'sibling')] }), notice()).status).toBe('fail')
    expect(evaluateRule(rule, profile({ householdMembers: [member('parent', 'applicant_parent', 'separate')] }), notice()).status).toBe('fail')
  })
  it('supports explicit fetal eligibility at the dated cutoff and the solo area limit', () => {
    expect(evaluateRule(rule, profile({ pregnant: true, factSnapshots: [{ group: 'pregnancy', date: cutoff, values: { pregnant: true } }] }), notice()).status).toBe('pass')
    expect(evaluateRule(rule, profile(), notice(60)).status).toBe('pass')
    expect(evaluateRule(rule, profile(), notice(60.01)).status).toBe('fail')
    expect(evaluateRule(rule, profile({ pregnant: null }), notice())).toMatchObject({ status: 'review', category: 'missing_input', profileField: 'pregnant' })
  })
  it('connects a genuinely missing pregnancy history to its existing common history input', () => {
    const value = profile({ pregnant: true, factChanges: { household: { mode: 'known', date: '2026-09-01' }, marital: { mode: 'known', date: '2026-09-01' }, children: { mode: 'never_changed', date: '' } } })
    const n = notice(), model = getProfileQuestionModel([n], today)
    expect(evaluateRule(rule, value, n)).toMatchObject({ category: 'past_fact', profileField: 'pregnant', historyGroup: 'pregnancy' })
    expect(getProfileHistoryTarget('pregnant', value, model)).toBe('pregnancy')
    const html = renderToStaticMarkup(<ProfileDialog profile={value} onChange={() => {}} onClose={() => {}} today={today} notices={[n]} initialField="pregnant" initialHistoryGroup="pregnancy" />)
    expect(html).toContain('data-fact-group="pregnancy"')
  })
  it('keeps absent or ambiguous canonical child facts as real input gaps', () => {
    expect(evaluateRule(rule, profile({ hasChildren: true, children: [{ dateOfBirth: '2010-01-01', adopted: true }] }), notice())).toMatchObject({ status: 'review', category: 'missing_input', profileField: 'householdMembers' })
    expect(evaluateRule(rule, profile({ householdMembers: [member('child')], pointsFamily: {} }), notice())).toMatchObject({ status: 'review', category: 'missing_input', profileField: 'pointsFamily', profileMemberId: 'child' })
    expect(evaluateRule(rule, profile({ householdMembers: [{ ...member('child'), register: 'unknown' }] }), notice())).toMatchObject({ status: 'review', profileField: 'householdMembers' })
  })
  it('does not ask a separate child marital fact when every other route is impossible', () => {
    const value = profile({ householdMembers: [member('child', 'applicant_child', 'separate')] })
    expect(evaluateRule(rule, value, notice()).status).toBe('fail')
    const model = getProfileQuestionModel([notice()], today)
    expect(getFirstHomeChildQuestionState(value, model)).toEqual({ memberIds: [], historyNeeded: false })
  })
  it('asks that separate child marital fact when it changes the 60㎡ one-person route', () => {
    const value = profile({ householdMembers: [member('child', 'applicant_child', 'separate')] })
    const n = notice(60), model = getProfileQuestionModel([n], today)
    expect(evaluateRule(rule, value, n)).toMatchObject({ category: 'missing_input', profileField: 'pointsFamily', profileMemberId: 'child' })
    expect(getFirstHomeChildQuestionState(value, model)).toEqual({ memberIds: ['child'], historyNeeded: false })
    expect(evaluateRule(rule, { ...value, pointsFamily: { child: { ...emptyPointsFamilyFact(), unmarried: false } } }, n).status).toBe('pass')
    expect(evaluateRule(rule, { ...value, pointsFamily: { child: { ...emptyPointsFamilyFact(), unmarried: true } } }, n).status).toBe('fail')
  })
  it('mounts the actual missing child input without irrelevant points confirmation', () => {
    const value = profile({ householdMembers: [member('child', 'applicant_child', 'separate')] })
    const render = (n: Notice) => renderToStaticMarkup(<ProfileDialog profile={value} onChange={() => {}} onClose={() => {}} today={today} notices={[n]} initialField="pointsFamily" />)
    const html = render(notice(60))
    expect(html).toContain('data-profile-field="pointsFamily"')
    expect(html.match(/이 자녀가 미혼인가요\?/g)).toHaveLength(1)
    expect(html).not.toContain('본인 또는 배우자와 같은 등본에 연속 등재된 날')
    expect(html).not.toContain('공고의 자녀 국외 체류 제외 기준에 해당하나요?')
    expect(render(notice())).not.toContain('이 자녀가 미혼인가요?')
  })
  it('preserves legacy generic first-home semantics for other notices', () => {
    const generic: NoticeRule = { kind: 'first_home_family', verification: 'official', criterion_date: cutoff, evidence_url: source, include_adoption: true, solo_max_area_sqm: 60 }
    const value = profile({ hasChildren: true, children: [{ dateOfBirth: '2010-01-01', adopted: false }] })
    expect(evaluateRule(generic, value, notice()).status).toBe('pass')
    expect(evaluateRule(rule, value, notice())).toMatchObject({ status: 'review', profileField: 'householdMembers' })
  })
})
