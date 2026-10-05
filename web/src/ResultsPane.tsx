import { useEffect, useMemo, useRef, useState } from 'react'
import { useEvaluations } from './useEvaluations'
import { reuseUnchangedNotices } from './publicNoticeCache'
import type { NoticeEvaluation } from './evaluation'
import { CalendarDays, ChevronDown, RotateCcw } from 'lucide-react'
import { getCalendarNotices } from './api'
import type { LocalProfile, Notice, ResidenceArea } from './types'
import { competitionUnitKey, resultCompetitionDecision, resultCompetitionRows, type CompetitionDecision } from './competition'
import './ResultsPane.css'

export interface ResultsSummary { notices: number; rows: number; unavailableNotices?: number; unavailableUnits?: number }
export const RESULTS_INTEREST_STORAGE_KEY = 'cheongyak-results-interest-v1'

export interface ResultInterestItem { notice: Notice; decision: CompetitionDecision; rows: number }
export function resultInterestItems(notices: Notice[], profile: LocalProfile, overrides: Record<string, ResidenceArea>, now: number, _legacyHideClosed?: boolean): ResultInterestItem[] {
  return notices.map((notice) => {
    const decision = resultCompetitionDecision(notice, profile, overrides[notice.id], now)
    return { notice, decision, rows: resultCompetitionRows(notice).length }
  }).filter((item) => item.rows > 0)
}

