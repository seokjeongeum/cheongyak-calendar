import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeEvent, type NoticeCompetition, type OfferedSupply } from './types'
import { competitionUnitKey, competitionRowUnavailable, generalCompetition, generalPriorityEvent, type CompetitionDecision } from './competition'
import { evaluateQualification, evaluateRule, officialClauseApplicability, offeredSpecialSupplies, isGeneralSupply, officialOfferedSupplies as qualificationInventory, type EligibilityReason, type EligibilityResult } from './qualification'
import { getEvaluationToday } from './factTimeline'
export { ELIGIBILITY_LABEL, deriveRank, unitRankResults, specialDiagnostics, specialType, offeredSpecialSupplies, evaluateRule, conditionCoverage } from './qualification'
export type { EligibilityStatus, ReasonStatus, EligibilityReason, EligibilityResult, RankResult, SpecialDiagnosis, SpecialType } from './qualification'
// Public notices and profiles are immutable within one worker revision.
let evaluationCache = new WeakMap<Notice, WeakMap<LocalProfile, Map<string, EligibilityResult>>>()
export function beginEvaluationRevision(): void { evaluationCache = new WeakMap() }
export function evaluateEligibility(notice: Notice, profile: LocalProfile = EMPTY_PROFILE, unitType?: string, supplyType?: string): EligibilityResult {
  let profiles = evaluationCache.get(notice)
  if (!profiles) { profiles = new WeakMap(); evaluationCache.set(notice, profiles) }
  let results = profiles.get(profile)
  if (!results) { results = new Map(); profiles.set(profile, results) }
  const key = `${getEvaluationToday()}\u0000${unitType || ''}\u0000${supplyType || ''}`
  let result = results.get(key)
  if (!result) { result = evaluateQualification(notice, profile, unitType, supplyType); results.set(key, result) }
  return result
}

export function applyCompetitionEligibility(result: EligibilityResult, notice: Notice, decision: CompetitionDecision, unitType?: string, supplyType?: string): EligibilityResult {
  const closedUnits = unitType
    ? decision.closedUnits.filter((unit) => competitionUnitKey(unit) === competitionUnitKey(unitType))
    : decision.closedUnits
  if (!closedUnits.length) return result
  const generalSupply = !!supplyType && /^(일반공급|general)$/i.test(supplyType.replace(/\s+/g, ''))
  // A general-supply closing result says nothing about a special-supply
  // combination. Keep its diagnosis and evidence separate.
  if (supplyType && !generalSupply) return result
  const closedRow = (notice.competitions || []).find((row) => row.result_status === 'local_first_closed' &&
    row.verification === 'official' && row.rank === 1 && row.residence_area === 'local' &&
    closedUnits.some((unit) => competitionUnitKey(unit) === competitionUnitKey(row.unit_type)))
  const proof = decision.closureProofs?.find((item) => closedUnits.some((unit) => competitionUnitKey(unit) === competitionUnitKey(item.unitType)))
  const blocked = generalSupply || (!unitType && decision.allApplicationsUnavailable === true)
  const closureReason: EligibilityReason = {
    status: blocked ? 'fail' : 'review', label: '기타지역 1순위 접수 마감',
    detail: blocked
      ? `${closedUnits.join(', ')} 일반공급의 기타지역 1순위 접수가 종료됐습니다. ${proof?.reason || '공식 해당지역 1순위 마감 결과를 확인했습니다.'}`
      : `${closedUnits.join(', ')} 일반공급의 기타지역 1순위 접수가 종료됐습니다. 신청할 주택형·공급유형별 결과를 확인하세요.`,
    evidenceUrl: proof?.competitionEvidenceUrl || closedRow?.evidence_url || notice.competition?.evidence_url,
    evidenceText: proof ? [proof.competitionEvidenceText, proof.allocationEvidenceText].filter(Boolean).join('\n') : closedRow?.result_text,
  }
  return { status: blocked ? 'mismatch' : result.status === 'possible' ? 'review' : result.status,
    reasons: [...result.reasons, closureReason] }
}

export interface SupplySummary { supplyType: string; unitTypes: string[]; result: EligibilityResult }

