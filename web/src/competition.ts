import type { LocalProfile, Notice, NoticeCompetition, NoticeEvent, NoticeRule, ResidenceArea } from './types'
import { matchesRegionScope, scopeIsDistrict, provinceAliases, provinceCode, provinceOptions } from './regions'
import { criterionDate, deriveRank, fullMonths, numberFrom, offeredSpecialSupplies, specialDiagnostics, residenceStartDate, applicantRegionEligibility, regionDecision, isGeneralSupply } from './qualification'

export const RESIDENCE_AREA_LABEL: Record<ResidenceArea, string> = {
  local: '해당지역', other_gyeonggi: '기타경기', other: '기타지역', unknown: '지역 확인 필요',
}

export function competitionUnitKey(value: string): string { return value.replace(/[.\s]/g, '').toUpperCase() }

function durationPass(rule: NoticeRule, notice: Notice, profile: LocalProfile): boolean | null {
  if (rule.kind !== 'residence_months') return true
  const date = criterionDate(rule, notice)
  const start = residenceStartDate(rule, profile)
  const months = date && start ? fullMonths(start, date) : null
  const required = numberFrom(rule.value, true)
  if (months === null || required === null) return null
  const operator = rule.operator || '>='
  if (operator === '>=') return months >= required
  if (operator === '>') return months > required
  if (operator === '=') return months === required
  return null
}
function scopeProvince(rule: NoticeRule): string | null {
  const code = rule.region_code?.slice(0, 2)
  if (code && provinceOptions().some((p) => p.code === code)) return code
  const name = rule.region_name?.replace(/\s+/g, '') || ''
  return provinceOptions().find((p) => provinceAliases(p.name).some((alias) => name.startsWith(alias)))?.code || null
}
function officialMetadata(notice: Notice, kind: string): NoticeRule | undefined {
  return (notice.rules || []).find((rule) => rule.kind === kind && rule.effect === 'metadata' &&
    rule.verification === 'official' && !!(rule.evidence_url || rule.evidence_text || rule.text))
}

function regionScope(value: unknown): { region_code?: string; region_name?: string; [key: string]: unknown } | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  const code = record.region_code || record.code, name = record.region_name || record.name
  if (typeof code !== 'string' && typeof name !== 'string') return null
  return { ...record, region_code: typeof code === 'string' ? code : undefined, region_name: typeof name === 'string' ? name : undefined }
}

/** Other-region membership needs an official applicant scope, not a different address. */
export function residenceArea(notice: Notice, profile: LocalProfile, override?: ResidenceArea): ResidenceArea {
  const automatic = regionDecision(notice, profile, { supplyType: '일반공급' })
  if (automatic.status === 'outside' || applicantRegionEligibility(notice, profile)?.status === 'fail') return 'unknown'
  if (override) return override
  const currentScope = (notice.rules || []).some((rule) => rule.kind === 'applicant_regions' && rule.verification === 'official' && rule.scope_complete === true)
  if (currentScope) return ['local', 'other_gyeonggi', 'other'].includes(automatic.status) ? automatic.status as ResidenceArea : 'unknown'
  if ((!profile.region && !profile.regionCode) || profile.regionNeedsReview) return 'unknown'
  const applicant = officialMetadata(notice, 'applicant_regions')
  const accepted = applicantRegionEligibility(notice, profile)
  if (accepted?.status === 'fail' || applicant && accepted?.status !== 'pass') return 'unknown'
  const rules = (notice.rules || []).filter((rule) => rule.verification === 'official' && rule.effect === 'priority' &&
    !rule.unit_type && !rule.supply_type && ['residence_months', 'residence_region', 'residence_area', 'region'].includes(rule.kind) &&
    (rule.evidence_url || rule.evidence_text || rule.text || notice.official_url))
  const metadataLocal = regionScope(applicant?.local_priority)
  const localRules: NoticeRule[] = metadataLocal ? [{
    ...metadataLocal, kind: metadataLocal.min_months == null ? 'residence_region' : 'residence_months',
    value: typeof metadataLocal.min_months === 'number' ? metadataLocal.min_months : null,
    verification: 'official', effect: 'priority', criterion_date: metadataLocal.criterion_date || applicant?.criterion_date,
  }] : rules.filter((rule) => rule.value !== 'other_gyeonggi' && rule.value !== 'other')
  if (!localRules.length) return 'unknown'
  const matches = localRules.map((rule) => matchesRegionScope(profile, rule, criterionDate(rule, notice)))
  if (matches.some((match) => match === null) || new Set(matches).size !== 1) return 'unknown'
  const provinces = localRules.map(scopeProvince)
  if (provinces.some((p) => !p) || new Set(provinces).size !== 1) return 'unknown'
  const homeProvince = profile.regionCode || provinceCode(profile.region)
  if (matches.every((match) => match === true)) {
    const durations = localRules.map((rule) => durationPass(rule, notice, profile))
    if (durations.every((pass) => pass === true)) return 'local'
    if (durations.some((pass) => pass === null)) return 'unknown'
  }
  const hasOtherGyeonggi = rules.some((rule) => rule.kind === 'residence_area' && rule.value === 'other_gyeonggi' &&
    scopeProvince(rule) === '41' && !scopeIsDistrict(rule))
  if (accepted?.status === 'pass') return homeProvince === '41' && hasOtherGyeonggi ? 'other_gyeonggi' : 'other'
  // Legacy explicit area rules can identify a group, but cannot turn every
  // different province into the unbounded “other” group.
  const explicitOther = rules.some((rule) => rule.kind === 'residence_area' && rule.value === 'other' &&
    matchesRegionScope(profile, rule, criterionDate(rule, notice)) === true)
  if (explicitOther) return 'other'
  return homeProvince === '41' && hasOtherGyeonggi ? 'other_gyeonggi' : 'unknown'
}

