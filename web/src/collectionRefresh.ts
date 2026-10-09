import type { CoverageResponse } from './types'

export interface NoticeRefreshState {
  applied: string | null
  completed: string | null
  refreshedAt: number
}
export const AUTOMATIC_NOTICE_REFRESH_MS = 180_000

/** Poll small status responses often; coalesce large public notice reads.
 * Completion bypasses the interval so finished official results appear promptly.
 */
export function needsAutomaticNoticeRefresh(state: NoticeRefreshState, coverage: CoverageResponse, now: number): boolean {
  const progress = coverage.sources.map((source) =>
    `${source.source}:${source.last_success_at || ''}:${source.record_count ?? ''}${source.source === 'cheongyak_competition' ? `:${source.status}:${source.last_attempt_at || ''}` : ''}`,
  ).sort().join('|')
  const completed = coverage.sources.map((source) =>
    `${source.source}:${source.last_success_at || ''}${source.source === 'cheongyak_competition' && !['pending', 'running'].includes(source.status) ? `:${source.status}:${source.last_attempt_at || ''}` : ''}`,
  ).sort().join('|')
  if (state.applied === null) {
    state.applied = progress
    state.completed = completed
    state.refreshedAt = now
    return false // The initial calendar and agenda requests already run.
  }
  if (progress === state.applied || completed === state.completed && now - state.refreshedAt < AUTOMATIC_NOTICE_REFRESH_MS) return false
  state.applied = progress
  state.completed = completed
  state.refreshedAt = now
  return true
}