/** The card's outcome belongs to an offered supply, never a mixture of special types. */
export function supplySummaries(notice: Notice, profile: LocalProfile, decision?: CompetitionDecision, combinations?: EligibilityCombination[]): SupplySummary[] {
  const groups = new Map<string, SupplySummary>()
  for (const combo of combinations || eligibilityCombinations(notice, profile, decision)) {
    const key = JSON.stringify([combo.supplyType, combo.result.status, [...new Set(actionableReasons(combo.result.reasons).map(comparisonReasonKey))].sort()])
    const previous = groups.get(key)
    if (previous) previous.unitTypes.push(combo.unitType)
    else groups.set(key, { supplyType: combo.supplyType, unitTypes: [combo.unitType], result: combo.result })
  }
  return [...groups.values()].sort((a, b) => Number(isGeneralSupply(b.supplyType)) - Number(isGeneralSupply(a.supplyType)))
}

export function noticeEligibilitySummary(notice: Notice, profile: LocalProfile, decision?: CompetitionDecision, summaries?: SupplySummary[]): EligibilityResult {
  const supplies = summaries || supplySummaries(notice, profile, decision)
  if (!supplies.length) return evaluateEligibility(notice, profile)
  const status = supplies.some((supply) => supply.result.status === 'possible') ? 'possible'
    : supplies.every((supply) => supply.result.status === 'mismatch') ? 'mismatch'
    : supplies.every((supply) => supply.result.status === 'unpublished') ? 'unpublished' : 'review'
  return { status, reasons: status === 'mismatch' ? uniqueReasons(supplies.flatMap((supply) => supply.result.reasons).filter((reason) => reason.status === 'fail')) : [] }
}

export interface ApplicationAvailability { unavailable: boolean; reason: string | null }

/** A missing condition is never enough to mark an event as unavailable. */
export function applicationEventAvailability(event: NoticeEvent, notice: Notice, profile: LocalProfile, decision?: CompetitionDecision, combinations?: EligibilityCombination[], commonResult?: EligibilityResult): ApplicationAvailability {
  if (decision) {
    const audience = `${event.audience || ''} ${event.label || ''}`
    const audienceArea = /기타경기/.test(audience) ? 'other_gyeonggi' : /기타지역|타지역/.test(audience) ? 'other' : /해당지역|당해지역/.test(audience) ? 'local' : null
    if (audienceArea && decision.area !== 'unknown' && decision.area !== audienceArea) return {
      unavailable: true, reason: `이 접수는 ${audienceArea === 'local' ? '해당지역' : audienceArea === 'other_gyeonggi' ? '기타경기' : '기타지역'} 대상입니다. 내 공고별 배정 지역과 다릅니다.`,
    }
    if (generalPriorityEvent(event) && decision.allGeneralUnavailable) return {
      unavailable: true, reason: '모든 일반공급 주택형의 기타지역 1순위 배정 기회가 종료됐습니다.',
    }
  }
  const combos = combinations || eligibilityCombinations(notice, profile, decision)
  const special = /special|특별/.test(`${event.kind} ${event.label}`)
  const relevant = generalPriorityEvent(event) ? combos.filter((combo) => isGeneralSupply(combo.supplyType))
    : special ? combos.filter((combo) => !isGeneralSupply(combo.supplyType) && combo.supplyType !== '공통 조건') : combos
  const named = special ? relevant.filter((combo) => event.label.includes(combo.supplyType.replace(/\s*특별공급$/, ''))) : []
  const outcomes = named.length ? named : relevant
  const specialInventoryKnown = notice.rules_complete === true || (notice.rules || []).some((rule) =>
    rule.kind === 'condition_coverage' && rule.effect === 'metadata' && rule.verification === 'official' && Array.isArray(rule.offered_supply_types) && rule.offered_supply_types.length > 0)
  if ((!special || named.length > 0 || specialInventoryKnown) && outcomes.length && outcomes.every((combo) => combo.result.status === 'mismatch')) return {
    unavailable: true, reason: uniqueReasons(outcomes.flatMap((combo) => combo.result.reasons)).filter((reason) => reason.status === 'fail').map((reason) => reason.detail).join(' '),
  }
  // Generic special events with no official type inventory stay open for review.
  if (special && !outcomes.length) return { unavailable: false, reason: null }
  const common = commonResult || evaluateEligibility(notice, profile)
  return common.status === 'mismatch' ? { unavailable: true, reason: common.reasons.find((reason) => reason.status === 'fail')?.detail || '공고의 공통 신청 조건을 충족하지 않습니다.' }
    : { unavailable: false, reason: null }
}

