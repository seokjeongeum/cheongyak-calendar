import type { CoverageResponse, NoticesResponse } from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

async function getJson<T>(path: string, params?: URLSearchParams, signal?: AbortSignal): Promise<T> {
  const url = `${API_BASE}${path}${params ? `?${params}` : ''}`
  const response = await fetch(url, { headers: { Accept: 'application/json' }, cache: 'no-store', signal })
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

export interface IntegrationSettingsResponse {
  admin_initialized: boolean
  admin_setup_url?: string | null
  services: { name: string; label: string; key_url: string; configured: boolean; storage: string; uses_shared_key: boolean }[]
  gemini_unbilled_confirmed: boolean
}

export interface CollectionStatus {
  job_id: string | null
  status: 'idle' | 'running' | 'completed' | 'error' | 'interrupted'
  trigger: string | null
  started_at: string | null
  finished_at: string | null
  message: string
}

export function getCollectionStatus(signal?: AbortSignal): Promise<CollectionStatus> {
  return getJson<CollectionStatus>('/api/collection', undefined, signal)
}

export async function startCollection(token: string): Promise<CollectionStatus> {
  const response = await fetch(`${API_BASE}/api/collection`, {
    method: 'POST', headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
    cache: 'no-store', referrerPolicy: 'no-referrer',
  })
  if (!response.ok) throw new Error(response.status === 401
    ? '수집을 시작하려면 관리자 인증키를 확인하세요.'
    : '수집을 시작하지 못했습니다. 저장된 설정을 유지하며 다시 시도할 수 있습니다.')
  return response.json() as Promise<CollectionStatus>
}

export function getIntegrationSettings(): Promise<IntegrationSettingsResponse> {
  return getJson<IntegrationSettingsResponse>('/api/integrations')
}

export async function saveIntegrationSettings(token: string, keys: Record<string, string>, confirmed: boolean): Promise<IntegrationSettingsResponse> {
  const response = await fetch(`${API_BASE}/api/integrations`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    cache: 'no-store', referrerPolicy: 'no-referrer',
    body: JSON.stringify({ keys, gemini_unbilled_confirmed: confirmed }),
  })
  if (!response.ok) throw new Error(response.status === 401 ? '관리자 인증키를 확인하세요.' : '저장하지 못했습니다. 키 형식과 서버 연결을 확인하세요.')
  return response.json() as Promise<IntegrationSettingsResponse>
}
