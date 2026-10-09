import type { ReactNode } from 'react'
import { Check, ChevronDown, ExternalLink, Info, MapPin, X } from 'lucide-react'
import { actionableReasons, applicationInstructions, comparisonReasonKey, conditionCoverage, conditionSourceStatus, officialOfferedSupplies, deriveRank, unitRankResults, ELIGIBILITY_LABEL, eligibilityCombinations, evaluateEligibility, rankUnitComparisons, reasonKey, uniqueReasons, supplyInventorySummary, supplySummaries, type EligibilityReason, type EligibilityResult, type RankResult } from './eligibility'
import type { CompetitionDecision } from './competition'
import type { NoticeEvaluation } from './evaluation'
import type { FactChangeGroup, LocalProfile, Notice } from './types'
import { regionDecision, type RegionDecision } from './qualification'
import './EligibilityDetails.css'

type ProfileAction = (field?: keyof LocalProfile, historyGroup?: FactChangeGroup) => void
function safeHref(url?: string | null): string | undefined {
  if (!url) return undefined
  try { const parsed = new URL(url); return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : undefined } catch { return undefined }
}
const tone = (result: EligibilityResult) => result.status === 'possible' ? 'possible' : result.status === 'mismatch' ? 'mismatch' : 'review'
const REGION_DECISION_LABEL: Record<RegionDecision['status'], string> = {
  local: '해당지역', other_gyeonggi: '기타경기', other: '기타지역', outside: '신청지역 밖',
  not_divided: '신청지역 충족', missing_input: '지역 정보 입력 필요', source_gap: '공식 지역 조건 확인 필요',
}
const SOURCE_STAGE_LABEL: Record<string, string> = { discovery: '공고문 찾기', download: '공고문 다운로드', conversion: '문서 형식 변환', decode: '문서 형식 변환·텍스트 추출', interpretation: '신청 조건 판독', identity: '공고번호·날짜·문서 변경 확인' }
export function noticeRegionGroups(notice: Notice, profile: LocalProfile): { decision: RegionDecision; scopes: string[] }[] {
  const inventory = officialOfferedSupplies(notice)
  const combinations = inventory.length ? inventory.map((item) => ({ supplyType: item.supply_type, unitType: item.unit_type || undefined }))
    : eligibilityCombinations(notice, profile).map((item) => ({ supplyType: item.supplyType === '공통 조건' ? undefined : item.supplyType, unitType: item.unitType === '전체 주택형' ? undefined : item.unitType }))
  if (!combinations.length) return [{ decision: regionDecision(notice, profile), scopes: [] }]
  const groups = new Map<string, { decision: RegionDecision; scopes: string[] }>()
  for (const scope of combinations) {
    const decision = regionDecision(notice, profile, scope)
    const signature = JSON.stringify([decision.status, decision.reason, decision.criterionDate, decision.reasons.map((item) => [item.status, item.input, item.requirement])])
    const label = [scope.supplyType, scope.unitType].filter(Boolean).join(' · ')
    const existing = groups.get(signature)
    if (existing) { if (label && !existing.scopes.includes(label)) existing.scopes.push(label) }
    else groups.set(signature, { decision, scopes: label ? [label] : [] })
  }
  return [...groups.values()]
}
export function NoticeRegionDecision({ notice, profile, onProfile, groups: prepared }: { notice: Notice; profile: LocalProfile; onProfile: ProfileAction; groups?: NoticeEvaluation['regions'] }) {
  const groups = prepared || noticeRegionGroups(notice, profile)
  return <section className="notice-region-decisions" aria-label="내 지역 판정"><strong className="notice-region-heading"><MapPin size={14} />내 지역 판정</strong>{groups.map(({ decision, scopes }, index) => {
    const question = decision.reasons.find((item) => item.profileField && ['missing_input', 'past_fact'].includes(item.category || ''))
    const label = decision.status === 'source_gap' && decision.reasons.some((item) => item.status === 'review' && item.category === 'past_fact') ? '과거 거주 이력 확인 필요' : REGION_DECISION_LABEL[decision.status]
    const priorityComparison = ['other', 'other_gyeonggi'].includes(decision.status) ? decision.reasons.find((item) => item.status === 'fail' && item.input && item.requirement) : undefined
    return <div className={`notice-region-decision${groups.length > 1 ? ' notice-region-scope' : ''}`} data-region-status={decision.status} key={index}>
      {groups.length > 1 && <small className="notice-region-scope-label">{scopes.join(' / ')}</small>}
      <div className="notice-region-result"><strong>{label}</strong><span>{decision.reason}</span></div>
      {priorityComparison && <p className="notice-region-comparison">내 입력 {priorityComparison.input} · 공고 요구 {priorityComparison.requirement}</p>}
      {decision.criterionDate && <small className="notice-region-date">지역 판정 기준일 {decision.criterionDate}</small>}
      {question && <button type="button" className="qualification-input-action" onClick={() => onProfile(question.profileField, question.historyGroup)}>{question.label} 입력하기</button>}
    </div>
  })}</section>
}
function rankGroups(notice: Notice, profile: LocalProfile): { units: string[]; result: RankResult }[] {
  const groups = new Map<string, { units: string[]; result: RankResult }>()
  for (const { unitType, result } of unitRankResults(notice, profile)) {
    const key = JSON.stringify([result.rank, result.status, result.label])
    const existing = groups.get(key)
    if (existing) existing.units.push(unitType)
    else groups.set(key, { units: [unitType], result })
  }
  return [...groups.values()]
}
export function reasonStatusLabel(reason: EligibilityReason): string {
  return reason.status === 'pass' ? '충족' : reason.status === 'fail' ? '불일치' : reason.category === 'missing_input' ? '내 입력 부족' : reason.category === 'past_fact' ? '과거 사실 미확인' : ['source_gap', 'unverified'].includes(reason.category || '') ? '서비스 원문 검토 부족' : '추가 확인 필요'
}
const needsProfile = (reason: EligibilityReason) => ['missing_input', 'past_fact'].includes(reason.category || '') && !!reason.profileField

