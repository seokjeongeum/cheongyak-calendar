import type { LocalProfile, Notice, ResidenceArea } from './types'
import { competitionDecision, competitionFresh, resultCompetitionDecision, type CompetitionDecision } from './competition'
import { beginEvaluationRevision, evaluateEligibility, eligibilityCombinations, supplySummaries, noticeEligibilitySummary, applicationEventAvailability, unitApplicationUnavailable, competitionRowAvailability, rankUnitComparisons, actionableReasons, reasonKey, type EligibilityResult, type EligibilityCombination, type SupplySummary, type ApplicationAvailability, type RankResult, type EligibilityReason } from './eligibility'
import { deriveRank, unitRankResults, regionDecision, type RegionDecision } from './qualification'
import { setEvaluationToday } from './factTimeline'
import { selectionOpportunity, type OpportunityResult } from './opportunity'
import { contractComparisonNote } from './contractPresentation'
import { eventCandidate, candidateLabel, candidateExplanation } from './candidates'

export interface NoticeEvaluation {
  opportunity: OpportunityResult
  decision: CompetitionDecision
  fresh: boolean
  common: EligibilityResult
  combinations: EligibilityCombination[]
  supplies: SupplySummary[]
  summary: EligibilityResult
  rank: RankResult
  rankedUnits: { units: string[]; result: RankResult }[]
  rankComparisons: { units: string[]; reasons: EligibilityReason[] }[]
  regions: { decision: RegionDecision; scopes: string[] }[]
  sharedReasons: EligibilityReason[]
  events: ApplicationAvailability[]
  candidateEvents: boolean[]
  candidateLabel: string
  candidateReason: string
  priceUnavailable: boolean[]
  competitionRows: ApplicationAvailability[]
  contractNote: string | null
}
export interface EvaluationRequest {
  revision: number
  catalog?: Notice[]
  profile: LocalProfile
  today: string
  now: number
  overrides: Record<string, ResidenceArea>
  mode: 'schedule' | 'results'
}
export interface EvaluationResponse { revision: number; evaluations: Record<string, NoticeEvaluation>; elapsedMs: number; error?: string }

function regionGroups(notice: Notice, profile: LocalProfile, combinations: EligibilityCombination[]): NoticeEvaluation['regions'] {
  const groups = new Map<string, { decision: RegionDecision; scopes: string[] }>()
  for (const combo of combinations.length ? combinations : [{ unitType: '전체 주택형', supplyType: '공통 조건' }]) {
    const decision = regionDecision(notice, profile, { unitType: combo.unitType === '전체 주택형' ? undefined : combo.unitType, supplyType: combo.supplyType === '공통 조건' ? undefined : combo.supplyType })
    const key = JSON.stringify([decision.status, decision.reason, decision.criterionDate, decision.reasons.map((r) => [r.status, r.input, r.requirement])])
    const scope = combinations.length ? [combo.supplyType, combo.unitType === '전체 주택형' ? '' : combo.unitType].filter(Boolean).join(' · ') : ''
    const existing = groups.get(key)
    if (existing) { if (scope && !existing.scopes.includes(scope)) existing.scopes.push(scope) }
    else groups.set(key, { decision, scopes: scope ? [scope] : [] })
  }
  return [...groups.values()]
}

export function evaluateNotice(notice: Notice, profile: LocalProfile, today: string, now: number, override?: ResidenceArea, mode: 'schedule' | 'results' = 'schedule', suppliedDecision?: CompetitionDecision): NoticeEvaluation {
  setEvaluationToday(today)
  const decision = suppliedDecision || (mode === 'results' ? resultCompetitionDecision(notice, profile, override, now) : competitionDecision(notice, profile, today, override, now))
  const common = evaluateEligibility(notice, profile)
  const combinations = eligibilityCombinations(notice, profile, decision)
  const supplies = supplySummaries(notice, profile, decision, combinations)
  const summary = noticeEligibilitySummary(notice, profile, decision, supplies)
  const rank = deriveRank(notice, profile)
  const unitRanks = new Map<string, { units: string[]; result: RankResult }>()
  for (const item of unitRankResults(notice, profile)) {
    const key = JSON.stringify([item.result.rank, item.result.status, item.result.label])
    const existing = unitRanks.get(key)
    if (existing) existing.units.push(item.unitType)
    else unitRanks.set(key, { units: [item.unitType], result: item.result })
  }
  const occurrences = new Map<string, { reason: EligibilityReason; count: number }>()
  for (const supply of supplies) for (const reason of actionableReasons(supply.result.reasons)) {
    const key = reasonKey(reason), existing = occurrences.get(key)
    if (existing) existing.count++
    else occurrences.set(key, { reason, count: 1 })
  }
  const events = notice.events.map((event) => applicationEventAvailability(event, notice, profile, decision, combinations, common))
  return {
    decision, fresh: competitionFresh(notice, now), common, combinations, supplies, summary, rank, rankedUnits: [...unitRanks.values()],
    rankComparisons: rankUnitComparisons(notice, profile), regions: regionGroups(notice, profile, combinations),
    sharedReasons: [...occurrences.values()].filter((item) => item.count > 1).map((item) => item.reason),
    events, candidateEvents: notice.events.map((event, i) => summary.status !== 'mismatch' && !decision.allApplicationsUnavailable && !events[i].unavailable && eventCandidate(event, notice, profile)),
    candidateLabel: candidateLabel(notice, profile), candidateReason: candidateExplanation(notice, profile),
    priceUnavailable: notice.prices.map((price) => unitApplicationUnavailable(notice, profile, price.unit_type, decision, combinations)),
    competitionRows: (notice.competitions || []).map((row) => competitionRowAvailability(row, notice, profile, decision)),
    contractNote: contractComparisonNote(notice, today),
    opportunity: selectionOpportunity(notice, profile, override),
  }
}

export function evaluateCatalog(catalog: Notice[], request: Omit<EvaluationRequest, 'catalog'>): EvaluationResponse {
  const started = performance.now()
  beginEvaluationRevision()
  const evaluations: Record<string, NoticeEvaluation> = {}
  for (const notice of catalog) evaluations[notice.id] = evaluateNotice(notice, request.profile, request.today, request.now, request.overrides[notice.id], request.mode)
  return { revision: request.revision, evaluations, elapsedMs: performance.now() - started }
}

export function candidateInRange(notice: Notice, evaluation: NoticeEvaluation | undefined, start: string, end: string): boolean {
  return !!evaluation && notice.events.some((event, i) => evaluation.candidateEvents[i] && (event.end_date || event.start_date) >= start && event.start_date <= end)
}
