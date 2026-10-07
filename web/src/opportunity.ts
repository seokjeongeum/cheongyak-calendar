import type { LocalProfile, Notice, NoticeRule, ResidenceArea } from './types'
import { regionDecision } from './qualification'
import { calculatePoints, type PointsResult } from './points'
import { competitionUnitKey } from './competition'

export interface OpportunityRow { units: string[]; supplyTypes: string[]; label: string; detail: string; limited: boolean; evidenceUrl?: string; evidencePage?: number; pointsPercent?: number; lotteryPercent?: number; benchmark?: { minimum: number; difference: number | null; label: string; evidenceUrl?: string } }
export interface OpportunityResult { rows: OpportunityRow[]; points: PointsResult | null; unavailableMethod: boolean }
const official = (notice: Notice) => (notice.selection_methods || notice.rules).filter((r) => r.effect === 'metadata' && r.verification === 'official' && !!r.evidence_url)
function forUnit(rule: NoticeRule, unit: string, supplyType = '일반공급'): boolean {
  // Legacy selection metadata without a supply scope describes general supply.
  // A special-supply method needs its own scope or an explicit shared scope.
  const supplyScoped = !!rule.supply_type || Array.isArray(rule.supply_types)
  return (supplyScoped || supplyType === '일반공급') && (!rule.supply_type || rule.supply_type === supplyType) && (!Array.isArray(rule.supply_types) || rule.supply_types.includes(supplyType)) && (!rule.unit_type || competitionUnitKey(rule.unit_type) === competitionUnitKey(unit)) && (!Array.isArray(rule.unit_types) || rule.unit_types.some((u) => typeof u === 'string' && competitionUnitKey(u) === competitionUnitKey(unit)))
}
function selectionOrder(rule: NoticeRule): string {
  const order = Array.isArray(rule.selection_order) ? rule.selection_order.filter((stage): stage is string => typeof stage === 'string' && !!stage.trim()) : []
  const exceptions = Array.isArray(rule.selection_stage_exceptions) ? rule.selection_stage_exceptions.filter((stage): stage is { stage_number: number; selection_order: string[]; rank_applies?: boolean; evidence_text: string } => !!stage && typeof stage === 'object' && Number.isSafeInteger(stage.stage_number) && stage.stage_number > 0 && Array.isArray(stage.selection_order) && stage.selection_order.length > 0 && stage.selection_order.every((part: unknown) => typeof part === 'string' && !!part.trim()) && typeof stage.evidence_text === 'string' && !!stage.evidence_text.trim()) : []
  const base = order.length ? `${exceptions.length ? '기본 선정 순서' : '선정 순서'}: ${order.join(' → ')}. ` : ''
  return base + exceptions.map((stage) => {
    const stageOrder = `${stage.stage_number}단계 선정 순서: ${stage.selection_order.join(' → ')}. `
    if (stage.rank_applies === false && rule.allocation_method === 'region_priority' && stage.selection_order.join(':') === '지역:추첨') return stageOrder + `순위와 관계없이 ${localAreaName(rule)}을 먼저 선정하고, 경쟁 시 추첨합니다. `
    return stageOrder + (stage.rank_applies === false ? '순위를 적용하지 않습니다. ' : '')
  }).join('')
}
const evidencePage = (rule: NoticeRule): number | undefined => typeof rule.evidence_page === 'number' && Number.isSafeInteger(rule.evidence_page) && rule.evidence_page > 0 ? rule.evidence_page : undefined
function localAreaName(rule: NoticeRule): string {
  for (const scope of [rule.local_priority, rule.local_region]) {
    if (scope && typeof scope === 'object' && 'region_name' in scope && typeof scope.region_name === 'string' && scope.region_name) return `해당지역(${scope.region_name})`
  }
  return '해당지역'
}
function quotaDetail(rule: NoticeRule): string {
  const shares = Array.isArray(rule.regional_shares) ? rule.regional_shares.filter((share): share is { residence_area: string; percent: number; label?: string } => !!share && typeof share === 'object' && typeof share.percent === 'number' && Number.isFinite(share.percent) && share.percent >= 0 && share.percent <= 100) : []
  const labels: Record<string, string> = { local: '해당지역', other_gyeonggi: '기타경기', other: '기타지역', local_and_other_gyeonggi: '경기도' }
  const summary = shares.map((share) => `${typeof share.label === 'string' && share.label ? share.label : labels[share.residence_area] || share.residence_area} ${share.percent}%`).join(' · ')
  let detail = summary ? `${summary}로 배정합니다. ` : '공식 지역별 배정 물량이 있습니다. '
  if (rule.local_priority_within_first_quota === true) detail += `경기도 배정에서는 ${localAreaName(rule)}을 먼저 선정합니다. `
  if (rule.unsuccessful_applicants_advance === true) detail += '앞선 배정의 낙첨자는 다음 지역 배정에 다시 포함됩니다. '
  if (rule.local_priority_in_remaining_quota === false) detail += '그 배정에서는 해당지역 우선을 적용하지 않습니다. '
  return detail + selectionOrder(rule) + '배정 단계와 잔여물량 이동은 원문 기준입니다.'
}
/** Selection opportunity is informative; it cannot change eligibility or totals. */
export function selectionOpportunity(notice: Notice, profile: LocalProfile, confirmedArea?: ResidenceArea): OpportunityResult {
  const publicRules = official(notice)
  const supplies = (notice.offered_supplies || []).filter((s) => s.verification === 'official' && (s.supply_count == null || s.supply_count > 0))
  const units = [...new Set(supplies.filter((s) => s.supply_type === '일반공급').map((s) => s.unit_type).filter((unit): unit is string => !!unit))]
  const methods = publicRules.filter((r) => r.kind === 'selection_method' && r.rank === 1 && typeof r.points_percent === 'number' && typeof r.lottery_percent === 'number' && r.points_percent + r.lottery_percent === 100 && Math.min(r.points_percent, r.lottery_percent) >= 0)
  const methodForUnit = new Map(units.map((unit) => {
    const matched = methods.filter((method) => forUnit(method, unit))
    const agreed = matched.length && new Set(matched.map((r) => `${r.points_percent}:${r.lottery_percent}`)).size === 1 ? matched[0] : undefined
    return [unit, agreed] as const
  }))
  const points = [...methodForUnit.values()].some((r) => r && (r.points_percent as number) > 0) ? calculatePoints(notice, profile) : null
  const rows: OpportunityRow[] = []
  let house: string | null = null, announcement: string | null = null
  try {
    const query = new URL(notice.official_url || 'https://www.applyhome.co.kr').searchParams
    house = query.get('houseManageNo'); announcement = query.get('pblancNo')
  } catch { /* An invalid public source URL cannot invalidate the whole catalog. */ }
  const regions = new Map<string, ReturnType<typeof regionDecision>>()
  const manualUnits = new Set<string>()
  for (const supply of supplies) {
    const unit = supply.unit_type || '전체 주택형', supplyType = supply.supply_type
    const automatic = regionDecision(notice, profile, { supplyType, unitType: supply.unit_type || undefined })
    // A direct selection applies to general-supply allocation only. It cannot
    // override a verified regional result or establish admission eligibility.
    let region = automatic
    if (supplyType === '일반공급' && ['source_gap', 'missing_input'].includes(automatic.status) && confirmedArea && confirmedArea !== 'unknown') {
      region = { ...automatic, status: confirmedArea }
      manualUnits.add(unit)
    }
    regions.set(`${supplyType}:${unit}`, region)
    const allocations = publicRules.filter((r) => r.kind === 'regional_allocation' && forUnit(r, unit, supplyType))
    const allocation = new Set(allocations.map((r) => JSON.stringify([r.allocation_method, r.regional_shares, r.local_share_percent, r.selection_order, r.selection_stage_exceptions, r.local_priority, r.local_region, r.local_priority_within_first_quota, r.unsuccessful_applicants_advance, r.local_priority_in_remaining_quota]))).size === 1 ? allocations[0] : undefined
    if (allocation?.allocation_method === 'institution_recommendation') {
      rows.push({ units: [unit], supplyTypes: [supplyType], label: '추천기관 우선순위로 선정', detail: '추천기관이 정한 우선순위에 따라 확정·예비대상자를 선정합니다. 기관 추천 여부 등 신청 요건은 별도로 확인하세요.', limited: false, evidenceUrl: allocation.evidence_url || undefined, evidencePage: evidencePage(allocation) })
    } else if (region.status === 'other' || region.status === 'other_gyeonggi' || region.status === 'local' && allocation && (allocation.allocation_method === 'regional_quota' || supplyType !== '일반공급' && ['region_priority', 'all_local_first'].includes(String(allocation.allocation_method)))) {
      if (allocation?.allocation_method === 'regional_quota') {
        rows.push({ units: [unit], supplyTypes: [supplyType], label: region.status === 'local' ? '해당지역 · 지역별 배정' : region.status === 'other_gyeonggi' ? '기타경기 · 지역별 배정' : '기타지역 별도 배정', detail: quotaDetail(allocation), limited: false, evidenceUrl: allocation.evidence_url || undefined, evidencePage: evidencePage(allocation) })
      } else if (allocation && ['region_priority', 'all_local_first'].includes(String(allocation.allocation_method))) {
        rows.push({ units: [unit], supplyTypes: [supplyType], label: region.status === 'local' ? '해당지역 우선 선정' : '해당지역 우선 · 기타지역 기회 제한', detail: selectionOrder(allocation) + (supplyType === '일반공급' ? `같은 순위에서는 ${localAreaName(allocation)}을 먼저 선정합니다.` : `공고의 지역 선정 단계에서 ${localAreaName(allocation)}을 먼저 선정합니다.`) + ' 신청 자격은 별도로 확인하세요.', limited: region.status !== 'local', evidenceUrl: allocation.evidence_url || undefined, evidencePage: evidencePage(allocation) })
      } else {
        const area = region.status === 'other_gyeonggi' ? '기타경기' : '기타지역'
        const basis = supplyType === '일반공급' && manualUnits.has(unit) ? `직접 선택한 ${area} 기준입니다.` : `거주지의 지역 구분은 ${area}입니다.`
        rows.push({ units: [unit], supplyTypes: [supplyType], label: `${area} · 배정 방식 확인 필요`, detail: `${basis} 이 공급유형의 공식 지역별 물량·선정 순서는 아직 확인하지 못했습니다. 신청 자격은 별도로 확인하세요.`, limited: false, evidenceUrl: region.evidenceUrl || undefined })
      }
    }
  }
  for (const unit of units) {
    const region = regions.get(`일반공급:${unit}`)!
    const method = methodForUnit.get(unit)
    if (!method) continue
    const percent = method.points_percent as number, lottery = method.lottery_percent as number
    const benchmark = (notice.winning_scores || []).filter((row) => row.verification === 'official' && !!row.evidence_url && row.collection_status !== 'error' && row.house_manage_no === house && row.notice_no === announcement && competitionUnitKey(row.unit_type) === competitionUnitKey(unit) && row.residence_area === region.status && row.supply_type === '일반공급' && row.rank === 1 && row.selection_path === 'points' && row.criterion_date === points?.date && Number.isFinite(row.min_score) && row.min_score >= 0 && row.min_score <= 84)
    const agreed = new Set(benchmark.map((r) => r.min_score)).size === 1 ? benchmark[0] : undefined
    const minimum = agreed?.min_score
    const manualRegion = manualUnits.has(unit)
    rows.push({ units: [unit], supplyTypes: ['일반공급'], pointsPercent: percent, lotteryPercent: lottery, label: percent === 100 ? '가점제 100% · 추첨 배정 없음' : percent === 0 ? '추첨제 100%' : `가점 ${percent}% · 추첨 ${lottery}%`, detail: (percent === 100 ? `가점순 선정입니다.${method.tie_break === 'account_duration_then_lottery' ? ' 동점이면 통장 가입기간을 비교하고, 그 뒤 추첨합니다.' : ' 동점자 처리 방식은 원문을 확인하세요.'}` : '일반공급 1순위에 적용하는 공식 비율입니다.') + (manualRegion ? ' 직접 선택한 청약 지역 기준으로 비교합니다. 신청 자격 확인과는 별도입니다.' : ''), limited: percent === 100, evidenceUrl: method.evidence_url || undefined, evidencePage: evidencePage(method),
      benchmark: minimum != null ? { minimum, difference: points?.total != null ? points.total - minimum : null, label: points?.total != null && points.total < minimum ? '과거 최저가점 미만' : '공식 당첨 최저가점 비교', evidenceUrl: agreed!.evidence_url } : undefined })
  }
  const groups = new Map<string, OpportunityRow>()
  for (const row of rows) {
    // Keep each supply's actual units together. Merging both axes would imply
    // nonexistent offers, such as an 85㎡-limited special supply on a 123㎡ unit.
    const key = JSON.stringify({ ...row, units: undefined }), prior = groups.get(key)
    if (prior) prior.units = [...new Set([...prior.units, ...row.units])]
    else groups.set(key, row)
  }
  return { rows: [...groups.values()], points, unavailableMethod: units.length > 0 && notice.housing_kind === 'private' && notice.application_method === 'apt_ranked' && units.some((unit) => !methodForUnit.get(unit)) }
}
