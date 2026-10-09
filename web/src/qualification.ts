import { EMPTY_PROFILE, type FactChangeGroup, type LocalProfile, type Notice, type NoticeRule, type NoticePrice, type OfferedSupply } from './types'
import { matchesRegionScope, scopeIsDistrict, parentCityCode, districtName, resolveLegacyRegion, provinceCode } from './regions'
import { deriveHousehold } from './household'
import { evaluateHouseholdOwnership, evaluatePropertyOwnership, ownershipInventoryComplete, OWNERSHIP_LAW_URL } from './ownership'
import { contractEvaluationDate, FACT_GROUP_ANCHORS, factGroupForRule, factsAtDate, getEvaluationToday } from './factTimeline'
import { isParentRule, resolveParentSupport } from './parentSupport'
import { accountWinningUsageAtDate } from './accountUsage'
import { applicationHistoryCoveredPeople, applicationHistoryEventComplete } from './applicationHistoryFacts'
export { setEvaluationToday } from './factTimeline'

export type EligibilityStatus = 'possible' | 'mismatch' | 'review' | 'unpublished'
export type ReasonStatus = 'pass' | 'fail' | 'review'
export type ReasonCategory = 'condition' | 'missing_input' | 'past_fact' | 'source_gap' | 'unverified' | 'selection'
export interface EligibilityReason {
  status: ReasonStatus
  label: string
  detail: string
  input?: string
  requirement?: string
  criterionDate?: string | null
  evidenceUrl?: string | null
  evidenceText?: string | null
  category?: ReasonCategory
  profileField?: keyof LocalProfile
  profileMemberId?: string
  ruleId?: string
  historyGroup?: FactChangeGroup
  contractPreview?: boolean
  todayPreview?: boolean
}
export interface EligibilityResult { status: EligibilityStatus; reasons: EligibilityReason[] }
export interface RankResult extends EligibilityResult { rank: 'first' | 'unknown' | 'not_applicable'; label: string }
export type SpecialType = 'newlywed' | 'newborn' | 'first_home' | 'multi_child' | 'elder_parent' | 'institution' | 'young' | 'relocation' | 'other'
export interface SpecialDiagnosis { supplyType: string; type: SpecialType; result: EligibilityResult }

export const ELIGIBILITY_LABEL: Record<EligibilityStatus, string> = {
  possible: '조건상 가능성 있음', mismatch: '명확한 불일치', review: '추가 확인 필요', unpublished: '공고 조건 정리 중',
}
const law27 = 'https://www.law.go.kr/법령/주택공급에관한규칙/제27조'
const law28 = 'https://www.law.go.kr/법령/주택공급에관한규칙/제28조'
const law53 = 'https://www.law.go.kr/법령/주택공급에관한규칙/제53조'
const ACCOUNT_LABEL: Record<string, string> = { comprehensive: '주택청약종합저축', savings: '청약저축', deposit: '청약예금', installment: '청약부금', none: '통장 없음', unknown: '미확인' }
const MARITAL_LABEL: Record<string, string> = { married: '혼인 중', single: '미혼', engaged: '혼인 예정', divorced: '이혼', widowed: '사별', unknown: '미확인' }
const RECOMMENDATION_LABEL: Record<string, string> = { unknown: '미확인', none: '추천 없음', pending: '추천 신청·심사 중', confirmed: '기관 추천 확인' }
const compact = (value: string) => value.replace(/\s+/g, '')
export const isGeneralSupply = (value: string) => /^(일반공급|general|전체공급|일반매각|선착순계약)$/i.test(compact(value))
export function exclusiveArea(price: NoticePrice): number | null {
  const area = price.exclusive_area_sqm ?? (price.area_basis === 'exclusive' ? price.area_sqm : null)
  return typeof area === 'number' && Number.isFinite(area) && area > 0 ? area : null
}

export function numberFrom(value: unknown, integer = false): number | null {
  if (typeof value !== 'number' && typeof value !== 'string') return null
  if (typeof value === 'string' && !/^\d+(?:,\d{3})*(?:\.\d+)?$/.test(value.trim())) return null
  const n = Number(typeof value === 'string' ? value.replaceAll(',', '') : value)
  return Number.isFinite(n) && n >= 0 && (!integer || Number.isSafeInteger(n)) ? n : null
}
export function parseDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day ? date : null
}
export function fullMonths(start: string, end: string): number | null {
  const s = parseDate(start), e = parseDate(end)
  if (!s || !e || s > e) return null
  let months = (e.getUTCFullYear() - s.getUTCFullYear()) * 12 + e.getUTCMonth() - s.getUTCMonth()
  const y = s.getUTCFullYear() + Math.floor((s.getUTCMonth() + months) / 12), m = (s.getUTCMonth() + months) % 12
  const anniversary = new Date(Date.UTC(y, m, Math.min(s.getUTCDate(), new Date(Date.UTC(y, m + 1, 0)).getUTCDate())))
  if (e < anniversary) months -= 1
  return months
}
export function ageAt(birth: string, date: string): number | null {
  const b = parseDate(birth), d = parseDate(date)
  if (!b || !d || b > d) return null
  return d.getUTCFullYear() - b.getUTCFullYear() - (d.getUTCMonth() < b.getUTCMonth() || (d.getUTCMonth() === b.getUTCMonth() && d.getUTCDate() < b.getUTCDate()) ? 1 : 0)
}
function compare(actual: number, expected: number, operator: unknown, fallback: '>=' | '<='): boolean | null {
  switch (operator || fallback) {
    case '>=': return actual >= expected
    case '>': return actual > expected
    case '<=': return actual <= expected
    case '<': return actual < expected
    case '=': case '==': return actual === expected
    default: return null
  }
}
function originalAnnouncementDate(notice: Notice): string | null {
  const metadata = (notice.rules || []).find((r) => r.kind === 'qualification_context' && r.effect === 'metadata' && r.verification === 'official')
  const value = metadata?.value
  const original = value && typeof value === 'object' ? (value as Record<string, unknown>).original_announcement_date : null
  const publicDate = notice.qualification_context?.original_announcement_date
  return typeof original === 'string' && parseDate(original) ? original : typeof publicDate === 'string' && parseDate(publicDate) ? publicDate : null
}
export function criterionDate(rule: NoticeRule, notice: Notice): string | null {
  if (rule.criterion_basis === 'application_date') return getEvaluationToday()
  if (rule.criterion_basis === 'contract_date') return contractEvaluationDate(notice)
  const specified = rule.criterion_date || rule.reference_date
  if (typeof specified === 'string') return parseDate(specified) ? specified : null
  if (rule.criterion_basis === 'original_announcement') return originalAnnouncementDate(notice)
  if (rule.criterion_basis && !['announcement', 'announcement_date'].includes(String(rule.criterion_basis))) return null
  if (notice.application_method && notice.application_method !== 'apt_ranked' && notice.application_method !== 'unknown') {
    const current = notice.qualification_context?.application_criterion_date || notice.application_method_evidence?.criterion_date
    return typeof current === 'string' && parseDate(current) ? current : notice.announcement_date && parseDate(notice.announcement_date) ? notice.announcement_date : null
  }
  return originalAnnouncementDate(notice) || (notice.announcement_date && parseDate(notice.announcement_date) ? notice.announcement_date : null)
}

