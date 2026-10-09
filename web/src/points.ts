import type { LocalProfile, Notice } from './types'
import { ageAt, fullMonths, parseDate, criterionDate } from './qualification'
import { getEvaluationToday, factsAtDate } from './factTimeline'
import { deriveHousehold } from './household'
import { evaluateHouseholdOwnership, evaluatePropertyOwnership, ownershipInventoryComplete } from './ownership'

export const POINTS_SOURCE = 'https://www.applyhome.co.kr/ap/apg/selectAddpntCalculatorView.do'
export interface PointsPart { label: string; score: number | null; maximum: number; detail: string; field?: keyof LocalProfile }
export interface PointsResult { date: string | null; total: number | null; confirmed: number; parts: PointsPart[] }
const years = (start: string, end: string) => Math.floor((fullMonths(start, end) ?? 0) / 12)
function birthday(birth: string, age: number): string { const y = Number(birth.slice(0, 4)) + age; return `${y}${birth.slice(4)}`.replace(/-02-29$/, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? '-02-29' : '-02-28') }
function yearsBefore(date: string, years: number): string { return birthday(date, -years) }
export function bankPoints(months: number): number { return months < 6 ? 1 : months < 12 ? 2 : Math.min(17, Math.floor(months / 12) + 2) }
/** Article 10(6): pre-2024 minor years capped at 2; total minor years capped at 5.
 * Keep the recognized interval continuous so split dates do not discard partial months.
 * https://www.law.go.kr/lsInfoP.do?lsiSeq=286965&viewCls=lsRvsDocInfoR
 */
