import { describe, expect, it } from 'vitest'
import { getProfileQuestionModel, warmProfileQuestionModel } from './profileQuestionModel'
import type { Notice, NoticeRule } from './types'
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
  it('keeps source evidence on cards while avoiding repeated full PDF quotations in the form', () => {
    const rows = Array.from({ length: 10 }, () => notice([{ ...rule('provider_employee_restriction'), evidence_text: '공식 임직원 범위 '.repeat(500) }]))
    const model = getProfileQuestionModel(rows, '2026-10-05')
    expect(model.providerHelp.length).toBeLessThan(200)
    expect(model.scopedRules[0].rule.evidence_text).toBe(rows[0].rules[0].evidence_text)
  })
})
