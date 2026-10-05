import type { Notice } from './types'

/** Keep references only when all public content is identical, including evidence. */
export function reuseUnchangedNotices(previous: Notice[], incoming: Notice[]): Notice[] {
  const byId = new Map(previous.map((notice) => [notice.id, notice]))
  const rows = incoming.map((notice) => {
    const old = byId.get(notice.id)
    return old && JSON.stringify(old) === JSON.stringify(notice) ? old : notice
  })
  return rows.length === previous.length && rows.every((notice, i) => notice === previous[i]) ? previous : rows
}
