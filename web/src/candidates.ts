import type { LocalProfile, Notice, NoticeEvent } from './types'
import { matchesRegionScope, provinceAliases, scopeIsDistrict } from './regions'
import { applicantRegionEligibility } from './qualification'
import { residenceArea, RESIDENCE_AREA_LABEL, type CompetitionDecision } from './competition'
import { noticeEligibilitySummary, applicationEventAvailability, evaluateRule } from './eligibility'
export function isApplicationEvent(event: NoticeEvent): boolean {
  return !/^(announcement|contract|result|winner)$/i.test(event.kind) && !/당첨자 발표|계약일|계약 체결/i.test(event.label)
}
function regionMatch(notice: Notice, profile: LocalProfile): boolean {
  if (!profile.region || profile.regionNeedsReview) return false
  return matchesRegionScope(profile, { region_name: notice.region_name, region_code: notice.region_code }, notice.announcement_date) === true ||
    provinceAliases(profile.region).some((name) => (notice.address || '').startsWith(name))
}

function localMatch(notice: Notice, profile: LocalProfile): boolean {
  if (!regionMatch(notice, profile)) return false
  const scope = { region_name: notice.region_name, region_code: notice.region_code }
  if (scopeIsDistrict(scope)) return matchesRegionScope(profile, scope, notice.announcement_date) === true
  if (!profile.district.trim()) return true
  // Use a published district scope or the address's complete city/district prefix.
  const addressScope = (notice.address || '').match(/^(?:[^ ]+[시도]\s+)?(?:[^ ]+시\s+)?[^ ]+[시군구]/)?.[0]
  if (addressScope) return matchesRegionScope(profile, { region_name: addressScope }, notice.announcement_date) === true
  return false
}

function residencePeriodMatch(notice: Notice, profile: LocalProfile, effect: 'eligibility' | 'priority' = 'eligibility'): boolean | null {
  const rules = (notice.rules || []).filter((rule) =>
    rule.kind === 'residence_months' && rule.verification === 'official' &&
    (effect === 'priority' ? rule.effect === 'priority' : rule.effect !== 'priority') &&
    !rule.unit_type && !rule.supply_type)
  if (!rules.length) return null
  const results = rules.map((rule) => evaluateRule({ ...rule, effect: 'eligibility' }, profile, notice))
  if (results.some((item) => item.status === 'fail')) return false
  return results.some((item) => item.status === 'review') ? null : true
}

function hasPriorityResidenceRule(notice: Notice): boolean {
  return (notice.rules || []).some((rule) =>
    rule.kind === 'residence_months' && rule.verification === 'official' && rule.effect === 'priority',
  )
}

export function eventCandidate(event: NoticeEvent, notice: Notice, profile: LocalProfile): boolean {
  if (!profile.region || !isApplicationEvent(event)) return false
  const admitted = applicantRegionEligibility(notice, profile)
  if (admitted && admitted.status !== 'pass') return false
  const area = residenceArea(notice, profile)
  const audience = `${event.audience || ''} ${event.label || ''} ${event.kind || ''}`
  const local = localMatch(notice, profile)
  const residenceAllowed = residencePeriodMatch(notice, profile) !== false
  // A local resident can sometimes apply on an "other region" day when a
  // residence duration only controls local priority. The published audience
  // wording must still be checked against the original notice.
  const alternativeDay = local && hasPriorityResidenceRule(notice) && residencePeriodMatch(notice, profile, 'priority') !== true
  if (/기타경기/i.test(audience)) return area === 'other_gyeonggi'
  if (/기타지역|타지역|other.region/i.test(audience)) return area === 'other' || !!admitted && alternativeDay
  if (/해당지역|당해지역|local.region/i.test(audience)) return area !== 'other' && area !== 'other_gyeonggi' && local && residenceAllowed
  const names = [profile.region, ...provinceAliases(profile.region)]
  return (admitted?.status === 'pass' || names.some((name) => audience.includes(name)) || local) && residenceAllowed
}

export function hasResidenceCandidate(notice: Notice, profile: LocalProfile, start: string, end: string, decision?: CompetitionDecision): boolean {
  if (noticeEligibilitySummary(notice, profile, decision).status === 'mismatch' || decision?.allApplicationsUnavailable) return false
  return (notice.events || []).some((event) =>
    isApplicationEvent(event) && (event.end_date || event.start_date) >= start && event.start_date <= end &&
    eventCandidate(event, notice, profile) && !applicationEventAvailability(event, notice, profile, decision).unavailable,
  )
}

export function candidateLabel(notice: Notice, profile: LocalProfile): string {
  const region = (notice.rules || []).find((rule) => rule.kind === 'applicant_regions' && rule.verification === 'official')
  if (region?.unrestricted === true) return '신청지역 제한 없음 · 접수일 후보'
  const area = residenceArea(notice, profile)
  if (area === 'other' || area === 'other_gyeonggi') return `${RESIDENCE_AREA_LABEL[area]} 접수일 후보`
  if (hasPriorityResidenceRule(notice)) {
    const priority = residencePeriodMatch(notice, profile, 'priority')
    if (priority === false) return '지역 우선순위 미충족 · 접수일 확인'
    if (priority === true) return '지역 우선순위 충족 후보'
    return '지역 우선순위·접수일 확인 필요'
  }
  const period = residencePeriodMatch(notice, profile)
  return period === true ? '거주기간 충족 후보' : '지역 일치 · 기간 확인 필요'
}

export function candidateExplanation(notice: Notice, profile: LocalProfile): string {
  const region = (notice.rules || []).find((rule) => rule.kind === 'applicant_regions' && rule.verification === 'official')
  if (region?.unrestricted === true) return '공식 공고에 신청지역·지역 우선 거주기간 제한이 없습니다. 나머지 신청 조건은 아래에서 별도로 비교합니다.'
  const location = `${profile.region} ${profile.district}`.trim()
  const admitted = applicantRegionEligibility(notice, profile)
  const area = residenceArea(notice, profile)
  if (admitted?.status === 'pass' && (area === 'other' || area === 'other_gyeonggi')) return `${location} · ${admitted.detail} 공식 지역 배정 기준에서는 ${RESIDENCE_AREA_LABEL[area]} 접수 대상입니다.`
  const priority = residencePeriodMatch(notice, profile, 'priority')
  const period = residencePeriodMatch(notice, profile)
  if (priority === false) return `${location}는 공고 지역과 일치하지만 지역 우선공급 기간은 충족하지 않습니다. 기타지역 접수일과 배정 순서를 확인할 후보입니다.`
  if (priority === true || period === true) return `${location}와 공식 거주 범위가 일치하고, 입력한 연속 거주일이 공개된 기간 조건을 충족합니다. 나머지 신청 자격은 별도로 비교합니다.`
  return `${location}와 공고의 거주 범위가 일치합니다. 공식 거주기간 조건 또는 해당 범위의 연속 거주 시작일이 없어 기간은 확인이 필요합니다.`
}

