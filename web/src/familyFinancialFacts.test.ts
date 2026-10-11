import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setEvaluationToday } from './factTimeline'
import { evaluateRule } from './qualification'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'

const date = '2026-10-02'
const rule = (extra: Partial<NoticeRule> = {}): NoticeRule => ({ kind: 'shinhee_income', verification: 'official',
  criterion_date: date, min_household_size: 4, normal_percent: 130,
  percentage_tables: { '130': [{ household_size: 3, max_krw: 4000000 }, { household_size: 4, max_krw: 8000000 }],
    '145': [{ household_size: 4, max_krw: 9000000 }] }, ...extra })
const notice = (r: NoticeRule): Notice => ({ id: 'new-family', title: '새 공고의 소득 조건', category: 'public_sale',
  source: 'official', provider: '공식 기관', address: null, region_code: null, region_name: null, announcement_date: date,
  official_url: 'https://official.example/new.pdf', price_cap_status: 'unknown', events: [], prices: [], rules: [r],
  rules_complete: false, updated_at: null, version: 1 })
const profile = (extra: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE,
  incomeHouseholdSize: '1', monthlyIncomeKrw: '8000000', officialNetAssetsKrw: '110000000',
  factChanges: { income: { mode: 'never_changed', date: '' }, assets: { mode: 'never_changed', date: '' } }, ...extra })
const relaxation = { child_relaxation_policy_supported: true, child_relaxation_since: '2025-01-01',
  one_child_bonus_percent: 15, two_children_bonus_percent: 25, one_child_count: 1, two_children_count_min: 2,
  include_older_children_when_recent_child_exists: true }
beforeEach(() => setEvaluationToday(date))
afterEach(() => setEvaluationToday(null))

describe('source financial table facts', () => {
  it('uses the source minimum household size rather than a fixed three-person threshold', () => {
    const r = rule()
    expect(evaluateRule(r, profile(), notice(r))).toMatchObject({ status: 'pass', detail: expect.stringContaining('4인 기준') })
    expect(evaluateRule(r, profile({ monthlyIncomeKrw: '8000001' }), notice(r)).status).toBe('review')
    expect(evaluateRule(rule({ min_household_size: undefined }), profile(), notice(r)).status).toBe('review')
  })
  it('uses documented child bonus percentages and their matching amount rows', () => {
    const r = rule(relaxation)
    const p = profile({ monthlyIncomeKrw: '9000000', hasChildren: true,
      children: [{ dateOfBirth: '2025-09-01', adopted: false }], pregnant: false })
    expect(evaluateRule(r, p, notice(r))).toMatchObject({ status: 'pass', detail: expect.stringContaining('145%') })
    const missing = { ...r, percentage_tables: { '130': [{ household_size: 4, max_krw: 8000000 }] } }
    expect(evaluateRule(missing, p, notice(missing)).status).toBe('review')
  })
  it('selects the documented child asset amount without assuming a 10-percent bonus', () => {
    const r = rule({ ...relaxation, kind: 'shinhee_assets', base_max_krw: 100000000,
      one_child_max_krw: 115000000, two_children_max_krw: 125000000 })
    const p = profile({ hasChildren: true, children: [{ dateOfBirth: '2025-09-01', adopted: false }], pregnant: false })
    expect(evaluateRule(r, p, notice(r))).toMatchObject({ status: 'pass', requirement: '<= 115,000,000원' })
    expect(evaluateRule({ ...r, child_relaxation_policy_supported: false }, p, notice(r)).status).toBe('review')
  })
})
