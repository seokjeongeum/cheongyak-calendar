import { describe, it, expect } from 'vitest'
import { EMPTY_PROFILE, type Notice } from './types'
import { reuseUnchangedNotices } from './publicNoticeCache'
import { evaluateCatalog, candidateInRange } from './evaluation'
import { demoNotices } from './demo'

function notice(): Notice {
  const base = demoNotices()[0]
  return { ...base, id: 'same-public-id', events: [{ kind: 'general', label: '일반공급', start_date: '2026-10-05', end_date: '2026-11-05', audience: null }],
    rules: [{ id: 'age', kind: 'age_min', value: 19, verification: 'official', evidence_text: '성년자', criterion_date: '2026-10-05' }],
    rules_complete: true, offered_supplies: [{ supply_type: '일반공급', unit_type: '59A', verification: 'official', supply_count: 1 }] }
}
const request = { revision: 1, profile: { ...EMPTY_PROFILE, dateOfBirth: '1993-01-01' }, today: '2026-10-05', now: Date.parse('2026-10-05T00:00:00+09:00'), overrides: {}, mode: 'schedule' as const }

describe('shared browser evaluations and public content revisions', () => {
  it('reuses unchanged responses, but rules/evidence changes at the same id invalidate', () => {
    const first = [notice()]
    expect(reuseUnchangedNotices(first, structuredClone(first))).toBe(first)
    const changed = structuredClone(first); changed[0].rules[0].value = 40
    expect(reuseUnchangedNotices(first, changed)[0]).not.toBe(first[0])
    const evidence = structuredClone(first); evidence[0].rules[0].evidence_text = '정정 기준'
    expect(reuseUnchangedNotices(first, evidence)[0]).not.toBe(first[0])
  })
  it('updates all views after a same-id official correction and retains the public record', () => {
    const first = notice()
    const passed = evaluateCatalog([first], request)
    const corrected = { ...first, rules: [{ ...first.rules[0], value: 40 }] }
    const failed = evaluateCatalog([corrected], { ...request, revision: 2 })
    expect(passed.evaluations[first.id].summary.status).toBe('possible')
    const result = failed.evaluations[first.id]
    expect(result.summary.status).toBe('mismatch')
    expect(result.combinations.every((pair) => pair.result.status === 'mismatch')).toBe(true)
    expect(result.events[0].unavailable).toBe(true)
    expect(Object.keys(failed.evaluations)).toContain(first.id)
    expect(candidateInRange(corrected, result, '2026-10-05', '2026-11-01')).toBe(false)
  })
  it('keeps a corrected failing price row separate from another offered unit', () => {
    const first = notice()
    first.offered_supplies!.push({ supply_type: '일반공급', unit_type: '84A', verification: 'official', supply_count: 1 })
    first.rules = [{ ...first.rules[0], unit_type: '59A', value: 40 }]
    const snapshot = evaluateCatalog([first], request).evaluations[first.id]
    expect(snapshot.combinations.find((pair) => pair.unitType === '59A')?.result.status).toBe('mismatch')
    expect(snapshot.combinations.find((pair) => pair.unitType === '84A')?.result.status).not.toBe('mismatch')
    expect(snapshot.events[0].unavailable).toBe(false)
  })
})