function profileForResidenceDate(profile: LocalProfile, date: string | null): LocalProfile {
  const snapshot = date && profile.residenceHistory?.find((entry) => entry.criterionDate === date)
  if (!snapshot) return profile
  const identity = resolveLegacyRegion(snapshot.region, snapshot.district)
  return { ...profile, ...snapshot, regionCode: identity.regionCode, districtCode: identity.districtCode, regionNeedsReview: identity.needsReview }
}
function residenceScopeIsDistrict(rule: NoticeRule): boolean {
  // A province code can accompany a more specific municipality name.
  return scopeIsDistrict(rule) || scopeIsDistrict({ region_name: rule.region_name })
}
function residenceParentCity(rule: NoticeRule, profile: LocalProfile): string | null {
  const homeCode = profile.districtCode || resolveLegacyRegion(profile.region, profile.district).districtCode
  const parent = parentCityCode(homeCode)
  return parent && matchesRegionScope({ ...profile, district: districtName(parent), districtCode: parent }, rule) === true ? parent : null
}
export function residenceStartDate(rule: NoticeRule, profile: LocalProfile): string {
  if (!residenceScopeIsDistrict(rule)) return profile.movedInDate
  return residenceParentCity(rule, profile) ? profile.cityMovedInDate : profile.districtMovedInDate
}
function residenceCutoffReview(rule: NoticeRule, profile: LocalProfile, notice: Notice, requirement?: string): EligibilityReason | null {
  const date = criterionDate(rule, notice)
  if (!date) return unsupported(rule, notice, '거주지역을 비교할 공식 기준일이 필요합니다.', '공고 기준일 거주지역')
  const starts = [{ date: profile.movedInDate, label: '시도' }]
  let field: 'movedInDate' | 'cityMovedInDate' | 'districtMovedInDate' = 'movedInDate'
  let establishedExclusion = false
  if (residenceScopeIsDistrict(rule)) {
    // A stable province outside the scope already proves exclusion; moving
    // within that province cannot change the result for another province.
    const provinceMatch = matchesRegionScope({ ...profile, district: '', districtCode: '' }, rule, date)
    const provinceStart = parseDate(profile.movedInDate)
    establishedExclusion = provinceMatch === false && !!provinceStart && profile.movedInDate <= date
    field = residenceParentCity(rule, profile) ? 'cityMovedInDate' : 'districtMovedInDate'
    if (!establishedExclusion) {
      const homeCode = profile.districtCode || resolveLegacyRegion(profile.region, profile.district).districtCode
      const parent = parentCityCode(homeCode)
      const cityStart = parseDate(profile.cityMovedInDate)
      const stableOtherCity = parent && cityStart && profile.cityMovedInDate <= date &&
        matchesRegionScope({ ...profile, district: districtName(parent), districtCode: parent }, rule, date) === false
      establishedExclusion = !!stableOtherCity
      if (parent) starts.push({ date: profile.cityMovedInDate, label: `${districtName(parent)} 전체` })
      if (!stableOtherCity) {
        const start = residenceStartDate(rule, profile)
        starts.push({ date: start, label: parent && residenceParentCity(rule, profile) ? `${districtName(parent)} 전체` : '시·군·구' })
      }
    }
  }
  const changed = starts.find((start) => parseDate(start.date) && start.date > date)
  if (!changed) {
    if (establishedExclusion || parseDate(profile[field])) return null
    const label = field === 'movedInDate' ? '시도' : field === 'cityMovedInDate' ? '상위 시 전체' : '시·군·구'
    return missingInput(rule, notice, '공고 기준일 거주지역', `현재 ${label} 연속 거주 시작일을 입력하면 공고 기준일 ${date}의 거주지역을 공식 신청 범위${requirement ? ` ${requirement}` : ''}와 비교할 수 있습니다.`, requirement, field)
  }
  return { ...reason(rule, notice, 'review', '공고 기준일 거주지역', `현재 ${changed.label} 연속 거주 시작일 ${changed.date}은 공고 기준일 ${date} 이후입니다. 저장된 당시 주소가 없어 과거 거주지역은 판정을 보류합니다.`, `${profile.region} ${profile.district} · ${changed.date}부터`, requirement), category: 'past_fact' }
}
function reason(rule: NoticeRule, notice: Notice, status: ReasonStatus, label: string, detail: string, input?: string, requirement?: string): EligibilityReason {
  return { status, label, detail, input, requirement, category: 'condition', ruleId: rule.id, criterionDate: criterionDate(rule, notice), evidenceUrl: rule.evidence_url || notice.official_url, evidenceText: rule.evidence_text || rule.text, ...(rule.criterion_basis === 'contract_date' ? { contractPreview: true } : {}), ...(rule.criterion_basis === 'application_date' && rule.evaluation_mode === 'today_precheck' ? { todayPreview: true } : {}) }
}
function result(reasons: EligibilityReason[]): EligibilityResult {
  return { status: reasons.some((r) => r.status === 'fail') ? 'mismatch' : reasons.some((r) => r.status === 'review') ? 'review' : reasons.length ? 'possible' : 'unpublished', reasons }
}
function unsupported(rule: NoticeRule, notice: Notice, detail: string, label = '조건 확인'): EligibilityReason {
  return { ...reason(rule, notice, 'review', label, detail), category: 'source_gap' }
}
export function profileFieldForRule(rule: NoticeRule, notice: Notice): keyof LocalProfile | undefined {
  const fields: Record<string, keyof LocalProfile> = {
    homeless: 'householdMembers', household_head: 'isHouseholdHead', applying_restriction: 'restrictedFromApplying',
    previous_winning: 'previousWinning', special_winning: 'specialWinning', employed: 'employed', dual_income: 'dualIncome',
    parent_same_register: 'parentSameRegister', parent_owns_home: 'parentOwnsHome', parent_spouse_owns_home: 'parentSpouseOwnsHome', relocated_worker: 'relocatedWorker', pregnant: 'pregnant',
    account_type: 'accountType', deposit_min_krw: 'privateDepositKrw', recognized_payments_min: 'nationalRecognizedPayments',
    account_unused_after_winning: 'currentAccountUsedForWinning',
    recognized_amount_min_krw: 'nationalRecognizedAmountKrw', household_min: 'householdMembers', tax_years_min: 'taxYears',
    marital_status: 'maritalStatus', marriage_months_max: 'marriageDate', age_min: 'dateOfBirth', age_max: 'dateOfBirth',
    parent_age_min: 'parentDateOfBirth', parent_support_months_min: 'parentSupportSince', children_min: 'hasChildren',
    newborn_children_min: 'hasChildren', never_owned_home: 'applicantPreviouslyOwnedHome', recommendation: 'recommendationStatus',
    private_rank_months: 'privateRankBaseDate', national_rank_months: 'nationalRankBaseDate',
    residence_region: 'regionCode', residence_area: 'regionCode', region: 'regionCode',
    citizenship: 'citizenship', overseas_residence: 'overseasContinuousDays', application_restriction: 'applicationRestrictionFacts', ownership_count_max: 'ownershipFacts', military_service_years: 'militaryServiceYears', military_currently_serving: 'militaryCurrentlyServing',
    first_home_family: 'householdMembers', first_home_tax_activity: 'employed', monthly_income_max_krw: 'monthlyIncomeKrw', real_estate_max_krw: 'realEstateKrw', real_estate_assets_max_krw: 'realEstateKrw',
    provider_employee_restriction: 'providerEmployeeOrRelatedFamily', domestic_residence: 'currentlyDomesticResident', income_tax_paid_within_past_year: 'incomeTaxPaidWithinPastYear',
    shinhee_income: 'monthlyIncomeKrw', shinhee_assets: 'officialNetAssetsKrw', planned_marriage: 'plannedMarriage', single_parent_family: 'raisesChildWithoutSpouse',
  }
  if (rule.kind === 'application_restriction' && ['prior_project_winner', 'prior_project_contract'].includes(String(rule.restriction))) return 'applicationHistoryEvents'
  if (rule.kind === 'original_project_contract_ownership') return 'applicationHistoryEvents'
  if (['previous_winning', 'special_winning'].includes(rule.kind)) return 'applicationHistoryEvents'
  if (rule.kind === 'subscription_months') return notice.housing_kind === 'private' ? 'privateRankBaseDate' : 'nationalRankBaseDate'
  if (rule.kind === 'residence_months') return residenceScopeIsDistrict(rule) ? 'districtMovedInDate' : 'movedInDate'
  if (rule.kind === 'income_max_krw') return rule.period === 'annual' ? 'annualIncomeKrw' : rule.period === 'monthly' ? 'monthlyIncomeKrw' : undefined
  if (rule.kind === 'assets_max_krw') return rule.asset_basis === 'real_estate' ? 'realEstateKrw' : ['automobile', 'vehicle'].includes(String(rule.asset_basis)) ? 'vehicleKrw' : !rule.asset_basis || rule.asset_basis === 'total_household' ? 'assetsKrw' : undefined
  return fields[rule.kind]
}
function missingInput(rule: NoticeRule, notice: Notice, label: string, detail: string, requirement?: string, field = profileFieldForRule(rule, notice)): EligibilityReason {
  if (field === 'householdSnapshotDate' && criterionDate(rule, notice) && criterionDate(rule, notice)! < getEvaluationToday()) return { ...reason(rule, notice, 'review', '가족 구성 변경일', detail, undefined, requirement), category: 'past_fact', profileField: field, historyGroup: 'household' }
  return { ...reason(rule, notice, 'review', label, detail, undefined, requirement), category: 'missing_input', profileField: field }
}
const HISTORY_LABELS: Record<FactChangeGroup, string> = {
  household: '가족 구성 변경일', household_head: '세대주 상태 변경일', domestic_residence: '국내 거주 상태 변경일', restrictions: '청약 제한 상태 변경일', overseas: '해외 체류 상태 변경일', military: '군 복무 상태 변경일', income_tax: '소득세 납부 사실 변경일', income: '소득 변경일', assets: '자산 변경일', bank_private: '민영 통장 잔액 변경일', bank_national: '국민 통장 납입 변경일', bank_account: '현재 청약통장 당첨 사용 이력 변경일', citizenship: '국적 변경일', employment: '근로 상태 변경일', parent_support: '부양 시작일', marital: '혼인 상태 변경일', children: '자녀 구성 변경일', pregnancy: '임신 상태 변경일', points: '청약가점 사실 변경일', provider_employee: '공급기관 임직원·관련 가족 상태 변경일', ownership: '주택 보유 상태 변경일',
}
function pastFact(rule: NoticeRule, notice: Notice, group: FactChangeGroup, detail?: string): EligibilityReason {
  const date = criterionDate(rule, notice), label = HISTORY_LABELS[group]
  return { ...reason(rule, notice, 'review', label, detail || `${date} 당시 사실을 확인할 저장된 이력이 없습니다. ${label} 또는 저장된 당시 사실을 입력하면 같은 기준일의 다른 공고에도 재사용합니다.`, undefined, `${date} 당시 사실`), category: 'past_fact', profileField: FACT_GROUP_ANCHORS[group], historyGroup: group }
}
function legacyFactObservation(profile: LocalProfile, group: Parameters<typeof factsAtDate>[1]) {
  const observations = {
    household: { date: profile.householdSnapshotDate, confirmations: profile.householdHistoryConfirmations, unchangedSince: profile.householdCompositionUnchanged === true },
    overseas: { date: profile.overseasFactsAsOfDate, confirmations: profile.overseasFactsHistoryConfirmations },
    domestic_residence: { date: profile.domesticResidenceFactsAsOfDate || '', confirmations: profile.domesticResidenceHistoryConfirmations },
    military: { date: profile.militaryFactsAsOfDate || '', confirmations: profile.militaryFactsHistoryConfirmations },
    income_tax: { date: profile.incomeTaxFactsAsOfDate || '', confirmations: profile.incomeTaxFactsHistoryConfirmations },
    bank_private: { date: profile.privateDepositAsOfDate, unchangedSince: profile.privateDepositMaintained === true }, bank_national: { date: profile.nationalPaymentsAsOfDate },
    ownership: { date: profile.householdSnapshotDate, confirmations: profile.householdHistoryConfirmations },
  }
  return observations[group as keyof typeof observations]
}
function commonApplicationHistory(rule: NoticeRule, profile: LocalProfile, notice: Notice, scope = 'household', project?: string): EligibilityReason | null {
  const coveredPeople = applicationHistoryCoveredPeople(profile)
  if (profile.applicationHistoryPresence == null && !profile.applicationHistoryEvents?.length && !coveredPeople.size) return null
  const date = criterionDate(rule, notice)
  const label = project ? `${project} 사업 ${rule.restriction === 'prior_project_contract' ? '계약' : '당첨·예비당첨'} 이력` : rule.kind === 'special_winning' ? '특별공급 당첨 이력' : '당첨 이력'
  if (!date) return unsupported(rule, notice, '사건 날짜를 비교할 공식 기준일이 확인되지 않았습니다.', label)
  let people = ['applicant']
  if (scope !== 'applicant') {
    const household = deriveHousehold(profile, date)
    if (!household.complete) return missingInput(rule, notice, '당첨·계약 확인 대상 가족', household.reviewDetail || '가족 구성을 확인하세요.', undefined, household.profileField)
    people = household.members.filter((person) => person.included && (scope !== 'applicant_spouse' || ['applicant', 'spouse'].includes(person.id))).map((person) => person.id)
  }
  const contract = rule.restriction === 'prior_project_contract'
  const events = (profile.applicationHistoryEvents || []).filter((event) => applicationHistoryEventComplete(event) && people.includes(event.personId) && (!project || event.projectId === project) && event.eventDate <= date &&
    (contract ? ['contract', 'additional_resident_contract'].includes(event.eventKind) : project ? ['winning', 'reserve_winning'].includes(event.eventKind) : event.eventKind === 'winning'))
  const window = numberFrom(rule.window_months ?? rule.months, true)
  const applicable = events.filter((event) => {
    if (window === null) return true
    const won = parseDate(event.eventDate)!, cutoff = parseDate(date)!, totalMonth = won.getUTCMonth() + window
    const year = won.getUTCFullYear() + Math.floor(totalMonth / 12), month = totalMonth % 12
    return cutoff <= new Date(Date.UTC(year, month, Math.min(won.getUTCDate(), new Date(Date.UTC(year, month + 1, 0)).getUTCDate())))
  })
  const matched = rule.kind === 'special_winning' ? applicable.filter((event) => event.specialSupply === true) : applicable
  if (matched.length) return { ...factualBoolean(rule, notice, true, label), detail: matched.map((event) => `${event.personId} · ${event.projectId} · ${event.eventDate} ${event.eventKind}`).join(' / ') }
  const covered = people.every((person) => coveredPeople.has(person))
  if (!covered || rule.kind === 'special_winning' && applicable.some((event) => event.specialSupply == null)) {
    const rows = profile.applicationHistoryEvents || []
    const unansweredPerson = !rows.some((event) => !event.personId) && people.find((person) => !coveredPeople.has(person) && !rows.some((event) => event.personId === person))
    return missingInput(rule, notice, label, '이력이 있는 확인 대상은 사업번호·사건 종류·날짜를 입력하고, 이력이 없는 사람은 해당 사람의 이력 없음 사실을 입력하세요. 다른 사업의 이력은 이 사업의 이력으로 적용하지 않습니다.', '확인 대상의 실제 당첨·계약 사건 또는 이력 없음', unansweredPerson ? 'applicationHistoryAbsencePeople' : 'applicationHistoryEvents')
  }
  return { ...factualBoolean(rule, notice, false, label), detail: `확인 대상 ${people.length}명의 공통 이력에서 ${date}까지${project ? ` 사업 ${project}의` : ''} 해당 사건이 없습니다.` }
}
function originalProjectContractOwnership(rule: NoticeRule, profile: LocalProfile, notice: Notice): EligibilityReason {
  const date = criterionDate(rule, notice), original = typeof rule.original_announcement_date === 'string' ? rule.original_announcement_date : null
  const project = typeof rule.project_id === 'string' && /^(?:\d{10}|LH-[A-Z0-9-]{1,64})$/.test(rule.project_id) ? rule.project_id : null
  const label = '최초 공고 당첨 후 계약에 따른 주택 소유'
  if (!date || !original || !parseDate(original) || !project || rule.scope !== 'applicant') return unsupported(rule, notice, '최초 공고일·사업번호·계약에 따른 소유 판정 범위를 확인해야 합니다.', label)
  const events = (profile.applicationHistoryEvents || []).filter((event) => event.personId === 'applicant' && event.projectId === project && parseDate(event.eventDate) && original <= event.eventDate && event.eventDate <= date && event.eventDate <= getEvaluationToday())
  const winners = events.filter((event) => event.eventKind === 'winning')
  const contracts = events.filter((event) => event.eventKind === 'contract' && winners.some((winner) => winner.eventDate <= event.eventDate))
  if (!contracts.length) {
    if (applicationHistoryCoveredPeople(profile).has('applicant')) return reason(rule, notice, 'pass', label, `사업 ${project}의 공통 이력에서 최초 당첨 후 계약은 없습니다. 최초 당첨 또는 부적격 판정만으로 이 경로를 제외하지 않습니다.`, winners.length ? '최초 당첨 · 계약 없음' : '최초 당첨 후 계약 없음', '최초 당첨 후 계약으로 인한 주택 소유 아님')
    return missingInput(rule, notice, '최초 당첨·계약 사건', `최초 공고 ${original}의 사업 ${project}에서 본인이 실제 당첨 후 계약했는지 공통 사건 이력을 확인하세요. 당첨만 있거나 부적격 이력만 있다는 이유로 제외하지 않습니다.`, '본인의 사업별 날짜가 있는 당첨·계약 이력', 'applicationHistoryEvents')
  }
  const dates = contracts.map((event) => event.eventDate)
  const matched = profile.ownershipFacts.filter((fact) => fact.projectId === project && (fact.ownerMemberId || fact.ownerRelation) === 'applicant' && dates.includes(fact.acquiredDate) && fact.propertyKind !== 'officetel')
  if (!matched.length) return missingInput(rule, notice, '최초 계약 주택의 취득·처분', `사업 ${project}에서 최초 당첨 후 ${dates.join(' · ')}에 계약했습니다. 계약으로 취득한 주택·분양권을 이 사업번호에 연결하고 실제 취득·처분일을 공통 주택 이력에 입력하면 ${date}의 소유 여부와 공식 예외를 비교합니다. 같은 날 취득한 다른 주택을 대신 적용하지 않습니다.`, '해당 사업 계약 주택·권리의 실제 취득·처분 이력', 'ownershipFacts')
  const context = { criterionDate: date, assessmentDate: getEvaluationToday(), supplyType: rule.supply_type || undefined, publicRental: notice.category === 'public_rental' }
  const active = profile.ownershipFacts.filter((fact) => fact.propertyKind !== 'officetel' && parseDate(fact.acquiredDate) && fact.acquiredDate <= date && !(parseDate(fact.disposedDate) && fact.disposedDate <= date))
  const count = active.length > 1 && active.every((fact) => fact.ownedShare === true) ? null : active.length
  const evaluated = matched.map((fact) => evaluatePropertyOwnership(fact, context, count))
  const owner = evaluated.find((entry) => entry.counted === true)
  if (owner) return reason(rule, notice, 'fail', label, `최초 당첨 후 계약으로 취득한 주택·권리를 ${date}에 소유한 것으로 계산합니다. ${owner.detail}`, `${dates.join(' · ')} 계약 · 주택·권리 보유`, '최초 당첨 후 계약으로 인한 주택 소유 아님')
  const pending = evaluated.find((entry) => entry.counted === null)
  if (pending) return missingInput(rule, notice, '최초 계약 주택의 소유 예외', pending.detail, '최초 계약 주택의 처분 또는 공식 소유 예외', 'ownershipFacts')
  return reason(rule, notice, 'pass', label, `최초 당첨 후 계약 이력은 있으나 ${date}의 소유 판정에서는 ${evaluated.map((entry) => entry.detail).join(' / ')}`, '처분 또는 공식 소유 예외', '최초 당첨 후 계약으로 인한 주택 소유 아님')
}
function factualSnapshotReview(rule: NoticeRule, notice: Notice, profile: LocalProfile, snapshot: string, confirmations: { criterionDate: string; unchanged: boolean | null }[], field: keyof LocalProfile, label: string): EligibilityReason | null {
  const cutoff = criterionDate(rule, notice)
  if (!cutoff) return unsupported(rule, notice, `${label}을 비교할 공식 기준일이 필요합니다.`, label)
  const groups: Partial<Record<keyof LocalProfile, Parameters<typeof factsAtDate>[1]>> = { overseasFactsAsOfDate: 'overseas', domesticResidenceFactsAsOfDate: 'domestic_residence', militaryFactsAsOfDate: 'military', incomeTaxFactsAsOfDate: 'income_tax', applicationRestrictionFacts: 'restrictions' }
  const group = groups[field] || factGroupForRule(rule)
  if (group && factsAtDate(profile, group, cutoff, { date: snapshot, confirmations }).known) return null
  if (!group && (snapshot === cutoff || confirmations.find((entry) => entry.criterionDate === cutoff)?.unchanged === true)) return null
  if (cutoff >= getEvaluationToday()) return null
  return group ? pastFact(rule, notice, group) : { ...missingInput(rule, notice, label, `현재 사실을 ${cutoff}에 적용할 저장된 당시 사실이 없습니다.`, `${cutoff} 당시 사실`, field), category: 'past_fact' }
}
function factualBoolean(rule: NoticeRule, notice: Notice, actual: boolean | null, label: string): EligibilityReason {
  if (typeof rule.value !== 'boolean') return unsupported(rule, notice, `${label}의 공고 요구값을 아직 정리하지 못했습니다.`, label)
  if (typeof actual !== 'boolean') return missingInput(rule, notice, label, `${label} 질문에 답하면 공고의 요구값과 비교할 수 있습니다.`, rule.value ? '예' : '아니오')
  return reason(rule, notice, actual === rule.value ? 'pass' : 'fail', label, `내 입력 ${actual ? '예' : '아니오'} · 공고 요구 ${rule.value ? '예' : '아니오'}`, actual ? '예' : '아니오', rule.value ? '예' : '아니오')
}
function numeric(rule: NoticeRule, notice: Notice, actual: number | null, label: string, unit: string, fallback: '>=' | '<=' = '>='): EligibilityReason {
  const required = numberFrom(rule.value)
  if (required === null) return unsupported(rule, notice, `${label}의 공식 요구값을 아직 정리하지 못했습니다.`, label)
  if (actual === null) {
    const requirement = `${rule.operator || fallback} ${required.toLocaleString('ko-KR')}${unit}`
    if (!criterionDate(rule, notice) && /months|age_|children/.test(rule.kind)) return { ...unsupported(rule, notice, `${label}을 비교할 공식 기준일이 필요합니다.`, label), requirement }
    return missingInput(rule, notice, label, `${label} 정보를 입력하면 ${requirement} 조건과 비교할 수 있습니다.`, requirement)
  }
  const matches = compare(actual, required, rule.operator, fallback)
  if (matches === null) return unsupported(rule, notice, '지원되지 않는 비교 조건입니다.', label)
  const input = `${actual.toLocaleString('ko-KR')}${unit}`, requirement = `${rule.operator || fallback} ${required.toLocaleString('ko-KR')}${unit}`
  return reason(rule, notice, matches ? 'pass' : 'fail', label, `내 입력 ${input} · 공고 요구 ${requirement}`, input, requirement)
}
export function householdHomeless(profile: LocalProfile, notice?: Notice, supplyType?: string) {
  return evaluateHouseholdOwnership(profile, { criterionDate: notice ? criterionDate({ kind: 'homeless' }, notice) : null, supplyType, publicRental: notice?.category === 'public_rental' })
}
function conditionChildren(rule: NoticeRule): NoticeRule[] {
  return Array.isArray(rule.conditions) ? rule.conditions.filter((child): child is NoticeRule => !!child && typeof child === 'object' && typeof child.kind === 'string') : []
}
export function inheritedCondition(parent: NoticeRule, child: NoticeRule): NoticeRule {
  const inherited: Partial<NoticeRule> = {}
  for (const key of ['verification', 'evidence_url', 'evidence_text', 'document_hash', 'criterion_date', 'reference_date', 'criterion_basis', 'evaluation_mode', 'requires_maintained_until_application', 'supply_type', 'supply_types', 'unit_type', 'unit_types', 'housing_kind']) if (parent[key] !== undefined && child[key] === undefined) inherited[key] = parent[key]
  return { ...inherited, ...child }
}
function exceptionScopeMatches(parent: NoticeRule, child: NoticeRule, unitType?: string): boolean {
  if (unitType && !scopedRule({ ...child, supply_type: undefined, supply_types: undefined }, unitType)) return false
  if (parent.supply_type && !scopedRule({ ...child, unit_type: undefined, unit_types: undefined }, undefined, parent.supply_type)) return false
  for (const [singular, plural] of [['supply_type', 'supply_types'], ['unit_type', 'unit_types']] as const) {
    const scopes = (rule: NoticeRule) => {
      const one = typeof rule[singular] === 'string' ? [compact(rule[singular] as string)] : null
      const many = Array.isArray(rule[plural]) ? (rule[plural] as unknown[]).filter((item): item is string => typeof item === 'string').map(compact) : null
      return one && many ? one.filter((item) => many.includes(item)) : one || many
    }
    const a = scopes(parent), b = scopes(child)
    if (a && b && !a.some((item) => b.includes(item))) return false
  }
  return true
}
function marriageClauseApplicability(rule: NoticeRule, profile: LocalProfile, notice: Notice): boolean | null {
  const date = criterionDate(rule, notice), state = factsAtDate(profile, 'marital', date)
  if (!state.known || state.profile.maritalStatus === 'unknown') return null
  if (state.profile.maritalStatus === 'married') return true
  // Conflicting spouse facts are unresolved facts, never an exclusion.
  return state.profile.hasSpouse === true ? null : false
}
function birthClauseApplicability(rule: NoticeRule, profile: LocalProfile, notice: Notice): boolean | null {
  if (rule.supply_type && !['multi_child', 'newlywed', 'elder_parent', 'newborn'].includes(specialType(rule.supply_type))) return false
  const date = criterionDate(rule, notice)
  if (!date) return null
  const pregnancy = factsAtDate(profile, 'pregnancy', date)
  if (pregnancy.known && pregnancy.profile.pregnant === true) return true
  const childState = factsAtDate(profile, 'children', date), children = childState.profile.children
  if (!childState.known || childState.profile.hasChildren == null) return null
  if (childState.profile.hasChildren === false && (children.length || profile.householdMembers.some((member) => ['applicant_child', 'spouse_child'].includes(member.relation)))) return null
  if (childState.profile.hasChildren === true && !children.length) return null
  if (!pregnancy.known || pregnancy.profile.pregnant == null) return null
  if (childState.profile.hasChildren === false) return false
  // Use only the source's birth-bound date, not an unrelated date elsewhere
  // in a long excerpt. Older children cannot use a recent-birth waiver.
  const bound = String(rule.evidence_text || '').match(/[‘’'\"]?(\d{4}|\d{2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*\.?\s*이후\s*출생/)
  const structured = rule.birth_since || rule.child_relaxation_since
  const cutoff = typeof structured === 'string' && parseDate(structured) ? structured : bound ? `${bound[1].length === 2 ? `${Number(bound[1]) < 70 ? '20' : '19'}${bound[1]}` : bound[1]}-${bound[2].padStart(2, '0')}-${bound[3].padStart(2, '0')}` : null
  if (!cutoff || !parseDate(cutoff)) return null
  let unknown = false
  for (const child of children) {
    if (!parseDate(child.dateOfBirth) || child.dateOfBirth > getEvaluationToday()) { unknown = true; continue }
    if (child.dateOfBirth < cutoff || child.dateOfBirth > date) continue
    if (child.adopted === false) return true
    if (child.adopted == null || !parseDate(child.adoptionDate || '')) { unknown = true; continue }
    if (child.adoptionDate! <= date) return true
  }
  return unknown ? null : false
}
/** False only when dated facts exclude every recognized route in this clause. */
export function officialClauseApplicability(rule: NoticeRule, profile: LocalProfile, notice: Notice): boolean | null {
  // The evidence excerpt may include many unrelated provisions. Classify
  // only this exact clause's label/text, retaining unsupported alternatives.
  const clause = compact(`${typeof rule.label === 'string' ? rule.label : ''} ${rule.text || ''}`)
  if (/제53조|과거주택소유/.test(clause)) return null
  if (Array.isArray(rule.allowed_recommendation_reasons)) {
    const allowed = rule.allowed_recommendation_reasons.filter((value): value is string => typeof value === 'string')
    if (!allowed.length || !profile.recommendationReason || ['unknown', '기타'].includes(profile.recommendationReason)) return null
    return allowed.includes(profile.recommendationReason)
  }
  if (/동일배우자.*재혼|재혼.*혼인기간.*합산/.test(clause)) {
    if (/예정세대|사전청약|예비신혼/.test(clause)) return null
    return marriageClauseApplicability(rule, profile, notice)
  }
  const alternatives: (boolean | null)[] = []
  if (/출산특례/.test(clause)) alternatives.push(birthClauseApplicability(rule, profile, notice))
  if (/배우자혼인전.*당첨|혼인특례/.test(clause)) alternatives.push(marriageClauseApplicability(rule, profile, notice))
  if (!alternatives.length || /통장면제|세대소득면제|제36조/.test(clause)) return null
  return alternatives.includes(true) ? true : alternatives.every((value) => value === false) ? false : null
}
function allKinds(rules: NoticeRule[]): string[] { return rules.flatMap((r) => [r.kind, ...allKinds(conditionChildren(r))]) }
function scopeProblem(rule: NoticeRule, notice: Notice): string | null {
  if (rule.housing_kind && rule.housing_kind !== notice.housing_kind) return '공고의 민영·국민주택 구분과 조건의 적용 범위를 확인해야 합니다.'
  const d = criterionDate(rule, notice)
  if ((rule.valid_from || rule.valid_until || rule.effective_from || rule.effective_to) && !d) return '법령 시행기간과 기준일을 확인해야 합니다.'
  const from = rule.valid_from || rule.effective_from, until = rule.valid_until || rule.effective_to
  if ((typeof from === 'string' && d && d < from) || (typeof until === 'string' && d && d > until)) return '이 조건의 시행기간 밖 공고입니다. 적용 법령과 경과조치를 확인해야 합니다.'
  if (typeof rule.public_housing === 'boolean' && notice.qualification_context?.public_housing !== rule.public_housing) return '공공주택 특별법 적용 여부가 확인되지 않았거나 조건 범위가 다릅니다.'
  return null
}
/** Exact notices may require unmarried children on the applicant's own register. */
function strictFirstHomeFamily(rule: NoticeRule, profile: LocalProfile, notice: Notice, date: string, unitType?: string): EligibilityReason {
  const pregnancy = rule.include_pregnancy === true ? factsAtDate(profile, 'pregnancy', date) : null
  if (pregnancy?.known && pregnancy.profile.pregnant === true) return reason(rule, notice, 'pass', '생애최초 가족 조건', '공고 기준일의 임신 사실이 태아를 인정하는 가족 조건을 충족합니다.', '임신 중', '공고가 인정하는 태아')
  const pregnancyGap = pregnancy && !pregnancy.known && profile.pregnant != null
    ? pastFact(rule, notice, 'pregnancy') : pregnancy && pregnancy.profile.pregnant == null
      ? missingInput(rule, notice, '생애최초 임신 조건', '태아를 인정하는 공고입니다. 임신 사실이 다른 가족 경로를 충족하는지 입력하세요.', '공고가 인정하는 태아', 'pregnant') : null
  const household = deriveHousehold(profile, date)
  if (!household.complete) return missingInput(rule, notice, '생애최초 가족·등본 조건', household.reviewDetail || '가족 관계와 등본 위치를 입력하세요.', '미혼 자녀의 동일 등본 또는 1인 가구 분기', household.profileField)
  const familyFacts = factsAtDate(profile, 'household', date, legacyFactObservation(profile, 'household')).profile
  const children = familyFacts.householdMembers.filter((member) => member.relation === 'applicant_child')
  const points = factsAtDate(profile, 'points', date)
  const ascendant = familyFacts.householdMembers.some((member) => ['applicant_parent', 'applicant_grandparent'].includes(member.relation) && (['applicant', 'both'].includes(member.register) || member.register === 'spouse' && familyFacts.spouseSameRegister === true))
  const maximum = numberFrom(rule.solo_max_area_sqm), prices = (notice.prices || []).filter((price) => !unitType || price.unit_type === unitType)
  // A child on a separate register can never satisfy the child route. Its
  // marital fact only matters if a childless one-person route could succeed.
  const noChildRoutePossible = (rule.non_solo_requires_ascendant === true ? ascendant : household.legalCount! > 1) || maximum === null || !prices.length || prices.some((price) => exclusiveArea(price) === null || exclusiveArea(price)! <= maximum)
  let childGap: EligibilityReason | null = null, unmarriedOutsideRegister = false
  for (const child of children) {
    const sameRegister = ['applicant', 'both'].includes(child.register) || child.register === 'spouse' && familyFacts.spouseSameRegister === true
    if (rule.unmarried_applicant_child_same_register === true && !sameRegister && !noChildRoutePossible) continue
    if (!parseDate(child.dateOfBirth)) { childGap ||= { ...missingInput(rule, notice, '생애최초 자녀 생년월일', '가족 목록에 있는 자녀의 생년월일을 입력하면 공고 기준일의 자녀 사실을 비교합니다.', '공고 기준일에 존재하는 자녀', 'householdMembers'), profileMemberId: child.id }; continue }
    if (child.dateOfBirth > date) continue
    const unmarried = points.profile.pointsFamily[child.id]?.unmarried
    if (!points.known && unmarried != null) { childGap ||= { ...pastFact(rule, notice, 'points', `${date} 당시 이 자녀의 미혼 여부를 확인할 저장된 가족 이력이 없습니다. 가족 혼인 사실의 기존 변경일을 재사용합니다.`), profileMemberId: child.id }; continue }
    if (unmarried == null) { childGap ||= { ...missingInput(rule, notice, '생애최초 자녀 혼인 여부', '가족 목록의 이 자녀가 미혼인지 가족 혼인 입력에 한 번 입력하세요.', '미혼인 자녀', 'pointsFamily'), profileMemberId: child.id }; continue }
    if (!unmarried) continue
    if (rule.unmarried_applicant_child_same_register !== true || sameRegister) return reason(rule, notice, 'pass', '생애최초 가족 조건', '선택한 가족 목록의 미혼 자녀가 본인과 같은 등본에 있습니다. 이 가족의 혼인·등본 사실을 재사용했습니다.', '미혼 자녀 · 본인 동일 등본', '공고가 정한 미혼 자녀 조건')
    unmarriedOutsideRegister = true
  }
  if (!children.length) {
    const childFacts = factsAtDate(profile, 'children', date)
    if (!childFacts.known && profile.hasChildren != null) childGap ||= pastFact(rule, notice, 'children')
    else if (childFacts.profile.hasChildren !== false || childFacts.profile.children.length > 0) childGap ||= missingInput(rule, notice, '생애최초 자녀·등본 연결', '자녀가 있다면 가족 목록에 자녀를 연결해 미혼 여부와 본인 등본 위치를 비교하세요. 생년월일만 적힌 자녀 목록으로 혼인·등본 조건을 추정하지 않습니다.', '자녀별 혼인 상태·본인 등본 위치', 'householdMembers')
  }
  if (childGap) return childGap
  if (unmarriedOutsideRegister) return pregnancyGap || reason(rule, notice, 'fail', '생애최초 미혼 자녀 등본 조건', '미혼 자녀가 본인과 같은 등본에 있지 않아 이 공고의 자녀 경로에 해당하지 않습니다. 미혼 자녀가 있는데 없는 1인 가구로 바꾸어 비교하지 않습니다.', '미혼 자녀 · 본인 별도 등본', '본인과 같은 등본의 미혼 자녀')
  if (rule.non_solo_requires_ascendant === true ? ascendant : household.legalCount! > 1) return reason(rule, notice, 'pass', '생애최초 비단독 1인 가구 조건', '혼인·미혼 자녀가 없고 직계존속과 본인의 같은 등본에 있는 비단독 1인 가구 조건을 충족합니다.', '직계존속 · 본인 동일 등본', '공고가 정한 비단독 1인 가구')
  if (maximum === null || !prices.length || prices.some((price) => exclusiveArea(price) === null)) return unsupported(rule, notice, '단독 1인 가구의 공식 신청 면적과 주택형 전용면적을 확인해야 합니다.', '생애최초 단독 1인 가구 면적')
  const matches = prices.map((price) => exclusiveArea(price)! <= maximum)
  if (matches.some(Boolean) && matches.some((match) => !match)) return { ...unsupported(rule, notice, '단독 1인 가구가 신청 가능한 면적과 초과 면적이 함께 있습니다. 주택형별 조건을 확인하세요.', '생애최초 단독 1인 가구 면적'), category: 'selection' }
  if (!matches.every(Boolean) && pregnancyGap) return pregnancyGap
  return reason(rule, notice, matches.every(Boolean) ? 'pass' : 'fail', '생애최초 단독 1인 가구 면적', `직계존속과 같은 등본의 비단독 가구 요건이 충족되지 않아 전용 ${maximum}㎡ 이하의 1인 가구 조건을 비교했습니다.`, '혼인·미혼 자녀 없는 단독 1인 가구', `전용 ${maximum}㎡ 이하`)
}
export function evaluateRule(rule: NoticeRule, profile: LocalProfile, notice: Notice, unitType?: string): EligibilityReason {
  if (rule.verification !== 'official') return { ...unsupported(rule, notice, '문서에서 추출한 내용입니다. 원문과 적용 범위를 검토하기 전에는 자격 판정에 사용하지 않습니다.', '자동 추출 참고 내용'), category: 'unverified' }
  if (!rule.evidence_url && !rule.evidence_text && !rule.text && !notice.official_url) return unsupported(rule, notice, '공식 조건의 원문 근거가 제공되지 않아 자동 판정하지 않습니다.', '근거 미공개')
  if (rule.kind === 'unparsed') return unsupported(rule, notice, rule.text || rule.evidence_text || '공고의 이 조항을 아직 비교 가능한 조건으로 정리하지 못했습니다.', typeof rule.label === 'string' && rule.label ? rule.label : '신청자격 조항 검토 필요')
  if (rule.criterion_basis === 'contract_date') rule = { ...rule, criterion_date: contractEvaluationDate(notice) }
  profile = profileForResidenceDate(profile, criterionDate(rule, notice))
  const problem = scopeProblem(rule, notice)
  if (problem) return unsupported(rule, notice, problem, '적용 범위')
  if (rule.effect === 'priority') return unsupported(rule, notice, '당첨 우선순위 조건입니다. 신청 가능 여부와 별개로 공고문의 배정 순서를 확인하세요.', '공급 우선순위')
  if (rule.kind === 'recommendation' && (profile.recommendationReason === 'none' || profile.recommendationStatus === 'none')) return reason(rule, notice, 'fail', '기관추천', profile.recommendationReason === 'none' ? '기관추천 대상 사유에 해당 없음으로 입력했습니다.' : '기관 추천이 없다고 입력했습니다.', profile.recommendationReason === 'none' ? '해당 없음' : '추천 없음', '기관추천 대상 및 기관의 확정 추천')
  if (Array.isArray(rule.exceptions) && rule.exceptions.length) {
    const exceptionRules = rule.exceptions.filter((r): r is NoticeRule => !!r && typeof r === 'object' && typeof r.kind === 'string')
    const base = evaluateRule({ ...rule, exceptions: undefined }, profile, notice, unitType)
    const exceptions = exceptionRules.filter((child) => exceptionScopeMatches(rule, child, unitType)).map((child) => inheritedCondition(rule, child))
      .filter((child) => officialClauseApplicability(child, profile, notice) !== false).map((child) => evaluateRule(child, profile, notice, unitType))
    if (exceptions.some((r) => r.status === 'pass')) return reason(rule, notice, 'pass', base.label, `공식 예외 충족: ${exceptions.filter((r) => r.status === 'pass').map((r) => r.detail).join(' / ')}`, base.input, '공식 예외 조건')
    if (base.status === 'fail' && (exceptionRules.length !== rule.exceptions.length || exceptions.some((r) => r.status === 'review'))) {
      const unresolved = exceptions.find((entry) => entry.status === 'review')
      return unresolved ? { ...unresolved, detail: `${base.detail} · 공식 예외: ${unresolved.detail}`, ruleId: rule.id } : unsupported(rule, notice, `${base.detail} · 공식 예외 조항을 판독하지 못했습니다.`, base.label)
    }
    return base
  }
  const children = conditionChildren(rule)
  if (['all', 'any', 'not', 'condition_group'].includes(rule.kind)) {
    if (!children.length) return unsupported(rule, notice, '조건 분기의 세부 조건이 공개되지 않았습니다.', '조건 분기')
    if (!Array.isArray(rule.conditions) || rule.conditions.length !== children.length) return unsupported(rule, notice, '조건 분기에 판독할 수 없는 세부 조건이 포함되어 있습니다.', '조건 분기')
    const mode = rule.kind === 'condition_group' ? rule.operator : rule.kind
    if (mode === 'all') {
      const marriage = children.find((child) => child.kind === 'marital_status' && (child.value === 'married' || Array.isArray(child.allowed_values) && child.allowed_values.length === 1 && child.allowed_values[0] === 'married'))
      if (marriage) {
        const required = evaluateRule(inheritedCondition(rule, marriage), profile, notice, unitType)
        if (required.status === 'fail') return { ...required, ruleId: rule.id, label: typeof rule.label === 'string' ? rule.label : '혼인 필수 조건' }
      }
    }
    const evaluated = children.map((child) => evaluateRule(inheritedCondition(rule, child), profile, notice, unitType))
    const statuses = evaluated.map((r) => r.status)
    const status: ReasonStatus = mode === 'any' ? statuses.includes('pass') ? 'pass' : statuses.every((s) => s === 'fail') ? 'fail' : 'review'
      : mode === 'not' && evaluated.length === 1 ? statuses[0] === 'pass' ? 'fail' : statuses[0] === 'fail' ? 'pass' : 'review'
      : mode === 'all' ? statuses.includes('fail') ? 'fail' : statuses.includes('review') ? 'review' : 'pass' : 'review'
    // Explain the met or unresolved alternative. Failed sibling regions or
    // family routes cannot close a branch that is still possible.
    const explained = mode === 'any' ? evaluated.filter((r) => r.status === status) : mode === 'all' && status === 'fail' ? evaluated.filter((r) => r.status === 'fail') : evaluated
    const inputs = [...new Set(explained.map((r) => r.input).filter((input): input is string => !!input))]
    const requirements = [...new Set(evaluated.map((r) => r.requirement).filter((requirement): requirement is string => !!requirement))]
    const requirement = rule.text || requirements.join(mode === 'any' ? ' 또는 ' : ' 및 ') || undefined
    const question = evaluated.find((entry) => entry.status === 'review' && ['missing_input', 'past_fact'].includes(entry.category || ''))
    return { ...reason(rule, notice, status, typeof rule.label === 'string' ? rule.label : mode === 'any' ? '대체 충족 조건' : '함께 필요한 조건', explained.map((r) => `${r.label}: ${r.detail}`).join(' / '), inputs.length ? inputs.join(' / ') : undefined, requirement), category: status === 'review' ? question?.category || 'source_gap' : 'condition', profileField: status === 'review' ? question?.profileField : undefined, historyGroup: status === 'review' ? question?.historyGroup : undefined }
  }
  const date = criterionDate(rule, notice)
  if (rule.kind === 'account_unused_after_winning') {
    if (!date) return unsupported(rule, notice, '현재 청약통장의 당첨 사용 여부를 비교할 공식 기준일이 확인되지 않았습니다.', '현재 청약통장 사용 이력')
    const usage = accountWinningUsageAtDate(profile, date)
    const preview = rule.criterion_basis === 'application_date' && rule.evaluation_mode === 'today_precheck' ? ' 오늘의 통장 상태로 미리 비교하며, 접수일까지 유효한 통장을 유지해야 합니다.' : ''
    if (usage.status === 'past_fact') return pastFact(rule, notice, 'bank_account', usage.detail + preview)
    if (usage.status === 'missing_input') return missingInput(rule, notice, usage.profileField === 'currentAccountFirstWinningDate' ? '현재 청약통장 최초 당첨일' : '현재 청약통장 당첨 사용 이력', usage.detail + preview, '당첨에 사용되지 않은 현재 통장', usage.profileField)
    const compared = factualBoolean(rule, notice, usage.value, '현재 청약통장 당첨 사용 이력')
    return { ...compared, detail: `${usage.detail} ${compared.detail}${preview}` }
  }
  if (isParentRule(rule.kind)) {
    const parent = resolveParentSupport(profile, date || getEvaluationToday())
    if (parent.mode !== 'legacy') {
      if (!date) return unsupported(rule, notice, '부모 부양 사실을 비교할 공식 기준일이 확인되지 않았습니다.', '공고 기준일의 사실')
      if (parent.mode === 'selection') return missingInput(rule, notice, '부양 대상 부모·조부모', '가족 목록에서 실제 부양 대상 한 명을 선택하세요. 여러 부모의 생년월일·보유 답변을 섞어 비교하지 않습니다.', '비교할 부양 대상', 'parentSupportMemberId')
      const entry = parent.facts[rule.kind]
      if (!entry.temporalKnown && entry.value != null && entry.value !== '') return pastFact(rule, notice, entry.historyGroup || 'household', `${parent.label}의 ${date} 당시 사실을 저장된 가족·주택 이력에서 확인할 수 없습니다. 해당 사실의 기존 변경일 입력을 사용하며 부모 부양 전체의 변경일을 다시 묻지 않습니다.`)
      let compared: EligibilityReason
      if (rule.kind === 'parent_age_min') compared = numeric(rule, notice, ageAt(String(entry.value || ''), date), '부모 만 나이', '세')
      else if (rule.kind === 'parent_support_months_min') {
        const start = typeof entry.value === 'string' ? entry.value : ''
        const same = parent.facts.parent_same_register
        const months = start && parseDate(start) ? start > date ? 0 : fullMonths(start, date) : same.temporalKnown && same.value === false ? 0 : null
        compared = numeric(rule, notice, months, '부모 연속 부양 기간', '개월')
        if (compared.category === 'missing_input') compared = { ...compared, label: '부양 시작일', detail: '선택한 가족이 본인과 같은 등본에서 연속 등재된 시작일을 입력하세요. 가점과 다른 공고에도 같은 날짜를 사용합니다.' }
      } else {
        const label = { parent_same_register: '부모 동일 등본', parent_owns_home: '부모 주택 보유', parent_spouse_owns_home: '부양 대상 부모의 배우자 주택 보유' }[rule.kind]
        compared = factualBoolean(rule, notice, typeof entry.value === 'boolean' ? entry.value : null, label)
      }
      return { ...compared, profileField: compared.status === 'review' ? entry.profileField : undefined, detail: `${parent.label} · ${compared.detail}${entry.detail ? ` ${entry.detail}` : ''}` }
    }
  }
  if (rule.kind === 'overseas_residence' && rule.currently_abroad_only === true) {
    const domestic = evaluateRule({ ...rule, kind: 'domestic_residence', value: true, overseas_residence_equivalence: undefined, conditions: undefined, exceptions: undefined }, profile, notice, unitType)
    if (domestic.status === 'review') return domestic
    if (domestic.status === 'pass') return reason(rule, notice, 'pass', '해외 연속 체류', '공고 기준일에 국내로 귀국해 거주한다고 입력했습니다. 완료된 과거 해외 체류만으로 현재 해외 장기체류자로 제외하지 않습니다.', '기준일 국내 거주', '기준일 현재 연속 해외 체류 90일 초과 아님')
  }
  const group = factGroupForRule(rule), currentField = profileFieldForRule(rule, notice)
  let ownershipInventoryDate: string | undefined
  const currentValue = rule.kind === 'marriage_months_max' ? profile.maritalStatus : group === 'ownership' ? profile.applicantOwnsHome : currentField ? profile[currentField] : undefined
  const savedOwnership = group === 'ownership' && profile.factSnapshots?.some((snapshot) => snapshot.group === 'ownership' && snapshot.date === date && Object.keys(snapshot.values).length > 0)
  if (!['children_min', 'newborn_children_min'].includes(rule.kind) && group && (savedOwnership || currentValue != null && currentValue !== '' && currentValue !== 'unknown')) {
    const legacy = legacyFactObservation(profile, group)
    const temporal = factsAtDate(profile, group, date, legacy)
    const actualMarriage = group === 'marital' && profile.maritalStatus === 'married' && parseDate(profile.marriageDate) && date && profile.marriageDate <= date && !profile.factChanges?.marital
    const actualSupport = ['parent_support_months_min', 'parent_same_register'].includes(rule.kind) && parseDate(profile.parentSupportSince) && date && profile.parentSupportSince <= date && (rule.kind !== 'parent_same_register' || profile.parentSameRegister === true)
    const actualOwnership = group === 'ownership' && ownershipInventoryComplete(profile) && profile.ownershipFacts.length > 0 && profile.ownershipFacts.every((fact) => parseDate(fact.acquiredDate))
    if (!date) return unsupported(rule, notice, '이 사실을 비교할 공식 기준일이 확인되지 않았습니다.', '공고 기준일의 사실')
    if (!temporal.known && !actualMarriage && !actualSupport && !actualOwnership) return pastFact(rule, notice, group)
    if (group === 'ownership' && temporal.source === 'snapshot') ownershipInventoryDate = date || undefined
    profile = temporal.profile
  }
  if (['residence_months', 'residence_region', 'residence_area', 'region'].includes(rule.kind)) {
    const match = matchesRegionScope(profile, rule, date)
    if (rule.residence_union === true && match === null && !profile.districtCode) return missingInput(rule, notice, '해당지역 범위', '공고가 정한 여러 구 중 현재 거주하는 구를 선택하세요.', rule.region_name || undefined, 'districtCode')
    if (match === null || profile.regionNeedsReview) return !profile.regionCode && !profile.region ? missingInput(rule, notice, '거주지역', '현재 거주 시도와 시·군·구를 선택하세요.', rule.region_name || rule.region_code || undefined, 'regionCode') : unsupported(rule, notice, '선택한 행정구역과 공고의 공식 거주 범위·시행일을 확인해야 합니다.', '거주지역')
    const historical = residenceCutoffReview(rule, profile, notice, rule.region_name || rule.region_code || undefined)
    if (historical) return historical
    if (!match) return reason(rule, notice, 'fail', '거주지역', '선택한 거주지와 공식 신청 지역 조건이 다릅니다.', `${profile.region} ${profile.district}`, rule.region_name || rule.region_code || '')
    if (rule.kind !== 'residence_months') return reason(rule, notice, 'pass', '거주지역', '선택한 거주지가 공식 신청 지역에 포함됩니다.', `${profile.region} ${profile.district}`, rule.region_name || rule.region_code || '')
    const start = residenceStartDate(rule, profile)
    const months = date && start ? fullMonths(start, date) : null
    const r = numeric(rule, notice, months, '거주기간', '개월')
    // Staying in one mapped district proves residence in the wider union.
    // A shorter district stay alone cannot disprove continuous residence
    // across the other districts in that same official territory.
    if (rule.residence_union === true && r.status === 'fail') return { ...reason(rule, notice, 'review', '공식 해당지역 연속 거주 이력', `현재 구의 거주기간만으로는 공고가 정한 여러 구 사이의 이동 전 기간을 확인할 수 없습니다. 공식 해당지역 범위에서 ${rule.value}개월간 연속 거주한 이력을 추가 대조해야 합니다.`), category: 'past_fact' }
    if (r.category === 'missing_input' && residenceScopeIsDistrict(rule)) {
      r.profileField = residenceParentCity(rule, profile) ? 'cityMovedInDate' : 'districtMovedInDate'
    }
    r.detail = `${residenceScopeIsDistrict(rule) ? '시·군·구' : '시도'} 연속 거주 시작일 ${start || '미입력'} · ${r.detail}`
    return r
  }
  if (rule.kind === 'citizenship') {
    const allowed = Array.isArray(rule.allowed_values) ? rule.allowed_values : typeof rule.value === 'string' ? [rule.value] : []
    if (!allowed.length || allowed.some((value) => !['korean', 'foreign'].includes(String(value)))) return unsupported(rule, notice, '공고에서 인정하는 국적을 아직 정리하지 못했습니다.', '국적')
    if (profile.citizenship === 'unknown') return missingInput(rule, notice, '국적', '대한민국 또는 외국 국적 여부를 선택하면 공고의 국적 조건과 비교합니다.', allowed.includes('korean') ? '대한민국 국적' : '공고가 인정하는 국적', 'citizenship')
    return reason(rule, notice, allowed.includes(profile.citizenship) ? 'pass' : 'fail', '국적', `내 입력 ${profile.citizenship === 'korean' ? '대한민국' : '외국'} 국적 · 공고에서 인정하는 국적과 비교했습니다.`, profile.citizenship === 'korean' ? '대한민국 국적' : '외국 국적', allowed.map((value) => value === 'korean' ? '대한민국 국적' : '외국 국적').join(', '))
  }
  if (rule.kind === 'overseas_residence') {
    const maximum = numberFrom(rule.max_continuous_days, true), days = numberFrom(profile.overseasContinuousDays, true)
    if (maximum === null || rule.value_basis !== 'continuous_days_including_reentry_within_7_days') return unsupported(rule, notice, '공고의 해외 체류 기간·재입국 합산 기준이 아직 정리되지 않았습니다.', '해외 거주')
    if (days === null) return missingInput(rule, notice, '해외 거주', `공고 기준일의 연속 해외 체류 일수를 입력하세요. 귀국 후 7일 이내${rule.reentry_same_country === true ? ' 같은 국가로' : ''} 재출국했다면 해당 기간을 포함합니다. 계속 국내에 있었다면 0일입니다.`, `연속 해외 체류 ${maximum}일 이하${rule.livelihood_exception === true ? ' 또는 공식 생업 예외' : ''}`, 'overseasContinuousDays')
    const observed = factualSnapshotReview(rule, notice, profile, profile.overseasFactsAsOfDate, profile.overseasFactsHistoryConfirmations, 'overseasFactsAsOfDate', '해외 거주 사실의 기준일')
    if (observed) return observed
    if (days <= maximum) return reason(rule, notice, 'pass', '해외 거주', `입력한 연속 해외 체류 ${days}일이 공고의 ${maximum}일 이하 기준을 충족합니다. 귀국 후 7일 이내${rule.reentry_same_country === true ? ' 같은 국가로' : ''} 재출국 기간을 포함한 입력입니다.`, `${days}일`, `연속 ${maximum}일 이하`)
    if (rule.livelihood_exception === true) {
      if (rule.livelihood_exception_requires_family === true) {
        const household = deriveHousehold(profile, date)
        if (!household.complete) return missingInput(rule, notice, '해외 생업 예외의 가족 구성', household.reviewDetail || '본인 외 공식 세대구성원을 확인하세요.', '본인 외 국내 거주 세대구성원', household.profileField)
        if (household.legalCount === 1) return reason(rule, notice, 'fail', '해외 거주 생업 예외', `연속 해외 체류 ${days}일이 ${maximum}일을 넘으며, 공고는 단독세대주·동거인 세대에서 구성원으로 인정되지 않는 신청자에게 생업 예외를 허용하지 않습니다.`, `${days}일 · 본인만인 법정 세대`, '본인 외 국내 거주 세대구성원이 있는 생업 예외')
      }
      if (profile.overseasOnlyApplicantForLivelihood === null) return missingInput(rule, notice, '해외 거주 생업 예외', `연속 해외 체류 ${days}일이 ${maximum}일을 넘습니다. 본인만 생업을 위해 해외에 있고 배우자·확인 대상 가족은 국내에 거주하는지 입력하세요.`, '본인만 생업을 위한 해외 거주 · 나머지 확인 대상 가족 국내 거주', 'overseasOnlyApplicantForLivelihood')
      if (profile.overseasOnlyApplicantForLivelihood === true) return reason(rule, notice, 'pass', '해외 거주 생업 예외', '본인만 생업을 위해 해외에 있으며 확인 대상 가족은 국내에 거주한다고 입력한 사실이 공식 예외에 해당합니다.', `${days}일 · 본인만 생업 해외 거주`, '공식 생업 예외')
    }
    return reason(rule, notice, 'fail', '해외 거주', `연속 해외 체류 ${days}일은 ${maximum}일을 넘고${rule.livelihood_exception === true ? ' 공식 생업 예외에 해당하지 않습니다.' : ' 이 공고에 확인된 체류 예외가 없습니다.'}`, `${days}일`, `연속 ${maximum}일 이하${rule.livelihood_exception === true ? ' 또는 공식 생업 예외' : ''}`)
  }
  if (rule.kind === 'original_project_contract_ownership') return originalProjectContractOwnership(rule, profile, notice)
  if (rule.kind === 'application_restriction') {
    const scope = String(rule.scope)
    if (!['applicant', 'applicant_spouse', 'household'].includes(scope) || typeof rule.value !== 'boolean') return unsupported(rule, notice, '이 공고의 당첨·계약·제한 확인 범위를 아직 정리하지 못했습니다.', '청약 제한')
    const scopeLabel = scope === 'applicant' ? '본인' : scope === 'applicant_spouse' ? '본인·배우자' : '본인과 주택 보유를 함께 확인할 가족'
    if (scope !== 'applicant') {
      const household = deriveHousehold(profile, date)
      if (!household.complete) return missingInput(rule, notice, '제한 확인 대상 가족', household.reviewDetail || '가족 관계와 등본 위치를 입력하세요.', undefined, household.profileField)
    }
    if (['prior_project_winner', 'prior_project_contract'].includes(String(rule.restriction))) {
      const project = typeof rule.project_id === 'string' && /^(?:\d{10}|LH-[A-Z0-9-]{1,64})$/.test(rule.project_id) ? rule.project_id : null
      if (!project) return unsupported(rule, notice, '최초 모집 사업번호가 확인되지 않아 다른 공고의 당첨·계약 답변을 적용하지 않습니다.', '이 사업의 당첨·계약 이력')
      const common = commonApplicationHistory(rule, profile, notice, scope, project)
      if (common) return common
      const entry = profile.projectApplicationHistory[project]
      const contract = rule.restriction === 'prior_project_contract'
      const label = `${project} 사업 ${contract ? '계약 이력' : '당첨·예비당첨 이력'}`
      if (!entry || (contract ? entry.contractScope : entry.winningScope) !== scope) return missingInput(rule, notice, label, `${scopeLabel}의 공통 당첨·계약 이력을 입력하면 사업번호 ${project}과 사건 날짜를 비교합니다.`, rule.value ? '이력 있음' : '이력 없음', 'applicationHistoryEvents')
      if (entry.asOfDate !== date && entry.historyConfirmations.find((item) => item.criterionDate === date)?.unchanged !== true) return missingInput(rule, notice, label, '예전 사업별 답변은 사건 날짜가 있는 공통 이력으로 변환하지 않습니다. 실제 당첨·계약 이력을 입력하세요.', undefined, 'applicationHistoryEvents')
      const actual = contract ? entry.contract === true || entry.additionalResident === true ? true : entry.contract === false && entry.additionalResident === false ? false : null : entry.winning
      return { ...factualBoolean(rule, notice, actual, label), profileField: actual === null ? 'applicationHistoryEvents' : undefined, detail: typeof actual === 'boolean' ? `${scopeLabel} · 사업번호 ${project}: 저장된 ${date}의 명시적 사업별 답변은 이력 ${actual ? '있음' : '없음'}입니다.` : '공통 당첨·계약 이력에 실제 사건을 입력하세요.' }
    }
    const fields = { ineligible_restriction_active: ['ineligibleRestrictionActive', '부적격 당첨 청약 제한'], resale_restriction_active: ['resaleRestrictionActive', '공급질서 교란·전매 위반 청약 제한'], rewinning_restriction_active: ['rewinningRestrictionActive', '재당첨 제한'] } as const
    const entry = profile.applicationRestrictionFacts[scope as keyof typeof profile.applicationRestrictionFacts]
    const kind = String(rule.restriction) as keyof typeof fields
    if (!fields[kind]) return unsupported(rule, notice, '이 청약 제한의 공식 확인 항목을 아직 지원하지 않습니다.', '청약 제한')
    const [field, label] = fields[kind]
    if (!entry) return missingInput(rule, notice, label, `${scopeLabel}의 청약홈 ‘청약제한사항 확인’ 조회에 ${label}가 표시되는지 입력하세요.`, rule.value ? '제한 표시 있음' : '제한 표시 없음', 'applicationRestrictionFacts')
    const temporal = factsAtDate(profile, 'restrictions', date, { date: entry.asOfDate, confirmations: entry.historyConfirmations })
    if (temporal.known) profile = temporal.profile
    const datedEntry = profile.applicationRestrictionFacts[scope as keyof typeof profile.applicationRestrictionFacts] || entry
    const observed = factualSnapshotReview(rule, notice, profile, datedEntry.asOfDate, datedEntry.historyConfirmations, 'applicationRestrictionFacts', `${label} 조회 기준일`)
    if (observed) return observed
    return { ...factualBoolean(rule, notice, datedEntry[field], label), profileField: datedEntry[field] === null ? 'applicationRestrictionFacts' : undefined, detail: typeof datedEntry[field] === 'boolean' ? `${scopeLabel}의 공고 기준일 조회: ${label} ${datedEntry[field] ? '표시 있음' : '표시 없음'}` : `${scopeLabel}의 청약홈 조회에 ${label}가 실제로 표시되는지 입력하세요.` }
  }
  if (rule.kind === 'household_min') {
    const household = deriveHousehold(profile, date)
    if (!household.complete) return missingInput(rule, notice, '주택 보유 확인 가족 수', household.reviewDetail || '가족 관계와 등본 위치를 입력하세요.', undefined, household.profileField)
    return numeric(rule, notice, household.legalCount, '계산된 주택 보유 확인 가족 수', '명')
  }
  if (rule.kind === 'homeless') {
    const facts = evaluateHouseholdOwnership(profile, { criterionDate: date, inventoryDate: ownershipInventoryDate, supplyType: rule.supply_type || undefined, publicRental: notice.category === 'public_rental' })
    if (typeof rule.value !== 'boolean') return unsupported(rule, notice, '무주택 세대구성원에 대한 공식 요구값을 아직 정리하지 못했습니다.', '무주택 세대구성원')
    if (facts.value === null) {
      const field = facts.profileField
      return { ...(field ? missingInput(rule, notice, '무주택 세대구성원', facts.detail, rule.value ? '확인 대상자 모두 주택·권리 미보유 또는 법정 예외' : '주택 보유', field) : unsupported(rule, notice, facts.detail, '무주택 세대구성원')), evidenceUrl: OWNERSHIP_LAW_URL }
    }
    return { ...reason(rule, notice, facts.value === rule.value ? 'pass' : 'fail', '무주택 세대구성원', facts.detail, facts.value ? '미보유 또는 법정 예외 적용' : '주택·권리 보유', rule.value ? '무주택 세대구성원' : '주택 보유'), evidenceUrl: facts.properties.some((p) => p.clause) ? OWNERSHIP_LAW_URL : rule.evidence_url || law53 }
  }
  if (rule.kind === 'ownership_count_max') {
    const facts = evaluateHouseholdOwnership(profile, { criterionDate: date, inventoryDate: ownershipInventoryDate, supplyType: rule.supply_type || undefined, publicRental: notice.category === 'public_rental' })
    const assessed = numeric(rule, notice, facts.countedHomes, '법정 주택 소유 수', '호', '<=')
    assessed.detail = `${facts.detail} · ${assessed.detail}`
    assessed.evidenceUrl = OWNERSHIP_LAW_URL
    return assessed
  }
  if (rule.kind === 'domestic_residence') {
    if (profile.currentlyDomesticResident == null) return missingInput(rule, notice, '국내 거주', '공고 기준일 현재 국내에 거주하는지 입력하세요.', '국내 거주', 'currentlyDomesticResident')
    const observed = factualSnapshotReview(rule, notice, profile, profile.domesticResidenceFactsAsOfDate || '', profile.domesticResidenceHistoryConfirmations || [], 'domesticResidenceFactsAsOfDate', '국내 거주 사실의 기준일')
    if (observed) return observed
    if (profile.currentlyDomesticResident === false && rule.overseas_residence_equivalence === true) {
      const overseas = notice.rules.find((candidate) => candidate.kind === 'overseas_residence' && candidate.verification === 'official' && scopedRule(candidate, unitType, rule.supply_type || singleOfferedSupplyType(notice)) && criterionDate(candidate, notice) === date && (!rule.document_hash || candidate.document_hash === rule.document_hash))
      if (!overseas) return unsupported(rule, notice, '공고에서 국내 거주로 인정하는 해외 체류 조건의 원문 근거가 미확보입니다.', '국내 거주로 인정되는 해외 체류')
      const compared = evaluateRule(overseas, profile, notice, unitType)
      return { ...compared, label: '국내 거주로 인정되는 해외 체류', detail: `현재 해외 체류 여부와 별도로 공고의 국내 거주 인정 범위를 비교합니다. ${compared.detail}`, ruleId: rule.id }
    }
    return factualBoolean({ ...rule, value: rule.value ?? true }, notice, profile.currentlyDomesticResident, '국내 거주')
  }
  if (rule.kind === 'provider_employee_restriction') {
    if (profile.providerEmployeeOrRelatedFamily == null) return missingInput(rule, notice, '공급기관 임직원·관련 가족', '공고가 정한 공급기관 임직원 또는 매입 제한 관련 가족에 해당하는지 입력하세요. 해당 기관과 가족 범위는 원문 근거에 표시됩니다.', '공고의 임직원 매입 제한 대상 아님', 'providerEmployeeOrRelatedFamily')
    if (profile.providerEmployeeOrRelatedFamily === false) return reason(rule, notice, 'pass', '공급기관 임직원·관련 가족', '공고가 정한 임직원·관련 가족 매입 제한 대상에 해당하지 않는다고 입력했습니다.', '해당 없음', '임직원·관련 가족 제한 대상 아님')
    if (rule.purchase_approval_exception === true || rule.approval_exception === true) {
      if (profile.providerPurchaseApproval == null) return missingInput(rule, notice, '공급기관 매입 승인', '매입 제한 대상입니다. 공고에서 정한 매입 승인을 받은 사실이 있는지 입력하세요.', '공식 매입 승인', 'providerPurchaseApproval')
      return reason(rule, notice, profile.providerPurchaseApproval ? 'pass' : 'fail', '공급기관 매입 승인', profile.providerPurchaseApproval ? '공고가 허용하는 매입 승인을 받았다고 입력했습니다.' : '매입 제한 대상이며 공고가 허용하는 승인을 받지 않았다고 입력했습니다.', profile.providerPurchaseApproval ? '승인 있음' : '승인 없음', '공식 매입 승인')
    }
    if (rule.restriction_uncertain === true) return unsupported(rule, notice, '임직원·관련 가족에 해당합니다. 이 공고는 매입이 제한될 수 있다고 정했으므로 공급기관의 심사 결과가 필요합니다.', '공급기관 임직원 매입 심사')
    return reason(rule, notice, 'fail', '공급기관 임직원·관련 가족', '공고가 정한 임직원·관련 가족 매입 제한 대상에 해당한다고 입력했습니다.', '매입 제한 대상', '매입 제한 대상 아님')
  }
  if (rule.kind === 'military_currently_serving') {
    if (rule.require_as_of_date === true) {
      const observed = factualSnapshotReview(rule, notice, profile, profile.militaryFactsAsOfDate || '', profile.militaryFactsHistoryConfirmations || [], 'militaryFactsAsOfDate', '군 복무 사실의 기준일')
      if (observed) return observed
    }
    return factualBoolean(rule, notice, profile.militaryCurrentlyServing, '현재 군 복무')
  }
  if (rule.kind === 'military_service_years') {
    if (profile.militaryCurrentlyServing == null) return missingInput(rule, notice, '장기복무 군인 예외', '공고 기준일에 군 복무 중이었는지 입력하세요.', undefined, 'militaryCurrentlyServing')
    if (rule.require_as_of_date === true) {
      const observed = factualSnapshotReview(rule, notice, profile, profile.militaryFactsAsOfDate || '', profile.militaryFactsHistoryConfirmations || [], 'militaryFactsAsOfDate', '군 복무 사실의 기준일')
      if (observed) return observed
    }
    const serving = profile.militaryCurrentlyServing
    if (serving === null) return missingInput(rule, notice, '장기복무 군인 예외', '현재 군 복무 중인지 입력하세요.', undefined, 'militaryCurrentlyServing')
    if (serving === false) return reason(rule, notice, 'fail', '장기복무 군인 예외', '현재 군 복무 중이 아니라고 입력했습니다.', '현재 군 복무 아님', '공고의 장기복무 군인 예외')
    const compared = numeric(rule, notice, numberFrom(profile.militaryServiceYears), '군 복무 기간', '년')
    if (compared.status === 'pass' && rule.recommendation_required === true) return unsupported(rule, notice, `복무 기간은 충족하지만 공식 ${String(rule.recommendation_authority || '추천기관')} 추천이 있어야 해당지역 예외가 적용됩니다. 이 추천 사실을 대조할 입력 항목은 아직 지원하지 않습니다.`, '장기복무군인 해당지역 추천 요건')
    return compared
  }
  if (['subscription_months', 'private_rank_months', 'national_rank_months'].includes(rule.kind)) {
    const kind = rule.kind === 'private_rank_months' ? 'private' : rule.kind === 'national_rank_months' ? 'national' : rule.housing_kind || notice.housing_kind
    if (!['private', 'national'].includes(String(kind || '')) || notice.housing_kind_evidence?.verification !== 'official') return unsupported(rule, notice, '공식 민영·국민주택 구분을 확인해야 순위기산일을 비교할 수 있습니다.', '청약통장 기간')
    const base = kind === 'private' ? profile.privateRankBaseDate : profile.nationalRankBaseDate
    return numeric(rule, notice, date && base ? fullMonths(base, date) : null, `${kind === 'private' ? '민영' : '국민'} 순위 인정기간`, '개월')
  }
  const boolFields: Record<string, [boolean | null, string]> = {
    household_head: [profile.isHouseholdHead, '세대주'], applying_restriction: [profile.restrictedFromApplying, '현재 청약 제한'], special_winning: [profile.specialWinning, '특별공급 당첨 이력'], employed: [profile.employed, '근로·자영업 사실'], dual_income: [profile.dualIncome, '맞벌이'], parent_same_register: [profile.parentSameRegister, '부모 동일 등본'], parent_owns_home: [profile.parentOwnsHome, '부모 주택 보유'], parent_spouse_owns_home: [profile.parentSpouseOwnsHome ?? null, '부양 대상 부모의 배우자 주택 보유'], relocated_worker: [profile.relocatedWorker, '이전기관 종사'], pregnant: [profile.pregnant, '임신'],
  }
  if (rule.kind === 'previous_winning') {
    const common = commonApplicationHistory(rule, profile, notice, typeof rule.scope === 'string' ? rule.scope : 'household')
    if (common) return common
    const window = numberFrom(rule.window_months ?? rule.months, true)
    if (window === null || profile.previousWinning !== true) return factualBoolean(rule, notice, profile.previousWinning, '세대 당첨 이력')
    const won = parseDate(profile.previousWinningDate), cutoff = date && parseDate(date)
    if (!cutoff) return unsupported(rule, notice, '당첨 제한 기간을 비교할 공식 기준일이 필요합니다.', '세대 당첨 이력')
    if (!won || won > cutoff) return missingInput(rule, notice, '세대 당첨 이력', '확인 대상 세대의 가장 최근 당첨일을 입력하세요. 기준일 뒤의 날짜는 사용할 수 없습니다.', `${window}개월 이내 당첨 ${rule.value ? '있음' : '없음'}`, 'previousWinningDate')
    const totalMonth = won.getUTCMonth() + window, year = won.getUTCFullYear() + Math.floor(totalMonth / 12), month = totalMonth % 12
    const anniversary = new Date(Date.UTC(year, month, Math.min(won.getUTCDate(), new Date(Date.UTC(year, month + 1, 0)).getUTCDate())))
    const recent = cutoff <= anniversary
    return { ...factualBoolean(rule, notice, recent, '세대 당첨 이력'), detail: `최근 당첨일 ${profile.previousWinningDate} · 공식 기준일 ${date} · 제한 기간 ${window}개월 내 당첨 ${recent ? '있음' : '없음'}`, input: `${profile.previousWinningDate} 당첨`, requirement: `${window}개월 이내 당첨 ${rule.value ? '있음' : '없음'}` }
  }
  if (rule.kind === 'special_winning') {
    const common = commonApplicationHistory(rule, profile, notice, typeof rule.scope === 'string' ? rule.scope : 'household')
    if (common) return common
  }
  if (boolFields[rule.kind]) return factualBoolean(rule, notice, ...boolFields[rule.kind])
  if (rule.kind === 'account_type') {
    const allowed = Array.isArray(rule.allowed_values) ? rule.allowed_values : typeof rule.value === 'string' ? [rule.value] : []
    if (!allowed.length) return unsupported(rule, notice, '이 공급유형에서 인정하는 통장 종류를 아직 정리하지 못했습니다.', '통장 종류')
    if (profile.accountType === 'unknown') return missingInput(rule, notice, '통장 종류', '보유한 청약통장 종류를 선택하세요.', allowed.map((v) => ACCOUNT_LABEL[String(v)] || String(v)).join(', '))
    if (profile.accountType === 'installment' && rule.area_limit_for_installment !== undefined && allowed.includes('installment')) {
      const max = numberFrom(rule.area_limit_for_installment), prices = (notice.prices || []).filter((price) => !unitType || price.unit_type === unitType)
      if (max === null || !prices.length || prices.some((price) => exclusiveArea(price) === null)) return unsupported(rule, notice, '청약부금의 공식 신청 면적 제한과 주택형 전용면적을 확인해야 합니다.', '통장 종류')
      const matches = prices.map((price) => exclusiveArea(price)! <= max)
      if (matches.some(Boolean) && matches.some((match) => !match)) return { ...unsupported(rule, notice, '청약부금으로 신청 가능한 면적과 초과 면적이 함께 있습니다. 아래 주택형별 비교를 확인하세요.', '통장 종류'), category: 'selection' }
      return reason(rule, notice, matches.every(Boolean) ? 'pass' : 'fail', '통장 종류', `${ACCOUNT_LABEL[profile.accountType]}은 공고의 전용 ${max}㎡ 이하 주택형에 인정됩니다.`, ACCOUNT_LABEL[profile.accountType], `전용 ${max}㎡ 이하`)
    }
    return reason(rule, notice, allowed.includes(profile.accountType) ? 'pass' : 'fail', '통장 종류', `내 통장 ${ACCOUNT_LABEL[profile.accountType]} · 인정 ${allowed.map((v) => ACCOUNT_LABEL[String(v)] || '공고 확인').join(', ')}`, ACCOUNT_LABEL[profile.accountType], allowed.map((v) => ACCOUNT_LABEL[String(v)] || '공고 확인').join(', '))
  }
  if (rule.kind === 'deposit_min_krw' && Array.isArray(rule.deposit_table)) {
    type Tier = { max_area_sqm: number | null; amounts_krw: Record<string, unknown> }
    const tiers = rule.deposit_table.filter((tier): tier is Tier => !!tier && typeof tier === 'object' && (tier.max_area_sqm === null || typeof tier.max_area_sqm === 'number' && tier.max_area_sqm > 0) && !!tier.amounts_krw && typeof tier.amounts_krw === 'object')
    const valid = tiers.length === rule.deposit_table.length && tiers.length > 0 && tiers[tiers.length - 1].max_area_sqm === null && tiers.every((tier, index) => (index === tiers.length - 1 || tier.max_area_sqm !== null && (index === 0 || tiers[index - 1].max_area_sqm !== null && tier.max_area_sqm > tiers[index - 1].max_area_sqm!)) && ['seoul_busan', 'other_metropolitan', 'other'].every((bucket) => numberFrom(tier.amounts_krw[bucket], true) !== null))
    if (!valid) return unsupported(rule, notice, '공식 예치금 표의 면적 구간·지역별 금액을 아직 정리하지 못했습니다.', '민영주택 예치금')
    const province = profile.regionCode || resolveLegacyRegion(profile.region, profile.district).regionCode
    if (!province) return missingInput(rule, notice, '민영주택 예치금', '거주 시도를 선택하면 해당 지역의 예치금 기준과 비교합니다.', undefined, 'regionCode')
    if (!['11', '26', '27', '28', '29', '30', '31', '36', '41', '43', '44', '46', '47', '48', '50', '51', '52'].includes(province)) return unsupported(rule, notice, '선택한 시도의 공식 예치금 지역 구분을 확인해야 합니다.', '민영주택 예치금')
    if (profile.regionNeedsReview || matchesRegionScope(profile, { region_code: province }, date) !== true) return unsupported(rule, notice, '선택한 주소의 공식 예치금 지역 구분을 확인해야 합니다.', '민영주택 예치금 거주지역')
    const provenance = residenceCutoffReview({ ...rule, region_code: province, region_name: null }, profile, notice)
    if (provenance) return { ...provenance, label: '민영주택 예치금 거주지역', requirement: date ? `${date} 당시 거주 시도의 예치금 기준` : '공식 기준일 거주 시도의 예치금 기준', detail: !date ? '예치금 지역 구분을 비교할 공식 기준일이 필요합니다.' : !provenance.profileField ? `현재 시도 연속 거주 시작일 ${profile.movedInDate}은 공고 기준일 ${date} 이후입니다. 저장된 당시 주소가 없어 과거 거주지역은 판정을 보류합니다.` : `현재 시도 연속 거주 시작일을 입력하면 공고 기준일 ${date}의 거주 시도에 따른 예치금 기준과 비교할 수 있습니다.` }
    const bucket = ['11', '26'].includes(province) ? 'seoul_busan' : ['27', '28', '29', '30', '31'].includes(province) ? 'other_metropolitan' : 'other'
    const prices = (notice.prices || []).filter((price) => !unitType || price.unit_type === unitType)
    if (!prices.length || prices.some((price) => exclusiveArea(price) === null)) return { ...unsupported(rule, notice, `${unitType || '신청 주택형'}의 공식 전용면적을 확인해야 예치금 표와 비교할 수 있습니다. 공급면적을 대신 사용하지 않습니다.`, '민영주택 예치금'), category: 'source_gap' }
    const requiredAmounts = [...new Set(prices.map((price) => numberFrom(tiers.find((tier) => tier.max_area_sqm === null || exclusiveArea(price)! <= tier.max_area_sqm)!.amounts_krw[bucket], true)!))]
    if (requiredAmounts.length !== 1) return { ...unsupported(rule, notice, '주택형의 전용면적별 예치금 기준이 다릅니다. 아래 주택형별 비교를 확인하세요.', '민영주택 예치금'), category: 'selection' }
    const assessed = numeric({ ...rule, value: requiredAmounts[0] }, notice, numberFrom(profile.privateDepositKrw, true), '민영주택 예치금', '원')
    assessed.requirement = `${province === '11' ? '서울' : province === '26' ? '부산' : bucket === 'other_metropolitan' ? '그 밖의 광역시' : '그 밖의 지역'} · ${unitType ? `${unitType} ` : ''}전용면적 ${[...new Set(prices.map((price) => exclusiveArea(price)))].join(', ')}㎡ · >= ${requiredAmounts[0].toLocaleString('ko-KR')}원`
    return assessed
  }
  const numericFields: Record<string, [unknown, string, string, '>=' | '<=']> = {
    deposit_min_krw: [profile.privateDepositKrw, '민영주택 예치금', '원', '>='], recognized_payments_min: [profile.nationalRecognizedPayments, '국민주택 납입인정횟수', '회', '>='], recognized_amount_min_krw: [profile.nationalRecognizedAmountKrw, '국민주택 납입인정금액', '원', '>='], tax_years_min: [profile.taxYears, '소득세 납부 연수', '년', '>='],
  }
  if (numericFields[rule.kind]) { const [value, label, unit, op] = numericFields[rule.kind]; return numeric(rule, notice, numberFrom(value, true), label, unit, op) }
  if (rule.kind === 'monthly_income_max_krw') {
    if (rule.value_basis !== 'household_monthly_income' || rule.household_size_basis !== 'official_income_household') return unsupported(rule, notice, '공식 월평균소득의 가구원 범위와 산정 기준이 필요합니다.', '월평균소득 산정 기준')
    const size = numberFrom(profile.incomeHouseholdSize, true)
    if (size === null || size < 1) return missingInput(rule, notice, '소득 산정 가구원 수', '공고의 월평균소득 산정 대상에 포함되는 가구원 수를 입력하세요.', '공고의 소득 산정 가구원 수', 'incomeHouseholdSize')
    const minimum = numberFrom(rule.min_household_size, true)
    const rows = Array.isArray(rule.income_table) ? rule.income_table.filter((row): row is Record<string, unknown> => !!row && typeof row === 'object') : []
    const sizes = rows.map((row) => numberFrom(row.household_size, true))
    if (!rows.length || sizes.some((n) => n === null) || rows.some((row) => numberFrom(row.max_krw, true) === null)) return unsupported(rule, notice, '공식 가구원 수별 월평균소득 표를 아직 대조하지 못했습니다.', '월평균소득 표')
    const target = Math.max(size, minimum ?? size), largest = Math.max(...sizes as number[])
    const exact = rows.find((row) => row.household_size === target)
    const last = rows.find((row) => row.household_size === largest)
    const additional = numberFrom(rule.extra_person_krw, true)
    const extraBase = numberFrom(rule.extra_person_base_krw, true), lastBase = numberFrom(rule.extra_person_income_base_last_krw, true), percent = numberFrom(rule.income_percent)
    const expandedLimit = extraBase !== null && lastBase !== null && percent !== null ? Math.round((lastBase + (target - largest) * extraBase) * percent / 100) : last && additional !== null ? numberFrom(last.max_krw, true)! + (target - largest) * additional : null
    const limit = exact ? numberFrom(exact.max_krw, true) : target > largest ? expandedLimit : null
    if (limit === null) return unsupported(rule, notice, `${size}인 가구의 공식 월평균소득 기준을 아직 대조하지 못했습니다.`, '월평균소득 표')
    const assessed = numeric({ ...rule, value: limit }, notice, numberFrom(profile.monthlyIncomeKrw, true), '공고 기준 월평균소득', '원', '<=')
    assessed.requirement = `공식 소득 산정 ${size}인${target !== size ? ` (${target}인 기준 적용)` : ''} · ${rule.operator || '<='} ${limit.toLocaleString('ko-KR')}원`
    return assessed
  }
  if (['real_estate_assets_max_krw', 'real_estate_max_krw'].includes(rule.kind)) return numeric(rule, notice, numberFrom(profile.realEstateKrw, true), '공고 기준 부동산 가액', '원', '<=')
  if (rule.kind === 'first_home_family') {
    if (profile.maritalStatus === 'unknown' || profile.hasSpouse === null) return missingInput(rule, notice, '생애최초 가족 조건', '공고 기준일의 혼인 상태와 배우자 유무를 입력하세요.', '혼인·자녀 또는 공고의 1인 가구 조건', 'maritalStatus')
    if (profile.hasSpouse === true || profile.maritalStatus === 'married') return reason(rule, notice, 'pass', '생애최초 가족 조건', '혼인 중이라고 입력한 사실이 공고의 가족 조건을 충족합니다.', '혼인 중', '혼인 또는 자녀·1인 가구 분기')
    if (rule.unmarried_child_required === true || rule.unmarried_applicant_child_same_register === true || rule.non_solo_requires_ascendant === true) return date ? strictFirstHomeFamily(rule, profile, notice, date, unitType) : unsupported(rule, notice, '생애최초 가족 사실을 비교할 공식 기준일이 필요합니다.', '공고 기준일의 사실')
    if (profile.hasChildren === null) return missingInput(rule, notice, '생애최초 가족 조건', '혼인 중이 아니라면 자녀 유무를 입력하세요.', '자녀 또는 1인 가구 분기', 'hasChildren')
    if (profile.hasChildren === true) {
      if (!profile.children.length || profile.children.some((child) => !parseDate(child.dateOfBirth) || !date || child.dateOfBirth > date || child.adopted === null)) return missingInput(rule, notice, '생애최초 자녀 조건', '자녀의 생년월일과 입양 사실을 입력하세요.', '공고가 인정하는 자녀', 'children')
      if (profile.children.some((child) => child.adopted === false || rule.include_adoption === true)) return reason(rule, notice, 'pass', '생애최초 가족 조건', '공고가 인정하는 자녀가 있다고 입력했습니다.', '자녀 있음', '자녀 조건')
    }
    if (rule.include_pregnancy === true) {
      if (profile.pregnant === null) return missingInput(rule, notice, '생애최초 임신 조건', '공고가 임신 중인 자녀를 인정합니다. 임신 사실을 입력하세요.', '자녀 또는 1인 가구 분기', 'pregnant')
      if (profile.pregnant === true) return reason(rule, notice, 'pass', '생애최초 가족 조건', '공고가 인정하는 임신 사실이 있다고 입력했습니다.', '임신 중', '임신 중인 자녀 인정')
    }
    const household = deriveHousehold(profile, date)
    if (!household.complete) return missingInput(rule, notice, '생애최초 1인 가구 조건', household.reviewDetail || '같은 등본의 가족 관계를 입력하세요.', '단독·비단독 가구 분기', household.profileField)
    if (household.legalCount! > 1) return reason(rule, notice, 'pass', '생애최초 가족 조건', '혼인·자녀가 없고 직계가족과 같은 등본에 있는 비단독 가구로 입력했습니다.', `주택 보유 확인 대상 ${household.legalCount}명`, '공고의 비단독 1인 가구 조건')
    const maximum = numberFrom(rule.solo_max_area_sqm), prices = (notice.prices || []).filter((price) => !unitType || price.unit_type === unitType)
    if (maximum === null || !prices.length || prices.some((price) => exclusiveArea(price) === null)) return unsupported(rule, notice, '단독 1인 가구의 공식 신청 면적과 주택형 전용면적을 확인해야 합니다.', '생애최초 단독 1인 가구 면적')
    const matches = prices.map((price) => exclusiveArea(price)! <= maximum)
    if (matches.some(Boolean) && matches.some((match) => !match)) return { ...unsupported(rule, notice, '단독 1인 가구가 신청 가능한 면적과 초과 면적이 함께 있습니다. 주택형별 조건을 확인하세요.', '생애최초 단독 1인 가구 면적'), category: 'selection' }
    return reason(rule, notice, matches.every(Boolean) ? 'pass' : 'fail', '생애최초 단독 1인 가구 면적', `단독 1인 가구 · ${unitType || '주택형'} 전용 ${prices.map((price) => exclusiveArea(price)).join(', ')}㎡ · 공고의 ${maximum}㎡ 이하 조건과 비교했습니다.`, '혼인·자녀 없는 단독 1인 가구', `전용 ${maximum}㎡ 이하`)
  }
  if (rule.kind === 'first_home_tax_activity') {
    const required = numberFrom(rule.tax_years_min, true), years = numberFrom(profile.taxYears, true)
    if (required === null) return unsupported(rule, notice, '공고의 소득세 납부 연수와 최근 납부 기간을 대조해야 합니다.', '생애최초 소득세')
    if (years === null) return missingInput(rule, notice, '생애최초 소득세 납부 연수', rule.includes_tax_exemption === true ? '납부의무 면제 기간을 포함하여 공고에서 인정하는 소득세 납부 연수를 입력하세요.' : '공고에서 인정하는 소득세 납부 연수를 입력하세요.', `>= ${required}년`, 'taxYears')
    const period = numeric({ ...rule, value: required }, notice, years, '소득세 납부 연수', '년')
    if (period.status === 'fail') return period
    if (profile.employed == null) return missingInput(rule, notice, '생애최초 소득 활동', '공고 기준일에 근로자·자영업자인지 입력하세요.', '현재 근로·자영업 또는 최근 소득세 납부', 'employed')
    if (profile.employed === false && profile.incomeTaxPaidWithinPastYear == null) return missingInput(rule, notice, '최근 소득세 납부', `현재 근로자·자영업자가 아니라면 공고 기준일 이전 ${numberFrom(rule.recent_tax_months) ?? 12}개월 안에 소득세를 납부했는지 입력하세요.`, '최근 소득세 납부 사실', 'incomeTaxPaidWithinPastYear')
    const observed = factualSnapshotReview(rule, notice, profile, profile.incomeTaxFactsAsOfDate || '', profile.incomeTaxFactsHistoryConfirmations || [], 'incomeTaxFactsAsOfDate', '소득 활동·납세 사실의 기준일')
    if (observed) return observed
    const active = profile.employed === true || profile.incomeTaxPaidWithinPastYear === true
    return reason(rule, notice, active ? 'pass' : 'fail', '생애최초 소득 활동·납세', `소득세 납부 ${years}년 · ${profile.employed ? '현재 근로자·자영업자' : profile.incomeTaxPaidWithinPastYear ? '공고가 정한 최근 소득세 납부 있음' : '현재 근로·자영업과 최근 소득세 납부 없음'}`, `${years}년`, `${required}년 이상 및 현재 소득 활동 또는 최근 납부`)
  }
  if (rule.kind === 'income_max_krw') {
    if (!['annual', 'monthly'].includes(String(rule.period))) return unsupported(rule, notice, '공고의 소득 기준이 연 소득인지 법정 월평균소득인지 먼저 확인해야 합니다.', '소득 산정 기준')
    const value = rule.period === 'annual' ? profile.annualIncomeKrw : rule.period === 'monthly' ? profile.monthlyIncomeKrw : ''
    return numeric(rule, notice, numberFrom(value), rule.period === 'annual' ? '가구 연 소득' : '공고 기준 월평균소득', '원', '<=')
  }
  if (rule.kind === 'assets_max_krw') {
    if (rule.asset_basis && !['total_household', 'real_estate', 'automobile', 'vehicle'].includes(String(rule.asset_basis))) return unsupported(rule, notice, '공고의 자산 산정 범위를 먼저 확인해야 합니다.', '자산 산정 기준')
    const value = !rule.asset_basis || rule.asset_basis === 'total_household' ? profile.assetsKrw : rule.asset_basis === 'real_estate' ? profile.realEstateKrw : ['automobile', 'vehicle'].includes(String(rule.asset_basis)) ? profile.vehicleKrw : ''
    return numeric(rule, notice, numberFrom(value), rule.asset_basis === 'real_estate' ? '부동산 가액' : ['automobile', 'vehicle'].includes(String(rule.asset_basis)) ? '자동차 가액' : '가구 총자산', '원', '<=')
  }
  if (rule.kind === 'marital_status') {
    const allowed = Array.isArray(rule.allowed_values) ? rule.allowed_values : typeof rule.value === 'string' ? [rule.value] : []
    if (!allowed.length) return unsupported(rule, notice, '공고에서 인정하는 혼인 상태를 아직 정리하지 못했습니다.', '혼인 상태')
    if (profile.maritalStatus === 'unknown') return missingInput(rule, notice, '혼인 상태', '현재 혼인 상태를 선택하세요.', allowed.map((v) => MARITAL_LABEL[String(v)] || String(v)).join(', '))
    return reason(rule, notice, allowed.includes(profile.maritalStatus) ? 'pass' : 'fail', '혼인 상태', `입력 ${MARITAL_LABEL[profile.maritalStatus]} · 인정 ${allowed.map((v) => MARITAL_LABEL[String(v)] || '공고 확인').join(', ')}`, MARITAL_LABEL[profile.maritalStatus], allowed.map((v) => MARITAL_LABEL[String(v)] || '공고 확인').join(', '))
  }
  if (rule.kind === 'planned_marriage') {
    if (profile.maritalStatus === 'married') return reason(rule, notice, 'fail', '혼인 예정', '이미 혼인 중이므로 예비신혼부부 경로에 해당하지 않습니다. 신혼부부 유형의 조건을 비교하세요.', '혼인 중', '혼인 전 예비신혼부부')
    if (profile.plannedMarriage == null) return missingInput(rule, notice, '혼인 예정', '입주 전에 혼인신고할 예정인 상대방이 있는지 입력하세요. 미래 혼인신고를 이미 완료한 것으로 인정하지 않습니다.', '입주 전 혼인사실 증명', 'plannedMarriage')
    return reason(rule, notice, profile.plannedMarriage ? 'pass' : 'fail', '혼인 예정', profile.plannedMarriage ? '입주 전 혼인신고할 상대방이 있다고 입력했습니다. 혼인으로 구성할 세대의 소유·소득·자산도 별도로 확인하며, 입주 전 증빙이 필요합니다.' : '입주 전 혼인신고할 상대방이 없다고 입력했습니다.', profile.plannedMarriage ? '혼인 예정 상대 있음' : '혼인 계획 없음', '입주 전 혼인사실 증명')
  }
  if (rule.kind === 'single_parent_family') {
    if (profile.maritalStatus === 'unknown') return missingInput(rule, notice, '부모의 혼인 상태', '현재 혼인 상태를 선택하세요.', '공고가 정한 한부모가족', 'maritalStatus')
    if (profile.maritalStatus === 'married' || profile.hasDeFactoPartner === true) return reason(rule, notice, 'fail', '한부모 가족 관계', '법률상 배우자 또는 사실혼 상대가 있어 공고의 한부모 경로에 해당하지 않습니다.', '배우자 또는 사실혼 상대 있음', '공고가 정한 한부모가족')
    if (profile.raisesChildWithoutSpouse == null) return missingInput(rule, notice, '자녀 양육 관계', '배우자 없이 본인이 자녀를 양육하는 부모인지 입력하세요.', '한부모가족의 부 또는 모', 'raisesChildWithoutSpouse')
    if (!profile.raisesChildWithoutSpouse) return reason(rule, notice, 'fail', '자녀 양육 관계', '배우자 없이 자녀를 양육하는 부모가 아니라고 입력했습니다.', '해당 양육 관계 없음', '한부모가족의 부 또는 모')
    if (profile.hasDeFactoPartner == null) return missingInput(rule, notice, '사실혼 관계', '혼인신고 없이 부부로 생활하는 상대방이 있는지 입력하세요.', '사실혼 관계 없음', 'hasDeFactoPartner')
    return reason(rule, notice, 'pass', '한부모 가족 관계', '배우자·사실혼 상대 없이 본인이 자녀를 양육한다고 입력했습니다. 가족관계증명서·등본 등 공고가 정한 증빙 대상입니다.', '배우자 없이 자녀 양육', '공고가 정한 한부모가족')
  }
  if (rule.kind === 'shinhee_income' || rule.kind === 'shinhee_assets') {
    const assets = rule.kind === 'shinhee_assets'
    const amount = numberFrom(assets ? profile.officialNetAssetsKrw : profile.monthlyIncomeKrw, true)
    const label = assets ? '공고 기준 순자산' : '신혼희망타운 월평균소득'
    const field = assets ? 'officialNetAssetsKrw' : 'monthlyIncomeKrw'
    if (amount === null) return missingInput(rule, notice, label, assets ? '공고의 평가 방식으로 계산한 자산에서 인정 부채를 뺀 순자산을 입력하세요. 가구 자산 합계를 대신 사용하지 않습니다.' : '공고가 정한 가족 범위의 월평균소득을 입력하세요. 연 소득을 12로 나눈 값으로 대신하지 않습니다.', undefined, field)
    let percent = numberFrom(rule.normal_percent, true)
    if (!assets) {
      const dual = numberFrom(rule.dual_income_percent, true)
      if (dual !== null && profile.dualIncome === true) percent = dual
      else if (dual !== null && profile.dualIncome === null) {
        const size = numberFrom(profile.incomeHouseholdSize, true)
        const tables = rule.percentage_tables as Record<string, { household_size: number; max_krw: number }[]> | undefined
        const base = size !== null && size > 0 ? tables?.[String(percent)]?.find((entry) => entry.household_size === Math.max(3, size))?.max_krw : null
        if (base == null || amount > base) return missingInput(rule, notice, '본인·배우자 소득 활동', '본인과 배우자(예비배우자)가 모두 사업소득 또는 근로소득이 있는지 입력하세요.', '맞벌이 여부별 소득 기준', 'dualIncome')
      }
    }
    const size = assets ? 0 : numberFrom(profile.incomeHouseholdSize, true)
    if (!assets && (size === null || size < 1)) return missingInput(rule, notice, '소득 산정 가구원 수', '공고가 정한 소득 산정 가족과 태아를 포함한 가구원 수를 입력하세요.', '공식 소득 산정 가구원 수', 'incomeHouseholdSize')
    const maxAt = (bonus: number): number | null => {
      if (assets) return numberFrom(bonus === 20 ? rule.two_children_max_krw : bonus === 10 ? rule.one_child_max_krw : rule.base_max_krw, true)
      const table = (rule.percentage_tables as Record<string, { household_size: number; max_krw: number }[]> | undefined)?.[String((percent ?? 0) + bonus)]
      const value = table?.find((entry) => entry.household_size === Math.max(3, size!))?.max_krw
      return numberFrom(value, true)
    }
    let bonus = 0
    const base = maxAt(0)
    // Child and pregnancy information is only needed to establish the relaxed
    // threshold when the normal threshold is exceeded.
    if (base !== null && amount > base) {
      if (!date || typeof rule.child_relaxation_since !== 'string') return unsupported(rule, notice, '출산가구 완화의 기준일을 확인해야 합니다.', label)
      if (profile.hasChildren === null || profile.hasChildren && !profile.children.length || !profile.hasChildren && profile.children.length) return missingInput(rule, notice, '출산가구 완화', '자녀 유무와 자녀별 생년월일을 입력하면 출산가구의 완화 기준을 비교합니다.', undefined, 'children')
      if (profile.pregnant === null) return missingInput(rule, notice, '출산가구 완화', '본인 또는 배우자가 임신 중인지 입력하세요.', undefined, 'pregnant')
      if (profile.children.some((child) => !parseDate(child.dateOfBirth) || child.dateOfBirth > date || child.adopted === null)) return missingInput(rule, notice, '출산가구 완화', '공고 기준일의 자녀 생년월일과 입양 여부를 입력하세요.', undefined, 'children')
      const expected = profile.pregnant ? numberFrom(profile.expectedChildren, true) : 0
      if (expected === null || profile.pregnant && expected < 1) return missingInput(rule, notice, '출산가구 완화', '임신 중 태아 수를 입력하세요.', undefined, 'expectedChildren')
      const recent = profile.children.filter((child) => child.dateOfBirth >= String(rule.child_relaxation_since)).length + expected
      const total = profile.children.length + expected
      bonus = recent > 0 ? total > 1 ? 20 : 10 : 0
    }
    const maximum = maxAt(bonus)
    if (maximum === null) return unsupported(rule, notice, `입력한 가구원 수의 공식 ${assets ? '자산' : '소득'} 표를 아직 정리하지 못했습니다.`, label)
    const assessed = numeric({ ...rule, value: maximum, operator: '<=' }, notice, amount, label, '원', '<=')
    assessed.detail = `${assets ? '인정 부채를 차감한 공고 기준 순자산' : `${Math.max(3, size!)}인 기준 월평균소득 ${percent! + bonus}%`}${bonus ? ` · 출산가구 ${bonus}%p 완화` : ''}: 내 입력 ${amount.toLocaleString('ko-KR')}원 · 공고 한도 ${maximum.toLocaleString('ko-KR')}원`
    return assessed
  }
  if (rule.kind === 'marriage_months_max') {
    if (['single', 'engaged', 'divorced', 'widowed'].includes(profile.maritalStatus)) return reason(rule, notice, 'fail', '혼인 필수 조건', `현재 혼인 상태는 ${MARITAL_LABEL[profile.maritalStatus]}로 입력했습니다. 혼인기간 조건의 혼인 경로에 해당하지 않습니다.`, MARITAL_LABEL[profile.maritalStatus], '혼인 중')
    const assessed = numeric(rule, notice, date && profile.marriageDate ? fullMonths(profile.marriageDate, date) : null, '혼인 기간', '개월', '<=')
    const required = numberFrom(rule.value, true), marriage = parseDate(profile.marriageDate), cutoff = date && parseDate(date)
    if (rule.anniversary_limit === true && required !== null && marriage && cutoff && marriage <= cutoff) {
      const totalMonth = marriage.getUTCMonth() + required, year = marriage.getUTCFullYear() + Math.floor(totalMonth / 12), month = totalMonth % 12
      const anniversary = new Date(Date.UTC(year, month, Math.min(marriage.getUTCDate(), new Date(Date.UTC(year, month + 1, 0)).getUTCDate())))
      const inclusive = rule.operator !== '<'
      assessed.status = (inclusive ? cutoff <= anniversary : cutoff < anniversary) ? 'pass' : 'fail'
      assessed.detail = `혼인신고일 ${profile.marriageDate}부터 ${required}개월 되는 날 ${anniversary.toISOString().slice(0, 10)}${inclusive ? '까지' : '전'}를 기준일 ${date}과 비교했습니다.`
      assessed.input = profile.marriageDate
      assessed.requirement = `${anniversary.toISOString().slice(0, 10)}${inclusive ? '까지' : '전'} (${required}개월 ${inclusive ? '이내' : '미만'})`
    }
    return assessed
  }
  if (rule.kind === 'age_min' || rule.kind === 'age_max') return numeric(rule, notice, date ? ageAt(profile.dateOfBirth, date) : null, '공고 기준 만 나이', '세', rule.kind === 'age_max' ? '<=' : '>=')
  if (rule.kind === 'parent_age_min') return numeric(rule, notice, date ? ageAt(profile.parentDateOfBirth, date) : null, '부모 만 나이', '세')
  if (rule.kind === 'parent_support_months_min') {
    const compared = numeric(rule, notice, date && profile.parentSupportSince ? fullMonths(profile.parentSupportSince, date) : null, '부모 연속 부양 기간', '개월')
    return compared.category === 'missing_input' && !parseDate(profile.parentSupportSince)
      ? { ...compared, label: '부양 시작일', detail: `같은 등본에서 부모·조부모를 연속 부양하기 시작한 날짜를 입력하세요. 공고 기준일 ${date}까지의 기간을 ${compared.requirement} 조건과 비교하며, 입력한 시작일을 다른 공고에서도 재사용합니다.` }
      : compared
  }
  if (rule.kind === 'children_min' || rule.kind === 'newborn_children_min') {
    if (!date) return unsupported(rule, notice, '자녀 수를 비교할 공식 기준일이 필요합니다.', '자녀 수')
    const childState = factsAtDate(profile, 'children', date)
    if (profile.hasChildren !== null && !childState.known) return missingInput(rule, notice, '자녀 상태 변경일', `${date} 당시의 자녀 상태를 확인하려면 공통 자녀 상태 변경일 또는 계속 자녀 없음 사실을 입력하세요.`, `${date} 당시 자녀 상태`, 'children')
    profile = childState.profile
    if (profile.hasChildren === null || (profile.hasChildren === true && !profile.children.length)) return missingInput(rule, notice, '자녀 수', '자녀 유무를 답하고 자녀가 있다면 생년월일을 추가하세요.', undefined, profile.hasChildren === null ? 'hasChildren' : 'children')
    const includePregnancy = rule.include_pregnancy === true
    if (includePregnancy) {
      const pregnancy = factsAtDate(profile, 'pregnancy', date)
      if (profile.pregnant !== null && !pregnancy.known) return missingInput(rule, notice, '임신 상태 변경일', `${date} 당시 임신 상태의 마지막 변경일 또는 계속 임신 없음 사실을 입력하세요.`, `${date} 당시 임신 상태`, 'pregnant')
      profile = pregnancy.profile
      if (profile.pregnant === null) return missingInput(rule, notice, '임신 사실', '이 공고는 태아를 자녀 수에 포함합니다. 임신 유무를 입력하세요.', undefined, 'pregnant')
    }
    const children = profile.hasChildren ? profile.children : []
    if (children.some((child) => !parseDate(child.dateOfBirth) || child.adopted === null || child.adopted && !parseDate(child.adoptionDate || ''))) return missingInput(rule, notice, '자녀 생년월일·입양', '자녀의 생년월일과 입양한 경우 입양일을 입력하세요.', undefined, 'children')
    const ageLimit = numberFrom(rule.child_age_max, true)
    const monthLimit = numberFrom(rule.child_months_max, true)
    if (ageLimit === null && monthLimit === null) return unsupported(rule, notice, '공고가 인정하는 자녀의 나이 또는 월령 기준을 확인해야 합니다.', '자녀 수')
    const expected = profile.pregnant && includePregnancy ? numberFrom(profile.expectedChildren, true) : 0
    if (expected === null || profile.pregnant && includePregnancy && expected < 1) return missingInput(rule, notice, '자녀 수', '임신 중인 태아 수를 입력하세요.', undefined, 'expectedChildren')
    const limit = monthLimit ?? ageLimit!
    const count = children.filter((child) => {
      if (child.dateOfBirth > date || child.adopted && child.adoptionDate! > date) return false;
      const birth = parseDate(child.dateOfBirth)!
      const monthsLimit = monthLimit ?? limit * 12
      const totalMonth = birth.getUTCMonth() + monthsLimit
      const year = birth.getUTCFullYear() + Math.floor(totalMonth / 12), month = totalMonth % 12
      const cutoff = new Date(Date.UTC(year, month, Math.min(birth.getUTCDate(), new Date(Date.UTC(year, month + 1, 0)).getUTCDate())))
      return rule.child_age_inclusive === true ? parseDate(date)! <= cutoff : parseDate(date)! < cutoff
    }).length + expected
    return numeric(rule, notice, count, rule.kind === 'newborn_children_min' ? '신생아 조건 자녀 수' : '공고 인정 자녀 수', '명')
  }
  if (rule.kind === 'never_owned_home') {
    const household = deriveHousehold(profile, date)
    if (!household.complete) return missingInput(rule, notice, '과거 주택 소유 확인 가족', household.reviewDetail || '가족 관계와 등본 위치를 입력하세요.', undefined, household.profileField)
    const members = household.members.filter((member) => member.included === true)
    const missing = members.find((member) => member.previouslyOwnedHome === null)
    if (missing) return missingInput(rule, notice, '과거 주택 소유', `${missing.label}의 과거 주택·권리 소유 이력을 입력하세요.`, '공고가 인정하는 과거 주택 미소유', missing.id === 'applicant' ? 'applicantPreviouslyOwnedHome' : missing.id === 'spouse' ? 'spousePreviouslyOwnedHome' : 'householdMembers')
    const owned = members.filter((member) => member.previouslyOwnedHome === true)
    if (owned.length) {
      const spouseException = rule.exclude_spouse_pre_marriage_disposed === true && owned.every((member) => member.id === 'spouse')
      if (spouseException) {
        if (profile.spousePremarriageOwnershipDisposed == null) return missingInput(rule, notice, '배우자 혼인 전 소유 예외', '배우자의 과거 소유가 모두 혼인 전에 취득·처분한 주택인지 입력하세요. 현재 소유와 본인 소유 이력에는 이 예외를 적용하지 않습니다.', '배우자의 혼인 전 취득·처분만 있음', 'spousePremarriageOwnershipDisposed')
        if (profile.spousePremarriageOwnershipDisposed === true) return reason(rule, notice, 'pass', '과거 주택 소유 공식 예외', '배우자의 과거 소유가 모두 혼인 전에 취득·처분한 주택이라고 입력한 사실이 공고의 예외에 해당합니다.', '배우자 혼인 전 취득·처분', '공식 배우자 혼인 전 소유 예외')
        return reason(rule, notice, 'fail', '과거 주택 소유', '배우자의 과거 소유가 공고의 혼인 전 취득·처분 예외에 해당하지 않는다고 입력했습니다.', '예외 밖 과거 소유 있음', '공고가 인정하는 과거 주택 미소유 또는 예외')
      }
      if (rule.exclude_spouse_pre_marriage_disposed === true) return reason(rule, notice, 'fail', '과거 주택 소유', '본인 또는 확인 대상 가족의 과거 소유 이력이 있어 배우자 혼인 전 취득·처분 예외를 적용할 수 없습니다.', '과거 소유 있음', '과거 주택 미소유 또는 공식 배우자 예외')
      return unsupported(rule, notice, '과거 소유 이력이 있습니다. 해당 유형의 공식 예외를 확인해야 합니다.', '과거 주택 소유')
    }
    return factualBoolean(rule, notice, true, '과거 주택 미소유')
  }
  if (rule.kind === 'recommendation') {
    if (!profile.recommendationReason || profile.recommendationReason === 'unknown') return missingInput(rule, notice, '기관추천', '추천 대상 사유를 입력하세요.', undefined, 'recommendationReason')
    const allowed = Array.isArray(rule.allowed_reasons) ? rule.allowed_reasons : typeof rule.value === 'string' ? [rule.value] : []
    const matches = allowed.length > 0 && allowed.includes(profile.recommendationReason)
    const unsupportedReasons = Array.isArray(rule.unsupported_reasons) ? rule.unsupported_reasons.filter((value): value is string => typeof value === 'string') : null
    // An exact reviewed source can distinguish a real unmodeled subset from
    // a named reason it does not accept. A generic gap label cannot rescue
    // that known exclusion; older unstructured sources remain conservative.
    if (allowed.length > 0 && !matches && unsupportedReasons && !unsupportedReasons.includes(profile.recommendationReason)) return reason(rule, notice, 'fail', '기관추천 대상 사유', `추천 사유 ${profile.recommendationReason}는 이 공고가 열거한 기관추천 대상에 해당하지 않습니다.`, profile.recommendationReason, `공식 추천 사유 ${allowed.join(', ')}`)
    if (profile.recommendationStatus === 'unknown') return missingInput(rule, notice, '기관추천', '해당 기관의 추천 상태를 입력하세요.', undefined, 'recommendationStatus')
    if (profile.recommendationStatus === 'confirmed' && !matches && typeof rule.unsupported_reason_label === 'string') return unsupported(rule, notice, `추천 사유 ${profile.recommendationReason}는 확인했으나 이 사유의 공식 추천·통장 면제 분기를 아직 비교에 반영하지 못했습니다.`, rule.unsupported_reason_label)
    return reason(rule, notice, profile.recommendationStatus === 'confirmed' && matches ? 'pass' : 'review', '기관추천', `추천 사유 ${profile.recommendationReason} · 상태 ${RECOMMENDATION_LABEL[profile.recommendationStatus]}`, `${profile.recommendationReason} / ${RECOMMENDATION_LABEL[profile.recommendationStatus]}`, allowed.length ? `공식 추천 사유 ${allowed.join(', ')}` : '공고의 공식 추천 사유 미확인')
  }
  if (rule.kind === 'first_rank') {
    const derived = deriveRank(notice, profile, unitType)
    return { ...reason(rule, notice, derived.rank === 'first' ? 'pass' : derived.status === 'mismatch' ? 'fail' : 'review', '일반공급 1순위', derived.reasons.filter((r) => r.status !== 'pass').map((r) => r.detail).join(' / ') || derived.label, derived.rank === 'first' ? derived.label : undefined, '해당 주택 구분의 1순위'), category: derived.status === 'review' || derived.status === 'unpublished' ? 'source_gap' : 'condition' }
  }
  if (rule.kind === 'special_eligibility') return unsupported(rule, notice, '특별공급 유형명만으로 자격을 확정하지 않습니다. 해당 유형의 혼인·자녀·세대·소득·당첨 이력 등 공식 조건이 필요합니다.', '특별공급 세부 조건')
  return unsupported(rule, notice, '자동 진단에서 지원하지 않는 조건입니다. 공고문 원문을 확인하세요.', '기타 조건')
}

export interface ConditionCoverage {
  complete: boolean
  verifiedCount: number
  missingTopics: string[]
  status: string
  topics: { topic: string; status: 'verified' | 'partial' | 'missing' | 'not_applicable'; ruleIds: string[]; required: boolean; reason?: string }[]
}

/** undefined means inventory has not been collected; [] is an official empty inventory. */
export function officialOfferedSupplies(notice: Notice): OfferedSupply[] | undefined {
  if (notice.offered_supplies != null) return notice.offered_supplies.filter((supply) => supply.verification === 'official' && supply.supply_count !== 0)
  const inventory = (notice.rules || []).find((rule) => rule.kind === 'offered_supplies' && rule.effect === 'metadata' && rule.verification === 'official' && Array.isArray(rule.supplies))
  return inventory ? (inventory.supplies as OfferedSupply[]).filter((supply) => supply.verification === 'official' && supply.supply_count !== 0) : undefined
}
function singleOfferedSupplyType(notice: Notice): string | undefined {
  const supplies = [...new Set((officialOfferedSupplies(notice) || []).map((item) => item.supply_type))]
  return supplies.length === 1 ? supplies[0] : undefined
}

function scopedRule(rule: NoticeRule, unitType?: string, supplyType?: string): boolean {
  return (!rule.unit_type || rule.unit_type === unitType) && (!Array.isArray(rule.unit_types) || !!unitType && rule.unit_types.includes(unitType)) && (!rule.supply_type || compact(rule.supply_type) === compact(supplyType || '')) && (!Array.isArray(rule.supply_types) || !!supplyType && rule.supply_types.some((supply) => typeof supply === 'string' && compact(supply) === compact(supplyType)))
}

function applicationProcedure(rule: NoticeRule): boolean {
  return ['procedure', 'instruction'].includes(String(rule.effect)) || rule.purpose === 'application_instruction' || ['application_instructions', 'document_submission', 'payment_procedure', 'duplicate_application_instruction'].includes(rule.kind)
}
function concreteMissingTopic(topic: string): string {
  return /^(?:문서의 나머지 신청 제한·예외 검토|기타 공식 조건|신청 제한·연령 예외의 전체 검토)$/.test(topic.trim()) ? '신청자격 문단의 필수 조건·면제 검토 기록 미확보' : topic
}
function documentUrlIdentity(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try { const url = new URL(value); url.hash = ''; url.searchParams.sort(); return url.href } catch { return null }
}
function latestAttachmentUnreviewed(notice: Notice, reviewed: NoticeRule[]): boolean {
  const failures = notice.rules.filter((rule) => rule.kind === 'document_diagnostics' && rule.verification === 'official' && ['unreadable', 'error'].includes(String(rule.status)) && Array.isArray(rule.diagnostics))
  if (!failures.length) return false
  const urls = new Set(reviewed.filter((rule) => rule.verification === 'official' && typeof rule.document_hash === 'string').map((rule) => documentUrlIdentity(rule.evidence_url)).filter((url): url is string => !!url))
  const attachmentStages = ['download', 'conversion', 'decode', 'interpretation']
  return failures.some((rule) => (rule.diagnostics as Record<string, unknown>[]).some((entry) => {
    if (!entry || typeof entry !== 'object' || entry.status === 'ok') return false
    if (entry.stage === 'identity' || entry.code === 'current_document_mismatch') return true
    if (!attachmentStages.includes(String(entry.stage))) return false
    const url = documentUrlIdentity(entry.evidence_url)
    return urls.size > 0 && !!url && !urls.has(url)
  }))
}

export function conditionCoverage(notice: Notice, unitType?: string, supplyType?: string): ConditionCoverage {
  const metadata = (notice.rules || []).filter((r) => r.kind === 'condition_coverage' && r.effect === 'metadata')
  const scopes = metadata.flatMap((r) => Array.isArray(r.scopes) ? r.scopes.filter((s): s is Record<string, unknown> => !!s && typeof s === 'object').map((scope) => ({ scope, rule: r, official: r.verification === 'official', documentHash: typeof r.document_hash === 'string' ? r.document_hash : null })) : [])
  const matched = scopes.filter(({ scope }) => scopedRule({ ...scope, kind: 'condition_coverage' } as NoticeRule, unitType, supplyType))
  const selected = (notice.rules || []).filter((r) => !applicationProcedure(r) && r.effect !== 'metadata' && r.effect !== 'priority' && r.purpose !== 'first_rank' && r.verification === 'official' && scopedRule(r, unitType, supplyType))
  const topics = matched.flatMap(({ scope, official }) => official && Array.isArray(scope.topics) ? scope.topics.filter((topic): topic is Record<string, unknown> => !!topic && typeof topic === 'object').map((topic) => ({ topic: String(topic.topic || ''), status: ['verified', 'partial', 'missing', 'not_applicable'].includes(String(topic.status)) ? topic.status as 'verified' | 'partial' | 'missing' | 'not_applicable' : 'missing' as const, ruleIds: Array.isArray(topic.rule_ids) ? topic.rule_ids.filter((id): id is string => typeof id === 'string') : [], required: topic.required !== false && !['application', 'post_selection'].includes(String(topic.phase)), reason: typeof topic.reason === 'string' ? topic.reason : undefined })) : [])
  const changedDocument = matched.some(({ documentHash }) => documentHash && selected.some((rule) => typeof rule.document_hash === 'string' && rule.document_hash !== documentHash))
  const pendingAttachment = latestAttachmentUnreviewed(notice, [...selected, ...matched.map(({ rule }) => rule)])
  return {
    complete: !changedDocument && !pendingAttachment && (metadata.length ? matched.length > 0 && matched.every(({ scope, official }) => official && scope.complete === true) : notice.rules_complete === true) && topics.every((topic) => !topic.required || ['verified', 'not_applicable'].includes(topic.status)),
    verifiedCount: selected.length,
    missingTopics: [...new Set([...matched.flatMap(({ scope }) => !Array.isArray(scope.topics) && Array.isArray(scope.missing_topics) ? scope.missing_topics.filter((x): x is string => typeof x === 'string').map(concreteMissingTopic) : []), ...topics.filter((topic) => topic.required && !['verified', 'not_applicable'].includes(topic.status)).map((topic) => concreteMissingTopic(topic.reason || topic.topic)), ...(changedDocument ? ['신청 조건과 분기별 검토 기록의 문서 해시 불일치'] : []), ...(pendingAttachment ? ['최신 모집공고 첨부의 신청 제한·면제 원문 미확보'] : [])])],
    status: metadata.length ? String(metadata[metadata.length - 1].status || 'partial') : selected.length ? 'partial' : 'unsupported',
    topics,
  }
}
export function evaluateQualification(notice: Notice, profile: LocalProfile = EMPTY_PROFILE, unitType?: string, supplyType?: string): EligibilityResult {
  const inventory = officialOfferedSupplies(notice)
  supplyType ||= singleOfferedSupplyType(notice)
  if (inventory && supplyType && !inventory.some((supply) => compact(supply.supply_type) === compact(supplyType) && (!unitType || !supply.unit_type || supply.unit_type === unitType))) return { status: 'unpublished', reasons: [{ status: 'review', category: 'selection', label: '모집하지 않는 공급유형', detail: `이 공고는 ${supplyType}${unitType ? ` · ${unitType}` : ''} 조합을 모집하지 않습니다.`, evidenceUrl: notice.official_url }] }
  // Source uncertainty cannot create a referral the applicant explicitly
  // says they do not have. Other offered paths still compare independently.
  if (supplyType && specialType(supplyType) === 'institution' && (profile.recommendationReason === 'none' || profile.recommendationStatus === 'none')) return {
    status: 'mismatch', reasons: [{ status: 'fail', category: 'condition', label: '기관추천 대상·추천 상태',
      detail: profile.recommendationReason === 'none' ? '기관추천 대상 사유에 해당 없음으로 입력했습니다.' : '기관 추천이 없다고 입력했습니다.',
      input: profile.recommendationReason === 'none' ? '해당 없음' : '추천 없음', requirement: '기관추천 대상 및 기관의 확정 추천' }],
  }
  const coverage = conditionCoverage(notice, unitType, supplyType)
  // Standalone extraction candidates remain available in the collapsed source
  // panel. Once this exact scope has complete official conditions, candidates
  // cannot add another mandatory requirement or invalidate that verified set.
  const completeOfficialScope = coverage.complete && coverage.verifiedCount > 0
  const relevant = (notice.rules || []).filter((rule) => !applicationProcedure(rule) && (!completeOfficialScope || rule.verification === 'official') && rule.effect !== 'metadata' && rule.effect !== 'priority' && rule.purpose !== 'first_rank' &&
    (!unitType || (!rule.unit_type || rule.unit_type === unitType) && (!Array.isArray(rule.unit_types) || rule.unit_types.includes(unitType))) && (!supplyType || (!rule.supply_type || compact(rule.supply_type) === compact(supplyType)) && (!Array.isArray(rule.supply_types) || rule.supply_types.includes(supplyType))))
  const selected = relevant.filter((rule) => scopedRule(rule, unitType, supplyType))
  const needsSelection = relevant.some((rule) => ((rule.unit_type || Array.isArray(rule.unit_types)) && !unitType) || ((rule.supply_type || Array.isArray(rule.supply_types)) && !supplyType))
  const applicationRegion = applicantRegionEligibility(notice, profile, { unitType, supplyType })
  if (!selected.length && !needsSelection) {
    const gap: EligibilityReason = { status: 'review', category: 'source_gap', label: '공고 조건 정리 중', detail: '공고문 조건을 아직 정리하지 못했습니다. 공식 공고문에서 신청 요건을 확인할 수 있습니다.', evidenceUrl: notice.official_url }
    return applicationRegion ? result([applicationRegion, gap]) : { status: (notice.rules || []).some((rule) => rule.effect === 'priority') ? 'review' : 'unpublished', reasons: [gap] }
  }
  let reasons = selected.map((rule) => evaluateRule({ ...rule, supply_type: rule.supply_type || supplyType }, profile, notice, unitType))
  if (applicationRegion && !reasons.some((entry) => entry.ruleId && entry.ruleId === applicationRegion.ruleId)) reasons.unshift(applicationRegion)
  // One established failure is sufficient to close this supply path. Asking
  // its remaining personal facts cannot change that failure; other paths are
  // still evaluated independently by specialDiagnostics/eligibilityCombinations.
  if (supplyType && reasons.some((entry) => entry.status === 'fail')) reasons = reasons.filter((entry) => !['missing_input', 'past_fact'].includes(entry.category || ''))
  if (needsSelection) reasons.push({ status: 'review', category: 'selection', label: '유형별 조건 비교', detail: '주택형 또는 공급유형별 조건이 다릅니다. 해당 유형의 근거를 확인하세요.', evidenceUrl: notice.official_url })
  if (supplyType && !isGeneralSupply(supplyType)) {
    const expected: Record<SpecialType, string[]> = {
      newlywed: ['marital_status', 'marriage_months_max'], newborn: ['newborn_children_min'], first_home: ['never_owned_home'],
      multi_child: ['children_min'], elder_parent: ['parent_age_min', 'parent_support_months_min'], institution: ['recommendation'],
      young: ['age_min', 'age_max'], relocation: ['relocated_worker'], other: [],
    }
    const type = specialType(supplyType), kinds = allKinds(selected)
    const certifiedType = (notice.rules || []).some((rule) => rule.kind === 'condition_coverage' && rule.verification === 'official' && Array.isArray(rule.scopes) && rule.scopes.some((scope) => scope && typeof scope === 'object' && scope.supply_type === supplyType && scope.complete === true))
    if (!certifiedType && (!expected[type].length || !expected[type].some((kind) => kinds.includes(kind)))) reasons.push({ status: 'review', category: 'source_gap', label: '미확보 유형별 요건', detail: `${supplyType}의 ${expected[type].length ? expected[type].map((kind) => ({ marital_status: '혼인 상태', marriage_months_max: '혼인 기간', newborn_children_min: '신생아 출생 기준', never_owned_home: '과거 주택 소유', children_min: '미성년 자녀 수', parent_age_min: '부양 부모 나이', parent_support_months_min: '연속 부양 기간', recommendation: '기관 추천', age_min: '최소 나이', age_max: '최대 나이', relocated_worker: '이전기관 근로' })[kind]).join('·') : '신청자격 조항'} 원문 근거가 미확보입니다.`, evidenceUrl: notice.official_url })
  }
  if (!coverage.complete && !(needsSelection && !coverage.missingTopics.length)) reasons.push({ status: 'review', category: 'source_gap', label: '미확보 공고 조항', detail: coverage.missingTopics.length ? `서비스가 확보하지 못한 조항·검토 항목: ${coverage.missingTopics.join(' · ')}.` : '이 신청 분기의 필수 요건·면제 검토 기록을 확보하지 못했습니다. 문서 해시에 연결된 분기별 검토 기록이 필요합니다.', evidenceUrl: notice.official_url })
  return result(reasons)
}

function baselineRankReasons(notice: Notice, profile: LocalProfile): EligibilityReason[] {
  const privateHousing = notice.housing_kind === 'private'
  const kind = privateHousing ? '민영' : '국민'
  const source = privateHousing ? law28 : law27
  const date = criterionDate({ kind: 'baseline' }, notice)
  const start = privateHousing ? profile.privateRankBaseDate : profile.nationalRankBaseDate
  const months = date && start ? fullMonths(start, date) : null
  const context = notice.qualification_context
  const zone = context?.speculation_zone === true || context?.subscription_overheated === true
  const normal = context?.speculation_zone === false && context?.subscription_overheated === false
  const baselineMonths = zone ? 24 : normal && context?.weakened_area === true ? 1 : normal && context?.weakened_area === false && typeof context?.capital_region === 'boolean' ? context.capital_region ? 12 : 6 : null
  const lawDateKnown = !!date && date >= '2026-06-15'
  const period: EligibilityReason = {
    status: 'review', label: `${kind} 순위 인정기간`,
    detail: months === null ? `${kind} 순위기산일과 공식 기준일을 확인해야 합니다.` : `${kind} 순위기산일 ${start} → 기준일 ${date}: ${months}개월. ${baselineMonths === null ? '규제·위축지역과 공고의 기간 기준은 추가 확인이 필요합니다.' : `현행 법령 기본 ${baselineMonths}개월과 비교합니다. 공고의 연장 기준·경과조치를 별도로 확인해야 합니다.`}`,
    input: months === null ? undefined : `${months}개월`, category: months === null && !start ? 'missing_input' : 'source_gap', profileField: privateHousing ? 'privateRankBaseDate' : 'nationalRankBaseDate', requirement: baselineMonths === null ? '규제지역 24개월 · 수도권 기본 12개월 · 그 외 기본 6개월 · 위축지역 1개월; 공고 확인' : `현행 기본 >= ${baselineMonths}개월; 공고 확인`, criterionDate: date, evidenceUrl: source,
  }
  if (lawDateKnown && context?.public_housing === false && baselineMonths !== null && months !== null) { period.status = months >= baselineMonths ? 'pass' : 'fail'; period.category = 'condition' }
  const amount = numberFrom(privateHousing ? profile.privateDepositKrw : profile.nationalRecognizedPayments, true)
  const money: EligibilityReason = privateHousing ? {
    status: 'review', label: '민영주택 예치금', detail: `내 예치금 ${amount === null ? '미입력' : `${amount.toLocaleString('ko-KR')}원`}. 공식 거주지 구분과 신청 면적별 예치기준금액을 확인해야 합니다.`, input: amount === null ? undefined : `${amount.toLocaleString('ko-KR')}원`, category: amount === null ? 'missing_input' : 'source_gap', profileField: 'privateDepositKrw', requirement: '공식 지역·신청 면적별 예치기준금액', criterionDate: date, evidenceUrl: source,
  } : {
    status: 'review', label: '국민주택 납입인정횟수', detail: `내 납입인정횟수 ${amount === null ? '미입력' : `${amount}회`}. ${zone ? '규제지역 기본 24회' : normal && context?.capital_region === true ? '수도권 기본 12회' : normal && context?.capital_region === false ? '수도권 외 기본 6회' : '공고의 지역·적용 법령별 횟수'}와 비교하며 공식 연장 기준과 인정 범위를 확인해야 합니다.`, input: amount === null ? undefined : `${amount}회`, category: amount === null ? 'missing_input' : 'source_gap', profileField: 'nationalRecognizedPayments', requirement: zone ? '기본 >= 24회; 공고 확인' : normal && typeof context?.capital_region === 'boolean' ? `기본 >= ${context.capital_region ? 12 : 6}회; 공고 확인` : '지역·법령별 공식 횟수 확인', criterionDate: date, evidenceUrl: source,
  }
  if (!privateHousing && lawDateKnown && context?.public_housing === false && amount !== null && baselineMonths !== null && baselineMonths > 1) { money.status = amount >= baselineMonths ? 'pass' : 'fail'; money.category = 'condition' }
  const reasons = [period, money]
  if (zone) reasons.push({ status: profile.isHouseholdHead === true ? 'pass' : profile.isHouseholdHead === false && context?.public_housing === false && lawDateKnown ? 'fail' : 'review', label: '규제지역 세대주', detail: `세대주 입력 ${profile.isHouseholdHead === null ? '미확인' : profile.isHouseholdHead ? '예' : '아니오'}. 규제지역은 세대주·세대 당첨 이력·주택 보유 요건도 확인합니다.`, input: profile.isHouseholdHead === null ? '미확인' : profile.isHouseholdHead ? '예' : '아니오', requirement: '세대주 및 추가 세대 요건', criterionDate: date, evidenceUrl: source })
  return reasons
}

/** Complete rank coverage is independent of a notice's remaining eligibility rules. */
export function deriveRank(notice: Notice, profile: LocalProfile, unitType?: string): RankResult {
  const applicability = notice.rank_applicability
  if (applicability?.verification === 'official' && applicability.status === 'not_applicable') return {
    status: 'possible', rank: 'not_applicable', label: '아파트 1·2순위 적용 없음',
    reasons: [{ status: 'pass', category: 'condition', label: '순위 적용 없음', detail: applicability.reason || '이 공고에는 아파트 일반공급 1·2순위가 적용되지 않습니다.', requirement: applicability.account_required === false ? '청약통장 불필요' : undefined, evidenceUrl: applicability.evidence_url, evidenceText: applicability.evidence_text }],
  }
  const kind = notice.housing_kind, prefix = kind === 'private' ? '민영주택' : '국민주택'
  const evidence = notice.housing_kind_evidence
  if (!['private', 'national'].includes(kind || '') || evidence?.verification !== 'official') return {
    rank: 'unknown', status: 'review', label: '순위 적용 조건 정리 중',
    reasons: [{ status: 'review', category: 'source_gap', label: '공고의 순위 적용 방식', detail: '공고의 주택 종류와 순위 적용 방식을 아직 정리하지 못했습니다.', evidenceUrl: evidence?.evidence_url || notice.official_url }],
  }
  const rankRules = (notice.rules || []).filter((r) => r.effect !== 'metadata' && !r.supply_type && r.kind !== 'first_rank' && (r.purpose === 'first_rank' || ['private_rank_months', 'national_rank_months'].includes(r.kind)))
  const applicable = rankRules.filter((r) => (!r.housing_kind || r.housing_kind === kind) && (!r.unit_type || r.unit_type === unitType)).filter((r) => kind === 'private' ? r.kind !== 'national_rank_months' : r.kind !== 'private_rank_months')
  const metadata = (notice.rules || []).find((r) => r.effect === 'metadata' && r.verification === 'official' && r.kind === 'rank_requirements' && (!r.housing_kind || r.housing_kind === kind) && (!r.unit_type || r.unit_type === unitType))
  const reasons: EligibilityReason[] = []
  if (profile.accountType === 'unknown') reasons.push({ status: 'review', category: 'missing_input', profileField: 'accountType', label: '통장 종류', detail: '보유한 청약통장 종류를 선택하세요.' })
  if (profile.accountType === 'none') reasons.push({ status: 'fail', category: 'condition', label: '통장 종류', detail: '청약통장이 없다고 입력했습니다. 통장이 필요한 1순위 요건을 충족하지 않습니다.' })
  reasons.push(...applicable.map((r) => evaluateRule({ ...r, criterion_date: r.criterion_date || metadata?.criterion_date }, profile, notice, unitType)))
  if (!applicable.length) reasons.push(...baselineRankReasons(notice, profile))
  const kinds = allKinds(applicable)
  const hasDuration = kinds.some((k) => ['subscription_months', 'private_rank_months', 'national_rank_months'].includes(k))
  const hasMoney = kind === 'private' ? kinds.includes('deposit_min_krw') : kinds.includes('recognized_payments_min')
  const required = Array.isArray(metadata?.required_kinds) ? metadata.required_kinds.filter((k): k is string => typeof k === 'string') : []
  const complete = metadata?.complete === true || applicable.some((r) => r.rank_rules_complete === true && r.verification === 'official')
  const unitScopeMissing = !unitType && rankRules.some((r) => r.unit_type)
  if (!hasDuration || !hasMoney || !kinds.includes('account_type') || !complete || required.some((k) => !kinds.includes(k)) || unitScopeMissing) reasons.push({ status: 'review', category: 'source_gap', label: '공고별 1순위 요건', detail: unitScopeMissing ? '주택형별 예치금·통장 요건이 다릅니다. 각 주택형의 순위 비교를 확인하세요.' : `${prefix} 기간·${kind === 'private' ? '지역·전용면적별 예치금' : '납입인정횟수'}·통장 종류와 공고의 추가 1순위 요건을 확인하고 있습니다.`, evidenceUrl: metadata?.evidence_url || (kind === 'private' ? law28 : law27) })
  const assessed = result(reasons), first = assessed.status === 'possible'
  return { ...assessed, rank: first ? 'first' : 'unknown', label: first ? `${prefix} 1순위 조건 충족` : `${prefix} 1순위 ${assessed.status === 'mismatch' ? '요건 불일치' : '확인 필요'}` }
}

export function unitRankResults(notice: Notice, profile: LocalProfile): { unitType: string; result: RankResult }[] {
  return [...new Set((notice.prices || []).map((price) => price.unit_type))].map((unitType) => ({ unitType, result: deriveRank(notice, profile, unitType) }))
}

export interface RegionScopeSelection { supplyType?: string; unitType?: string }
export type RegionDecisionStatus = 'local' | 'other_gyeonggi' | 'other' | 'outside' | 'not_divided' | 'missing_input' | 'source_gap'
export interface RegionDecision {
  status: RegionDecisionStatus
  reason: string
  reasons: EligibilityReason[]
  criterionDate: string | null
  supplyType?: string
  unitType?: string
  evidenceUrl?: string | null
  evidenceText?: string | null
}

function applicantRegionMetadata(notice: Notice, selection: RegionScopeSelection): NoticeRule | undefined {
  const candidates = (notice.rules || []).filter((rule) => rule.kind === 'applicant_regions' && rule.effect === 'metadata' && rule.verification === 'official')
  const exact = candidates.filter((rule) => scopedRule(rule, selection.unitType, selection.supplyType))
    .sort((a, b) => Number(!!b.supply_type) + Number(!!b.unit_type) - Number(!!a.supply_type) - Number(!!a.unit_type))[0]
  if (exact || selection.supplyType || selection.unitType || !candidates.length) return exact
  // A notice summary can use identical regional scopes shared by every offer.
  const signature = (rule: NoticeRule) => JSON.stringify(['regions', 'unrestricted', 'domestic_only', 'local_priority', 'other_gyeonggi', 'priority_applicable', 'priority_division', 'exceptions', 'criterion_date', 'criterion_basis'].map((key) => rule[key]))
  return candidates.every((rule) => signature(rule) === signature(candidates[0])) ? { ...candidates[0], supply_type: null, unit_type: null, unit_types: undefined } : undefined
}
function regionMilitaryException(metadata: NoticeRule, profile: LocalProfile, notice: Notice, area?: string): EligibilityReason | null {
  const exceptions = Array.isArray(metadata.exceptions) ? metadata.exceptions.filter((entry): entry is Record<string, unknown> => !!entry && typeof entry === 'object') : []
  const military = exceptions.find((entry) => entry.kind === 'military_service_years' && (!area || entry.residence_area === area))
  if (!military) return null
  return evaluateRule({ ...metadata, ...military, effect: undefined, exceptions: undefined, kind: 'military_service_years', value: numberFrom(military.min_years ?? military.value), require_as_of_date: true }, profile, notice)
}

/** Official applicant scope is a prerequisite to treating a person as 'other region'. */
export function applicantRegionEligibility(notice: Notice, profile: LocalProfile, selection: RegionScopeSelection = {}): EligibilityReason | null {
  let metadata = applicantRegionMetadata(notice, selection)
  if (!metadata) return null
  if (metadata.criterion_basis === 'contract_date') metadata = { ...metadata, criterion_date: contractEvaluationDate(notice) }
  const date = criterionDate(metadata, notice)
  profile = profileForResidenceDate(profile, date)
  if (metadata.scope_complete === false) return unsupported(metadata, notice, '공식 신청 지역 범위와 거주 예외를 아직 대조하지 못했습니다.', '신청 가능한 지역')
  if (metadata.domestic_only === true) {
    const supplyType = selection.supplyType || singleOfferedSupplyType(notice)
    const equivalenceRules = notice.rules.filter((rule) => rule.kind === 'domestic_residence' && rule.verification === 'official' && rule.overseas_residence_equivalence === true && criterionDate(rule, notice) === date && (!metadata.document_hash || rule.document_hash === metadata.document_hash))
    const equivalence = equivalenceRules.find((rule) => scopedRule(rule, selection.unitType, supplyType))
    const domestic = evaluateRule(equivalence ? { ...equivalence, supply_type: equivalence.supply_type || supplyType } : { ...metadata, kind: 'domestic_residence', effect: undefined, exceptions: undefined, value: true }, profile, notice, selection.unitType)
    if (domestic.status === 'fail' && !supplyType && equivalenceRules.length) return { ...reason(metadata, notice, 'review', '공급유형별 국내 거주 인정 범위', '공식 해외 체류 예외는 해당 공급유형에만 적용됩니다. 모집 유형별 신청 조건에서 국내 거주 인정 여부를 비교합니다.'), category: 'selection' }
    if (domestic.status !== 'pass') return domestic
  }
  if (metadata.unrestricted === true) return reason(metadata, notice, 'pass', '신청 가능한 지역', '공식 공고는 신청 지역을 제한하지 않습니다. 해당지역 우선배정 여부는 별도로 비교합니다.', `${profile.region} ${profile.district}`.trim() || '주소 입력 불필요', '지역 제한 없음')
  const regions = Array.isArray(metadata.regions) ? metadata.regions.filter((r): r is Record<string, unknown> => !!r && typeof r === 'object') : []
  const scopes = regions.map((r) => ({ region_code: typeof (r.region_code || r.code) === 'string' ? String(r.region_code || r.code) : null, region_name: typeof (r.region_name || r.name) === 'string' ? String(r.region_name || r.name) : null }))
  const labels = scopes.map((s) => s.region_name || s.region_code).filter(Boolean).join(' · ')
  if (!scopes.length) return unsupported(metadata, notice, '공식 신청 지역의 세부 범위를 아직 정리하지 못했습니다.', '신청 가능한 지역')
  if (!profile.region && !profile.regionCode) return missingInput(metadata, notice, '신청 가능한 지역', '현재 거주 시도를 선택하면 공고의 신청 지역과 비교합니다.', labels, 'regionCode')
  if (!date) return unsupported(metadata, notice, '신청 지역을 비교할 공식 기준일이 필요합니다.', '공고 기준일 거주지역')
  if (profile.regionNeedsReview) return missingInput(metadata, notice, '신청 가능한 지역', '공고 기준일의 시도·시군구를 다시 확인해 공식 신청 범위와 비교하세요.', labels, 'regionCode')
  const matches = scopes.map((scope) => matchesRegionScope(profile, scope, date))
  const histories = scopes.map((scope, index) => matches[index] === null ? null : residenceCutoffReview({ ...metadata, ...scope }, profile, notice, labels))
  if (matches.some((match, index) => match === true && !histories[index])) return reason(metadata, notice, 'pass', '신청 가능한 지역', '내 거주지가 공고의 공식 신청 지역에 포함됩니다.', `${profile.region} ${profile.district}`, labels)
  if (matches.includes(null)) return missingInput(metadata, notice, '신청 가능한 지역', '공고 기준일의 시도·시군구를 다시 선택하면 공식 신청 범위와 비교합니다.', labels, 'regionCode')
  const historical = histories.find((entry) => entry !== null)
  const military = regionMilitaryException(metadata, profile, notice)
  if (military?.status === 'pass') return { ...military, ruleId: metadata.id, label: '장기복무군인 신청 지역 예외' }
  if (historical) return historical
  if (military?.status === 'review') return { ...military, label: '장기복무군인 신청 지역 예외', detail: `내 거주지는 ${labels} 신청 범위 밖입니다. ${military.detail}` }
  if (historical) return historical
  return reason(metadata, notice, 'fail', '신청 가능한 지역', `내 거주지 ${profile.region} ${profile.district}는 이 공고의 ${labels} 신청 범위 밖입니다.`, `${profile.region} ${profile.district}`, labels)
}

/** Applicant admission and regional allocation are deliberately separate decisions. */
export function regionDecision(notice: Notice, profile: LocalProfile, selection: RegionScopeSelection = {}): RegionDecision {
  const metadata = applicantRegionMetadata(notice, selection)
  const admitted = applicantRegionEligibility(notice, profile, selection)
  const date = metadata ? criterionDate(metadata, notice) : null
  const finish = (status: RegionDecisionStatus, detail: string, reasons: EligibilityReason[] = admitted ? [admitted] : []): RegionDecision => ({ status, reason: detail, reasons, criterionDate: date, ...selection, evidenceUrl: metadata?.evidence_url || notice.official_url, evidenceText: metadata?.evidence_text || metadata?.text })
  if (admitted?.status === 'fail') return finish('outside', admitted.detail)
  if (admitted?.status === 'review') return finish(admitted.category === 'missing_input' ? 'missing_input' : 'source_gap', admitted.detail)
  if (!metadata || !admitted) return finish('source_gap', '이 공고의 공식 신청 지역과 지역 배정 범위를 아직 대조하지 못했습니다.')
  if (metadata.priority_division === 'none' || metadata.priority_applicable === false) return finish('not_divided', '공식 공고는 해당지역·기타지역을 나누지 않습니다. 신청 지역 요건은 충족합니다.')
  const home = profileForResidenceDate(profile, date)
  const objectScope = (value: unknown): Record<string, unknown> | null => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
  const local = objectScope(metadata.local_priority)
  const priorityRules = (notice.rules || []).filter((rule) => rule.verification === 'official' && rule.effect === 'priority' && scopedRule(rule, selection.unitType, selection.supplyType) && ['residence_months', 'residence_region', 'residence_area', 'region'].includes(rule.kind))
  // Admission exceptions may allocate "other"; compare local exceptions
  // separately rather than inheriting them into the ordinary local rule.
  const localRules: NoticeRule[] = local ? [{ ...metadata, ...local, exceptions: undefined, effect: 'priority', kind: local.min_months == null ? 'residence_region' : 'residence_months', value: typeof local.min_months === 'number' ? local.min_months : null, region_code: typeof local.region_code === 'string' ? local.region_code : null, region_name: typeof (local.region_name || local.name) === 'string' ? String(local.region_name || local.name) : null }]
    : priorityRules.filter((rule) => !['other', 'other_gyeonggi'].includes(String(rule.value)))
  const mapping = objectScope(local?.mapping_evidence)
  if (local && Array.isArray(local.regions) && local.regions.length && metadata.document_hash && mapping?.document_hash === metadata.document_hash && typeof mapping.evidence_url === 'string' && typeof mapping.evidence_text === 'string' && mapping.evidence_text) {
    const mapped = local.regions.map(objectScope)
    if (mapped.every((scope) => scope && typeof scope.region_code === 'string' && typeof scope.region_name === 'string')) {
      const base = localRules[0]
      localRules.splice(0, localRules.length, { ...base, kind: 'any', label: '공식 해당지역의 지역·거주기간', conditions: mapped.map((scope) => ({ ...base, ...scope, effect: undefined, residence_union: mapped.length > 1 && Number(local.min_months) > 0 })) })
    }
  }
  if (!localRules.length) return finish('source_gap', '신청 지역 요건은 충족합니다. 해당지역 우선권·기타지역 배정 조건은 아직 대조하지 못했습니다.')
  const militaryLocal = regionMilitaryException(metadata, profile, notice, 'local')
  if (militaryLocal?.status === 'pass') return finish('local', '공고가 명시한 장기복무군인 해당지역 배정 예외를 충족합니다.', [admitted, militaryLocal])
  const compared = localRules.map((rule): EligibilityReason => {
    const effective = { ...rule, criterion_date: rule.criterion_date || date, effect: undefined }
    const provenance = effective.kind === 'any' ? null : residenceCutoffReview(effective, home, notice)
    if (provenance) return provenance
    return evaluateRule(effective, home, notice, selection.unitType)
  })
  if (compared.some((entry) => entry.status === 'review')) return finish(compared.some((entry) => entry.category === 'missing_input') ? 'missing_input' : 'source_gap', compared.filter((entry) => entry.status === 'review').map((entry) => entry.detail).join(' / '), [...(admitted ? [admitted] : []), ...compared])
  if (compared.every((entry) => entry.status === 'pass')) return finish('local', compared.map((entry) => entry.detail).join(' / '), [admitted, ...compared])
  const province = home.regionCode || provinceCode(home.region)
  const explicitOtherGyeonggi = priorityRules.some((rule) => rule.kind === 'residence_area' && rule.value === 'other_gyeonggi' && matchesRegionScope(home, rule, criterionDate(rule, notice)) === true)
  const gyeonggiScope = objectScope(metadata.other_gyeonggi)
  const otherGyeonggi = province === '41' && (explicitOtherGyeonggi || !!gyeonggiScope && matchesRegionScope(home, { region_code: typeof gyeonggiScope.region_code === 'string' ? gyeonggiScope.region_code : '41', region_name: typeof gyeonggiScope.region_name === 'string' ? gyeonggiScope.region_name : '경기도' }, date) === true)
  if (militaryLocal?.status === 'review') return finish(militaryLocal.category === 'missing_input' ? 'missing_input' : 'source_gap', militaryLocal.detail, [admitted, ...compared, militaryLocal])
  return finish(otherGyeonggi ? 'other_gyeonggi' : 'other', `${compared.map((entry) => entry.detail).join(' / ')} · 신청 지역 요건을 충족하여 ${otherGyeonggi ? '기타경기' : '기타지역'} 배정 대상입니다.`, [admitted, ...compared])
}

export function specialType(value: string): SpecialType {
  const text = compact(value).toLowerCase()
  if (/신생아|newborn/.test(text)) return 'newborn'
  if (/신혼|newlywed/.test(text)) return 'newlywed'
  if (/생애최초|first.?home/.test(text)) return 'first_home'
  if (/다자녀|multi.?child/.test(text)) return 'multi_child'
  if (/노부모|elder.?parent/.test(text)) return 'elder_parent'
  if (/기관추천|institution/.test(text)) return 'institution'
  if (/청년|young/.test(text)) return 'young'
  if (/이전기관|relocation/.test(text)) return 'relocation'
  return 'other'
}
export function offeredSpecialSupplies(notice: Notice): string[] {
  const inventory = officialOfferedSupplies(notice)
  if (inventory) return [...new Set(inventory.filter((supply) => !isGeneralSupply(supply.supply_type)).map((supply) => supply.supply_type))]
  const supplies = (notice.rules || []).filter((r) => r.effect !== 'metadata' && r.verification === 'official').flatMap((r) => r.supply_type && !isGeneralSupply(r.supply_type) ? [r.supply_type] : r.kind === 'special_eligibility' && typeof r.value === 'string' ? [r.value] : [])
  for (const metadata of (notice.rules || []).filter((r) => r.kind === 'condition_coverage' && r.effect === 'metadata' && r.verification === 'official')) {
    if (Array.isArray(metadata.offered_supply_types)) for (const supply of metadata.offered_supply_types) if (typeof supply === 'string' && !isGeneralSupply(supply)) supplies.push(supply)
  }
  for (const event of notice.events || []) {
    if (/special|특별/.test(`${event.kind} ${event.label}`)) {
      const label = event.label
      if (!supplies.some((s) => compact(s) === compact(String(label))) && (specialType(String(label)) !== 'other' || !supplies.length)) supplies.push(String(label))
    }
  }
  return [...new Set(supplies)]
}
export function specialDiagnostics(notice: Notice, profile: LocalProfile): SpecialDiagnosis[] {
  return offeredSpecialSupplies(notice).map((supplyType) => ({ supplyType, type: specialType(supplyType), result: evaluateQualification(notice, profile, undefined, supplyType) }))
}
