import type { Notice, NoticeEvent } from './types'

export function isReception(event: NoticeEvent): boolean {
  return !/^(announcement|contract|result|winner)$/i.test(event.kind) && !/당첨자 발표|계약일|계약 체결/i.test(event.label)
}
/** Only explicit source wording makes a missing end date an ongoing reception. */
export function isOpenEndedReception(event: NoticeEvent): boolean {
  return isReception(event) && event.end_date == null && /상시|마감\s*시|소진\s*시|종료일\s*미공개/.test(event.label)
}

export function receptionEndDate(event: NoticeEvent): string | null {
  return isOpenEndedReception(event) ? null : event.end_date || event.start_date
}

export function receptionOverlaps(event: NoticeEvent, start: string, end: string): boolean {
  const deadline = receptionEndDate(event)
  return isReception(event) && event.start_date <= end && (!deadline || deadline >= start)
}
/** The next stage deadline, including ongoing reception. Source dates stay intact. */
export function nextDeadline(notice: Notice, today: string, rangeEnd?: string): string | null {
  const dates = notice.events.filter((event) => isReception(event) && (!rangeEnd || event.start_date <= rangeEnd))
    .map(receptionEndDate)
    .filter((date): date is string => !!date && date >= today).sort()
  return dates[0] || null
}
