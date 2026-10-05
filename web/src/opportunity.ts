import type { LocalProfile, Notice, NoticeRule, ResidenceArea } from './types'
import { regionDecision } from './qualification'
import { calculatePoints, type PointsResult } from './points'
import { competitionUnitKey } from './competition'

export interface OpportunityRow { units: string[]; supplyTypes: string[]; label: string; detail: string; limited: boolean; evidenceUrl?: string; pointsPercent?: number; lotteryPercent?: number; benchmark?: { minimum: number; difference: number | null; label: string; evidenceUrl?: string } }
export interface OpportunityResult { rows: OpportunityRow[]; points: PointsResult | null; unavailableMethod: boolean }
const official = (notice: Notice) => (notice.selection_methods || notice.rules).filter((r) => r.effect === 'metadata' && r.verification === 'official' && !!r.evidence_url)
function forUnit(rule: NoticeRule, unit: string, supplyType = '일반공급'): boolean {
  return (!rule.supply_type || rule.supply_type === supplyType) && (!Array.isArray(rule.supply_types) || rule.supply_types.includes(supplyType)) && (!rule.unit_type || competitionUnitKey(rule.unit_type) === competitionUnitKey(unit)) && (!Array.isArray(rule.unit_types) || rule.unit_types.some((u) => typeof u === 'string' && competitionUnitKey(u) === competitionUnitKey(unit)))
}
/** Selection opportunity is informative; it cannot change eligibility or totals. */
export function selectionOpportunity(notice: Notice, profile: LocalProfile, confirmedArea?: ResidenceArea): OpportunityResult {
  const publicRules = official(notice)
  const supplies = (notice.offered_supplies || []).filter((s) => s.verification === 'official' && (s.supply_count == null || s.supply_count > 0))
  const units = [...new Set(supplies.filter((s) => s.supply_type === '일반공급').map((s) => s.unit_type).filter((unit): unit is string => !!unit))]
  const methods = publicRules.filter((r) => r.kind === 'selection_method' && r.rank === 1 && typeof r.points_percent === 'number' && typeof r.lottery_percent === 'number' && r.points_percent + r.lottery_percent === 100 && Math.min(r.points_percent, r.lottery_percent) >= 0)
  const points = methods.some((r) => (r.points_percent as number) > 0 && units.some((unit) => forUnit(r, unit))) ? calculatePoints(notice, profile) : null
  const rows: OpportunityRow[] = []
  const query = new URL(notice.official_url || 'https://www.applyhome.co.kr').searchParams
  const house = query.get('houseManageNo'), announcement = query.get('pblancNo')
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
    const allocation = new Set(allocations.map((r) => JSON.stringify([r.allocation_method, r.regional_shares, r.local_share_percent]))).size === 1 ? allocations[0] : undefined
    if (region.status === 'other' || region.status === 'other_gyeonggi') {
      if (allocation?.allocation_method === 'regional_quota') {
        const shares = Array.isArray(allocation.regional_shares) ? allocation.regional_shares.filter((v): v is { residence_area: string; percent: number } => !!v && typeof v === 'object' && typeof v.percent === 'number') : []
        const share = shares.find((s) => s.residence_area === region.status)
        rows.push({ units: [unit], supplyTypes: [supplyType], label: '기타지역 별도 배정', detail: share ? `공식 배정 ${share.percent}% · 배정 단계와 잔여물량 이동은 원문 기준입니다.` : '공식 지역별 배정 물량이 있습니다. 단순 후순위로 판단하지 않습니다.', limited: false, evidenceUrl: allocation.evidence_url || undefined })
      } else if (allocation && ['region_priority', 'all_local_first'].includes(String(allocation.allocation_method))) {
        rows.push({ units: [unit], supplyTypes: [supplyType], label: '해당지역 우선 · 기타지역 기회 제한', detail: '같은 순위에서는 해당지역을 먼저 선정합니다. 기타지역 신청 가능 여부와 당첨 기회는 별도입니다.', limited: true, evidenceUrl: allocation.evidence_url || undefined })
      } else rows.push({ units: [unit], supplyTypes: [supplyType], label: '기타지역 · 배정 방식 확인 필요', detail: '기타지역 자격은 확인했으나 공식 지역별 물량·선정 순서를 확보하지 못했습니다.', limited: false, evidenceUrl: region.evidenceUrl || undefined })
    }
  }
  for (const unit of units) {
    const region = regions.get(`일반공급:${unit}`)!
    const matched = methods.filter((method) => forUnit(method, unit))
    if (!matched.length || new Set(matched.map((r) => `${r.points_percent}:${r.lottery_percent}`)).size > 1) continue
    const method = matched[0], percent = method.points_percent as number, lottery = method.lottery_percent as number
    const benchmark = (notice.winning_scores || []).filter((row) => row.verification === 'official' && row.collection_status !== 'error' && row.house_manage_no === house && row.notice_no === announcement && competitionUnitKey(row.unit_type) === competitionUnitKey(unit) && row.residence_area === region.status && row.supply_type === '일반공급' && row.rank === 1 && row.selection_path === 'points' && row.criterion_date === points?.date && Number.isFinite(row.min_score) && row.min_score >= 0 && row.min_score <= 84)
    const agreed = new Set(benchmark.map((r) => r.min_score)).size === 1 ? benchmark[0] : undefined
    const minimum = agreed?.min_score
    const manualRegion = manualUnits.has(unit)
    rows.push({ units: [unit], supplyTypes: ['일반공급'], pointsPercent: percent, lotteryPercent: lottery, label: percent === 100 ? '가점제 100% · 추첨 배정 없음' : percent === 0 ? '추첨제 100%' : `가점 ${percent}% · 추첨 ${lottery}%`, detail: (percent === 100 ? `가점순 선정입니다.${method.tie_break === 'account_duration_then_lottery' ? ' 동점이면 통장 가입기간을 비교하고, 그 뒤 추첨합니다.' : ' 동점자 처리 방식은 원문을 확인하세요.'}` : '일반공급 1순위에 적용하는 공식 비율입니다.') + (manualRegion ? ' 직접 선택한 청약 지역 기준으로 비교합니다. 신청 자격 확인과는 별도입니다.' : ''), limited: percent === 100, evidenceUrl: method.evidence_url || undefined,
      benchmark: minimum != null ? { minimum, difference: points?.total != null ? points.total - minimum : null, label: points?.total != null && points.total < minimum ? '과거 최저가점 미만' : '공식 당첨 최저가점 비교', evidenceUrl: agreed!.evidence_url } : undefined })
  }
  const groups = new Map<string, OpportunityRow>()
  for (const row of rows) {
    const key = JSON.stringify({ ...row, units: undefined, supplyTypes: undefined }), prior = groups.get(key)
    if (prior) { prior.units = [...new Set([...prior.units, ...row.units])]; prior.supplyTypes = [...new Set([...prior.supplyTypes, ...row.supplyTypes])] }
    else groups.set(key, row)
  }
  return { rows: [...groups.values()], points, unavailableMethod: units.length > 0 && notice.housing_kind === 'private' && notice.application_method === 'apt_ranked' && units.some((unit) => !methods.some((method) => forUnit(method, unit))) }
}