export function recognizedAccountMonths(start: string, birth: string, cutoff: string): number | null {
  if (!parseDate(start) || !parseDate(birth) || !parseDate(cutoff) || start < birth || start > cutoff || birth > cutoff) return null
  const adult = birthday(birth, 19)
  if (start >= adult) return fullMonths(start, cutoff)
  const minorEnd = adult < cutoff ? adult : cutoff
  // 2024-01-01 is the shared boundary; ending on 2023-12-31 loses a day.
  const oldEnd = minorEnd < '2024-01-01' ? minorEnd : '2024-01-01'
  const oldStart = yearsBefore(oldEnd, 2)
  const totalStart = yearsBefore(minorEnd, 5)
  const recognizedStart = [start, oldStart, totalStart].sort().at(-1)!
  return fullMonths(recognizedStart, cutoff)
}
function homeless(profile: LocalProfile, date: string): PointsPart {
  const part: PointsPart = { label: '무주택기간', score: null, maximum: 32, detail: '', field: 'ownershipFacts' }
  const temporal = factsAtDate(profile, 'ownership', date)
  const dated = profile.ownershipFacts.length > 0 && ownershipInventoryComplete(profile) && profile.ownershipFacts.every((r) => !!parseDate(r.acquiredDate))
  if (!temporal.known && !dated) return { ...part, detail: '공고일의 주택 소유 사실이 필요합니다.', field: 'ownershipFacts' }
  profile = temporal.profile
  const ownership = evaluateHouseholdOwnership(profile, { criterionDate: date, inventoryDate: temporal.source === 'snapshot' ? date : undefined, supplyType: '일반공급' })
  if (ownership.value === false) return { ...part, score: 0, detail: '공고일 유주택으로 무주택기간 가점은 0점입니다.' }
  if (ownership.value === null) return { ...part, detail: ownership.detail, field: ownership.profileField || 'ownershipFacts' }
  const age = ageAt(profile.dateOfBirth, date)
  const marriage = factsAtDate(profile, 'marital', date)
  if (age === null) return { ...part, detail: '생년월일이 필요합니다.', field: 'dateOfBirth' }
  if (!marriage.known || marriage.profile.maritalStatus === 'unknown') return { ...part, detail: '공고일의 혼인 상태가 필요합니다.', field: 'maritalStatus' }
  profile = marriage.profile
  if (profile.maritalStatus === 'single' && age < 30) return { ...part, score: 0, detail: '만 30세 미만 미혼자는 무주택기간 가점 0점입니다.' }
  let base = birthday(profile.dateOfBirth, 30)
  if (profile.maritalStatus === 'married' && !parseDate(profile.marriageDate)) return { ...part, detail: '혼인신고일이 필요합니다.', field: 'marriageDate' }
  if (profile.marriageDate && profile.marriageDate <= date && profile.marriageDate < base) base = profile.marriageDate
  if (['divorced', 'widowed'].includes(profile.maritalStatus) && !profile.marriageDate) return { ...part, detail: '최초 혼인신고일을 확인해야 합니다.', field: 'marriageDate' }
  const relevant = profile.ownershipFacts.filter((r) => ['applicant', 'spouse'].includes(r.ownerRelation) && r.acquiredDate <= date && !(r.ownerRelation === 'spouse' && r.disposedDate && profile.marriageDate && r.disposedDate < profile.marriageDate))
  const pointsFacts = factsAtDate(profile, 'points', date)
  const reviewedSince = pointsFacts.known && parseDate(pointsFacts.profile.pointsHomelessSince) && pointsFacts.profile.pointsHomelessSince <= date && pointsFacts.profile.pointsHomelessSince <= getEvaluationToday() ? pointsFacts.profile.pointsHomelessSince : ''
  if (relevant.some((r) => !parseDate(r.disposedDate)) && !reviewedSince) return { ...part, detail: '보유 이력·법정 예외로 무주택이 된 날을 확인하세요.', field: 'pointsHomelessSince' }
  if ((profile.applicantPreviouslyOwnedHome !== false || profile.hasSpouse === true && profile.spousePreviouslyOwnedHome !== false) && !relevant.length && !reviewedSince) return { ...part, detail: '본인·배우자의 과거 소유 이력 또는 무주택이 된 날이 필요합니다.', field: 'pointsHomelessSince' }
  const since = [base, reviewedSince, ...relevant.map((r) => r.disposedDate)].filter((value) => !!parseDate(value)).sort().at(-1)!
  if (since > date) return { ...part, score: 0, detail: '공고일에는 무주택기간 산정 시작일 전입니다.' }
  return { ...part, score: Math.min(32, (years(since, date) + 1) * 2), detail: `${since}부터 ${years(since, date)}년 · 본인·배우자 소유 이력 기준` }
}
function dependants(profile: LocalProfile, date: string): PointsPart {
  const part: PointsPart = { label: '부양가족', score: null, maximum: 35, detail: '', field: 'pointsFamily' }
  const household = deriveHousehold(profile, date)
  if (!household.complete) return { ...part, detail: household.reviewDetail || '공고일 가족·등본 사실이 필요합니다.', field: household.profileField }
  const temporal = factsAtDate(profile, 'household', date)
  profile = temporal.profile
  const head = factsAtDate(profile, 'household_head', date)
  const pointsFacts = factsAtDate(profile, 'points', date)
  let count = profile.hasSpouse === true ? 1 : 0
  const exclusions: string[] = []
  const members = profile.householdMembers.filter((m) => m.register !== 'separate' && !['sibling', 'unrelated', 'descendant_spouse'].includes(m.relation))
  if (members.some((member) => !/parent$/.test(member.relation) || member.ownsHome !== true) && !pointsFacts.known) return { ...part, detail: '공고일의 가점용 가족 사실을 확인할 수 있는 변경 이력이 필요합니다.' }
  profile = pointsFacts.profile
  for (const member of members) {
    const f = profile.pointsFamily[member.id]
    const label = household.members.find((m) => m.id === member.id)?.label || member.id
    const ancestor = /parent$/.test(member.relation)
    if (ancestor && member.ownsHome === true) {
      const properties = profile.ownershipFacts.filter((r) => r.ownerMemberId === member.id)
      const decisions = properties.map((r) => evaluatePropertyOwnership(r, { criterionDate: date, supplyType: '노부모부양 특별공급' }, properties.length).counted)
      if (!properties.length || decisions.some((value) => value === true)) { exclusions.push(`${label}: 주택 소유 직계존속 제외 (60세 예외로 가점 인정하지 않음)`); continue }
      if (decisions.some((value) => value === null)) return { ...part, detail: `${label}의 소유 주택에 적용할 법정 예외를 확인해야 합니다.`, field: 'ownershipFacts' }
    }
    if (!f) return { ...part, detail: `${label}의 가점 인정 사실을 입력하세요.` }
    if (ancestor && f.spouseOwnsHome === true) { exclusions.push(`${label}: 직계존속 배우자 소유로 제외`); continue }
    if (f.overseasExcluded === true) { exclusions.push(`${label}: 공고의 국외 체류 기준으로 제외`); continue }
    if (f.overseasExcluded === null || !parseDate(f.registeredSince) || f.registeredSince > date) return { ...part, detail: `${label}의 연속 등본 등재일·국외 체류 사실이 필요합니다.` }
    if (ancestor) {
      if (!head.known || head.profile.isHouseholdHead === null || member.ownsHome === null || f.spouseOwnsHome === null) return { ...part, detail: `${label}의 주택·배우자 소유와 공고일 신청자의 세대주 사실이 필요합니다.`, field: !head.known || head.profile.isHouseholdHead === null ? 'isHouseholdHead' : part.field }
      if (!head.profile.isHouseholdHead || (fullMonths(f.registeredSince, date) || 0) < 36) { exclusions.push(`${label}: 세대주·3년 연속 등재 요건 미충족`); continue }
    } else {
      if (f.unmarried === false) { exclusions.push(`${label}: 혼인한 직계비속 제외`); continue }
      if (f.unmarried === null) return { ...part, detail: `${label}의 미혼 여부가 필요합니다.` }
      const age = ageAt(member.dateOfBirth, date)
      if (age === null) return { ...part, detail: `${label}의 생년월일이 필요합니다.`, field: 'householdMembers' }
      if (age >= 30 && (fullMonths(f.registeredSince, date) || 0) < 12) { exclusions.push(`${label}: 만 30세 이상 1년 연속 등재 요건 미충족`); continue }
      if (member.relation.includes('grandchild')) {
        if (f.grandchildrenParentsAbsent === null) return { ...part, detail: `${label}의 부모 사망 등 인정 사유가 필요합니다.` }
        if (!f.grandchildrenParentsAbsent) { exclusions.push(`${label}: 손자녀 인정 사유 미충족`); continue }
      }
      if (member.relation.startsWith('spouse_') && member.register === 'spouse' && profile.spouseSameRegister !== true) { exclusions.push(`${label}: 재혼 배우자 자녀는 본인 등본에 등재 필요`); continue }
    }
    count++
  }
  return { ...part, score: Math.min(35, (count + 1) * 5), detail: `본인 제외 ${count}명${exclusions.length ? ` · ${exclusions.join(' / ')}` : ''}` }
}
function bank(profile: LocalProfile, date: string): PointsPart {
  const part: PointsPart = { label: '통장 가입기간', score: null, maximum: 17, detail: '', field: 'privateRankBaseDate' }
  if (!['comprehensive', 'deposit', 'installment'].includes(profile.accountType)) return { ...part, detail: '민영 청약통장의 은행 인정 가입일이 필요합니다.' }
  const months = recognizedAccountMonths(profile.privateRankBaseDate, profile.dateOfBirth, date)
  if (months === null) return { ...part, detail: '은행 인정 순위기산일과 생년월일이 필요합니다.' }
  const mine = bankPoints(months)
  // Spouse account credit started on 2024-03-25; it cannot revise older results.
  // https://www.korea.kr/news/policyNewsView.do?newsId=148927399
  if (date < '2024-03-25') return { ...part, score: mine, detail: `본인 인정 ${months}개월 · ${mine}점 · 배우자 가입기간 합산 시행 전` }
  const marital = factsAtDate(profile, 'marital', date)
  if (!marital.known || marital.profile.hasSpouse === null) return { ...part, detail: '공고일 배우자 유무가 필요합니다.', field: 'maritalStatus' }
  profile = marital.profile
  if (profile.hasSpouse === false || mine === 17) return { ...part, score: mine, detail: `본인 인정 ${months}개월 · ${mine}점${mine === 17 ? ' (항목 상한)' : ''}` }
  const spouseFacts = factsAtDate(profile, 'points', date)
  if (!spouseFacts.known) return { ...part, detail: `본인 ${mine}점 확인 · 공고일의 배우자 통장 사실을 확인해야 합니다.`, field: 'spouseAccountBaseDate' }
  profile = spouseFacts.profile
  if (profile.spouseAccountPresent === false) return { ...part, score: mine, detail: `본인 인정 ${months}개월 · ${mine}점 · 공고일 배우자 통장 없음` }
  if (profile.spouseAccountPresent !== true || !parseDate(profile.spouseAccountBaseDate) || profile.spouseAccountBaseDate > date) return { ...part, detail: `본인 ${mine}점 확인 · 배우자 은행 인정 가입일이 필요합니다.`, field: 'spouseAccountBaseDate' }
  const half = Math.floor((fullMonths(profile.spouseAccountBaseDate, date) || 0) / 2)
  const spouse = Math.min(3, bankPoints(half))
  return { ...part, score: Math.min(17, mine + spouse), detail: `본인 ${mine}점 + 배우자 가입기간 50% ${spouse}점 · 합계 상한 17점` }
}
/** Personal facts never enter the public API. Unknown parts cannot produce a total. */
export function calculatePoints(notice: Notice, profile: LocalProfile): PointsResult {
  const dates = [...new Set((notice.selection_methods || notice.rules).filter((r) => r.kind === 'selection_method' && r.verification === 'official' && typeof r.criterion_date === 'string' && parseDate(r.criterion_date)).map((r) => String(r.criterion_date)))]
  const contextDate = notice.qualification_context?.application_criterion_date
  const date = dates.length === 1 ? dates[0] : dates.length > 1 ? null : typeof contextDate === 'string' && parseDate(contextDate) ? contextDate : criterionDate({ kind: 'selection_method' }, notice)
  const parts = date ? [homeless(profile, date), dependants(profile, date), bank(profile, date)] : ['무주택기간', '부양가족', '통장 가입기간'].map((label, i) => ({ label, score: null, maximum: [32, 35, 17][i], detail: '공식 모집공고 기준일 미확인' }))
  const confirmed = parts.reduce((sum, item) => sum + (item.score ?? 0), 0)
  return { date, parts, confirmed, total: parts.every((p) => p.score !== null) ? confirmed : null }
}