export function competitionRowAvailability(row: NoticeCompetition, notice: Notice, profile: LocalProfile, decision: CompetitionDecision): ApplicationAvailability {
  if (competitionRowUnavailable(row, decision)) return { unavailable: true, reason: '이 주택형의 기타지역 배정 기회가 종료됐습니다.' }
  const supply = row.supply_type_label || (generalCompetition(row) ? '일반공급' : undefined)
  // A generic special result cannot stand for every special-supply diagnosis.
  if (!supply || /^(특별공급|special)$/i.test(supply)) return { unavailable: false, reason: null }
  const result = applyCompetitionEligibility(evaluateEligibility(notice, profile, row.unit_type, supply), notice, decision, row.unit_type, supply)
  return { unavailable: result.status === 'mismatch', reason: result.status === 'mismatch' ? result.reasons.find((reason) => reason.status === 'fail')?.detail || '이 공급유형의 신청 조건을 충족하지 않습니다.' : null }
}

export function unitApplicationUnavailable(notice: Notice, profile: LocalProfile, unitType: string, decision?: CompetitionDecision, combinations?: EligibilityCombination[]): boolean {
  const combos = (combinations || eligibilityCombinations(notice, profile, decision)).filter((combo) => combo.unitType === '전체 주택형' || competitionUnitKey(combo.unitType) === competitionUnitKey(unitType))
  return combos.length > 0 ? combos.every((combo) => combo.result.status === 'mismatch') : evaluateEligibility(notice, profile, unitType).status === 'mismatch'
}

export interface EligibilityCombination { unitType: string; supplyType: string; result: EligibilityResult }

/** A reviewed supply table takes precedence over conditions inferred from prose. */
export function officialOfferedSupplies(notice: Notice): OfferedSupply[] {
  const inventory = qualificationInventory(notice) || []
  return [...new Map(inventory.filter((item) => item.verification === 'official' && item.supply_type.trim() &&
    (item.supply_count == null || item.supply_count > 0)).map((item) => [`${item.supply_type}\u0000${item.unit_type || ''}`, item])).values()]
}