function recentStart(today: string): string {
  const date = new Date(`${today}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() - 89)
  return date.toISOString().slice(0, 10)
}

export function ResultsPane({ active, today, refreshVersion, capOnly, category, categoryGroup, profile, residenceOverrides, now, onSummary, onRefresh, renderCard }: {
  active: boolean; today: string; refreshVersion: number; capOnly: boolean;
  category: 'all' | 'private' | 'public' | 'rent';
  categoryGroup: (category: string) => string;
  profile: LocalProfile; residenceOverrides: Record<string, ResidenceArea>; now: number;
  onSummary: (summary: ResultsSummary) => void; onRefresh: () => void;
  renderCard: (notice: Notice, start: string, end: string, decision: CompetitionDecision, evaluation?: NoticeEvaluation) => React.ReactNode;
}) {
  const [range, setRange] = useState(() => ({ start: recentStart(today), end: today }))
  const [rows, setRows] = useState<Notice[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [limit, setLimit] = useState(20)
  const previousToday = useRef(today)
  const previousQuery = useRef('')
  const validRange = !!range.start && !!range.end && range.start <= range.end && range.end <= today

  useEffect(() => {
    const previous = previousToday.current
    if (today !== previous) {
      setRange((current) => current.start === recentStart(previous) && current.end === previous
        ? { start: recentStart(today), end: today } : current)
      previousToday.current = today
    }
  }, [today])

  useEffect(() => {
    if (!active || !validRange) return
    const controller = new AbortController()
    const query = `${range.start}:${range.end}:${capOnly}`
    if (previousQuery.current !== query) { setLimit(20); setRows([]) }
    previousQuery.current = query
    setLoading(true)
    setError(false)
    void getCalendarNotices(range.start, range.end, controller.signal, capOnly, 'results')
      .then((items) => { if (!controller.signal.aborted) setRows((previous) => reuseUnchangedNotices(previous, items)) })
      .catch(() => { if (!controller.signal.aborted) setError(true) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [active, range.start, range.end, validRange, capOnly, refreshVersion])

  const filtered = useMemo(() => rows.filter((notice) =>
    notice.category !== 'public_rental' && !/공공임대/.test(notice.category) &&
    (category === 'all' || categoryGroup(notice.category) === category) &&
    (!capOnly || notice.price_cap_status === 'yes') &&
    (notice.competitions || []).some((row) => row.verification === 'official')),
  [rows, category, categoryGroup, capOnly])

  const computation = useEvaluations(filtered, profile, today, residenceOverrides, now, active, 'results')
  const decisions = useMemo(() => filtered.map((notice) => ({ notice,
    decision: computation.evaluations[notice.id]?.decision || { area: 'unknown' as const, closedUnits: [], reason: null } })), [filtered, computation.evaluations])
  const visible = useMemo(() => decisions.map((item) => ({ ...item,
    rows: resultCompetitionRows(item.notice).length,
  })).filter((item) => item.rows > 0), [decisions])
  const unavailableNotices = decisions.filter((item) => item.decision.allApplicationsUnavailable).length
  const unavailableUnits = decisions.reduce((sum, item) => sum + new Set(item.decision.closedUnits.map(competitionUnitKey)).size, 0)
  const visibleRows = visible.reduce((sum, item) => sum + item.rows, 0)

  useEffect(() => { onSummary({ notices: visible.length, rows: visibleRows, unavailableNotices, unavailableUnits }) },
    [visible.length, visibleRows, unavailableNotices, unavailableUnits, onSummary])
  useEffect(() => { setLimit(20) }, [category])

  if (!active) return null
  return <div className="agenda results-agenda" role="tabpanel" id="results-panel" aria-labelledby="results-tab">
    <div className="agenda-topline"><div><span className="section-kicker">COMPETITION RESULTS</span><h2>경쟁률·청약결과</h2><p>접수가 끝난 공고도 주택형별 가격과 공식 경쟁률을 확인할 수 있습니다.</p></div><div className="agenda-tools"><button type="button" className="period-button" onClick={onRefresh}><RotateCcw size={15} /> 새로고침</button></div></div>
    <div className="results-range"><label>접수 기간 시작<input aria-label="결과 접수 기간 시작" type="date" value={range.start} max={range.end || today} onChange={(event) => setRange((current) => ({ ...current, start: event.target.value }))} /></label><span aria-hidden="true">–</span><label>접수 기간 끝<input aria-label="결과 접수 기간 끝" type="date" value={range.end} min={range.start} max={today} onChange={(event) => setRange((current) => ({ ...current, end: event.target.value }))} /></label><button type="button" className="period-button" onClick={() => setRange({ start: recentStart(today), end: today })}>최근 90일</button></div>
    {!validRange && <p className="error-banner" role="alert">오늘까지의 올바른 접수 기간을 선택해 주세요.</p>}
    <div className="results-availability-note" role="note"><p>내 조건으로 신청할 수 없거나 기타지역 배정 기회가 끝난 항목도 회색으로 표시합니다. 가격·경쟁률·원문은 모두 확인할 수 있습니다.</p>{unavailableUnits > 0 && <span>기타지역 배정 기회 종료 {unavailableUnits}개 주택형 · 표시 건수와 경쟁률 행 수에 포함</span>}</div>
    <p className="results-explanation">선택한 기간과 접수일이 겹치는 공개 결과 {visible.length}건 · 경쟁률 {visibleRows}행 · 접수 종료일 최신순</p>
    {computation.pending && <p className="background-refresh" role="status">내 조건 반영 중 · 현재 결과와 가격은 유지됩니다.</p>}
    {computation.error && <p className="error-banner" role="alert">{computation.error}</p>}
    {error && <div className="error-banner" role="alert">청약결과를 불러오지 못했습니다. 저장된 목록은 유지됩니다. 새로고침으로 다시 확인해 주세요.</div>}
    {loading && rows.length > 0 && <p className="background-refresh" role="status">새 결과를 확인하고 있습니다. 현재 목록은 유지됩니다.</p>}
    {loading && !rows.length ? <div className="loading-state" role="status"><span className="loading-spinner" /><strong>공식 청약결과를 불러오는 중입니다</strong></div>
      : visible.length ? <div className="notice-stack results-stack">{visible.slice(0, limit).map(({ notice, decision }) => renderCard(notice, range.start, range.end, decision, computation.evaluations[notice.id]))}{visible.length > limit && <button type="button" className="load-more" onClick={() => setLimit((value) => value + 20)}>결과 더 보기 · {visible.length - limit}건 남음 <ChevronDown size={16} /></button>}</div>
        : validRange && <div className="empty-state"><div className="empty-icon"><CalendarDays size={27} /></div><h3>{error ? '결과 조회에 실패했습니다' : '이 기간에 수집된 공식 경쟁률이 없습니다'}</h3><p>접수 기간을 넓히거나 아래 청약홈 경쟁률 수집 상태를 확인해 주세요. 결과가 공개된 진행 중 공고도 이 목록에 포함됩니다.</p></div>}
  </div>
}
