import { criterionDate, evaluateRule, inheritedCondition, offeredSpecialSupplies, officialOfferedSupplies, specialType } from './qualification'
import { FACT_GROUP_ANCHORS, factGroupForRule, factsAtDate, setEvaluationToday } from './factTimeline'
import { parentCityCode } from './regions'
import { isParentRule, resolveParentSupport } from './parentSupport'
import { accountWinningUsageAtDate } from './accountUsage'
import type { FactChangeGroup, LocalProfile, Notice, NoticeRule } from './types'

export interface ProfileRuleContext { rule: NoticeRule; notice: Notice; date: string | null }
interface ElderParentScope { notice: Notice; supplyType: string; unitType?: string; rules: NoticeRule[] }
export interface ElderParentQuestionState { stopped: boolean; detail?: string }
export interface ProfileQuestionModel {
  scopedRules: ProfileRuleContext[]
  residenceRules: ProfileRuleContext[]
  restrictionRules: ProfileRuleContext[]
  pastKinds: Set<string>
  pastGroups: Set<FactChangeGroup>
  needsDetailedDistrict: boolean
  needsDomestic: boolean
  needsProvider: boolean
  providerHelp: string
  providerApproval: boolean
  firstHome: boolean
  elderParent: boolean
  elderParentScopes: ElderParentScope[]
  parentFactsShared: boolean
  institution: boolean
  relocation: boolean
  needsMonthly: boolean
  needsNetAssets: boolean
  needsPlannedMarriage: boolean
  needsSingleParent: boolean
  needsProperty: boolean
  needsAccountWinningUsage: boolean
}
const noticeContexts = new WeakMap<Notice, { today: string; rules: NoticeRule[]; rows: ProfileRuleContext[] }>()
const models = new WeakMap<Notice[], { today: string; model: ProfileQuestionModel }>()
const parentQuestionStates = new WeakMap<ProfileQuestionModel, WeakMap<LocalProfile, ElderParentQuestionState>>()
const PARENT_FACT_KINDS = ['parent_same_register', 'parent_support_months_min', 'parent_owns_home', 'parent_spouse_owns_home']
function matchesScope(rule: NoticeRule, supplyType: string, unitType?: string): boolean {
  return (!rule.supply_type || rule.supply_type.replace(/\s/g, '') === supplyType.replace(/\s/g, '')) &&
    (!Array.isArray(rule.supply_types) || rule.supply_types.some((supply) => typeof supply === 'string' && supply.replace(/\s/g, '') === supplyType.replace(/\s/g, ''))) &&
    (!rule.unit_type || rule.unit_type === unitType) && (!Array.isArray(rule.unit_types) || !!unitType && rule.unit_types.includes(unitType))
}
function elderParentScopes(notice: Notice): ElderParentScope[] {
  const inventory = officialOfferedSupplies(notice)
  const supplies = inventory ? inventory.filter((supply) => specialType(supply.supply_type) === 'elder_parent').map((supply) => ({ supplyType: supply.supply_type, unitType: supply.unit_type || undefined })) :
    offeredSpecialSupplies(notice).filter((supply) => specialType(supply) === 'elder_parent').map((supplyType) => ({ supplyType, unitType: undefined }))
  return [...new Map(supplies.map((scope) => [`${scope.supplyType}\0${scope.unitType || ''}`, scope])).values()].map(({ supplyType, unitType }) => ({ notice, supplyType, unitType,
    rules: notice.rules.filter((rule) => rule.verification === 'official' && rule.effect !== 'metadata' && rule.effect !== 'priority' && rule.purpose !== 'first_rank' && matchesScope(rule, supplyType, unitType)),
  }))
}
function sharedParentFact({ rule, notice }: ProfileRuleContext): boolean {
  if (!PARENT_FACT_KINDS.includes(rule.kind)) return false
  const inventory = officialOfferedSupplies(notice)
  if (inventory) return inventory.some((supply) => specialType(supply.supply_type) !== 'elder_parent' && matchesScope(rule, supply.supply_type, supply.unit_type || undefined))
  return !rule.supply_type || specialType(rule.supply_type) !== 'elder_parent'
}
function flatten(rule: NoticeRule, into: NoticeRule[]): void {
  if (rule.verification === 'official') into.push(rule)
  for (const list of [rule.conditions, rule.exceptions]) if (Array.isArray(list)) for (const entry of list) if (entry && typeof entry === 'object' && typeof entry.kind === 'string') flatten(inheritedCondition(rule, entry), into)
}
function contexts(notice: Notice, today: string): ProfileRuleContext[] {
  const cached = noticeContexts.get(notice)
  if (cached?.today === today && cached.rules === notice.rules) return cached.rows
  const rules: NoticeRule[] = []
  for (const rule of notice.rules) flatten(rule, rules)
  const rows = rules.map((rule) => ({ rule, notice, date: criterionDate(rule, notice) }))
  noticeContexts.set(notice, { today, rules: notice.rules, rows })
  return rows
}
/** Public source work is reusable across dialog opens and every field edit. */
export function getProfileQuestionModel(notices: Notice[], today: string): ProfileQuestionModel {
  const cached = models.get(notices)
  if (cached?.today === today) return cached.model
  setEvaluationToday(today)
  const scopedRules = notices.flatMap((notice) => contexts(notice, today))
  const kinds = new Set(scopedRules.map(({ rule }) => rule.kind))
  const pastKinds = new Set<string>(), pastGroups = new Set<FactChangeGroup>()
  for (const { rule, date } of scopedRules) if (date && date < today) {
    pastKinds.add(rule.kind)
    const group = factGroupForRule(rule)
    if (group) pastGroups.add(group)
    if (['children_min', 'newborn_children_min'].includes(rule.kind) && rule.include_pregnancy === true) pastGroups.add('pregnancy')
    if (rule.kind === 'first_home_family') {
      pastGroups.add('children')
      if (rule.include_pregnancy === true) pastGroups.add('pregnancy')
    }
    if (rule.domestic_only === true) pastGroups.add('domestic_residence')
  }
  const providerRules = scopedRules.filter(({ rule }) => rule.kind === 'provider_employee_restriction')
  const parentScopes = notices.flatMap(elderParentScopes)
  const offeringText = notices.flatMap((notice) => [...notice.rules.map((rule) => `${rule.supply_type || ''} ${rule.kind === 'special_eligibility' ? rule.value || '' : ''}`), ...notice.events.map((event) => event.label), ...(notice.competitions || []).map((row) => row.supply_type_label || '')]).join(' ')
  const model: ProfileQuestionModel = {
    scopedRules,
    residenceRules: scopedRules.filter(({ rule }) => ['citizenship', 'overseas_residence'].includes(rule.kind)),
    restrictionRules: scopedRules.filter(({ rule }) => ['application_restriction', 'previous_winning', 'special_winning', 'original_project_contract_ownership'].includes(rule.kind)),
    pastKinds, pastGroups,
    needsDetailedDistrict: scopedRules.some(({ rule }) => typeof rule.region_code === 'string' && !!parentCityCode(rule.region_code) || typeof rule.region_name === 'string' && /시\s*\S+구$/.test(rule.region_name)),
    needsDomestic: kinds.has('domestic_residence') || scopedRules.some(({ rule }) => rule.domestic_only === true || rule.kind === 'overseas_residence' && rule.currently_abroad_only === true),
    needsProvider: !!providerRules.length,
    providerHelp: `대상 기관: ${[...new Set(providerRules.map(({ notice }) => notice.provider))].join(' · ')}. 공고마다 배우자·직계존비속 등 확인 대상과 승인 예외가 다릅니다. 각 카드의 공식 근거에서 범위를 확인하세요.`,
    providerApproval: providerRules.some(({ rule }) => rule.purchase_approval_exception === true || rule.approval_exception === true),
    firstHome: /생애.?최초/.test(offeringText), elderParent: parentScopes.length > 0, elderParentScopes: parentScopes,
    parentFactsShared: scopedRules.some(sharedParentFact),
    institution: /기관추천|추천|장애인|국가유공자|중소기업/.test(offeringText), relocation: /이전기관|이전공공기관/.test(offeringText),
    needsMonthly: kinds.has('shinhee_income') || kinds.has('monthly_income_max_krw') || scopedRules.some(({ rule }) => rule.kind === 'income_max_krw' && rule.period !== 'annual'),
    needsNetAssets: kinds.has('shinhee_assets'), needsPlannedMarriage: kinds.has('planned_marriage'), needsSingleParent: kinds.has('single_parent_family'),
    needsProperty: scopedRules.some(({ rule }) => /real_estate|vehicle|자동차|부동산/.test(String(rule.asset_basis || rule.kind))),
    needsAccountWinningUsage: kinds.has('account_unused_after_winning'),
  }
  models.set(notices, { today, model })
  return model
}
export function warmProfileQuestionModel(notices: Notice[], today: string): void { getProfileQuestionModel(notices, today) }