// A price row proves that a unit exists, not that every special supply offers it.
// Keep notice-wide supply conditions together unless the official rule/inventory
// names its unit, or a general-supply competition row establishes that pairing.
export function eligibilityCombinations(notice: Notice, profile: LocalProfile = EMPTY_PROFILE, decision?: CompetitionDecision): EligibilityCombination[] {
  const rules = notice.rules || []
  const pairs = new Map<string, { unit?: string; supply?: string }>()
  const add = (unit?: string | null, supply?: string | null) => {
    const pair = { unit: unit || undefined, supply: supply || undefined }
    pairs.set(`${pair.unit || ''}\u0000${pair.supply || ''}`, pair)
  }
  const inventory = officialOfferedSupplies(notice)
  if (qualificationInventory(notice) !== undefined) {
    for (const item of inventory) add(item.unit_type, item.supply_type)
    return [...pairs.values()].map(({ unit, supply }) => {
      const assessed = evaluateEligibility(notice, profile, unit, supply)
      return { unitType: unit || '전체 주택형', supplyType: supply!, result: decision ? applyCompetitionEligibility(assessed, notice, decision, unit, supply) : assessed }
    })
  }
  const officialRules = rules.filter((rule) => rule.verification === 'official' && rule.effect !== 'metadata' && rule.purpose !== 'first_rank')
  for (const rule of officialRules) if (rule.unit_type) add(rule.unit_type, rule.supply_type)
  const explicitSupplies = [...new Set([...officialRules.map((rule) => rule.supply_type).filter((value): value is string => !!value), ...offeredSpecialSupplies(notice)])]
  for (const metadata of rules.filter((rule) => rule.kind === 'condition_coverage' && rule.effect === 'metadata' && rule.verification === 'official')) {
    if (Array.isArray(metadata.scopes)) for (const scope of metadata.scopes) {
      if (scope && typeof scope === 'object') {
        const unit = typeof scope.unit_type === 'string' ? scope.unit_type : undefined, supply = typeof scope.supply_type === 'string' ? scope.supply_type : undefined
        if (unit || ![...pairs.values()].some((pair) => pair.unit && pair.supply === supply)) add(unit, supply)
      }
    }
    if (Array.isArray(metadata.offered_supply_types)) for (const supply of metadata.offered_supply_types) if (typeof supply === 'string' && !explicitSupplies.includes(supply)) explicitSupplies.push(supply)
  }
  const generalUnits = [...new Set((notice.competitions || []).filter((row) => row.verification === 'official' && (!row.supply_type_label || isGeneralSupply(row.supply_type_label)) && (!row.supply_type || /general|^1$/.test(row.supply_type))).map((row) => row.unit_type))]
  if ((generalUnits.length || (notice.events || []).some(generalPriorityEvent)) && !explicitSupplies.some(isGeneralSupply)) explicitSupplies.push('일반공급')
  // The reception proves special supply exists, but not which type. Preserve
  // that uncertainty instead of declaring the whole notice unavailable.
  const unknownSpecialReception = (notice.events || []).some((event) => !/^(announcement|contract|result|winner)$/i.test(event.kind) &&
    !/당첨자 발표|계약일|계약 체결/.test(event.label) && /special|특별/.test(`${event.kind} ${event.label}`))
  if (unknownSpecialReception && !explicitSupplies.some((supply) => !isGeneralSupply(supply))) explicitSupplies.push('특별공급')
  for (const supply of explicitSupplies) {
    const existing = [...pairs.values()].filter((pair) => pair.supply === supply)
    if (isGeneralSupply(supply) && generalUnits.length) {
      pairs.delete(`\u0000${supply}`)
      for (const unit of generalUnits) add(unit, supply)
    } else if (!existing.length) {
      const closed = decision?.closedUnits.length && isGeneralSupply(supply)
      const units = closed ? [...new Set((notice.prices || []).map((price) => price.unit_type))] : []
      if (units.length) for (const unit of units) add(unit, supply)
      else add(undefined, supply)
    }
  }
  if (!pairs.size) return []
  return [...pairs.values()].map(({ unit, supply }) => {
    const assessed = evaluateEligibility(notice, profile, unit, supply)
    return { unitType: unit || '전체 주택형', supplyType: supply || '공통 조건', result: decision ? applyCompetitionEligibility(assessed, notice, decision, unit, supply) : assessed }
  })
}

export function reasonKey(reason: EligibilityReason): string {
  return JSON.stringify([reason.status, reason.category, reason.label, reason.detail, reason.input, reason.requirement, reason.criterionDate, reason.evidenceUrl, reason.evidenceText, reason.profileField, reason.contractPreview, reason.todayPreview, reason.historyGroup])
}
/** Identical factual comparisons share a card row even when the source repeats
 * that requirement in separate unit paragraphs. Full evidence remains in the
 * underlying combinations and expanded reasons, keyed by reasonKey.
 */
export function comparisonReasonKey(reason: EligibilityReason): string {
  return JSON.stringify([reason.status, reason.category, reason.label, reason.detail, reason.input, reason.requirement, reason.criterionDate, reason.profileField, reason.contractPreview, reason.todayPreview, reason.historyGroup])
}
export function uniqueReasons(reasons: EligibilityReason[]): EligibilityReason[] {
  return [...new Map(reasons.map((reason) => [reasonKey(reason), reason])).values()]
}
export function actionableReasons(reasons: EligibilityReason[]): EligibilityReason[] {
  return uniqueReasons(reasons.filter((reason) => !['source_gap', 'unverified', 'selection'].includes(reason.category || '')))
}

