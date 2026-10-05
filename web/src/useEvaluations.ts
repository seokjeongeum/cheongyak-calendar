import { startTransition, useEffect, useMemo, useRef, useState } from 'react'
import type { LocalProfile, Notice, ResidenceArea } from './types'
import { competitionFresh } from './competition'
import type { EvaluationRequest, EvaluationResponse } from './evaluation'

/** Coalesce drafts; obsolete results can never replace a newer profile. */
export function useEvaluations(notices: Notice[], profile: LocalProfile, today: string, overrides: Record<string, ResidenceArea>, now: number, active = true, mode: 'schedule' | 'results' = 'schedule') {
  const [result, setResult] = useState<EvaluationResponse>({ revision: 0, evaluations: {}, elapsedMs: 0 })
  const [pending, setPending] = useState(false)
  const worker = useRef<Worker | null>(null)
  const busy = useRef(false), latest = useRef<EvaluationRequest | null>(null), revision = useRef(0)
  const sentCatalog = useRef<Notice[] | null>(null), catalog = useRef(notices)
  catalog.current = notices
  const freshness = useMemo(() => notices.map((notice) => `${notice.id}:${competitionFresh(notice, now)}:${(notice.competitions || []).some((row) => row.observed_at && Date.parse(row.observed_at) > now + 60_000)}`).join('|'), [notices, now])
  const dispatch = useRef<() => void>(() => {})
  dispatch.current = () => {
    if (!worker.current || busy.current || !latest.current) return
    const request = latest.current
    latest.current = null
    const changedCatalog = sentCatalog.current !== catalog.current
    const next = { ...request, ...(changedCatalog ? { catalog: catalog.current } : {}) }
    sentCatalog.current = catalog.current
    busy.current = true
    worker.current.postMessage(next)
  }
  useEffect(() => {
    if (typeof Worker === 'undefined') return
    const instance = new Worker(new URL('./qualification.worker.ts', import.meta.url), { type: 'module' })
    worker.current = instance
    instance.onmessage = ({ data }: MessageEvent<EvaluationResponse>) => {
      busy.current = false
      if (data.revision === revision.current) {
        startTransition(() => { setResult((old) => data.revision === revision.current ? data : old); setPending((old) => data.revision === revision.current ? false : old) })
      }
      dispatch.current()
    }
    instance.onerror = () => {
      busy.current = false
      startTransition(() => { setResult((old) => ({ ...old, error: '조건 계산을 완료하지 못했습니다. 페이지를 다시 열어 확인해 주세요.' })); setPending(false) })
    }
    dispatch.current()
    return () => { instance.terminate(); worker.current = null; busy.current = false; sentCatalog.current = null }
  }, [])
  useEffect(() => {
    if (!active) { revision.current++; latest.current = null; return }
    revision.current++
    latest.current = { revision: revision.current, profile, today, overrides, now, mode }
    setPending(true)
    dispatch.current()
    // Only day/freshness transitions invalidate time-dependent results.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notices, profile, today, overrides, freshness, active, mode])
  return { ...result, pending }
}
