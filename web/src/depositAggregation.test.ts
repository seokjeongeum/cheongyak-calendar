import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { rankUnitComparisons } from './eligibility'
import { deriveRank, evaluateRule, unitRankResults } from './qualification'
import { setEvaluationToday } from './factTimeline'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'

const today = '2026-10-12', cutoff = '2026-10-02', source = 'https://official.example/rank.pdf'
const rule = (kind: string, extra: Partial<NoticeRule> = {}): NoticeRule => ({ kind, verification: 'official', purpose: 'first_rank', criterion_date: cutoff, evidence_url: source, ...extra })
const deposit = rule('deposit_min_krw', { deposit_table: [
  { max_area_sqm: 85, amounts_krw: { seoul_busan: 3000000, other_metropolitan: 2500000, other: 2000000 } },
  { max_area_sqm: 102, amounts_krw: { seoul_busan: 6000000, other_metropolitan: 4000000, other: 3000000 } },
  { max_area_sqm: 135, amounts_krw: { seoul_busan: 10000000, other_metropolitan: 7000000, other: 4000000 } },
  { max_area_sqm: null, amounts_krw: { seoul_busan: 15000000, other_metropolitan: 10000000, other: 5000000 } },
] })
const notice = (extra: Partial<Notice> = {}): Notice => ({
  id: 'aggregate-rank', title: '면적별 예치금 공고', category: 'apt', housing_kind: 'private', housing_kind_evidence: { verification: 'official' },
  source: 'cheongyak_home', provider: '공급자', address: null, region_code: '41', region_name: '경기도',
  announcement_date: cutoff, official_url: source, price_cap_status: 'no', events: [], updated_at: null, version: 1,
  prices: [59, 99, 129, 160].map((area, index) => ({ unit_type: `unit-${index + 1}`, exclusive_area_sqm: area, price_kind: 'sale' })),
  rules: [rule('private_rank_months', { value: 6 }), rule('account_type', { allowed_values: ['comprehensive'] }), deposit,
    rule('rank_requirements', { effect: 'metadata', complete: true, required_kinds: ['private_rank_months', 'account_type', 'deposit_min_krw'] })],
  ...extra,
})
const profile = (extra: Partial<LocalProfile> = {}): LocalProfile => ({
  ...EMPTY_PROFILE, region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590', movedInDate: '2020-01-01',
  accountType: 'comprehensive', privateRankBaseDate: '2009-01-01', accountConversionUnclear: false,
  privateDepositKrw: '19300000', factChanges: { bank_private: { mode: 'known', date: '2026-09-01' } }, ...extra,
})
beforeEach(() => setEvaluationToday(today))
afterEach(() => setEvaluationToday(null))