export function competitionFresh(notice: Notice, now = Date.now()): boolean {
  const state = notice.competition
  if (!state || state.proof_invalidated === true || !['ok', 'partial'].includes(state.status) || !state.last_success_at || !state.last_attempt_at) return false
  const success = Date.parse(state.last_success_at)
  const attempt = Date.parse(state.last_attempt_at)
  return Number.isFinite(success) && Number.isFinite(attempt) && success >= attempt &&
    success <= now + 60_000 && now - success <= 6 * 60 * 60 * 1000
}

export interface CompetitionClosureProof {
  unitType: string
  kind: 'explicit_local_first_closed' | 'all_local_first_exhausted'
  reason: string
  competitionEvidenceUrl: string
  competitionEvidenceText: string
  observedAt: string
  allocationEvidenceUrl?: string | null
  allocationEvidenceText?: string | null
}

export function generalCompetition(row: NoticeCompetition): boolean {
  return (!row.supply_type || /^(general|1)$/i.test(row.supply_type)) &&
    (!row.supply_type_label || isGeneralSupply(row.supply_type_label))
}

/** A source correction invalidates proofs; an ordinary failed retry preserves historical figures. */
export function historicalCompetitionValid(notice: Notice): boolean {
  const state = notice.competition
  if (state?.proof_invalidated === true) return false
  return !(state?.status === 'pending' && /공고 변경|정정|근거.*무효/.test(state.message || ''))
}

