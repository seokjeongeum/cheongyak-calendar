import { describe, expect, it } from 'vitest'
import { getProfileHistoryTarget, getProfileQuestionModel, warmProfileQuestionModel } from './profileQuestionModel'
import { EMPTY_PROFILE, type Notice, type NoticeRule } from './types'
const rule = (kind: string): NoticeRule => ({ kind, value: true, verification: 'official', criterion_date: '2026-10-02' })
const notice = (rules: NoticeRule[]): Notice => ({ id: 'same-notice', title: '공공분양', category: 'public_sale', source: 'lh', provider: 'LH', address: null, region_code: null, region_name: null, announcement_date: '2026-10-02', official_url: null, price_cap_status: 'unknown', events: [], prices: [], rules, updated_at: null, version: 1 })
describe('public profile question precomputation', () => {
  it('reuses the warmed immutable model across modal opens and edits', () => {
    const rows = [notice([rule('military_currently_serving'), rule('citizenship')])]
    warmProfileQuestionModel(rows, '2026-10-05')
    const first = getProfileQuestionModel(rows, '2026-10-05')
    expect(getProfileQuestionModel(rows, '2026-10-05')).toBe(first)
    expect(first.pastGroups.has('military')).toBe(true)
    expect(first.residenceRules).toHaveLength(1)
    // A new visible array can still reuse each immutable notice's source work.
    expect(getProfileQuestionModel([...rows], '2026-10-05').scopedRules[0]).toBe(first.scopedRules[0])
  })
  it('rebuilds questions when source content changes under the same notice id', () => {
    const original = notice([rule('citizenship')])
    const before = getProfileQuestionModel([original], '2026-10-05')
    const after = getProfileQuestionModel([{ ...original, rules: [rule('shinhee_income')], version: 2 }], '2026-10-05')
    expect(after.needsMonthly).toBe(true)
    expect(after.residenceRules).toHaveLength(0)
    expect(before.needsMonthly).toBe(false)
  })
  it('recomputes past-date question needs at the Korea-day boundary', () => {
    const rows = [notice([rule('citizenship')])]
    expect(getProfileQuestionModel(rows, '2026-10-02').pastGroups.has('citizenship')).toBe(false)
    expect(getProfileQuestionModel(rows, '2026-10-03').pastGroups.has('citizenship')).toBe(true)
  })
  it('renders past-history inputs for nested conditions that inherit official evidence and dates', () => {
    const child: NoticeRule = { kind: 'children_min', value: 2, include_pregnancy: true }
    const rows = [notice([{ ...rule('all'), criterion_date: '2026-09-01', conditions: [{ kind: 'any', conditions: [child] }] }])]
    const model = getProfileQuestionModel(rows, '2026-10-05')
    expect(model.scopedRules.find(({ rule }) => rule.kind === 'children_min')).toMatchObject({ date: '2026-09-01', rule: { verification: 'official', include_pregnancy: true } })
    expect(model.pastGroups.has('children')).toBe(true)
    expect(model.pastGroups.has('pregnancy')).toBe(true)
  })
  it('uses an inherited application-day criterion without inventing past-history questions', () => {
    const rows = [notice([{ ...rule('all'), criterion_date: undefined, criterion_basis: 'application_date', conditions: [{ kind: 'children_min', value: 2, include_pregnancy: true }] }])]
    const model = getProfileQuestionModel(rows, '2026-10-05')
    expect(model.scopedRules.find(({ rule }) => rule.kind === 'children_min')?.date).toBe('2026-10-05')
    expect(model.pastGroups.has('children')).toBe(false)
    expect(model.pastGroups.has('pregnancy')).toBe(false)
  })
  it('keeps a nested condition’s explicit verification and criterion overrides', () => {
    const rows = [notice([{ ...rule('all'), criterion_date: '2026-09-01', conditions: [{ kind: 'children_min', value: 2, verification: 'unknown' }, { kind: 'pregnant', verification: 'official', criterion_date: '2026-10-05' }] }])]
    const model = getProfileQuestionModel(rows, '2026-10-05')
    expect(model.scopedRules.some(({ rule }) => rule.kind === 'children_min')).toBe(false)
    expect(model.pastGroups.has('pregnancy')).toBe(false)
  })
  it('targets the actual independent child or pregnancy change input for past-history questions', () => {
    const model = getProfileQuestionModel([notice([{ ...rule('children_min'), include_pregnancy: true }])], '2026-10-05')
    const current = { ...EMPTY_PROFILE, hasChildren: false, pregnant: false }
    expect(getProfileHistoryTarget('children', current, model)).toBe('children')
    expect(getProfileHistoryTarget('pregnant', current, model)).toBe('pregnancy')
    const known = { ...current, factChanges: { children: { mode: 'never_changed' as const, date: '' } } }
    expect(getProfileHistoryTarget('children', known, model)).toBeUndefined()
    expect(getProfileHistoryTarget('pregnant', known, model)).toBe('pregnancy')
  })
  it('keeps source evidence on cards while avoiding repeated full PDF quotations in the form', () => {
    const rows = Array.from({ length: 10 }, () => notice([{ ...rule('provider_employee_restriction'), evidence_text: '공식 임직원 범위 '.repeat(500) }]))
    const model = getProfileQuestionModel(rows, '2026-10-05')
    expect(model.providerHelp.length).toBeLessThan(200)
    expect(model.scopedRules[0].rule.evidence_text).toBe(rows[0].rules[0].evidence_text)
  })
})
