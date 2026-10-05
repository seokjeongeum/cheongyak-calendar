import type { Notice, NoticeEvent } from './types'

export function isReception(event: NoticeEvent): boolean {
  return !/^(announcement|contract|result|winner)$/i.test(event.kind) && !/당첨자 발표|계약일|계약 체결/i.test(event.label)
}
/** The next stage deadline, including ongoing reception. Source dates stay intact. */
export function nextDeadline(notice: Notice, today: string, rangeEnd?: string): string | null {
  const dates = notice.events.filter((event) => isReception(event) && (!rangeEnd || event.start_date <= rangeEnd))
    .map((event) => event.end_date || (event.end_date === null && /상시|마감\s*시|소진\s*시|종료일\s*미공개/.test(event.label) ? null : event.start_date))
    .filter((date): date is string => !!date && date >= today).sort()
  return dates[0] || null
}
