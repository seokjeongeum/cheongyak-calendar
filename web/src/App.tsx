import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowRight, ArrowUpRight, CalendarDays, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight,
  CircleAlert, Clock3, Database, ExternalLink, Info, ListFilter, LockKeyhole, MapPin,
  RotateCcw, ShieldCheck, SlidersHorizontal, Sparkles, Wallet, X,
} from 'lucide-react'
import { getCalendarNotices, getCoverage } from './api'
import { competitionDecision, competitionFresh, competitionRateLabel, competitionRowLabel, competitionUnitKey, resultCompetitionRows, RESIDENCE_AREA_LABEL, type CompetitionDecision } from './competition'
import { demoNotices } from './demo'
import { ELIGIBILITY_LABEL, applicationEventAvailability, type EligibilityStatus } from './eligibility'
import { EMPTY_PROFILE, type CoverageResponse, type LocalProfile, type Notice, type NoticeEvent, type NoticePrice, type ResidenceArea } from './types'

import { ProfileDialogController, type ProfileDialogHandle } from './ProfileDialogController'
import { warmProfileQuestionModel } from './profileQuestionModel'
import { ResultsPane, type ResultsSummary } from './ResultsPane'
import { readProfile, saveProfile, selectProvince, selectDistrict } from './profile'
import { districtOptions, provinceOptions } from './regions'
export { eventCandidate, hasResidenceCandidate, candidateLabel, candidateExplanation } from './candidates'
import { EligibilityBrief, EligibilityDetails, NoticeRegionDecision } from './EligibilityDetails'
import { OpportunityPanel } from './OpportunityPanel'
import { isOpenEndedReception, nextDeadline, receptionEndDate, receptionOverlaps } from './deadlines'
import { useEvaluations } from './useEvaluations'
import { reuseUnchangedNotices } from './publicNoticeCache'
import { candidateInRange, evaluateNotice, type NoticeEvaluation } from './evaluation'
export { selectBriefReasons as briefReasons } from './EligibilityDetails'
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']
const RESIDENCE_OVERRIDE_KEY = 'cheongyak-residence-overrides-v1'
const KST_DISPLAY_TIME = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
const KST_OFFSET_MS = 9 * 60 * 60 * 1000

function kstToday(): string {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  const pick = (part: string) => parts.find((item) => item.type === part)?.value || ''
  return `${pick('year')}-${pick('month')}-${pick('day')}`
}

export function msUntilNextKstMidnight(now = Date.now()): number {
  const shifted = now + KST_OFFSET_MS
  return (Math.floor(shifted / 86_400_000) + 1) * 86_400_000 - shifted + 1000
}

function maxDate(a: string, b: string): string { return a > b ? a : b }

function monthShift(month: string, offset: number): string {
  const [year, mm] = month.split('-').map(Number)
  const date = new Date(Date.UTC(year, mm - 1 + offset, 1))
  return date.toISOString().slice(0, 7)
}

function monthEnd(month: string): string {
  const [year, mm] = month.split('-').map(Number)
  return new Date(Date.UTC(year, mm, 0)).toISOString().slice(0, 10)
}

function addDays(date: string, days: number): string {
  const next = new Date(`${date}T00:00:00Z`)
  next.setUTCDate(next.getUTCDate() + days)
  return next.toISOString().slice(0, 10)
}

