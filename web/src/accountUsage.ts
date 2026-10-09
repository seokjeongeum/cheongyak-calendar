import { factsAtDate, getEvaluationToday } from './factTimeline'
import type { LocalProfile } from './types'

export interface AccountWinningUsage {
  status: 'known' | 'missing_input' | 'past_fact'
  value: boolean | null
  profileField: 'currentAccountUsedForWinning' | 'currentAccountFirstWinningDate'
  detail: string
}
function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [y, m, d] = value.split('-').map(Number), parsed = new Date(Date.UTC(y, m - 1, d))
  return parsed.getUTCFullYear() === y && parsed.getUTCMonth() === m - 1 && parsed.getUTCDate() === d
}
/** The current account's own winning event is distinct from a person's past wins. */
export function accountWinningUsageAtDate(profile: LocalProfile, date: string): AccountWinningUsage {
  const temporal = factsAtDate(profile, 'bank_account', date, { date: profile.currentAccountFactsAsOfDate })
  const source = temporal.profile, used = source.currentAccountUsedForWinning, first = source.currentAccountFirstWinningDate
  if (temporal.known) {
    if (typeof used !== 'boolean') return { status: temporal.source === 'snapshot' ? 'past_fact' : 'missing_input', value: null, profileField: 'currentAccountUsedForWinning', detail: temporal.source === 'snapshot' ? `${date}의 저장된 통장 사실에 당첨 사용 여부가 없습니다. 오늘의 답변을 대신 적용하지 않습니다.` : '이번 신청에 사용할 현재 청약통장이 당첨자 선정에 사용된 적이 있는지 입력하세요.' }
    if (used && temporal.source !== 'current' && first && (!validDate(first) || first > getEvaluationToday() || first > date)) return { status: 'missing_input', value: null, profileField: 'currentAccountFirstWinningDate', detail: '저장된 당첨 사용 상태와 이 통장의 최초 당첨일이 서로 다릅니다. 최초 당첨자 선정일을 바로잡으세요.' }
    return { status: 'known', value: used, profileField: 'currentAccountUsedForWinning', detail: `${date} 기준 현재 사용할 통장은 당첨자 선정에 ${used ? '사용된 이력이 있습니다' : '사용된 이력이 없습니다'}. 계약 체결 여부와 별개로 비교합니다.` }
  }
  if (profile.currentAccountUsedForWinning === true) {
    if (!validDate(first) || first > getEvaluationToday()) return { status: 'missing_input', value: null, profileField: 'currentAccountFirstWinningDate', detail: '이 현재 통장이 가장 먼저 당첨자 선정에 사용된 실제 날짜를 입력하세요. 다른 통장으로 당첨된 날짜나 계약일은 대신 사용하지 않습니다.' }
    return { status: 'known', value: first <= date, profileField: 'currentAccountUsedForWinning', detail: `현재 사용할 통장의 최초 당첨자 선정일 ${first}을 공고 기준일 ${date}과 비교했습니다. 계약 여부는 이 통장의 재사용 판정에 영향을 주지 않습니다.` }
  }
  if (profile.currentAccountUsedForWinning == null) return { status: 'missing_input', value: null, profileField: 'currentAccountUsedForWinning', detail: '이번 신청에 사용할 현재 청약통장의 당첨 사용 여부를 입력하세요. 공통 당첨 이력만으로 어느 통장을 사용했는지 추정하지 않습니다.' }
  return { status: 'past_fact', value: null, profileField: 'currentAccountUsedForWinning', detail: `${date} 당시 현재 사용할 통장의 당첨 사용 여부를 확인할 저장된 사실이 없습니다. 통장 이력의 실제 변경일을 입력하세요. 민영·국민 순위기산일은 현재 통장 개설일과 같다고 가정하지 않습니다.` }
}