/** Stop this route only when every offered scope has an unavoidable, official age mismatch. */
export function getElderParentQuestionState(profile: LocalProfile, model: ProfileQuestionModel): ElderParentQuestionState {
  let cache = parentQuestionStates.get(model)
  if (!cache) { cache = new WeakMap(); parentQuestionStates.set(model, cache) }
  const cached = cache.get(profile)
  if (cached) return cached
  const ageFailure = (rule: NoticeRule, scope: ElderParentScope): boolean => {
    if (!matchesScope(rule, scope.supplyType, scope.unitType)) return false
    if (rule.kind === 'parent_age_min') return evaluateRule(rule, profile, scope.notice, scope.unitType).status === 'fail'
    if (!['all', 'any', 'condition_group'].includes(rule.kind) || !Array.isArray(rule.conditions)) return false
    const children = rule.conditions.filter((entry): entry is NoticeRule => !!entry && typeof entry === 'object' && typeof entry.kind === 'string').map((child) => inheritedCondition(rule, child))
    if (!children.length || children.length !== rule.conditions.length) return false
    const mode = rule.kind === 'condition_group' ? rule.operator : rule.kind
    const blocked = mode === 'all' ? children.some((child) => ageFailure(child, scope)) : mode === 'any' && children.every((child) => ageFailure(child, scope))
    return blocked && evaluateRule(rule, profile, scope.notice, scope.unitType).status === 'fail'
  }
  const failures = model.elderParentScopes.map((scope) => scope.rules.find((rule) => ageFailure(rule, scope)))
  const stopped = failures.length > 0 && failures.every(Boolean) && !model.parentFactsShared
  const state: ElderParentQuestionState = { stopped }
  if (stopped) {
    const first = model.elderParentScopes[0], rule = failures[0]!
    state.detail = `${evaluateRule(rule, profile, first.notice, first.unitType).detail} 노부모부양의 추가 질문을 멈췄습니다. 다른 공급유형은 입력한 공통 사실로 계속 비교합니다.`
  }
  cache.set(profile, state)
  return state
}

