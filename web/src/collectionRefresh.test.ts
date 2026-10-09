import { describe, expect, it } from 'vitest'
import { needsAutomaticNoticeRefresh, type NoticeRefreshState } from './collectionRefresh'
import type { CoverageResponse } from './types'
const coverage = (count: number, success: string | null = null): CoverageResponse => ({ sources: [{
  source: 'lh', status: success ? 'success' : 'running', record_count: count,
  last_success_at: success, last_attempt_at: '2026-10-09T12:00:00Z', message: null,
}] })
const state = (): NoticeRefreshState => ({ applied: null, completed: null, refreshedAt: 0 })
describe('bounded automatic notice refresh', () => {
  it('coalesces progress while preserving pending changes after counts stop changing', () => {
    const tracker = state()
    expect(needsAutomaticNoticeRefresh(tracker, coverage(1), 0)).toBe(false)
    for (let seconds = 30; seconds < 180; seconds += 30) expect(needsAutomaticNoticeRefresh(tracker, coverage(2), seconds * 1000)).toBe(false)
    expect(needsAutomaticNoticeRefresh(tracker, coverage(2), 180_000)).toBe(true)
    expect(needsAutomaticNoticeRefresh(tracker, coverage(2), 360_000)).toBe(false)
  })
  it('shows a completed source immediately even within the progress interval', () => {
    const tracker = state()
    needsAutomaticNoticeRefresh(tracker, coverage(1), 0)
    expect(needsAutomaticNoticeRefresh(tracker, coverage(2, '2026-10-09T12:00:30Z'), 30_000)).toBe(true)
    expect(needsAutomaticNoticeRefresh(tracker, coverage(2, '2026-10-09T12:00:30Z'), 60_000)).toBe(false)
  })
})
