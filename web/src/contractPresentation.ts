import type { Notice, NoticeRule } from './types'

function usesContractDate(rules: NoticeRule[]): boolean {
  return rules.some((rule) => !!rule && typeof rule === 'object' && (rule.criterion_basis === 'contract_date' ||
    Array.isArray(rule.conditions) && usesContractDate(rule.conditions as NoticeRule[])))
}

/** Public dates only; no personal planned date or posting deadline is used. */
export function contractComparisonNote(notice: Notice, today: string): string | null {
  if (notice.qualification_context?.application_criterion_basis !== 'contract_date' && !usesContractDate(notice.rules)) return null
  const schedule = notice.contract_schedule
  if (!schedule || schedule.verification !== 'official' || !schedule.start_date || schedule.status === 'unknown') return '공식 계약일을 확인하지 못해 계약일 기준 조건은 보류합니다.'
  const start = schedule.start_date, end = schedule.end_date
  const range = start === end || !end ? start : `${start} – ${end}`
  if (schedule.status === 'fixed') return `공식 계약일 ${start} 기준으로 비교합니다.${start > today ? ' 현재 입력이 유지될 때의 판정입니다.' : ''}`
  const until = schedule.evidence_text?.match(/(?:별도\s*(?:공지|공고)(?:\s*시)?까지|(?:잔여\s*세대\s*)?(?:소진|마감)\s*(?:시)?까지)/)?.[0] || '종료일 미공개'
  if (schedule.status === 'ongoing') return start <= today && (!end || today <= end)
    ? `공식 계약 일정 ${start}부터${end ? ` ${end}까지` : ` ${until}`} · 오늘 계약한다면 (${today}) 기준입니다.`
    : '현재 진행 중인 공식 계약 일정이 없어 계약일 기준 조건은 보류합니다.'
  if (today < start) return `공식 계약기간 ${range} · 시작일 ${start}에 현재 입력이 유지될 때의 판정입니다.`
  if (end && today <= end) return `공식 계약기간 ${range} · 오늘 계약한다면 (${today}) 기준입니다.`
  return `공식 계약기간 ${range} 종료 · 실제 계약일이 없어 계약일 기준 조건은 보류합니다.`
}
