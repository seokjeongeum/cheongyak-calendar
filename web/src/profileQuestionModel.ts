import { criterionDate } from './qualification'
import { factGroupForRule, setEvaluationToday } from './factTimeline'
import { parentCityCode } from './regions'
import type { FactChangeGroup, Notice, NoticeRule } from './types'

export interface ProfileRuleContext { rule: NoticeRule; notice: Notice; date: string | null }
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
  institution: boolean
  relocation: boolean
  needsMonthly: boolean
  needsNetAssets: boolean
  needsPlannedMarriage: boolean
  needsSingleParent: boolean
  needsProperty: boolean
}
const noticeContexts = new WeakMap<Notice, { today: string; rules: NoticeRule[]; rows: ProfileRuleContext[] }>()
const models = new WeakMap<Notice[], { today: string; model: ProfileQuestionModel }>()
function flatten(rule: NoticeRule, into: NoticeRule[]): void {
  if (rule.verification === 'official') into.push(rule)
  for (const list of [rule.conditions, rule.exceptions]) if (Array.isArray(list)) for (const entry of list) if (entry && typeof entry === 'object' && typeof entry.kind === 'string') flatten(entry, into)
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
    if (rule.domestic_only === true) pastGroups.add('domestic_residence')
  }
  const providerRules = scopedRules.filter(({ rule }) => rule.kind === 'provider_employee_restriction')
  const offeringText = notices.flatMap((notice) => [...notice.rules.map((rule) => `${rule.supply_type || ''} ${rule.kind === 'special_eligibility' ? rule.value || '' : ''}`), ...notice.events.map((event) => event.label), ...(notice.competitions || []).map((row) => row.supply_type_label || '')]).join(' ')
  const model: ProfileQuestionModel = {
    scopedRules,
    residenceRules: scopedRules.filter(({ rule }) => ['citizenship', 'overseas_residence'].includes(rule.kind)),
    restrictionRules: scopedRules.filter(({ rule }) => ['application_restriction', 'previous_winning', 'special_winning'].includes(rule.kind)),
    pastKinds, pastGroups,
    needsDetailedDistrict: scopedRules.some(({ rule }) => typeof rule.region_code === 'string' && !!parentCityCode(rule.region_code) || typeof rule.region_name === 'string' && /시\s*\S+구$/.test(rule.region_name)),
    needsDomestic: kinds.has('domestic_residence') || scopedRules.some(({ rule }) => rule.domestic_only === true),
    needsProvider: !!providerRules.length,
    providerHelp: `대상 기관: ${[...new Set(providerRules.map(({ notice }) => notice.provider))].join(' · ')}. 공고마다 배우자·직계존비속 등 확인 대상과 승인 예외가 다릅니다. 각 카드의 공식 근거에서 범위를 확인하세요.`,
    providerApproval: providerRules.some(({ rule }) => rule.purchase_approval_exception === true || rule.approval_exception === true),
    firstHome: /생애.?최초/.test(offeringText), elderParent: /노부모|부모부양/.test(offeringText), institution: /기관추천|추천|장애인|국가유공자|중소기업/.test(offeringText), relocation: /이전기관|이전공공기관/.test(offeringText),
    needsMonthly: kinds.has('shinhee_income') || kinds.has('monthly_income_max_krw') || scopedRules.some(({ rule }) => rule.kind === 'income_max_krw' && rule.period !== 'annual'),
    needsNetAssets: kinds.has('shinhee_assets'), needsPlannedMarriage: kinds.has('planned_marriage'), needsSingleParent: kinds.has('single_parent_family'),
    needsProperty: scopedRules.some(({ rule }) => /real_estate|vehicle|자동차|부동산/.test(String(rule.asset_basis || rule.kind))),
  }
  models.set(notices, { today, model })
  return model
}
export function warmProfileQuestionModel(notices: Notice[], today: string): void { getProfileQuestionModel(notices, today) }