describe('deposit outcomes across official exclusive-area tiers', () => {
  it('passes every tier before aggregating rank and retains the deposit reason and grouped criteria', () => {
    const item = notice(), facts = profile()
    expect(evaluateRule(deposit, facts, item)).toMatchObject({ status: 'pass', category: 'condition', input: '19,300,000원' })
    const rank = deriveRank(item, facts)
    expect(rank).toMatchObject({ rank: 'first', status: 'possible' })
    expect(rank.reasons.find((reason) => reason.label === '민영주택 예치금')).toMatchObject({ status: 'pass' })
    expect(rank.reasons.some((reason) => reason.category === 'selection')).toBe(false)
    const comparisons = rankUnitComparisons(item, facts)
    expect(comparisons).toHaveLength(4)
    expect(comparisons.every((comparison) => comparison.reasons.every((reason) => reason.status === 'pass'))).toBe(true)
    expect(comparisons.map((comparison) => comparison.reasons[0].requirement)).toEqual([
      '그 밖의 지역 · >= 2,000,000원', '그 밖의 지역 · >= 3,000,000원', '그 밖의 지역 · >= 4,000,000원', '그 밖의 지역 · >= 5,000,000원',
    ])
  })

  it('keeps genuinely mixed outcomes as a unit comparison', () => {
    const item = notice(), facts = profile({ privateDepositKrw: '3500000' })
    expect(evaluateRule(deposit, facts, item)).toMatchObject({ status: 'review', category: 'selection' })
    expect(deriveRank(item, facts)).toMatchObject({ rank: 'unknown', status: 'review' })
    expect(unitRankResults(item, facts).map((entry) => entry.result.status)).toEqual(['possible', 'possible', 'mismatch', 'mismatch'])
    expect(rankUnitComparisons(item, facts).map((entry) => entry.reasons[0].status)).toEqual(['pass', 'pass', 'fail', 'fail'])
  })

  it('matches an official inventory code padded by the API without changing its source record', () => {
    const item = notice({ offered_supplies: [{ supply_type: '일반공급', unit_type: 'unit-1 ', supply_count: 2, verification: 'official' }] })
    const before = JSON.stringify(item)
    expect(evaluateRule(deposit, profile(), item)).toMatchObject({ status: 'pass' })
    expect(deriveRank(item, profile())).toMatchObject({ rank: 'first' })
    expect(JSON.stringify(item)).toBe(before)
    const metadata = { ...item, offered_supplies: undefined, rules: [...item.rules, rule('offered_supplies', { effect: 'metadata', supplies: item.offered_supplies })] }
    expect(deriveRank(metadata, profile())).toMatchObject({ rank: 'first' })
  })

  it('fails an insufficient balance only when every official area comparison fails', () => {
    const item = notice(), facts = profile({ privateDepositKrw: '1000000' })
    expect(evaluateRule(deposit, facts, item)).toMatchObject({ status: 'fail', category: 'condition' })
    expect(deriveRank(item, facts)).toMatchObject({ rank: 'unknown', status: 'mismatch' })
    expect(rankUnitComparisons(item, facts)).toHaveLength(4)
    expect(rankUnitComparisons(item, facts).every((entry) => entry.reasons[0].status === 'fail')).toBe(true)
  })

  it('asks for a missing common amount once while preserving all known tier requirements', () => {
    const item = notice(), facts = profile({ privateDepositKrw: '' })
    expect(evaluateRule(deposit, facts, item)).toMatchObject({ status: 'review', category: 'missing_input', profileField: 'privateDepositKrw' })
    expect(rankUnitComparisons(item, facts)).toHaveLength(4)
    expect(deriveRank(item, facts).rank).toBe('unknown')
  })

  it('retains a source gap for an unknown area or an offered unit absent from the area rows', () => {
    const base = notice()
    for (const facts of [profile(), profile({ privateDepositKrw: '1000000' })]) {
      for (const item of [
        { ...base, prices: base.prices.map((price, index) => index === 3 ? { ...price, exclusive_area_sqm: null, area_sqm: 200, area_basis: 'supply' as const } : price) },
        { ...base, offered_supplies: [{ supply_type: '일반공급', unit_type: 'missing-area', supply_count: 1, verification: 'official' as const }] },
      ]) {
        expect(evaluateRule(deposit, facts, item)).toMatchObject({ status: 'review', category: 'source_gap' })
        expect(deriveRank(item, facts)).toMatchObject({ rank: 'unknown', status: 'review' })
      }
    }
  })

  it('rejects malformed, zero and nonfinite official tier criteria instead of passing or failing them', () => {
    const tables = [
      [{ max_area_sqm: 85, amounts_krw: { seoul_busan: 3000000, other_metropolitan: 2500000, other: 2000000 } }],
      [{ max_area_sqm: null, amounts_krw: { seoul_busan: 3000000, other_metropolitan: 2500000, other: 0 } }],
      [{ max_area_sqm: Infinity, amounts_krw: { seoul_busan: 3000000, other_metropolitan: 2500000, other: 2000000 } },
        { max_area_sqm: null, amounts_krw: { seoul_busan: 15000000, other_metropolitan: 10000000, other: 5000000 } }],
    ]
    for (const deposit_table of tables) {
      const invalid = { ...deposit, deposit_table }, item = notice({ rules: notice().rules.map((entry) => entry.kind === 'deposit_min_krw' ? invalid : entry) })
      for (const facts of [profile(), profile({ privateDepositKrw: '1000000' })]) {
        expect(evaluateRule(invalid, facts, item)).toMatchObject({ status: 'review', category: 'source_gap' })
        expect(deriveRank(item, facts)).toMatchObject({ rank: 'unknown', status: 'review' })
      }
    }
  })

  it('uses any new notice thresholds and residence bucket without privileging a particular amount', () => {
    const updated = { ...deposit, criterion_date: '2026-10-10', deposit_table: [
      { max_area_sqm: 100, amounts_krw: { seoul_busan: 13000000, other_metropolitan: 11000000, other: 7000000 } },
      { max_area_sqm: null, amounts_krw: { seoul_busan: 31000000, other_metropolitan: 27000000, other: 22000000 } },
    ] }
    const item = notice({ id: 'another-source', title: '새 기준 공고', announcement_date: '2026-10-10', rules: notice().rules.map((entry) => entry.kind === 'deposit_min_krw' ? updated : { ...entry, criterion_date: '2026-10-10' }) })
    expect(evaluateRule(updated, profile(), item)).toMatchObject({ status: 'review', category: 'selection' })
    expect(deriveRank(item, profile({ privateDepositKrw: '22000000' }))).toMatchObject({ rank: 'first' })
    const seoul = profile({ region: '서울특별시', regionCode: '11', district: '', districtCode: '', privateDepositKrw: '22000000' })
    expect(evaluateRule(updated, seoul, item)).toMatchObject({ status: 'review', category: 'selection' })
  })
})