function sourceForComparedSupplies(notice: Notice, profile: LocalProfile | undefined, compared: { supplyType: string; unitType?: string; result: EligibilityResult }[]) {
  const source = conditionSourceStatus(notice, profile)
  if (!compared.length) return source
  source.topics = source.topics.flatMap((topic) => {
    if (!topic.scopes.length) return [topic]
    const scopes = topic.scopes.filter((scope) => {
      const [supply, unit] = scope.split(' · ')
      const matches = compared.filter((item) => item.supplyType === supply && (!unit || !item.unitType || item.unitType === unit || item.unitType === '전체 주택형'))
      return !matches.length || matches.some((item) => item.result.status !== 'mismatch')
    })
    return scopes.length ? [{ ...topic, scopes }] : []
  })
  return source
}
function ReasonIcon({ reason }: { reason: EligibilityReason }) {
  return <span className={`qualification-icon qualification-icon-${reason.status}`} aria-hidden="true">{reason.status === 'pass' ? <Check size={12} /> : reason.status === 'fail' ? <X size={12} /> : <Info size={12} />}</span>
}
export function ReasonList({ reasons, demoMode = false, onProfile }: { reasons: EligibilityReason[]; demoMode?: boolean; onProfile?: ProfileAction }) {
  return <ul className="qualification-reasons">{uniqueReasons(reasons).map((reason) => {
    const link = demoMode ? undefined : safeHref(reason.evidenceUrl)
    const legalLink = demoMode ? undefined : safeHref(reason.legalEvidenceUrl)
    return <li className="qualification-reason" key={reasonKey(reason)}><ReasonIcon reason={reason} /><div className="qualification-reason-body"><strong>{reasonStatusLabel(reason)} · {reason.label}</strong>
      {(reason.input || reason.requirement || reason.criterionDate) && <dl className="qualification-comparison">{reason.input && <div><dt>내 입력</dt><dd>{reason.input}</dd></div>}{reason.requirement && <div><dt>공고 요구값</dt><dd>{reason.requirement}</dd></div>}{reason.criterionDate && <div><dt>{reason.contractPreview || reason.todayPreview ? '오늘 비교일 (한국 시간)' : '기준일'}</dt><dd>{reason.criterionDate}</dd></div>}</dl>}
      <p className="qualification-reason-detail">판단 이유: {reason.detail}</p>
      {needsProfile(reason) && onProfile && <button type="button" className="qualification-input-action" onClick={() => onProfile(reason.profileField, reason.historyGroup)}>{reason.label} 입력하기</button>}
      {reason.evidenceText && <blockquote className="qualification-evidence">{reason.evidenceText}</blockquote>}
      {link && <a href={link} target="_blank" rel="noopener noreferrer">원문 근거 <ExternalLink size={12} /></a>}
      {legalLink && <a href={legalLink} target="_blank" rel="noopener noreferrer">국토교통부 생애최초 예외 안내 <ExternalLink size={12} /></a>}
    </div></li>
  })}</ul>
}
export function selectBriefReasons(reasons: EligibilityReason[]): EligibilityReason[] {
  const useful = actionableReasons(reasons)
  const selected = ['fail', 'pass', 'review'].flatMap((status) => {
    const reason = status === 'review' ? useful.find((candidate) => needsProfile(candidate)) || useful.find((candidate) => candidate.status === status) : useful.find((candidate) => candidate.status === status)
    return reason ? [reason] : []
  })
  return [...selected, ...useful.filter((reason) => !selected.includes(reason))].slice(0, 3)
}
export function comparedConditionsLabel(result: EligibilityResult): string {
  if (result.status === 'mismatch') return '내 조건으로 신청 불가'
  if (result.status === 'possible') return ELIGIBILITY_LABEL.possible
  const useful = [...new Map(actionableReasons(result.reasons).map((reason) => [comparisonReasonKey(reason), reason])).values()]
  const missing = useful.filter((reason) => reason.category === 'missing_input').length
  const historical = useful.filter((reason) => reason.category === 'past_fact').length
  const passed = useful.filter((reason) => reason.status === 'pass').length
  return missing || historical ? [missing ? `내 입력 ${missing}개 필요` : '', historical ? `과거 사실 ${historical}개 확인 필요` : ''].filter(Boolean).join(' · ') : passed ? `확인한 ${passed}개 조건 충족` : '모집 정보'
}
function InventorySummary({ notice, demoMode = false }: { notice?: Notice; demoMode?: boolean }) {
  const summary = notice && supplyInventorySummary(notice)
  if (!summary) return null
  const link = demoMode ? undefined : safeHref(summary.evidenceUrl)
  return <p className="qualification-inventory-summary"><span>단지 전체 <strong>{summary.totalHouseholds.toLocaleString('ko-KR')}세대</strong> · 금회 모집 <strong>{summary.currentSupplyCount.toLocaleString('ko-KR')}세대</strong></span>{link && <a href={link} target="_blank" rel="noopener noreferrer">공식 공급 근거 <ExternalLink size={12} /></a>}</p>
}
function ApplicationInstructions({ notice, demoMode = false, brief = false }: { notice?: Notice; demoMode?: boolean; brief?: boolean }) {
  const instructions = notice ? applicationInstructions(notice) : []
  if (!instructions.length) return null
  return <section className={brief ? 'qualification-application-instructions qualification-instructions-brief' : 'qualification-section qualification-application-instructions'} aria-label="신청 시 지켜야 할 조건"><strong>신청 시 지켜야 할 조건</strong><ul>{instructions.map((item) => {
    const link = demoMode ? undefined : safeHref(item.evidenceUrl)
    return <li key={`${item.label}-${item.detail}`}><strong>{item.label}</strong><p>{item.detail}</p>{!brief && link && <a href={link} target="_blank" rel="noopener noreferrer">신청 조건 원문{item.evidencePage ? ` ${item.evidencePage}쪽` : ''} <ExternalLink size={12} /></a>}</li>
  })}</ul></section>
}
function MissingSourceTopics({ topics, demoMode = false }: { topics: ReturnType<typeof conditionSourceStatus>['topics']; demoMode?: boolean }) {
  return <ul className="qualification-remaining-topics">{topics.map((item) => {
    const link = demoMode ? undefined : safeHref(item.evidenceUrl)
    return <li key={JSON.stringify([item.label, item.reason, item.evidenceText, item.documentHash])}><strong>{item.label}</strong>{item.scopes.length > 0 && <small>적용: {item.scopes.join(' / ')}</small>}{item.reason && <span>{item.reason}</span>}{item.evidenceText && <blockquote className="qualification-evidence">{item.evidenceText}</blockquote>}{link && <a href={link} target="_blank" rel="noopener noreferrer">검토할 원문{item.evidencePage ? ` ${item.evidencePage}쪽` : ''} <ExternalLink size={12} /></a>}</li>
  })}</ul>
}
function OfferedUnits({ notice, supplyType, unitTypes }: { notice?: Notice; supplyType: string; unitTypes: string[] }) {
  const inventory = notice ? officialOfferedSupplies(notice).filter((item) => item.supply_type === supplyType && (!item.unit_type || unitTypes.includes(item.unit_type))) : []
  if (inventory.length) return <small className="qualification-offered-units">{inventory.map((item) => `${item.unit_type || '전체 주택형'}${item.supply_count != null ? ` · 모집 ${item.supply_count.toLocaleString('ko-KR')}세대` : ''}`).join(' / ')}</small>
  return unitTypes.some((unit) => unit !== '전체 주택형') ? <small>{unitTypes.join(' · ')}</small> : null
}
function UnavailableSupply({ className, heading, units, children }: { className: string; heading: ReactNode; units?: ReactNode; children: ReactNode }) {
  return <details className={`${className} qualification-supply-collapse`}>
    <summary className="qualification-supply-toggle"><div className="qualification-supply-toggle-heading">{heading}<ChevronDown size={15} aria-hidden="true" /></div>{units}<span className="qualification-supply-toggle-help"><span className="qualification-supply-show">불일치 근거 펼치기</span><span className="qualification-supply-hide">불일치 근거 접기</span></span></summary>
    {children}
  </details>
}
export function EligibilityBrief({ result, notice, profile, decision, onProfile, onDetails, candidateReason, snapshot, sourceDetailsOpen = false }: { result: EligibilityResult; notice?: Notice; profile?: LocalProfile; decision?: CompetitionDecision; onProfile: ProfileAction; onDetails?: () => void; candidateReason?: string; snapshot?: NoticeEvaluation; sourceDetailsOpen?: boolean }) {
  const supplies = snapshot?.supplies || (notice && profile ? supplySummaries(notice, profile, decision) : [])
  const rankResult = snapshot?.rank || (notice && profile ? deriveRank(notice, profile) : undefined)
  const fallback = snapshot?.common || (notice && profile ? evaluateEligibility(notice, profile) : result)
  const selected = selectBriefReasons(fallback.reasons)
  // A scope-free comparison can intentionally request a supply selection.
  // The actual offered scopes already include common requirements.
  const comparedReasons = supplies.length ? supplies.filter((supply) => supply.result.status !== 'mismatch').flatMap((supply) => supply.result.reasons) : fallback.reasons
  const hasGap = comparedReasons.some((reason) => ['source_gap', 'unverified'].includes(reason.category || ''))
  const rankConfirmed = (rankResult?.reasons || []).filter((reason) => reason.status === 'pass')
  const rankQuestion = (rankResult?.reasons || []).find(needsProfile)
  const rankedUnits = snapshot?.rankedUnits || (notice && profile ? rankGroups(notice, profile) : [])
  const showUnitRanks = rankedUnits.length > 1 || rankedUnits.some((group) => group.result.rank === 'first' && rankResult?.rank !== 'first')
  const source = notice ? sourceForComparedSupplies(notice, profile, supplies) : { diagnostics: [], topics: [] }
  const officialInventory = notice ? officialOfferedSupplies(notice) : []
  const visibleSupplies = supplies.filter((supply) => supply.result.status === 'mismatch' || actionableReasons(supply.result.reasons).length > 0 || officialInventory.some((item) => item.supply_type === supply.supplyType))
  const sharedReasons = (snapshot?.sharedReasons || uniqueReasons(supplies.flatMap((supply) => actionableReasons(supply.result.reasons))).filter((reason) => supplies.filter((supply) => actionableReasons(supply.result.reasons).some((item) => reasonKey(item) === reasonKey(reason))).length > 1))
    .filter((reason) => supplies.some((supply) => supply.result.status !== 'mismatch' && actionableReasons(supply.result.reasons).some((item) => reasonKey(item) === reasonKey(reason))))
  const sharedKeys = new Set(sharedReasons.map(reasonKey))
  const shownShared = selectBriefReasons(sharedReasons)
  const hasRankComparison = rankResult && (actionableReasons(rankResult.reasons).length > 0 || rankResult.rank === 'not_applicable')
  return <div className="qualification-brief" aria-label="자격 판단 이유">
    <InventorySummary notice={notice} />
    {candidateReason && <p className="qualification-candidate"><MapPin size={13} /><span>{candidateReason}</span></p>}
    {hasRankComparison && <div className="qualification-account-summary"><small>청약통장·순위 조건</small><strong>{rankResult.label}</strong>{rankConfirmed.length > 0 && <span>{rankConfirmed.map((reason) => `${reason.label} 충족`).join(' · ')}</span>}{rankQuestion && <button type="button" className="qualification-input-action" onClick={() => onProfile(rankQuestion.profileField, rankQuestion.historyGroup)}>{rankQuestion.label} 입력하기</button>}</div>}
    {showUnitRanks && <div className="qualification-unit-ranks" aria-label="주택형별 청약순위">{rankedUnits.map((group) => <div key={group.units.join(',')}><span>{group.units.join(' · ')}</span><strong>{group.result.label}</strong></div>)}</div>}
    {!!shownShared.length && <div className="qualification-brief-common"><strong>모집 유형에 공통으로 적용되는 조건</strong>{shownShared.map((reason) => <div className="qualification-brief-row" key={reasonKey(reason)}><ReasonIcon reason={reason} /><div><strong>{reasonStatusLabel(reason)} · {reason.label}</strong><span>{reason.detail}</span>{needsProfile(reason) && <button type="button" className="qualification-input-action" onClick={() => onProfile(reason.profileField, reason.historyGroup)}>{reason.label} 입력하기</button>}</div></div>)}</div>}
    {visibleSupplies.length > 0 ? <div className="qualification-supply-overview" aria-label="모집 유형별 신청 가능성"><strong className="qualification-application-heading">{visibleSupplies.some((supply) => actionableReasons(supply.result.reasons).length > 0) ? '이 공고의 신청 조건' : '공식 모집 유형'}</strong>{visibleSupplies.map((supply, index) => {
      const useful = actionableReasons(supply.result.reasons)
      const shown = selectBriefReasons(useful.filter((reason) => !sharedKeys.has(reasonKey(reason))))
      const className = `qualification-supply-brief qualification-${tone(supply.result)}${supply.result.status === 'mismatch' ? ' qualification-unavailable' : ''}${!useful.length ? ' qualification-inventory-only' : ''}`
      const heading = <div className="qualification-supply-title"><strong>{supply.supplyType}</strong>{(useful.length > 0 || supply.result.status === 'mismatch') && <span>{comparedConditionsLabel(supply.result)}</span>}</div>
      const units = <OfferedUnits notice={notice} supplyType={supply.supplyType} unitTypes={supply.unitTypes} />
      if (supply.result.status === 'mismatch') return <UnavailableSupply className={className} heading={heading} units={units} key={`${supply.supplyType}-${index}`}><ReasonList reasons={supply.result.reasons.filter((reason) => reason.status === 'fail')} /></UnavailableSupply>
      return <section className={className} key={`${supply.supplyType}-${index}`}>{heading}{units}{shown.map((reason) => <div className="qualification-brief-row" key={reasonKey(reason)}><ReasonIcon reason={reason} /><div><strong>{reasonStatusLabel(reason)} · {reason.label}</strong><span>{reason.detail}</span>{needsProfile(reason) && <button type="button" className="qualification-input-action" onClick={() => onProfile(reason.profileField, reason.historyGroup)}>{reason.label} 입력하기</button>}</div></div>)}</section>
    })}</div> : selected.map((reason) => <div className="qualification-brief-row" key={reasonKey(reason)}><ReasonIcon reason={reason} /><div><strong>{reasonStatusLabel(reason)} · {reason.label}</strong><span>{reason.detail}</span>{needsProfile(reason) && <button type="button" className="qualification-input-action" onClick={() => onProfile(reason.profileField, reason.historyGroup)}>{reason.label} 입력하기</button>}</div></div>)}
    <ApplicationInstructions notice={notice} brief />
    {!sourceDetailsOpen && (hasGap || source.diagnostics.length > 0 || source.topics.length > 0 || !selected.length && !visibleSupplies.length) && <section className="qualification-gap-note" aria-label="서비스 원문 검토 부족"><strong>서비스 원문 검토 부족</strong><p>{source.diagnostics.length ? `${SOURCE_STAGE_LABEL[source.diagnostics[0].stage] || '공고 자료 확인'} · ${source.diagnostics[0].message}` : source.topics.length ? '아래 공식 조항을 아직 비교에 반영하지 못했습니다.' : '이 공고의 필수 신청 요건과 예외에 대한 검토 기록을 확보하지 못했습니다.'}</p>{!!source.topics.length && <MissingSourceTopics topics={source.topics.slice(0, 3)} />}{source.topics.length > 3 && <small>추가 미확보 조항 {source.topics.length - 3}개</small>}{onDetails && <button type="button" className="qualification-input-action" onClick={onDetails}>남은 조항과 처리 단계 확인</button>}</section>}
  </div>
}