export function competitionClosureProof(notice: Notice, unit: string, mode: 'schedule' | 'results' = 'schedule', now = Date.now()): CompetitionClosureProof | null {
  if (mode === 'schedule' ? !competitionFresh(notice, now) : !historicalCompetitionValid(notice)) return null
  const rows = (notice.competitions || []).filter((row) => competitionUnitKey(row.unit_type) === competitionUnitKey(unit) &&
    row.rank === 1 && row.residence_area === 'local' && generalCompetition(row) && row.verification === 'official' &&
    !!row.evidence_url && !!row.observed_at && Number.isFinite(Date.parse(row.observed_at)) &&
    Date.parse(row.observed_at) <= now + 60_000 && (mode === 'results' || now - Date.parse(row.observed_at) <= 6 * 60 * 60 * 1000))
  const explicit = rows.find((row) => row.result_status === 'local_first_closed')
  if (explicit) return {
    unitType: unit, kind: 'explicit_local_first_closed', reason: '공식 해당지역 1순위 마감 결과로 기타지역 배정 기회가 종료됐습니다.',
    competitionEvidenceUrl: explicit.evidence_url!, competitionEvidenceText: explicit.result_text || '1순위 해당지역 마감', observedAt: explicit.observed_at!,
  }
  const applicantHash = officialMetadata(notice, 'applicant_regions')?.document_hash
  const allocation = (notice.rules || []).find((rule) => rule.kind === 'regional_allocation' && rule.effect === 'metadata' &&
    rule.verification === 'official' && isGeneralSupply(rule.supply_type || '') && rule.allocation_method === 'all_local_first' &&
    rule.local_share_percent === 100 && !!regionScope(rule.local_region) &&
    (!rule.housing_kind || rule.housing_kind === notice.housing_kind) &&
    !(typeof applicantHash === 'string' && typeof rule.document_hash === 'string' && applicantHash !== rule.document_hash) &&
    (!rule.unit_type || competitionUnitKey(rule.unit_type) === competitionUnitKey(unit)) &&
    !!rule.evidence_url && !!(rule.evidence_text || rule.text))
  if (!allocation) return null
  const exhausted = rows.find((row) => row.result_status === 'first_closed' &&
    /^1순위\s*마감(?:\s*\(청약\s*접수\s*종료\))?$/.test((row.result_text || '').trim()) &&
    row.supply_count !== null && Number.isSafeInteger(row.supply_count) && row.supply_count > 0 &&
    row.application_count !== null && Number.isSafeInteger(row.application_count) && row.application_count >= row.supply_count)
  if (!exhausted) return null
  return {
    unitType: unit, kind: 'all_local_first_exhausted',
    reason: `일반공급 전량 해당지역 우선배정이며, 공식 1순위 마감과 해당지역 모집 ${exhausted.supply_count}세대·접수 ${exhausted.application_count}건을 확인했습니다.`,
    competitionEvidenceUrl: exhausted.evidence_url!, competitionEvidenceText: exhausted.result_text!, observedAt: exhausted.observed_at!,
    allocationEvidenceUrl: allocation.evidence_url, allocationEvidenceText: allocation.evidence_text || allocation.text,
  }
}

export function unitClosedForOtherFirst(notice: Notice, unit: string, now = Date.now()): boolean {
  return !!competitionClosureProof(notice, unit, 'schedule', now)
}

function applicationEvent(event: NoticeEvent): boolean {
  return !/^(announcement|contract|result|winner)$/i.test(event.kind) && !/당첨자 발표|계약일|계약 체결/.test(event.label)
}

export function generalPriorityEvent(event: NoticeEvent): boolean {
  return /first|second|priority|general/i.test(event.kind) || /[12]순위|일반공급/.test(`${event.label} ${event.audience || ''}`)
}

export interface CompetitionDecision {
  area: ResidenceArea
  /** Compatibility only. Personal decisions never remove public records. */
  hidden?: boolean
  allGeneralUnavailable?: boolean
  allApplicationsUnavailable?: boolean
  closedUnits: string[]
  reason: string | null
  closureProofs?: CompetitionClosureProof[]
}

export function competitionEventAvailable(event: NoticeEvent, notice: Notice, profile: LocalProfile, decision: CompetitionDecision): boolean {
  const units = notice.competition?.unit_types || []
  const allClosed = decision.area === 'other' && notice.competition?.status === 'ok' &&
    notice.competition.complete === true && units.length > 0 && units.every((unit) => deriveRank(notice, profile, unit).rank === 'first' &&
      decision.closedUnits.some((closed) => competitionUnitKey(closed) === competitionUnitKey(unit)))
  return !(allClosed && generalPriorityEvent(event))
}