export interface SourceDiagnostic { stage: string; code: string; message: string; evidenceUrl?: string; sourceFormat?: string; httpStatus?: number; missingItems?: string[] }
export interface RemainingConditionTopic { label: string; scopes: string[]; reason?: string; evidenceUrl?: string; evidenceText?: string; evidencePage?: number; documentHash?: string }
function remainingTopicLabel(value: string): string {
  return /^(?:문서의 나머지 신청 제한·예외 검토|기타 공식 조건|신청 제한·연령 예외의 전체 검토)$/.test(value.trim()) ? '신청자격 문단의 필수 조건·면제 검토 기록 미확보' : value
}
export function conditionSourceStatus(notice: Notice, profile?: LocalProfile): { diagnostics: SourceDiagnostic[]; topics: RemainingConditionTopic[] } {
  const diagnostics = new Map<string, SourceDiagnostic>()
  const topics = new Map<string, RemainingConditionTopic>()
  for (const rule of notice.rules || []) {
    if (rule.effect !== 'metadata' || rule.verification !== 'official') continue
    if (rule.kind === 'document_diagnostics' && Array.isArray(rule.diagnostics)) for (const item of rule.diagnostics) {
      if (!item || typeof item !== 'object' || ['ok', 'resolved'].includes(String(item.status)) || typeof item.message !== 'string') continue
      const diagnostic = { stage: String(item.stage || 'interpretation'), code: String(item.code || ''), message: item.message,
        evidenceUrl: typeof item.evidence_url === 'string' ? item.evidence_url : undefined,
        sourceFormat: typeof item.source_format === 'string' ? item.source_format : undefined,
        httpStatus: typeof item.http_status === 'number' ? item.http_status : undefined,
        missingItems: Array.isArray(item.missing_items) ? item.missing_items.filter((value: unknown): value is string => typeof value === 'string' && !!value.trim()) : undefined }
      diagnostics.set(JSON.stringify([diagnostic.stage, diagnostic.code, diagnostic.message]), diagnostic)
    }
    if (rule.kind !== 'condition_coverage' || !Array.isArray(rule.scopes)) continue
    for (const scope of rule.scopes) {
      if (!scope || typeof scope !== 'object') continue
      const scopeLabel = [scope.supply_type, scope.unit_type].filter((value) => typeof value === 'string' && value).join(' · ')
      const hasTopics = Array.isArray(scope.topics)
      const remaining: Record<string, unknown>[] = hasTopics ? (scope.topics as unknown[]).filter((item: unknown): item is Record<string, unknown> => !!item && typeof item === 'object' &&
        (item as Record<string, unknown>).required !== false && !['application', 'post_selection'].includes(String((item as Record<string, unknown>).phase)) &&
        !['verified', 'not_applicable'].includes(String((item as Record<string, unknown>).status))) : []
      // A reviewed topic list can deliberately contain only instructions or
      // exempt requirements. Do not reintroduce stale legacy missing_topics.
      const labels: Record<string, unknown>[] = hasTopics ? remaining : (Array.isArray(scope.missing_topics) ? scope.missing_topics.filter((label: unknown): label is string => typeof label === 'string').map((topic: string) => ({ topic })) : [])
      for (const item of labels) {
        if (typeof item.topic !== 'string' || !item.topic.trim()) continue
        if (profile && officialClauseApplicability({ ...rule, kind: 'unparsed', label: item.topic, text: typeof item.reason === 'string' ? item.reason : item.topic,
          supply_type: typeof scope.supply_type === 'string' ? scope.supply_type : undefined,
          evidence_text: typeof item.evidence_text === 'string' ? item.evidence_text : undefined }, profile, notice) === false) continue
        const label = remainingTopicLabel(item.topic)
        const key = JSON.stringify([label, item.reason, item.evidence_text, item.document_hash || rule.document_hash])
        const previous = topics.get(key)
        if (previous) { if (scopeLabel && !previous.scopes.includes(scopeLabel)) previous.scopes.push(scopeLabel) }
        else topics.set(key, { label, scopes: scopeLabel ? [scopeLabel] : [], reason: typeof item.reason === 'string' ? item.reason : undefined,
          evidenceUrl: typeof item.evidence_url === 'string' ? item.evidence_url : typeof rule.evidence_url === 'string' ? rule.evidence_url : undefined,
          evidenceText: typeof item.evidence_text === 'string' ? item.evidence_text : undefined,
          evidencePage: typeof item.evidence_page === 'number' ? item.evidence_page : undefined,
          documentHash: typeof item.document_hash === 'string' ? item.document_hash : typeof rule.document_hash === 'string' ? rule.document_hash : undefined })
      }
    }
  }
  return { diagnostics: [...diagnostics.values()], topics: [...topics.values()] }
}