export function EligibilityDetails({ notice, profile, decision, demoMode = false, onProfile, children, snapshot }: { notice: Notice; profile: LocalProfile; decision?: CompetitionDecision; demoMode?: boolean; onProfile: ProfileAction; children?: ReactNode; snapshot?: NoticeEvaluation }) {
  const combinations = snapshot?.combinations || eligibilityCombinations(notice, profile, decision)
  const commonResult = snapshot?.common || evaluateEligibility(notice, profile)
  const expandedEvidenceKeys = new Set(combinations.filter((combo) => combo.result.status !== 'mismatch').flatMap((combo) => actionableReasons(combo.result.reasons).map(reasonKey)))
  const commonReasons = actionableReasons(commonResult.reasons).filter((reason) => !combinations.length || expandedEvidenceKeys.has(reasonKey(reason)))
  const commonKeys = new Set(commonReasons.map(reasonKey))
  const ranked = snapshot?.rank || deriveRank(notice, profile)
  const rankedUnits = snapshot?.rankedUnits || rankGroups(notice, profile)
  const showUnitRanks = rankedUnits.length > 1 || rankedUnits.some((group) => group.result.rank === 'first' && ranked.rank !== 'first')
  const areaComparisons = snapshot?.rankComparisons || rankUnitComparisons(notice, profile)
  const rankReasons = actionableReasons(ranked.reasons).filter((reason) => !commonKeys.has(reasonKey(reason)))
  const activeReasons = combinations.filter((combo) => combo.result.status !== 'mismatch').flatMap((combo) => combo.result.reasons)
  const activeKeys = new Set(activeReasons.map(reasonKey))
  const sourceGaps = uniqueReasons([...commonResult.reasons.filter((reason) => !combinations.length || activeKeys.has(reasonKey(reason))), ...ranked.reasons, ...activeReasons].filter((reason) => reason.category === 'source_gap'))
  const candidates = (notice.rules || []).filter((rule) => rule.effect !== 'metadata' && rule.verification !== 'official')
  const coverage = conditionCoverage(notice)
  const source = sourceForComparedSupplies(notice, profile, combinations)
  const additionalSourceGaps = sourceGaps.filter((reason) =>
    !['공고 조건 정리 중', '나머지 공고 조건'].includes(reason.label) &&
    !(reason.label === '미확보 공고 조항' && source.topics.length > 0) &&
    !source.topics.some((topic) => topic.label === reason.label))
  const inventory = officialOfferedSupplies(notice)
  const scopedReasons = new Map<string, { reason: EligibilityReason; scopes: Set<string>; expanded: boolean }>()
  for (const combo of combinations) {
    const scope = combo.unitType === '전체 주택형' ? combo.supplyType : `${combo.supplyType} · ${combo.unitType}`
    for (const reason of actionableReasons(combo.result.reasons)) {
      const key = reasonKey(reason)
      if (commonKeys.has(key)) continue
      const shared = scopedReasons.get(key)
      if (shared) { shared.scopes.add(scope); shared.expanded ||= combo.result.status !== 'mismatch' }
      else scopedReasons.set(key, { reason, scopes: new Set([scope]), expanded: combo.result.status !== 'mismatch' })
    }
  }
  const sharedKeys = new Set([...scopedReasons.entries()].filter(([, value]) => value.expanded && value.scopes.size > 1).map(([key]) => key))
  const sharedGroups = new Map<string, { scopes: string[]; reasons: EligibilityReason[] }>()
  for (const key of sharedKeys) {
    const shared = scopedReasons.get(key)!
    const scopes = [...shared.scopes], signature = JSON.stringify(scopes)
    const group = sharedGroups.get(signature)
    if (group) group.reasons.push(shared.reason)
    else sharedGroups.set(signature, { scopes, reasons: [shared.reason] })
  }
  const hasConclusiveSupply = combinations.some((combo) => ['possible', 'mismatch'].includes(combo.result.status))
  const grouped = new Map<string, { label: string; result: EligibilityResult; reasons: EligibilityReason[]; units: string[] }>()
  for (const combo of combinations) {
    const reasons = actionableReasons(combo.result.reasons).filter((reason) => !commonKeys.has(reasonKey(reason)) && !sharedKeys.has(reasonKey(reason)))
    // Moving evidence to the common section must not erase a supply's actual
    // outcome. Keep known outcomes and their review alternatives visible;
    // uniformly incomplete groups need only the single source-gap notice.
    if (!reasons.length && !hasConclusiveSupply) continue
    const signature = JSON.stringify([combo.supplyType, combo.result.status, reasons.map(reasonKey)])
    const existing = grouped.get(signature)
    if (existing) existing.units.push(combo.unitType)
    else grouped.set(signature, { label: combo.supplyType, result: combo.result, reasons, units: [combo.unitType] })
  }
  return <div className="qualification-details">
    <p className="qualification-intro">공식 공고의 조건과 입력한 사실을 비교합니다. 신청 전 최종 자격과 증빙은 공식 공고문에서 확인하세요.</p>
    {!!inventory.length && <section className="qualification-section qualification-inventory"><h5>공식 모집 주택형·공급유형</h5><InventorySummary notice={notice} demoMode={demoMode} /><ul>{inventory.map((item, index) => <li key={`${item.supply_type}-${item.unit_type}-${index}`}><strong>{item.supply_type}</strong><span>{item.unit_type || '전체 주택형'}{item.supply_count != null ? ` · 모집 ${item.supply_count.toLocaleString('ko-KR')}세대` : ''}</span>{!demoMode && safeHref(item.evidence_url) && <a href={safeHref(item.evidence_url)} target="_blank" rel="noopener noreferrer">모집표 원문 <ExternalLink size={12} /></a>}</li>)}</ul></section>}
    {!!commonReasons.length && <section className="qualification-section"><h5>이 공고의 공통 신청 조건</h5><ReasonList reasons={commonReasons} demoMode={demoMode} onProfile={onProfile} /></section>}
    {!!sharedGroups.size && <section className="qualification-section qualification-shared"><h5>유형 간 공통 조건</h5>{[...sharedGroups.entries()].map(([key, group]) => <div key={key}><p>적용: {group.scopes.join(' · ')}</p><ReasonList reasons={group.reasons} demoMode={demoMode} onProfile={onProfile} /></div>)}</section>}
    {!!rankReasons.length && <section className="qualification-section"><div className="qualification-section-head"><h5>청약통장·순위 조건</h5><span className={`qualification-badge qualification-${tone(ranked)}`}>{ranked.label}</span></div><ReasonList reasons={rankReasons} demoMode={demoMode} onProfile={onProfile} /></section>}
    {!!areaComparisons.length && <section className="qualification-section"><h5>면적별 청약통장 조건</h5>{areaComparisons.map((comparison) => <div className="qualification-unit-comparison" key={comparison.units.join(',')}><h6>{comparison.units.join(' · ')}</h6><ReasonList reasons={comparison.reasons} demoMode={demoMode} onProfile={onProfile} /></div>)}</section>}
    {showUnitRanks && <section className="qualification-section"><h5>주택형별 청약순위</h5>{rankedUnits.map((group) => <div className="qualification-unit-comparison" key={group.units.join(',')}><div className="qualification-section-head"><h6>{group.units.join(' · ')}</h6><span className={`qualification-badge qualification-${tone(group.result)}`}>{group.result.label}</span></div><ReasonList reasons={actionableReasons(group.result.reasons).filter((reason) => reason.status !== 'pass')} demoMode={demoMode} onProfile={onProfile} /></div>)}</section>}
    {[...grouped.entries()].map(([key, group]) => {
      const className = `qualification-section qualification-supply${group.result.status === 'mismatch' ? ' qualification-unavailable' : ''}`
      const heading = <div className="qualification-section-head"><h5>{group.label}<small>{[...new Set(group.units)].join(' · ')}</small></h5><span className={`qualification-badge qualification-${tone(group.result)}`}>{group.result.status === 'unpublished' ? '조건 비교 자료 확인' : group.result.status === 'mismatch' ? '내 조건으로 신청 불가' : ELIGIBILITY_LABEL[group.result.status]}</span></div>
      if (group.result.status === 'mismatch') return <UnavailableSupply className={className} heading={heading} key={key}><ReasonList reasons={uniqueReasons([...group.reasons, ...group.result.reasons.filter((reason) => reason.status === 'fail')])} demoMode={demoMode} onProfile={onProfile} /></UnavailableSupply>
      return <section className={className} key={key}>{heading}{!!group.reasons.length && <ReasonList reasons={group.reasons} demoMode={demoMode} onProfile={onProfile} />}</section>
    })}
    <ApplicationInstructions notice={notice} demoMode={demoMode} />
    {(sourceGaps.length > 0 || source.diagnostics.length > 0 || source.topics.length > 0 || !coverage.verifiedCount && !grouped.size) && <section className="qualification-source-gap" aria-label="서비스 원문 검토 부족"><strong>서비스 원문 검토 부족 · 미확보 조항과 처리 단계</strong><p>{commonReasons.length || sharedGroups.size || grouped.size || rankReasons.length || areaComparisons.length ? '확인한 조건은 위에서 비교했습니다. 아래 공식 조항은 서비스의 원문 검토가 더 필요합니다.' : '현재 확보한 자료로 신청 조건을 비교할 수 없습니다. 개인 정보 미입력이나 신청 자격 불일치로 판단하지 않습니다.'}</p>
      {!!source.diagnostics.length && <ul className="qualification-source-diagnostics">{source.diagnostics.map((item, index) => <li key={`${item.stage}-${item.code}-${index}`}><strong>{SOURCE_STAGE_LABEL[item.stage] || '공고 자료 확인'}</strong><span>{item.message}</span>{!!item.missingItems?.length && <small>미확보 항목: {item.missingItems.join(' · ')}</small>}{!demoMode && safeHref(item.evidenceUrl) && <a href={safeHref(item.evidenceUrl)} target="_blank" rel="noopener noreferrer">관련 원문 <ExternalLink size={12} /></a>}</li>)}</ul>}
      {!!source.topics.length && <MissingSourceTopics topics={source.topics} demoMode={demoMode} />}
      {!!additionalSourceGaps.length && <ReasonList reasons={additionalSourceGaps} demoMode={demoMode} />}
      {!demoMode && safeHref(notice.official_url) && <a href={safeHref(notice.official_url)} target="_blank" rel="noopener noreferrer">공식 공고문 확인 <ExternalLink size={12} /></a>}
    </section>}
    {!!candidates.length && <details className="qualification-candidates"><summary>자동 추출 참고 내용 {candidates.length}건 · 원문 검토 전</summary><p>검토 전 내용은 자격 충족이나 신청 불가 판단에 사용하지 않습니다.</p><ul>{candidates.map((rule, index) => <li key={rule.id || index}>{rule.supply_type && <strong>{rule.supply_type} · </strong>}{rule.evidence_text || rule.text || '추출 내용의 원문을 확인해 주세요.'}{!demoMode && safeHref(rule.evidence_url) && <a href={safeHref(rule.evidence_url)} target="_blank" rel="noopener noreferrer">원문 <ExternalLink size={12} /></a>}</li>)}</ul></details>}
    {children}
  </div>
}