describe('deposit balances retain their historical provenance', () => {
  it('does not treat a newly observed high current balance as the older announcement balance', () => {
    const item = notice(), facts = profile({ factChanges: {}, privateDepositAsOfDate: today })
    expect(evaluateRule(deposit, facts, item)).toMatchObject({ status: 'review', category: 'past_fact', historyGroup: 'bank_private', profileField: 'privateDepositAsOfDate' })
    expect(deriveRank(item, facts).rank).toBe('unknown')
    expect(rankUnitComparisons(item, facts)).toEqual([])
  })

  it('reuses an exact observation, a known earlier change or maintained legacy balance', () => {
    const item = notice()
    for (const facts of [
      profile({ factChanges: {}, privateDepositAsOfDate: cutoff }),
      profile({ factChanges: { bank_private: { mode: 'known', date: cutoff } }, privateDepositAsOfDate: today }),
      profile({ factChanges: { bank_private: { mode: 'never_changed', date: '' } }, privateDepositAsOfDate: today }),
      profile({ factChanges: {}, privateDepositAsOfDate: '2026-09-01', privateDepositMaintained: true }),
    ]) expect(deriveRank(item, facts)).toMatchObject({ rank: 'first', status: 'possible' })
  })

  it('uses the actual saved older amount after a change instead of inheriting today\'s high amount', () => {
    const facts = profile({ factChanges: { bank_private: { mode: 'known', date: '2026-10-05' } }, privateDepositAsOfDate: today,
      factSnapshots: [{ group: 'bank_private', date: cutoff, values: { privateDepositKrw: '1000000' } }] })
    expect(evaluateRule(deposit, facts, notice())).toMatchObject({ status: 'fail', input: '1,000,000원' })
    expect(deriveRank(notice(), facts)).toMatchObject({ rank: 'unknown', status: 'mismatch' })
  })

  it('can use a saved historical amount when the current amount is blank', () => {
    const facts = profile({ privateDepositKrw: '', factChanges: {},
      factSnapshots: [{ group: 'bank_private', date: cutoff, values: { privateDepositKrw: '19300000' } }] })
    expect(evaluateRule(deposit, facts, notice())).toMatchObject({ status: 'pass', input: '19,300,000원' })
    expect(deriveRank(notice(), facts)).toMatchObject({ rank: 'first' })
  })

  it('does not fill a saved snapshot missing its balance with today\'s balance', () => {
    const facts = profile({ factChanges: {},
      factSnapshots: [{ group: 'bank_private', date: cutoff, values: { accountType: 'comprehensive' } }] })
    expect(evaluateRule(deposit, facts, notice())).toMatchObject({ status: 'review', category: 'past_fact' })
    expect(deriveRank(notice(), facts).rank).toBe('unknown')
  })

  it('aggregates genuine all-failing unit-scoped deposits and supports unit lists', () => {
    const item = notice({ rules: [
      ...notice().rules.filter((entry) => entry.kind !== 'deposit_min_krw'),
      rule('deposit_min_krw', { value: 2000000, unit_types: ['unit-1', 'unit-2'] }),
      rule('deposit_min_krw', { value: 5000000, unit_types: ['unit-3', 'unit-4'] }),
    ] })
    expect(deriveRank(item, profile({ privateDepositKrw: '1000000' }))).toMatchObject({ rank: 'unknown', status: 'mismatch' })
    expect(deriveRank(item, profile())).toMatchObject({ rank: 'first', status: 'possible' })
    expect(unitRankResults(item, profile({ privateDepositKrw: '3000000' })).map((entry) => entry.result.status)).toEqual(['possible', 'possible', 'mismatch', 'mismatch'])
  })
})
