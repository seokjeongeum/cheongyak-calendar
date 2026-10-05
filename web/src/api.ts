import type { CoverageResponse, NoticesResponse } from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

async function getJson<T>(path: string, params?: URLSearchParams, signal?: AbortSignal): Promise<T> {
  const url = `${API_BASE}${path}${params ? `?${params}` : ''}`
  const response = await fetch(url, { headers: { Accept: 'application/json' }, signal })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json() as Promise<T>
}

export function getNotices(start: string, end: string, page = 1, capOnly = false, signal?: AbortSignal, view: 'schedule' | 'results' = 'schedule'): Promise<NoticesResponse> {
  const params = new URLSearchParams({
    start, end, page: String(page), page_size: '100',
    exclude_public_rental: 'true', application_only: 'true',
  })
  if (view === 'results') params.set('view', 'results')
  if (capOnly) params.set('cap_only', 'true')
  return getJson<NoticesResponse>('/api/notices', params, signal)
}

// The public API paginates notices. The compact calendar needs every application
// date in its displayed month, including dates on later pages of the agenda.
export async function getCalendarNotices(start: string, end: string, signal?: AbortSignal, capOnly = false, view: 'schedule' | 'results' = 'schedule'): Promise<NoticesResponse['items']> {
  const first = await getNotices(start, end, 1, capOnly, signal, view)
  const items = [...first.items]
  const pages = Math.ceil(first.total / first.page_size)
  for (let offset = 2; offset <= pages; offset += 4) {
    const requests = Array.from({ length: Math.min(4, pages - offset + 1) }, (_, index) =>
      getNotices(start, end, offset + index, capOnly, signal, view),
    )
    const batch = await Promise.all(requests)
    for (const page of batch) items.push(...page.items)
  }
  return items
}

export function getCoverage(signal?: AbortSignal): Promise<CoverageResponse> {
  return getJson<CoverageResponse>('/api/coverage', undefined, signal)
}