export interface SupplyInventorySummary { totalHouseholds: number; currentSupplyCount: number; evidenceUrl?: string; evidenceText?: string }
/** Distinguish a development's total homes from the offer in this notice. */
export function supplyInventorySummary(notice: Notice): SupplyInventorySummary | undefined {
  const rule = (notice.rules || []).find((item) => item.kind === 'supply_inventory_summary' && item.effect === 'metadata' && item.verification === 'official' &&
    typeof item.total_households === 'number' && Number.isInteger(item.total_households) && item.total_households > 0 &&
    typeof item.current_supply_count === 'number' && Number.isInteger(item.current_supply_count) && item.current_supply_count >= 0 && item.current_supply_count <= item.total_households)
  return rule ? { totalHouseholds: rule.total_households as number, currentSupplyCount: rule.current_supply_count as number,
    evidenceUrl: rule.evidence_url || undefined, evidenceText: rule.evidence_text || undefined } : undefined
}

export interface ApplicationInstruction { label: string; detail: string; evidenceUrl?: string; evidenceText?: string; evidencePage?: number }
/** Actions when applying do not count as an unanswered personal condition. */
export function applicationInstructions(notice: Notice): ApplicationInstruction[] {
  const rows: ApplicationInstruction[] = []
  for (const rule of notice.rules || []) if (rule.kind === 'application_instructions' && rule.effect === 'metadata' && rule.verification === 'official' && Array.isArray(rule.instructions)) {
    for (const item of rule.instructions) if (item && typeof item === 'object' && item.phase !== 'post_selection' && typeof item.label === 'string' && typeof item.detail === 'string') {
      rows.push({ label: item.label, detail: item.detail, evidenceUrl: typeof item.evidence_url === 'string' ? item.evidence_url : rule.evidence_url || undefined,
        evidenceText: typeof item.evidence_text === 'string' ? item.evidence_text : undefined, evidencePage: typeof item.evidence_page === 'number' ? item.evidence_page : undefined })
    }
  }
  return [...new Map(rows.map((row) => [JSON.stringify([row.label, row.detail]), row])).values()]
}

export function rankUnitComparisons(notice: Notice, profile: LocalProfile): { units: string[]; reasons: EligibilityReason[] }[] {
  const rules = (notice.rules || []).filter((rule) => rule.verification === 'official' && rule.purpose === 'first_rank' && !rule.supply_type && (Array.isArray(rule.deposit_table) || rule.kind === 'account_type' && rule.area_limit_for_installment !== undefined))
  const units = [...new Set((notice.prices || []).map((price) => price.unit_type).filter(Boolean))]
  if (!rules.length || !units.length || !rules.some((rule) => evaluateRule(rule, profile, notice).category === 'selection')) return []
  const groups = new Map<string, { units: string[]; reasons: EligibilityReason[] }>()
  for (const unit of units) {
    const reasons = actionableReasons(rules.map((rule) => {
      const reason = evaluateRule(rule, profile, notice, unit)
      // Group identical area-tier requirements without repeating them per unit.
      if (reason.requirement && rule.kind === 'deposit_min_krw') reason.requirement = reason.requirement.replace(`${unit} `, '').replace(/전용면적 [^·]+ · /, '')
      return reason
    }))
    if (!reasons.length) continue
    const key = JSON.stringify(reasons.map(reasonKey)), existing = groups.get(key)
    if (existing) existing.units.push(unit)
    else groups.set(key, { units: [unit], reasons })
  }
  return [...groups.values()]
}