export function competitionDecision(notice: Notice, profile: LocalProfile, today: string, override?: ResidenceArea, now = Date.now()): CompetitionDecision {
  const area = residenceArea(notice, profile, override)
  const target = area === 'other'
  const closureProofs = target ? (notice.competition?.unit_types || []).filter((unit) => deriveRank(notice, profile, unit).rank === 'first')
    .map((unit) => competitionClosureProof(notice, unit, 'schedule', now)).filter((proof): proof is CompetitionClosureProof => !!proof) : []
  const closedUnits = closureProofs.map((proof) => proof.unitType)
  const units = notice.competition?.unit_types || []
  const allClosed = target && notice.competition?.status === 'ok' && notice.competition.complete === true && units.length > 0 && units.every((unit) => closedUnits.some((closed) => competitionUnitKey(closed) === competitionUnitKey(unit)))
  const special = specialDiagnostics(notice, profile)
  const otherApplication = (notice.events || []).some((event) => {
    if (!applicationEvent(event) || (event.end_date || event.start_date) < today || generalPriorityEvent(event)) return false
    if (!/special|특별/.test(`${event.kind} ${event.label}`)) return true
    // Generic special reception does not establish all offered categories.
    // Missing or incomplete types must keep the notice visible.
    const offered = offeredSpecialSupplies(notice)
    if (!offered.length || !special.length || special.some((diagnosis) => diagnosis.type === 'other')) return true
    return special.some((diagnosis) => diagnosis.result.status !== 'mismatch')
  })
  const specialScheduleMissing = offeredSpecialSupplies(notice).length > 0 && !(notice.events || []).some((event) =>
    applicationEvent(event) && /special|특별/.test(`${event.kind} ${event.label}`))
  const allApplicationsUnavailable = allClosed && !otherApplication && !specialScheduleMissing
  return { area, hidden: false, allGeneralUnavailable: allClosed, allApplicationsUnavailable, closedUnits: target ? closedUnits : [], closureProofs: target ? closureProofs : [], reason: allApplicationsUnavailable
    ? '기타지역 1순위 · 모든 일반공급 주택형이 해당지역 1순위에서 마감됐습니다.' : null }
}

/** Historical opportunity labels are independent of account rank and the six-hour live gate. */
export function resultCompetitionDecision(notice: Notice, profile: LocalProfile, override?: ResidenceArea, now = Date.now()): CompetitionDecision {
  const area = residenceArea(notice, profile, override)
  const units = [...new Set((notice.competitions || []).filter((row) => row.verification === 'official' && generalCompetition(row)).map((row) => row.unit_type))]
  const closureProofs = area === 'other' ? units.map((unit) => competitionClosureProof(notice, unit, 'results', now)).filter((proof): proof is CompetitionClosureProof => !!proof) : []
  const closedUnits = closureProofs.map((proof) => proof.unitType)
  const officialRows = (notice.competitions || []).filter((row) => row.verification === 'official')
  const allGeneralUnavailable = units.length > 0 && units.every((unit) => closedUnits.some((closed) => competitionUnitKey(closed) === competitionUnitKey(unit)))
  const specialReceptionExists = (notice.events || []).some((event) => applicationEvent(event) && /special|특별/.test(`${event.kind} ${event.label}`))
  const allApplicationsUnavailable = allGeneralUnavailable && officialRows.every((row) => generalCompetition(row)) && offeredSpecialSupplies(notice).length === 0 && !specialReceptionExists
  return { area, hidden: false, allGeneralUnavailable, allApplicationsUnavailable, closedUnits, closureProofs,
    reason: allGeneralUnavailable ? '수집된 일반공급 주택형의 기타지역 배정 기회가 종료됐습니다. 공식 결과는 계속 표시합니다.' : null }
}

export function resultCompetitionRows(notice: Notice, _decision?: CompetitionDecision, _legacyHideClosedUnits?: boolean): NoticeCompetition[] {
  return (notice.competitions || []).filter((row) => row.verification === 'official')
}

export function competitionRowUnavailable(row: NoticeCompetition, decision: CompetitionDecision): boolean {
  return generalCompetition(row) && decision.closedUnits.some((unit) => competitionUnitKey(unit) === competitionUnitKey(row.unit_type))
}

export function competitionRateLabel(value: string | null | undefined): string {
  const raw = value?.trim() || '-'
  if (raw === '-') return '미공개'
  const shortage = raw.match(/^\(?\s*[△▲]\s*([\d,]+)\s*\)?$/)
  return shortage ? `미달 ${shortage[1]}세대` : raw
}

export function competitionRowLabel(row: NoticeCompetition): string {
  if (row.result_status === 'local_first_closed') return '해당지역 1순위 마감'
  if (row.result_status === 'first_closed') return '1순위 마감'
  if (row.result_status === 'open') return '접수 중'
  return row.result_text || '마감 여부 미공개'
}