function formatDate(date: string | null | undefined, withYear = false): string {
  if (!date) return '일정 미공개'
  const parsed = new Date(`${date.slice(0, 10)}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return date
  const year = parsed.getUTCFullYear()
  const month = parsed.getUTCMonth() + 1
  const day = parsed.getUTCDate()
  const weekday = WEEKDAYS[parsed.getUTCDay()]
  return `${withYear ? `${year}년 ` : ''}${month}월 ${day}일 (${weekday})`
}

function formatShortDate(date: string | null | undefined): string {
  if (!date) return '미공개'
  const parts = date.slice(0, 10).split('-').map(Number)
  if (parts.length < 3) return date
  return `${parts[1]}.${String(parts[2]).padStart(2, '0')}`
}

function formatFullShortDate(date: string | null | undefined): string {
  if (!date) return '미공개'
  const parts = date.slice(0, 10).split('-').map(Number)
  if (parts.length < 3 || parts.some((part) => !Number.isFinite(part))) return date
  return `${parts[0]}.${parts[1]}.${String(parts[2]).padStart(2, '0')}`
}

function formatEventRange(event: NoticeEvent, today: string): string {
  if (isOpenEndedReception(event)) return `${event.start_date <= today ? '접수 중' : formatFullShortDate(event.start_date)} · 종료일 미공개`
  const end = event.end_date || event.start_date
  if (event.start_date <= today && end >= today) return `접수 중 · 종료 ${formatFullShortDate(end)}`
  if (end === event.start_date) return formatFullShortDate(event.start_date)
  if (event.start_date.slice(0, 4) !== end.slice(0, 4)) {
    return `${formatFullShortDate(event.start_date)} – ${formatFullShortDate(end)}`
  }
  return `${formatFullShortDate(event.start_date)} – ${formatShortDate(end)}`
}

function formatWon(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || !Number.isFinite(amount)) return '가격 미공개'
  if (amount === 0) return '0원'
  const roundedMan = Math.round(amount / 10_000)
  const eok = Math.floor(roundedMan / 10_000)
  const man = roundedMan % 10_000
  if (eok && man) return `${eok}억 ${man.toLocaleString('ko-KR')}만원`
  if (eok) return `${eok}억원`
  if (man) return `${man.toLocaleString('ko-KR')}만원`
  return `${amount.toLocaleString('ko-KR')}원`
}

function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : undefined
  } catch {
    return undefined
  }
}

function isRent(price: NoticePrice): boolean {
  return price.monthly_krw != null || /rent|rental|deposit|임대|보증/i.test(price.price_kind)
}

function verificationLabel(verification: string | null | undefined): string {
  if (verification === 'official') return '공식 자료'
  if (verification === 'ai_unverified' || verification === 'auto_unverified') return '자동 추출 · 미검증'
  return '확인 필요'
}

const SOURCE_NAMES: Record<string, string> = {
  cheongyak_home: '청약홈', myhome: '마이홈', myhome_sale: '마이홈 공공분양', lh: 'LH', ih: 'iH', sh: 'SH', gh: 'GH',
  cheongyak_competition: '청약홈 경쟁률',
  official_conditions: '공고문 조건',
}

function sourceName(source: string, evidenceUrl?: string | null): string {
  const link = safeHref(evidenceUrl)
  if (link) {
    const host = new URL(link).hostname.toLowerCase()
    if (host.includes('applyhome')) return '청약홈'
    if (host.includes('myhome')) return '마이홈'
    if (host.includes('lh.or.kr')) return 'LH'
    if (host.includes('ih.co.kr')) return 'iH'
    if (host.includes('i-sh.co.kr')) return 'SH'
    if (host.includes('gh.or.kr')) return 'GH'
    return host.replace(/^www\./, '')
  }
  return SOURCE_NAMES[source] || source
}

function isApplicationEvent(event: NoticeEvent): boolean {
  return !/^(announcement|contract|result|winner)$/i.test(event.kind) &&
    !/당첨자 발표|계약일|계약 체결/i.test(event.label)
}

function isPublicRental(notice: Notice): boolean {
  return notice.category.toLowerCase() === 'public_rental' || /공공임대/.test(notice.category)
}

export function activeApplicationEvents(notice: Notice, today: string): NoticeEvent[] {
  return (notice.events || []).filter((event) => receptionOverlaps(event, today, today))
}

export function hasVisibleApplication(notice: Notice, start: string, end: string): boolean {
  return (notice.events || []).some((event) => receptionOverlaps(event, start, end))
}

function categoryGroup(category: string): 'private' | 'public' | 'rent' | 'other' {
  const code = category.toLowerCase()
  if (['private_rental', 'public_rental', 'rental', 'rent', 'myhome_rental'].includes(code)) return 'rent'
  if (['public_sale', 'public_housing', 'myhome_sale'].includes(code)) return 'public'
  if (['apt', 'urban', 'unsold', 'optional_supply', 'officetel', 'living_accommodation'].includes(code)) return 'private'
  if (/임대|rent|행복주택|국민주택/i.test(category)) return 'rent'
  if (/공공분양|신혼희망|뉴홈/i.test(category)) return 'public'
  if (/민간|APT|아파트|분양|무순위|취소후/i.test(category)) return 'private'
  return 'other'
}

function categoryDisplay(category: string): string {
  const labels: Record<string, string> = {
    apt: '아파트 분양', urban: '도시형생활주택', unsold: '무순위 청약',
    private_rental: '민간임대', optional_supply: '임의공급', officetel: '오피스텔',
    living_accommodation: '생활숙박시설',
    public_sale: '공공분양', public_rental: '공공임대', myhome_sale: '공공분양',
    myhome_rental: '공공임대',
  }
  return labels[category.toLowerCase()] || category || '유형 미공개'
}

function primaryDate(notice: Notice, start?: string, end?: string): string {
  return nextDeadline(notice, start || kstToday(), end) || '9999-12-31'
}

export 
function dateIsInEvent(event: NoticeEvent, date: string): boolean {
  return receptionOverlaps(event, date, date)
}

function readResidenceOverrides(): Record<string, ResidenceArea> {
  try {
    const value = JSON.parse(localStorage.getItem(RESIDENCE_OVERRIDE_KEY) || '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
    return Object.fromEntries(Object.entries(value).filter(([, area]) =>
      ['local', 'other_gyeonggi', 'other', 'unknown'].includes(String(area)))) as Record<string, ResidenceArea>
  } catch { return {} }
}

function statusTone(status: EligibilityStatus): string {
  return `eligibility-${status}`
}

function App() {
  const [today, setToday] = useState(kstToday)
  const [competitionNow, setCompetitionNow] = useState(Date.now)
  const [profile, setProfile] = useState<LocalProfile>(readProfile)
  const [residenceOverrides, setResidenceOverrides] = useState(readResidenceOverrides)
  const profileDialog = useRef<ProfileDialogHandle>(null)
  const [view, setView] = useState<'schedule' | 'results'>('schedule')
  const [resultsSummary, setResultsSummary] = useState<ResultsSummary>({ notices: 0, rows: 0 })
  const [calendarMonth, setCalendarMonth] = useState(today.slice(0, 7))
  const [windowMode, setWindowMode] = useState<'upcoming' | 'month'>('upcoming')
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [category, setCategory] = useState<'all' | 'private' | 'public' | 'rent'>('all')
  const [capOnly, setCapOnly] = useState(false)
  const [localFirst, setLocalFirst] = useState(true)
  const [notices, setNotices] = useState<Notice[]>([])
  const [calendarNotices, setCalendarNotices] = useState<Notice[]>([])
  const [calendarLoading, setCalendarLoading] = useState(true)
  const [calendarError, setCalendarError] = useState(false)
  const [visibleLimit, setVisibleLimit] = useState(100)
  const [loading, setLoading] = useState(true)
  const [demoMode, setDemoMode] = useState(false)
  const [dataError, setDataError] = useState(false)
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null)
  const [coverageError, setCoverageError] = useState(false)
  const [refreshVersion, setRefreshVersion] = useState(0)
  const [coverageRefreshVersion, setCoverageRefreshVersion] = useState(0)
  const coverageSuccessRef = useRef<string | null>(null)
  const queryKeyRef = useRef('')

  const effectiveMonth = maxDate(calendarMonth, today.slice(0, 7))
  const effectiveSelectedDate = selectedDate && selectedDate >= today ? selectedDate : null
  const start = effectiveSelectedDate || (windowMode === 'upcoming' ? today : maxDate(today, `${effectiveMonth}-01`))
  const end = effectiveSelectedDate || (windowMode === 'upcoming' ? monthEnd(monthShift(today.slice(0, 7), 2)) : monthEnd(effectiveMonth))

  const openProfile = useCallback((field?: keyof LocalProfile) => {
    profileDialog.current?.open(field)
  }, [])

  const refreshAll = useCallback(() => {
    setToday(kstToday())
    setCompetitionNow(Date.now())
    setRefreshVersion((value) => value + 1)
    setCoverageRefreshVersion((value) => value + 1)
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') { setCompetitionNow(Date.now()); setToday(kstToday()) }
    }, 60_000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    let timer: number
    const onMidnight = () => {
      setToday(kstToday())
      setCompetitionNow(Date.now())
      timer = window.setTimeout(onMidnight, msUntilNextKstMidnight())
    }
    const onFocus = () => {
      if (document.visibilityState === 'hidden') return
      // Focus changes only the local date/freshness clock. A date change
      // naturally changes the query range; focus itself never starts a fetch.
      setToday(kstToday())
      setCompetitionNow(Date.now())
    }
    timer = window.setTimeout(onMidnight, msUntilNextKstMidnight())
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
    }
  }, [])

  useEffect(() => {
    if (calendarMonth < today.slice(0, 7)) {
      setCalendarMonth(today.slice(0, 7))
      setWindowMode('upcoming')
    }
    if (selectedDate && selectedDate < today) setSelectedDate(null)
  }, [today, calendarMonth, selectedDate])

  const latestProfile = useRef(profile)
  latestProfile.current = profile
  useEffect(() => {
    const timer = window.setTimeout(() => { const draft = profileDialog.current?.currentDraft(); if (!draft || draft === profile) saveProfile(profile) }, 300)
    return () => window.clearTimeout(timer)
  }, [profile])
  useEffect(() => {
    const flush = () => saveProfile(profileDialog.current?.currentDraft() || latestProfile.current)
    window.addEventListener('pagehide', flush)
    return () => window.removeEventListener('pagehide', flush)
  }, [])

  useEffect(() => {
    try { localStorage.setItem(RESIDENCE_OVERRIDE_KEY, JSON.stringify(residenceOverrides)) } catch { /* browser-only storage */ }
  }, [residenceOverrides])

  const updateResidenceOverride = useCallback((id: string, area: ResidenceArea | 'automatic') => {
    setResidenceOverrides((previous) => {
      const next = { ...previous }
      if (area === 'automatic') delete next[id]
      else next[id] = area
      return next
    })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let timer: number
    const poll = async () => {
      if (document.visibilityState === 'hidden') {
        timer = window.setTimeout(poll, 30_000)
        return
      }
      try {
        const value = await getCoverage(controller.signal)
        if (controller.signal.aborted) return
        const successSignature = value.sources.map((source) =>
          `${source.source}:${source.last_success_at || ''}:${source.record_count ?? ''}${source.source === 'cheongyak_competition' ? `:${source.status}:${source.last_attempt_at || ''}` : ''}`,
        ).sort().join('|')
        const firstCompletedSource = coverageSuccessRef.current === null && value.sources.some((source) => !!source.last_success_at)
        if (firstCompletedSource || (coverageSuccessRef.current !== null && coverageSuccessRef.current !== successSignature)) {
          setRefreshVersion((version) => version + 1)
        }
        coverageSuccessRef.current = successSignature
        setCoverage(value)
        setCoverageError(false)
        timer = window.setTimeout(poll, value.sources.some((source) =>
          source.status === 'pending' || source.status === 'running') ? 30_000 : 300_000)
      } catch {
        if (controller.signal.aborted) return
        setCoverageError(true)
        timer = window.setTimeout(poll, 30_000)
      }
    }
    void poll()
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [coverageRefreshVersion])

  useEffect(() => {
    const controller = new AbortController()
    setCalendarLoading(true)
    setCalendarError(false)
    getCalendarNotices(maxDate(today, `${effectiveMonth}-01`), monthEnd(effectiveMonth), controller.signal)
      .then((items) => { if (!controller.signal.aborted) { setCalendarNotices((previous) => reuseUnchangedNotices(previous, items)); setCalendarError(false) } })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setCalendarError(true)
        console.error('월간 접수 일정 조회 실패', error)
      })
      .finally(() => { if (!controller.signal.aborted) setCalendarLoading(false) })
    return () => controller.abort()
  }, [effectiveMonth, today, refreshVersion])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    const queryKey = `${start}:${end}:${capOnly}`
    if (queryKeyRef.current !== queryKey) setVisibleLimit(100)
    queryKeyRef.current = queryKey
    getCalendarNotices(start, end, controller.signal, capOnly).then((items) => {
      if (controller.signal.aborted) return
      const rows = items.map((notice) => ({ ...notice, events: notice.events || [], prices: notice.prices || [], rules: notice.rules || [] }))
      setNotices((previous) => reuseUnchangedNotices(previous, rows))
      setDemoMode(false)
      setDataError(false)
    }).catch(() => {
      if (controller.signal.aborted) return
      setDataError(true)
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [start, end, capOnly, refreshVersion])

  const catalog = useMemo(() => [...new Map([...calendarNotices, ...notices].map((notice) => [notice.id, notice])).values()], [notices, calendarNotices])
  useEffect(() => { warmProfileQuestionModel(notices, today) }, [notices, today])
  const computation = useEvaluations(catalog, profile, today, residenceOverrides, competitionNow, view === 'schedule')
  const evaluations = computation.evaluations
  const decisions = useMemo(() => new Map(Object.entries(evaluations).map(([id, value]) => [id, value.decision])), [evaluations])
  const shown = useMemo(() => notices.filter((notice) => {
    if (isPublicRental(notice) || !hasVisibleApplication(notice, start, end)) return false
    if (category !== 'all' && categoryGroup(notice.category) !== category) return false
    if (capOnly && notice.price_cap_status !== 'yes') return false
    return !effectiveSelectedDate || notice.events.some((event) => dateIsInEvent(event, effectiveSelectedDate))
  }).map((notice) => ({ notice, date: primaryDate(notice, start, end), candidate: candidateInRange(notice, evaluations[notice.id], start, end) }))
    .sort((a, b) => a.date.localeCompare(b.date) || (localFirst ? Number(b.candidate) - Number(a.candidate) : 0) || a.notice.title.localeCompare(b.notice.title, 'ko'))
    .map((item) => item.notice), [notices, category, capOnly, effectiveSelectedDate, localFirst, start, end, evaluations])
  const rendered = useMemo(() => shown.slice(0, visibleLimit), [shown, visibleLimit])
  const calendarShown = useMemo(() => (demoMode ? notices : calendarNotices).filter((notice) =>
    !isPublicRental(notice) && (category === 'all' || categoryGroup(notice.category) === category) &&
    (!capOnly || notice.price_cap_status === 'yes')), [demoMode, notices, calendarNotices, category, capOnly])

  const grouped = useMemo(() => {
    const groups: { date: string; items: Notice[] }[] = []
    for (const notice of rendered) {
      const date = primaryDate(notice, start, end)
      const last = groups[groups.length - 1]
      if (last?.date === date) last.items.push(notice)
      else groups.push({ date, items: [notice] })
    }
    return groups
  }, [rendered, effectiveSelectedDate, windowMode, today, start, end])

  const highlighted = useMemo(() => shown.filter((notice) => candidateInRange(notice, evaluations[notice.id], start, end)).length, [shown, evaluations, start, end])
  const sourceStates = coverage?.sources || []
  const collecting = sourceStates.some((source) => source.status === 'running')
  const awaitingSources = sourceStates.some((source) => source.status === 'pending')
  const allSourcesUnavailable = sourceStates.length > 0 && sourceStates.every((source) =>
    source.status === 'disabled' || source.status === 'error')
  const hasActiveFilter = category !== 'all' || capOnly || !!effectiveSelectedDate
  const emptyTitle = dataError ? '공고를 불러오지 못했어요'
    : coverageError && !coverage ? '수집 상태를 불러오지 못했어요'
      : collecting ? '공식 공고를 수집 중입니다'
        : awaitingSources || !coverage ? '기관별 수집 결과를 기다리는 중입니다'
          : allSourcesUnavailable ? '공고 출처를 확인해 주세요'
            : hasActiveFilter ? '선택한 조건에 맞는 접수일이 없어요'
              : '이 기간에 예정된 접수일이 없어요'
  const emptyDescription = dataError ? '공고 API 연결을 확인하고 다시 시도해 주세요.'
    : coverageError && !coverage ? '기관별 수집 상태 API 연결을 확인하고 다시 시도해 주세요.'
      : collecting ? '기관별 진행 상황이 갱신되면 공고 목록을 다시 확인합니다.'
        : awaitingSources || !coverage ? '수집 대기는 아직 결과가 없다는 뜻입니다. 기관별 상태를 확인하거나 새로고침해 주세요.'
          : allSourcesUnavailable ? '현재 연결 미설정 또는 수집 실패 상태입니다. 아래 기관별 상태를 확인해 주세요.'
            : hasActiveFilter ? '필터를 해제하거나 다른 날짜를 선택해 주세요.'
              : '공식 접수일이 확인되면 여기에 표시됩니다. 기관별 수집 상태도 확인할 수 있습니다.'

  function showDemo() {
    const sample = demoNotices().filter((notice) =>
      !isPublicRental(notice) && hasVisibleApplication(notice, start, end) &&
      (!capOnly || notice.price_cap_status === 'yes'),
    )
    setNotices(sample)
    setDemoMode(true)
  }

  function changeMonth(offset: number) {
    setCalendarMonth((current) => maxDate(monthShift(current, offset), today.slice(0, 7)))
    setWindowMode('month')
    setSelectedDate(null)
  }

  function resetUpcoming() {
    setView('schedule')
    setCalendarMonth(today.slice(0, 7))
    setWindowMode('upcoming')
    setSelectedDate(null)
  }

  const renderResultCard = useCallback((notice: Notice, resultStart: string, resultEnd: string, decision: CompetitionDecision, evaluation?: NoticeEvaluation) => <NoticeCard key={notice.id} notice={notice} profile={profile} demoMode={false} today={today} viewStart={resultStart} viewEnd={resultEnd} decision={decision} override={residenceOverrides[notice.id]} onOverrideId={updateResidenceOverride} now={competitionNow} onProfile={openProfile} evaluation={evaluation} deferEvaluation resultsMode />, [profile, today, residenceOverrides, updateResidenceOverride, competitionNow, openProfile])

  return (
    <div className="app-shell" data-evaluation-revision={computation.revision} data-evaluation-pending={computation.pending || undefined} data-evaluation-duration={computation.elapsedMs.toFixed(1)}>
      <header className="site-header">
        <div className="header-inner page-width">
          <a className="brand" href="#top" aria-label="청약한눈 첫 화면">
            <span className="brand-symbol"><CalendarDays size={19} strokeWidth={2.5} /></span>
            <span>청약<span className="brand-accent">한눈</span></span>
          </a>
          <nav className="header-nav" aria-label="주 메뉴">
            <a href="#calendar">청약 캘린더</a>
            <a href="#coverage">데이터 출처</a>
          </nav>
          <button className="header-profile" type="button" aria-label="내 조건 설정" onClick={() => openProfile()}>
            <SlidersHorizontal size={16} /><span>내 조건 설정</span><ArrowRight size={15} />
          </button>
        </div>
      </header>

      <main id="top" className="page-width">
        <section className="intro">
          <div className="eyebrow"><span className="eyebrow-dot" /> 전국 청약 일정 · 한국 시간 기준</div>
          <div className="intro-grid">
            <div>
              <h1>내 거주지에서 시작하는<br /><em>청약 캘린더</em></h1>
              <p>접수일과 주택형별 가격, 분양가상한제 여부까지<br className="desktop-break" /> 공고를 열기 전에 먼저 살펴보세요.</p>
            </div>
            <div className="intro-stats" aria-label="현재 목록 요약">
              <div><span>{view === 'results' ? '결과 공고' : '표시 중인 공고'}</span><strong>{view === 'results' ? resultsSummary.notices : shown.length}<small>건</small></strong></div>
              <div><span>{view === 'results' ? '공식 경쟁률' : '거주지 기준 후보'}</span><strong>{view === 'results' ? resultsSummary.rows : profile.region ? highlighted : '—'}<small>{view === 'results' ? '행' : profile.region ? '건' : ''}</small></strong></div>
              <span className="stats-caption">{view === 'results' ? '선택한 접수 기간의 공개 결과' : windowMode === 'upcoming' ? '오늘부터 약 3개월 기준' : `${effectiveMonth.replace('-', '년 ')}월 기준`}</span>
            </div>
          </div>
        </section>

        <section className="location-bar" aria-label="거주지 설정">
          <div className="location-icon"><MapPin size={20} /></div>
          <div className="location-copy"><strong>거주지 기준 접수일 후보를 먼저</strong><span>최종 자격은 공고문으로 확인 · 입력 정보는 브라우저에만 저장</span></div>
          <label className="inline-field"><span>현재 거주지</span>
            <select value={profile.regionCode} onChange={(event) => setProfile(selectProvince(profile, event.target.value))} aria-label="현재 거주 지역">
              <option value="">지역 선택</option>{provinceOptions().map((region) => <option key={region.code} value={region.code}>{region.name}</option>)}
            </select>
          </label>
          <label className="inline-field district-field"><span>시·군·구 (선택)</span>
            <select value={profile.districtCode} disabled={!profile.regionCode} onChange={(event) => setProfile(selectDistrict(profile, event.target.value, { preserveOrdinaryDistrict: profile.districtScopeSpecific }))} aria-label="현재 거주 시군구"><option value="">시·군·구 선택</option>{districtOptions(profile.regionCode, { includeOrdinaryDistricts: profile.districtScopeSpecific }).map((district) => <option key={district.code} value={district.code}>{district.displayName}</option>)}</select>
          </label>
          <label className="inline-field date-field"><span>시도 연속 거주 시작일</span>
            <input type="date" value={profile.movedInDate} max={today} onChange={(event) => setProfile({ ...profile, movedInDate: event.target.value })} aria-label="시도 연속 거주 시작일" />
          </label>
          <button className="bar-more" type="button" onClick={() => openProfile()}>자격 더 알아보기 <ArrowUpRight size={15} /></button>
        </section>

        {profile.regionNeedsReview && <p className="region-migration-note" role="status">기존 지역 ‘{profile.region} {profile.district}’은 행정구역 변경 또는 명칭 불확실성으로 재선택이 필요합니다.</p>}

        <div className="view-tabs" role="tablist" aria-label="공고 보기">
          <button type="button" id="schedule-tab" role="tab" aria-selected={view === 'schedule'} aria-controls="schedule-panel" onClick={() => setView('schedule')}>접수 일정</button>
          <button type="button" id="results-tab" role="tab" aria-selected={view === 'results'} aria-controls="results-panel" onClick={() => setView('results')}>경쟁률·청약결과</button>
        </div>
        <section className="content-grid" id="calendar">
          <aside className="sidebar" aria-label="달력과 필터">
            <div className="side-card calendar-card" hidden={view === 'results'}>
              <div className="side-card-heading"><span><CalendarDays size={17} /> 월간 달력</span><button type="button" onClick={resetUpcoming}>오늘</button></div>
              <MiniCalendar month={effectiveMonth} today={today} selectedDate={effectiveSelectedDate} notices={calendarShown} profile={profile} overrides={residenceOverrides} now={competitionNow} evaluations={evaluations} onMonth={changeMonth} onSelect={(date) => { setWindowMode('month'); setSelectedDate(effectiveSelectedDate === date ? null : date) }} />
              <p className="calendar-hint"><span className="calendar-hint-dot" /> {calendarLoading && !demoMode ? '월간 접수일을 확인하는 중입니다.' : calendarError && !demoMode ? '달력 접수일을 불러오지 못했습니다.' : '점은 접수 일정입니다. 회색 점은 내 조건으로 모든 접수가 불가한 날입니다.'}</p>
            </div>

            <div className="side-card filter-card">
              <div className="side-card-heading"><span><ListFilter size={17} /> 한눈에 필터</span><button type="button" onClick={() => { setCategory('all'); setCapOnly(false); setSelectedDate(null); setLocalFirst(true) }}><RotateCcw size={13} /> 초기화</button></div>
              <div className="filter-label">공급 유형</div>
              <div className="category-list" role="group" aria-label="공급 유형">
                {([['all', '전체 공고'], ['private', '민간분양'], ['public', '공공분양'], ['rent', '민간임대']] as const).map(([value, label]) => (
                  <button key={value} className={category === value ? 'category-option active' : 'category-option'} type="button" aria-pressed={category === value} onClick={() => setCategory(value)}><span>{label}</span>{category === value && <Check size={16} />}</button>
                ))}
              </div>
              <div className="filter-divider" />
              <label className="switch-row"><span className="switch-text"><strong>분양가상한제만</strong><small>적용 공고만 보기</small></span><input type="checkbox" checked={capOnly} onChange={(event) => setCapOnly(event.target.checked)} /><span className="switch" aria-hidden="true" /></label>
              <label className="switch-row" hidden={view === 'results'}><span className="switch-text"><strong>거주지 후보 우선</strong><small>같은 마감일 안에서 먼저 표시</small></span><input type="checkbox" checked={localFirst} onChange={(event) => setLocalFirst(event.target.checked)} /><span className="switch" aria-hidden="true" /></label>
              <p className="competition-filter-note" hidden={view === 'results'}>기타지역 1순위일 때 공식 마감·일반공급 지역 배정 근거를 함께 확인하고, 신청 불가 항목도 회색으로 표시합니다.</p>
            </div>

            <div className="privacy-note"><LockKeyhole size={17} /><span>자격 정보는 서버로 전송되지 않습니다. 판정은 이 브라우저에서만 계산됩니다.</span></div>
          </aside>

          <div className="agenda" hidden={view !== 'schedule'} role="tabpanel" id="schedule-panel" aria-labelledby="schedule-tab">
            <div className="agenda-topline"><div><span className="section-kicker">APPLICATION SCHEDULE</span><h2>{effectiveSelectedDate ? `${formatDate(effectiveSelectedDate)} 접수` : windowMode === 'upcoming' ? '다가오는 청약 일정' : `${effectiveMonth.replace('-', '년 ')}월 청약 일정`}</h2><p>{profile.region ? `${profile.region}${profile.district ? ` ${profile.district}` : ''} 거주지 기준 접수일 후보를 같은 마감일 안에서 먼저 보여드려요.` : '거주지를 설정하면 접수 대상 표기와 지역을 비교해 후보 일정을 먼저 보여드려요.'}</p></div><div className="agenda-tools"><button type="button" className="period-button" onClick={refreshAll}><RotateCcw size={15} /> 새로고침</button><button type="button" className="period-button" onClick={resetUpcoming}><Clock3 size={15} /> 다가오는 일정</button></div></div>

            {demoMode && <div className="demo-banner" role="status"><CircleAlert size={19} /><div><strong>예시 데이터 · 실제 공고가 아닙니다</strong><span>아래 일정과 금액은 화면 사용법을 보여주기 위해 만든 가상 데이터입니다.</span></div><button type="button" onClick={() => { setNotices([]); setDemoMode(false) }}>예시 닫기</button></div>}
            {dataError && !demoMode && <div className="error-banner" role="alert">일부 공고를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.</div>}
            {effectiveSelectedDate && <button className="clear-date" type="button" onClick={() => setSelectedDate(null)}><X size={14} /> 날짜 선택 해제</button>}

            {computation.pending && <p className="background-refresh" role="status" data-evaluation-pending="true">내 조건 반영 중 · 현재 목록과 가격은 유지됩니다.</p>}
            {computation.error && <p className="error-banner" role="alert">{computation.error}</p>}
            {loading && notices.length > 0 && <p className="background-refresh" role="status">새 공고를 확인하고 있습니다. 현재 목록은 유지됩니다.</p>}
            {loading && !notices.length ? <div className="loading-state"><span className="loading-spinner" /><strong>공식 공고를 불러오는 중입니다</strong><span>일정과 주택형 가격을 정리하고 있어요.</span></div> : shown.length ? (
              <div className="agenda-groups">
                {grouped.map((group) => <section className="day-group" key={group.date} aria-label={group.date === '9999-12-31' ? '마감일 미공개' : `${formatDate(group.date)} 접수 마감`}><div className="day-heading"><div className="day-marker"><span>{group.date === '9999-12-31' ? '—' : formatShortDate(group.date)}</span></div><h3>{group.date === '9999-12-31' ? '접수 마감일 미공개' : `${formatDate(group.date, group.date.slice(0, 4) !== today.slice(0, 4))} 접수 마감`}</h3><span className="day-count">{group.items.length}건</span></div><div className="notice-stack">{group.items.map((notice) => <NoticeCard key={notice.id} notice={notice} profile={profile} demoMode={demoMode} today={today} viewStart={start} viewEnd={end} decision={decisions.get(notice.id)!} override={residenceOverrides[notice.id]} now={competitionNow} onProfile={openProfile} evaluation={evaluations[notice.id]} deferEvaluation onOverrideId={updateResidenceOverride} />)}</div></section>)}
                {shown.length > rendered.length && <button type="button" className="load-more" onClick={() => setVisibleLimit((value) => value + 100)}>공고 더 보기 · {shown.length - rendered.length}건 남음 <ChevronDown size={16} /></button>}
              </div>
            ) : <div className="empty-state"><div className="empty-icon"><CalendarDays size={27} /></div><h3>{emptyTitle}</h3><p>{emptyDescription}</p><div className="empty-actions">{(hasActiveFilter || windowMode === 'month') && <button type="button" onClick={() => { resetUpcoming(); setCategory('all'); setCapOnly(false) }}>다가오는 전체 일정 보기 <ArrowRight size={16} /></button>}{(dataError || coverageError || collecting || awaitingSources) && <button type="button" onClick={refreshAll}>수집 상태 새로고침 <RotateCcw size={16} /></button>}{!notices.length && !collecting && !awaitingSources && <button type="button" className="demo-button" onClick={showDemo}>예시 화면 보기 <ArrowUpRight size={16} /></button>}</div></div>}
          </div>
          <ResultsPane active={view === 'results'} today={today} refreshVersion={refreshVersion} capOnly={capOnly} category={category} categoryGroup={categoryGroup} profile={profile} residenceOverrides={residenceOverrides} now={competitionNow} onSummary={setResultsSummary} onRefresh={refreshAll} renderCard={renderResultCard} />
        </section>

        <section className="coverage-section" id="coverage"><div className="coverage-heading"><div><span className="section-kicker">DATA TRANSPARENCY</span><h2>어디에서 가져온 공고인가요?</h2><p>기관별 마지막 수집 상태를 공개합니다. 일정과 가격은 반드시 공식 공고문에서 다시 확인하세요.</p></div><Database size={26} /></div><CoveragePanel coverage={coverage} error={coverageError} /></section>
      </main>

      <footer className="site-footer"><div className="page-width footer-inner"><div className="footer-brand"><span className="brand-symbol"><CalendarDays size={15} /></span><strong>청약한눈</strong></div><p>정보 안내용 서비스입니다. 청약 자격·금액·일정의 최종 기준은 각 기관의 공식 모집공고입니다.</p><span>대한민국 표준시 KST</span></div></footer>
      <ProfileDialogController ref={profileDialog} profile={profile} onChange={setProfile} today={today} notices={notices} />
    </div>
  )
}

export function applicationDatesInMonth(notices: Notice[], month: string, today?: string): Set<string> {
  const eventDays = new Set<string>()
  const first = today ? maxDate(`${month}-01`, today) : `${month}-01`
  const last = monthEnd(month)
  for (const notice of notices) for (const event of notice.events || []) {
    if (isPublicRental(notice)) continue
    if (!isApplicationEvent(event)) continue
    let date = event.start_date < first ? first : event.start_date
    const eventEnd = receptionEndDate(event) || last
    const end = eventEnd > last ? last : eventEnd
    while (date <= end) {
      eventDays.add(date)
      date = addDays(date, 1)
    }
  }
  return eventDays
}

/** Every official event contributes to the calendar, including unavailable ones. */
export function applicationAvailabilityInMonth(notices: Notice[], month: string, today: string, profile: LocalProfile, overrides: Record<string, ResidenceArea> = {}, now = Date.now()): Map<string, { unavailable: boolean; events: number }> {
  const states = new Map<string, { unavailable: boolean; events: number }>()
  const first = maxDate(`${month}-01`, today), last = monthEnd(month)
  for (const notice of notices) {
    if (isPublicRental(notice)) continue
    const decision = competitionDecision(notice, profile, today, overrides[notice.id], now)
    for (const event of notice.events || []) {
      if (!isApplicationEvent(event)) continue
      const unavailable = applicationEventAvailability(event, notice, profile, decision).unavailable
      let date = maxDate(event.start_date, first)
      const deadline = receptionEndDate(event) || last
      const end = deadline < last ? deadline : last
      while (date <= end) {
        const previous = states.get(date)
        states.set(date, { unavailable: unavailable && (previous?.unavailable ?? true), events: (previous?.events || 0) + 1 })
        date = addDays(date, 1)
      }
    }
  }
  return states
}

export function MiniCalendar({ month, today, selectedDate, notices, profile = EMPTY_PROFILE, overrides = {}, now = Date.now(), evaluations, onMonth, onSelect }: { month: string; today: string; selectedDate: string | null; notices: Notice[]; profile?: LocalProfile; overrides?: Record<string, ResidenceArea>; now?: number; evaluations?: Record<string, NoticeEvaluation>; onMonth: (offset: number) => void; onSelect: (date: string) => void }) {
  const [year, mm] = month.split('-').map(Number)
  const firstWeekday = new Date(Date.UTC(year, mm - 1, 1)).getUTCDay()
  const days = Number(monthEnd(month).slice(-2))
  const cells = Array.from({ length: Math.ceil((firstWeekday + days) / 7) * 7 }, (_, index) => index - firstWeekday + 1)
  const availability = useMemo(() => {
    if (!evaluations) return applicationAvailabilityInMonth(notices, month, today, profile, overrides, now)
    const states = new Map<string, { unavailable: boolean; events: number }>()
    for (const notice of notices) for (const [i, event] of notice.events.entries()) {
      if (!isApplicationEvent(event)) continue
      const unavailable = evaluations[notice.id]?.events[i]?.unavailable || false
      let date = maxDate(event.start_date, maxDate(`${month}-01`, today))
      const deadline = receptionEndDate(event) || monthEnd(month)
      const end = deadline < monthEnd(month) ? deadline : monthEnd(month)
      while (date <= end) { const previous = states.get(date); states.set(date, { unavailable: unavailable && (previous?.unavailable ?? true), events: (previous?.events || 0) + 1 }); date = addDays(date, 1) }
    }
    return states
  }, [evaluations, notices, month, today, profile, overrides, now])
  const eventDays = new Set(availability.keys())
  return <div className="mini-calendar"><div className="calendar-month"><strong>{year}년 {mm}월</strong><div><button type="button" aria-label="이전 달" disabled={month <= today.slice(0, 7)} onClick={() => onMonth(-1)}><ChevronLeft size={17} /></button><button type="button" aria-label="다음 달" onClick={() => onMonth(1)}><ChevronRight size={17} /></button></div></div><div className="calendar-grid">{WEEKDAYS.map((day) => <span className="weekday" key={day}>{day}</span>)}{cells.map((day, index) => day < 1 || day > days ? <span className="calendar-empty" key={`blank-${index}`} /> : (() => { const date = `${month}-${String(day).padStart(2, '0')}`; if (date < today) return <span key={date} className="calendar-empty past" aria-hidden="true" />; return <button key={date} className={`calendar-day${date === today ? ' today' : ''}${selectedDate === date ? ' selected' : ''}${availability.get(date)?.unavailable ? ' unavailable-dot' : ''}`} type="button" aria-pressed={selectedDate === date} aria-label={`${formatDate(date)}, ${eventDays.has(date) ? availability.get(date)?.unavailable ? '접수 일정 있음 · 내 조건으로 모든 접수 신청 불가' : '접수 일정 있음' : '접수 일정 없음'}`} onClick={() => onSelect(date)}><span>{day}</span>{eventDays.has(date) && <i aria-hidden="true" />}</button> })())}</div></div>
}

export const NoticeCard = memo(function NoticeCard({ notice, profile, demoMode, today, viewStart, viewEnd, decision, override, onOverride, onOverrideId, now, onProfile, evaluation: prepared, deferEvaluation = false, resultsMode = false }: { notice: Notice; profile: LocalProfile; demoMode: boolean; today: string; viewStart: string; viewEnd: string; decision: CompetitionDecision; override?: ResidenceArea; onOverride?: (area: ResidenceArea | 'automatic') => void; onOverrideId?: (id: string, area: ResidenceArea | 'automatic') => void; now: number; onProfile: (field?: keyof LocalProfile) => void; evaluation?: NoticeEvaluation; deferEvaluation?: boolean; resultsMode?: boolean }) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const evaluation = useMemo(() => prepared || (deferEvaluation ? undefined : evaluateNotice(notice, profile, today, now, override, resultsMode ? 'results' : 'schedule', decision)), [prepared, deferEvaluation, notice, profile, today, now, override, resultsMode, decision])
  const effectiveDecision = evaluation?.decision || decision || { area: 'unknown', closedUnits: [], reason: null } as CompetitionDecision
  decision = effectiveDecision
  const isLocal = !resultsMode && candidateInRange(notice, evaluation, viewStart, viewEnd)
  const mainResult = evaluation?.summary || { status: 'review' as const, reasons: [] }
  const changeOverride = useCallback((area: ResidenceArea | 'automatic') => { if (onOverrideId) onOverrideId(notice.id, area); else onOverride?.(area) }, [notice.id, onOverrideId, onOverride])
  const unavailable = mainResult.status === 'mismatch' || decision.allApplicationsUnavailable === true
  const officialLink = demoMode ? undefined : safeHref(notice.official_url)
  const categoryLabel = categoryDisplay(notice.category)
  const methodLabel = officialApplicationMethodLabel(notice)
  const visibleEvents = (notice.events || []).filter((event) =>
    receptionOverlaps(event, resultsMode ? viewStart : maxDate(viewStart, today), viewEnd))

  const sources = [...new Set(notice.sources?.length ? notice.sources : [notice.source])].map((source) => sourceName(source)).join(' · ')
  const unitCount = new Set(notice.prices.map((price) => price.unit_type)).size

  return <article className={`notice-card${isLocal ? ' local-notice' : ''}${resultsMode ? ' result-card' : ''}${unavailable ? ' notice-unavailable' : ''}`} data-unavailable={unavailable || undefined} data-evaluation-ready={!!evaluation || undefined}>
    <div className="notice-head"><div className="notice-tags">{!resultsMode && activeApplicationEvents(notice, today).length > 0 && <span className="ongoing-badge">현재 접수 중</span>}{unavailable && <span className="unavailable-badge">내 조건으로 신청 불가</span>}{methodLabel && <span className="application-method-tag">{methodLabel}</span>}<span className={`type-tag type-${categoryGroup(notice.category)}`}>{categoryLabel}</span>{notice.housing_kind !== 'not_applicable' && <span className="unknown-tag">{notice.housing_kind === 'private' ? '민영주택' : notice.housing_kind === 'national' ? '국민주택' : '주택 종류 확인 중'}</span>}{notice.rank_applicability?.status === 'not_applicable' && <span className="unknown-tag">아파트 1·2순위 적용 없음</span>}{notice.rank_applicability?.account_required === false && <span className="local-tag">청약통장 불필요</span>}{isLocal && <span className="local-tag"><MapPin size={12} /> {evaluation?.candidateLabel}</span>}{notice.price_cap_status === 'yes' && <span className="cap-tag"><Sparkles size={13} /> 분양가상한제 적용</span>}{notice.price_cap_status === 'unknown' && <span className="unknown-tag">상한제 확인 필요</span>}{resultsMode && <span className="result-status-tag">{(notice.application_end_date || '') >= today ? '접수 중 결과' : '접수 종료'}</span>}</div><div className="notice-provider"><span>{notice.provider ? `${notice.provider} · ` : ''}출처 {sources}</span>{(notice.correction_of_id || notice.correction_of_external_id) && <span className="revision-tag">정정 공고</span>}{notice.version > 1 && <span className="revision-tag">자료 갱신 {notice.version}판</span>}</div></div>
    <div className="notice-title-line"><div><h4>{notice.title}</h4><div className="notice-address"><MapPin size={14} />{notice.address || notice.region_name || '지역 미공개'}<span className="address-separator" />모집공고 {formatShortDate(notice.announcement_date)}</div></div>{officialLink && <a className="official-link" href={officialLink} target="_blank" rel="noopener noreferrer" aria-label={`${notice.title} 공식 공고 보기`}>원문 <ArrowUpRight size={16} /></a>}</div>

    {evaluation && <NoticeRegionDecision notice={notice} profile={profile} onProfile={onProfile} groups={evaluation.regions} />}

    {unavailable && !decision.reason && mainResult.reasons.length > 0 && <p className="notice-unavailable-explanation">{mainResult.reasons[0].detail}</p>}
    {decision.reason && <div className="competition-exclusion-reason"><CircleAlert size={15} /><span>{decision.reason} 공식 결과와 공고별 배정 근거를 아래에서 확인할 수 있습니다.</span></div>}

    <div className="schedule-row"><div className="row-heading"><CalendarDays size={15} /><strong>접수 일정</strong></div><div className="event-list">{visibleEvents.length ? visibleEvents.map((event, index) => {
      const availability = evaluation?.events[notice.events.indexOf(event)] || { unavailable: false, reason: null }
      const candidate = !resultsMode && !availability.unavailable && evaluation?.candidateEvents[notice.events.indexOf(event)]
      return <div className={`event-pill${candidate ? ' event-candidate' : ''}${availability.unavailable ? ' event-unavailable' : ''}`} data-unavailable={availability.unavailable || undefined} title={availability.reason || undefined} key={`${event.kind}-${event.start_date}-${index}`}><span className="event-dot" /><strong>{event.label || event.kind}</strong><span>{formatEventRange(event, today)}</span>{event.audience && <small>{event.audience}</small>}{candidate && <small className="candidate-note">접수일 후보 · 원문 확인</small>}{availability.unavailable && <span className="event-unavailable-note"><strong>내 조건으로 신청 불가</strong><span>{availability.reason}</span></span>}</div>
    }) : <span className="missing-text">이 기간의 접수 일정 미공개</span>}</div></div>
    {!resultsMode && evaluation?.contractNote && <p className="contract-comparison-note">{evaluation.contractNote}{safeHref(notice.contract_schedule?.evidence_url) && <a href={safeHref(notice.contract_schedule?.evidence_url)} target="_blank" rel="noopener noreferrer">계약 일정 원문 <ExternalLink size={12} /></a>}</p>}


    <div className="prices-section"><div className="prices-heading"><div><Wallet size={16} /><strong>주택형별 가격</strong><span className="price-count">{unitCount}개 주택형</span></div>{notice.price_cap_status === 'no' && <span className="cap-no">분양가상한제 미적용</span>}{notice.price_cap_status === 'not_applicable' && <span className="cap-na">분양가상한제 해당 없음</span>}</div>
      {notice.prices.length ? <div className="price-table" role="table" aria-label={`${notice.title} 주택형별 가격`}><div className="price-table-header" role="row"><span role="columnheader">주택형</span><span role="columnheader">금액</span><span role="columnheader">기준 · 출처</span></div>{notice.prices.map((price, index) => <PriceRow key={`${price.unit_type}-${price.price_kind}-${index}`} price={price} source={notice.source} officialUrl={notice.official_url} demoMode={demoMode} unavailable={evaluation?.priceUnavailable[index] || false} closed={decision.closedUnits.some((unit) => competitionUnitKey(unit) === competitionUnitKey(price.unit_type)) || resultsMode && (notice.competitions || []).some((row) => row.verification === 'official' && row.result_status === 'local_first_closed' && competitionUnitKey(row.unit_type) === competitionUnitKey(price.unit_type))} closedLabel={decision.closedUnits.length ? '기타지역 배정 기회 종료' : '해당지역 1순위 마감'} applicationFeeKrw={applicationFee(notice, price.unit_type)} />)}</div> : <div className="price-empty"><CircleAlert size={16} /> 주택형별 가격 미공개 · 공식 공고문을 확인해 주세요.</div>}
    </div>

    <CompetitionSection notice={notice} profile={profile} decision={decision} override={override} onOverride={changeOverride} now={now} demoMode={demoMode} resultsMode={resultsMode} evaluation={evaluation} />

    {evaluation?.opportunity && <OpportunityPanel value={evaluation.opportunity} onProfile={onProfile} />}
    {!resultsMode && <><div className="notice-foot"><div className="eligibility-summary"><ShieldCheck size={17} /><span>자격 진단</span><span className={`eligibility-badge ${statusTone(mainResult.status)}`}>{unavailable ? '내 조건으로 신청 불가' : mainResult.status === 'unpublished' ? '조건 비교 자료 확인' : ELIGIBILITY_LABEL[mainResult.status]}</span></div><div className="notice-actions"><button type="button" onClick={() => onProfile()}>내 조건 입력</button><button className="details-button" type="button" aria-expanded={detailsOpen} onClick={() => setDetailsOpen(!detailsOpen)}>{detailsOpen ? '근거 접기' : '유형별 근거'} {detailsOpen ? <ChevronDown className="chevron-up" size={15} /> : <ChevronDown size={15} />}</button></div></div>
    {evaluation && <EligibilityBrief snapshot={evaluation} result={mainResult} notice={notice} profile={profile} decision={decision} onProfile={onProfile} onDetails={() => setDetailsOpen(true)} candidateReason={isLocal ? evaluation?.candidateReason : undefined} />}
    {detailsOpen && evaluation && <EligibilityDetails snapshot={evaluation} notice={notice} profile={profile} decision={decision} demoMode={demoMode} onProfile={onProfile}><div className="official-schedule"><strong>원문 일정 · 지난 일정 포함</strong>{notice.events.length ? <ul>{notice.events.map((event, index) => <li key={`${event.kind}-${event.start_date}-${index}`}><span>{event.label || event.kind}</span><time>{formatFullShortDate(event.start_date)}{event.end_date && event.end_date !== event.start_date ? ` – ${formatFullShortDate(event.end_date)}` : ''}</time>{event.audience && <small>{event.audience}</small>}</li>)}</ul> : <p>원문 일정 미공개</p>}{officialLink && <a href={officialLink} target="_blank" rel="noopener noreferrer">공식 공고문 <ExternalLink size={12} /></a>}</div></EligibilityDetails>}
    </>}
  </article>
}, (a, b) => a.notice === b.notice && a.evaluation === b.evaluation && a.decision === b.decision && a.override === b.override && a.demoMode === b.demoMode && a.today === b.today && a.viewStart === b.viewStart && a.viewEnd === b.viewEnd && a.resultsMode === b.resultsMode && a.onProfile === b.onProfile && a.onOverride === b.onOverride && a.onOverrideId === b.onOverrideId && a.deferEvaluation === b.deferEvaluation && (a.deferEvaluation || a.profile === b.profile && a.now === b.now))

function applicationFee(notice: Notice, unit: string): number | undefined {
  for (const rule of notice.rules) {
    if (rule.kind !== 'supply_financial_terms' || rule.verification !== 'official' || !Array.isArray(rule.units)) continue
    const item = rule.units.find((value) => value && typeof value === 'object' && competitionUnitKey(String(value.unit_type || '')) === competitionUnitKey(unit))
    if (item && typeof item.application_fee_krw === 'number' && Number.isSafeInteger(item.application_fee_krw) && item.application_fee_krw >= 0) return item.application_fee_krw
  }
  return undefined
}

export function officialApplicationMethodLabel(notice: Notice): string | null {
  const metadata = (notice.rules || []).find((rule) => rule.kind === 'application_method' && rule.effect === 'metadata' && rule.verification === 'official')
  const method = notice.application_method || metadata?.value
  const official = notice.application_method_evidence?.verification === 'official' || metadata?.verification === 'official'
  if (!official || typeof method !== 'string') return null
  return ({ unranked_after: '무순위 사후접수', optional_supply: '임의공급', cancelled_resupply: '계약취소 후 재공급', first_come: '선착순 공급' } as Record<string, string>)[method] || null
}

function PriceRow({ price, source, officialUrl, demoMode, unavailable = false, closed = false, closedLabel = '기타지역 1순위 마감', applicationFeeKrw }: { price: NoticePrice; source: string; officialUrl: string | null; demoMode: boolean; unavailable?: boolean; closed?: boolean; closedLabel?: string; applicationFeeKrw?: number }) {
  const rental = isRent(price)
  const amount = price.amount_krw
  const basis = price.basis_label || (!rental && price.price_kind === 'sale_max' ? '주택형별 최고 분양금액' : rental ? '임대보증금' : '가격 기준 미공개')
  const link = demoMode ? undefined : safeHref(price.evidence_url || officialUrl)
  const origin = demoMode ? '화면 예시' : price.source ? sourceName(price.source) : sourceName(source, price.evidence_url)
  return <div className="price-row" role="row"><div className={`unit-name${unavailable ? ' unit-unavailable' : ''}`} role="cell"><strong>{price.unit_type || '주택형 미공개'}</strong>{price.exclusive_area_sqm != null && <small>전용 {price.exclusive_area_sqm.toLocaleString('ko-KR')}㎡</small>}{price.area_sqm != null && price.area_sqm !== price.exclusive_area_sqm && <small>{price.area_basis === 'supply' ? '공급 ' : price.area_basis === 'exclusive' ? '전용 ' : '면적 '}{price.area_sqm.toLocaleString('ko-KR')}㎡</small>}{unavailable && <span className="unavailable-badge">내 조건으로 신청 불가</span>}{closed && <span className="competition-closed-badge">{closedLabel}</span>}</div><div className="price-main" role="cell">{rental ? <><strong>{amount == null ? '보증금 미공개' : `보증금 ${formatWon(amount)}`}</strong><span>{price.monthly_krw == null ? '월 임대료 미공개' : `월 ${formatWon(price.monthly_krw)}`}</span></> : <strong className={amount == null ? 'missing-price' : ''}>{formatWon(amount)}</strong>}{applicationFeeKrw != null && <span>청약신청금 {formatWon(applicationFeeKrw)}</span>}</div><div className="price-evidence" role="cell"><span>{basis}</span><span className="price-origin">출처 {origin}</span><span className={`verification ${price.verification === 'official' ? 'verified' : price.verification === 'ai_unverified' || price.verification === 'auto_unverified' ? 'unverified' : 'unknown'}`}>{verificationLabel(price.verification)}</span>{link && <a href={link} target="_blank" rel="noopener noreferrer" aria-label={`${price.unit_type} 가격 원문 근거`}>원문 <ExternalLink size={12} /></a>}{price.evidence_text && <small className="evidence-text">원문 근거: {price.evidence_text}</small>}</div></div>
}

function CompetitionSection({ notice, decision, override, onOverride, now, demoMode, evaluation, resultsMode = false }: { notice: Notice; profile: LocalProfile; decision: CompetitionDecision; override?: ResidenceArea; onOverride: (area: ResidenceArea | 'automatic') => void; now: number; demoMode: boolean; evaluation?: NoticeEvaluation; resultsMode?: boolean }) {
  const rows = resultsMode ? resultCompetitionRows(notice) : notice.competitions || []
  const state = notice.competition
  const fresh = evaluation?.fresh ?? competitionFresh(notice, now)
  const latestObserved = rows.map((row) => row.observed_at || '').filter(Boolean).sort().at(-1)
  const lastObserved = state?.last_success_at || latestObserved
  const successDate = lastObserved ? new Date(lastObserved) : null
  const observed = successDate && !Number.isNaN(successDate.getTime()) ? KST_DISPLAY_TIME.format(successDate) : null
  return <section className="competitions-section" aria-label={`${notice.title} 경쟁률`}>
    <div className="competition-heading"><strong>주택형별 경쟁률</strong><span>{observed ? `조회 ${observed} KST` : '조회 기록 없음'}</span></div>
    {notice.rank_applicability?.status !== 'not_applicable' && <><div className="competition-personal"><span>{resultsMode ? '내 청약 지역' : `내 조건: ${evaluation?.rank.label || '조건 반영 중'}`} · {RESIDENCE_AREA_LABEL[decision.area]}</span><label><span>이 공고의 청약 지역</span><select value={override || 'automatic'} aria-label={`${notice.title} 청약 지역`} onChange={(event) => onOverride(event.target.value as ResidenceArea | 'automatic')}><option value="automatic">공식 조건으로 확인</option><option value="local">해당지역</option><option value="other_gyeonggi">기타경기</option><option value="other">기타지역</option><option value="unknown">지역 확인 필요</option></select></label></div>
    <p className="competition-condition-note">공식 신청지역·거주기간으로 자동 판단합니다. 직접 선택은 공고의 배정 조건을 확인했을 때 사용하세요. 선택 정보는 이 브라우저에만 저장됩니다.</p></>}
    {!!decision.closureProofs?.length && <details className="competition-proof-details"><summary>기타지역 배정 기회 종료 근거 {decision.closureProofs.length}개 주택형</summary>{decision.closureProofs.map((proof) => <div key={proof.unitType}><strong>{proof.unitType}</strong><p>{proof.reason}</p>{safeHref(proof.competitionEvidenceUrl) && <a href={safeHref(proof.competitionEvidenceUrl)} target="_blank" rel="noopener noreferrer">공식 경쟁률 결과</a>}{proof.allocationEvidenceUrl && safeHref(proof.allocationEvidenceUrl) && <a href={safeHref(proof.allocationEvidenceUrl)} target="_blank" rel="noopener noreferrer">지역 배정 공고문</a>}{proof.competitionEvidenceText && <blockquote>{proof.competitionEvidenceText}</blockquote>}{proof.allocationEvidenceText && <blockquote>{proof.allocationEvidenceText}</blockquote>}</div>)}</details>}
    {rows.length ? <div className="competition-table" role="table" aria-label={`${notice.title} 주택형별 경쟁률`}><div className="competition-table-header" role="row"><span role="columnheader">주택형 · 순위 · 지역</span><span role="columnheader">모집 · 접수</span><span role="columnheader">경쟁률 · 결과</span></div>{rows.map((row, index) => {
      const link = demoMode ? undefined : safeHref(row.evidence_url)
      const availability = evaluation?.competitionRows[(notice.competitions || []).indexOf(row)] || { unavailable: false, reason: null }
      return <div className={`competition-row${availability.unavailable ? ' competition-row-unavailable' : ''}`} data-unavailable={availability.unavailable || undefined} role="row" key={`${row.unit_type}-${row.rank}-${row.residence_area}-${index}`}><div role="cell"><strong>{row.unit_type || '주택형 미공개'}</strong><span>{row.rank ? `${row.rank}순위` : '순위 미공개'} · {row.residence_area_label || RESIDENCE_AREA_LABEL[row.residence_area] || '지역 미공개'}</span>{row.supply_type_label && <small>{row.supply_type_label}</small>}{availability.unavailable && <span className="unavailable-badge">내 조건으로 신청 불가</span>}</div><div className="competition-counts" role="cell"><span>모집 {row.supply_count == null ? '미공개' : `${row.supply_count.toLocaleString('ko-KR')}세대`}</span><span>접수 {row.application_count == null ? '미공개' : `${row.application_count.toLocaleString('ko-KR')}건`}</span></div><div role="cell"><strong>{competitionRateLabel(row.competition_rate)}</strong>{row.competition_rate && row.competition_rate !== '-' && <small>원문 {row.competition_rate}</small>}<span className={row.result_status === 'local_first_closed' || decision.closedUnits.some((unit) => competitionUnitKey(unit) === competitionUnitKey(row.unit_type)) ? 'competition-closed-badge' : ''}>{decision.closedUnits.some((unit) => competitionUnitKey(unit) === competitionUnitKey(row.unit_type)) ? '기타지역 배정 기회 종료' : competitionRowLabel(row)}</span><small>{verificationLabel(row.verification)} · {sourceName(row.source)}</small>{row.observed_at && <small>조회 {new Date(row.observed_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })}</small>}{link && <a href={link} target="_blank" rel="noopener noreferrer">경쟁률 원문 <ExternalLink size={12} /></a>}{row.result_text && <small>원문 결과: {row.result_text}</small>}{availability.unavailable && <p className="competition-unavailable-reason">{availability.reason}</p>}</div></div>
    })}</div> : <div className="competition-empty">{state?.status === 'error' ? '경쟁률 수집 실패 · 원문에서 확인해 주세요.' : state?.status === 'not_applicable' ? '경쟁률 제공 대상이 아닙니다.' : '경쟁률 미공개 · 공식 결과를 기다리는 중입니다.'}</div>}
    {!!rows.length && resultsMode && !fresh && <p className="competition-stale-note">{state?.status === 'error' ? '최근 재조회 실패 · ' : state?.status === 'running' ? '결과 재확인 중 · ' : ''}마지막으로 수집한 공식 결과입니다. 이후 정정 여부는 원문에서 확인할 수 있습니다.</p>}
    {!!rows.length && !resultsMode && !fresh && <p className="competition-stale-note">{state?.status === 'error' ? '최근 조회 실패' : state?.status === 'running' ? '경쟁률 갱신 중' : '최신 결과 확인 필요'} · 이전 결과는 참고용이며 현재 접수 불가 판단에 사용하지 않습니다.</p>}
    {!!rows.length && !resultsMode && fresh && !state?.complete && <p className="competition-stale-note">일부 주택형·결과 확인 필요 · 전체 접수 불가로 판단하지 않습니다.</p>}
    {state?.message && <p className="competition-collection-message">{state.message}</p>}
  </section>
}

const CoveragePanel = memo(function CoveragePanel({ coverage, error }: { coverage: CoverageResponse | null; error: boolean }) {
  const sources = coverage?.sources || []
  if (error) return <div className="coverage-empty"><CircleAlert size={18} /> 수집 상태 API에 연결할 수 없습니다. 공고별 원문 링크를 확인해 주세요.</div>
  if (!coverage) return <div className="coverage-empty">수집 상태를 불러오는 중입니다…</div>
  if (!sources.length) return <div className="coverage-empty"><Info size={18} /> 아직 기록된 수집 상태가 없습니다. 공고별 원문 링크를 확인해 주세요.</div>
  const displayTime = (value?: string | null) => {
    const date = value ? new Date(value) : null
    return date && !Number.isNaN(date.getTime())
      ? KST_DISPLAY_TIME.format(date)
      : '기록 없음'
  }
  return <div className="coverage-list">{sources.map((item, index) => {
    const lastSuccess = item.last_success_at ? new Date(item.last_success_at) : null
    const stale = item.status === 'ok' && !!lastSuccess && !Number.isNaN(lastSuccess.getTime()) && Date.now() - lastSuccess.getTime() > 6 * 60 * 60 * 1000
    const ok = item.status === 'ok' && !stale
    const status = item.status === 'running' ? '수집 중' : item.status === 'partial' ? '일부 누락' : item.status === 'error' ? '수집 실패' : item.status === 'disabled' ? '연결 미설정' : item.status === 'pending' ? '수집 대기' : stale ? '갱신 지연' : ok ? '정상' : '확인 필요'
    return <div className="coverage-item" key={`${item.source}-${index}`}><div className={`source-icon ${ok ? 'source-ok' : 'source-warn'}`}>{ok ? <CheckCircle2 size={19} /> : item.status === 'running' ? <Clock3 size={19} /> : <CircleAlert size={19} />}</div><div className="coverage-copy"><strong>{sourceName(item.source)}</strong><span>{item.message || status}</span><small>마지막 시도 {displayTime(item.last_attempt_at)} · 성공 {displayTime(item.last_success_at)}{item.record_count != null ? ` · ${item.record_count}건` : ''}</small></div><div className="coverage-meta"><span className={ok ? 'coverage-ok' : 'coverage-warn'}>{status}</span></div></div>
  })}</div>
})

export default App
