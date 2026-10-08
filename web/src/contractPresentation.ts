import type { Notice, NoticeRule } from './types'

function usesContractDate(rules: NoticeRule[]): boolean {
  return rules.some((rule) => !!rule && typeof rule === 'object' && (rule.criterion_basis === 'contract_date' ||
    Array.isArray(rule.conditions) && usesContractDate(rule.conditions as NoticeRule[])))
}

/** The preview compares today's local facts; the public period is context only. */
export function contractComparisonNote(notice: Notice, today: string): string | null {
  if (notice.qualification_context?.application_criterion_basis !== 'contract_date' && !usesContractDate(notice.rules)) return null
  const preview = `오늘의 내 상태로 미리 비교 · 한국 시간 ${today}.`
  const schedule = notice.contract_schedule
  if (!schedule || schedule.verification !== 'official' || !schedule.start_date || schedule.status === 'unknown') return `${preview} 공식 계약기간은 아직 확보하지 못했습니다. 실제 계약일까지 현재 상태가 유지된다는 전제로 비교합니다.`
  const start = schedule.start_date, end = schedule.end_date
  const range = start === end || !end ? start : `${start} – ${end}`
  const until = schedule.evidence_text?.match(/(?:별도\s*(?:공지|공고)(?:\s*시)?까지|(?:잔여\s*세대\s*)?(?:소진|마감)\s*(?:시)?까지)/)?.[0] || '종료일 미공개'
  const official = schedule.status === 'fixed' ? `공식 계약일 ${start}` : schedule.status === 'ongoing' && !end ? `공식 계약기간 ${start}부터 ${until}` : `공식 계약기간 ${range}`
  const ended = end && end < today ? ' (공식 기간 종료)' : ''
  return `${preview} ${official}${ended}. 실제 계약일까지 현재 상태가 유지된다는 전제로 비교합니다.`
}