/** A history question shares a field anchor with today's value, but needs its dated input. */
export function getProfileHistoryTarget(field: keyof LocalProfile, profile: LocalProfile, model: ProfileQuestionModel): FactChangeGroup | undefined {
  // The support start is its own dated fact. Past ownership questions pass an
  // explicit history group instead of diverting the actual start-date input.
  if (field === 'parentSupportSince') return undefined
  if (field === 'currentAccountFirstWinningDate') return undefined
  if (field === 'currentAccountUsedForWinning') return model.scopedRules.some(({ rule, date }) => rule.kind === 'account_unused_after_winning' && date && accountWinningUsageAtDate(profile, date).status === 'past_fact') ? 'bank_account' : undefined
  const parentKind = ({ parentSameRegister: 'parent_same_register', parentOwnsHome: 'parent_owns_home', parentSpouseOwnsHome: 'parent_spouse_owns_home' } as const)[field as 'parentSameRegister' | 'parentOwnsHome' | 'parentSpouseOwnsHome']
  if (parentKind && resolveParentSupport(profile).mode !== 'legacy') {
    for (const { rule, date } of model.scopedRules) if (rule.kind === parentKind && date) {
      const entry = resolveParentSupport(profile, date).facts[parentKind]
      if (!entry.temporalKnown && entry.value != null && entry.value !== '') return entry.historyGroup
    }
    return undefined
  }
  if (profile[field] == null || profile[field] === '' || profile[field] === 'unknown') return undefined
  return (Object.entries(FACT_GROUP_ANCHORS) as [FactChangeGroup, keyof LocalProfile][]).find(([group, anchor]) => anchor === field && model.scopedRules.some(({ rule, date }) =>
    (factGroupForRule(rule) === group || group === 'pregnancy' && ['children_min', 'newborn_children_min', 'first_home_family'].includes(rule.kind) && rule.include_pregnancy === true || group === 'children' && rule.kind === 'first_home_family') && date && !factsAtDate(profile, group, date).known,
  ))?.[0]
}

/** Parent facts reuse the dated input for their original household/points/ownership source. */
export function getParentSupportHistoryGroups(profile: LocalProfile, model: ProfileQuestionModel): FactChangeGroup[] {
  const groups = new Set<FactChangeGroup>()
  if (resolveParentSupport(profile).mode !== 'linked' || getElderParentQuestionState(profile, model).stopped) return []
  for (const { rule, date } of model.scopedRules) if (isParentRule(rule.kind) && date) {
    const entry = resolveParentSupport(profile, date).facts[rule.kind]
    if (!entry.temporalKnown && entry.value != null && entry.value !== '' && entry.historyGroup) groups.add(entry.historyGroup)
  }
  return [...groups]
}

/** Mount a canonical child-marital input only when it changes an offered route. */
export function getFirstHomeChildQuestionState(profile: LocalProfile, model: ProfileQuestionModel): { memberIds: string[]; historyNeeded: boolean } {
  const memberIds = new Set<string>()
  let historyNeeded = false
  for (const { rule, notice } of model.scopedRules) {
    if (rule.kind !== 'first_home_family' || rule.unmarried_child_required !== true && rule.unmarried_applicant_child_same_register !== true && rule.non_solo_requires_ascendant !== true) continue
    const assessed = evaluateRule(rule, profile, notice, rule.unit_type || undefined)
    if (assessed.status !== 'review' || assessed.profileField !== 'pointsFamily') continue
    if (assessed.profileMemberId) memberIds.add(assessed.profileMemberId)
    if (assessed.historyGroup === 'points') historyNeeded = true
  }
  return { memberIds: [...memberIds], historyNeeded }
}
