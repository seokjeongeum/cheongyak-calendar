import { describe, expect, it } from 'vitest'
import { contractComparisonNote } from './contractPresentation'
import { demoNotices } from './demo'
import type { Notice } from './types'

const today = '2026-10-05'
function notice(status: 'fixed' | 'range' | 'ongoing', start: string, end: string | null): Notice {
  return { ...demoNotices()[0], rules: [{ kind: 'domestic_residence', criterion_basis: 'contract_date', verification: 'official' }],
    contract_schedule: { status, start_date: start, end_date: end, verification: 'official' } }
}
describe('today preview with an independently verified official contract period', () => {
  it('previews today before, during, and after the public period without asking a personal contract date', () => {
    for (const row of [notice('range', '2026-10-10', '2026-10-12'), notice('range', '2026-10-01', today), notice('range', '2026-10-01', '2026-10-04')]) {
      const note = contractComparisonNote(row, today)
      expect(note).toContain('오늘의 내 상태로 미리 비교')
      expect(note).toContain(`한국 시간 ${today}`)
      expect(note).toContain('실제 계약일까지 현재 상태가 유지된다는 전제')
      expect(note).not.toContain('개인 계약일')
      expect(note).not.toContain('보류')
    }
    expect(contractComparisonNote(notice('range', '2026-10-01', '2026-10-04'), today)).toContain('공식 기간 종료')
  })
  it('shows the entire Gyeongsan future period alongside the current preview date', () => {
    const note = contractComparisonNote(notice('range', '2026-10-27', '2027-08-31'), '2026-10-07')
    expect(note).toContain('한국 시간 2026-10-07')
    expect(note).toContain('공식 계약기간 2026-10-27 – 2027-08-31')
    expect(note).not.toContain('시작일 2026-10-27에')
  })
  it('shows the official open-ended period and does not take a posting expiry', () => {
    const row = notice('ongoing', '2026-07-23', null)
    row.events.push({ kind: 'announcement', label: '공고 게시', audience: null, start_date: '2026-07-23', end_date: '2027-03-31' })
    const note = contractComparisonNote(row, today)
    expect(note).toContain('종료일 미공개')
    expect(note).toContain(today)
    expect(note).not.toContain('2027-03-31')
    row.contract_schedule = null
    expect(contractComparisonNote(row, today)).toContain('공식 계약기간은 아직 확보하지 못했습니다')
    expect(contractComparisonNote(row, today)).toContain(`한국 시간 ${today}`)
    expect(contractComparisonNote(row, today)).not.toContain('보류')
  })
  it('does not convert an official announcement-date condition to a today preview', () => {
    const row = notice('range', '2026-10-27', '2027-08-31')
    row.rules = [{ kind: 'age_min', value: 19, criterion_date: '2026-10-02', verification: 'official' }]
    expect(contractComparisonNote(row, today)).toBeNull()
  })
})
