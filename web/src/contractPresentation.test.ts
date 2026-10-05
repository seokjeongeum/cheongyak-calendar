import { describe, expect, it } from 'vitest'
import { contractComparisonNote } from './contractPresentation'
import { demoNotices } from './demo'
import type { Notice } from './types'

const today = '2026-10-05'
function notice(status: 'fixed' | 'range' | 'ongoing', start: string, end: string | null): Notice {
  return { ...demoNotices()[0], rules: [{ kind: 'domestic_residence', criterion_basis: 'contract_date', verification: 'official' }],
    contract_schedule: { status, start_date: start, end_date: end, verification: 'official' } }
}
describe('official contract scenario explanation', () => {
  it('distinguishes upcoming assumptions, ongoing today, and an expired range', () => {
    expect(contractComparisonNote(notice('range', '2026-10-10', '2026-10-12'), today)).toContain('현재 입력이 유지될 때')
    expect(contractComparisonNote(notice('range', '2026-10-01', today), today)).toContain('오늘 계약한다면')
    expect(contractComparisonNote(notice('range', '2026-10-01', '2026-10-04'), today)).toContain('실제 계약일이 없어')
  })
  it('shows the official open-ended period and does not take a posting expiry', () => {
    const row = notice('ongoing', '2026-07-23', null)
    row.events.push({ kind: 'announcement', label: '공고 게시', audience: null, start_date: '2026-07-23', end_date: '2027-03-31' })
    const note = contractComparisonNote(row, today)
    expect(note).toContain('종료일 미공개')
    expect(note).toContain(today)
    expect(note).not.toContain('2027-03-31')
    row.contract_schedule = null
    expect(contractComparisonNote(row, today)).toContain('보류')
  })
})
