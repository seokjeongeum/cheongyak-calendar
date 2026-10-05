import { afterEach, describe, expect, it, vi } from 'vitest'
import { getCalendarNotices, getNotices } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('public notice requests', () => {
  it('applies the reception-only and public-rental exclusions to agenda and calendar pages', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], total: 0, page: 1, page_size: 100 }) })
    vi.stubGlobal('fetch', fetchMock)

    await getNotices('2026-09-30', '2026-11-30', 1, true)
    await getCalendarNotices('2026-09-30', '2026-09-30')

    expect(fetchMock).toHaveBeenCalledTimes(2)
    for (const [url, init] of fetchMock.mock.calls) {
      const parsed = new URL(String(url), 'http://localhost')
      expect(parsed.pathname).toBe('/api/notices')
      expect(parsed.searchParams.get('exclude_public_rental')).toBe('true')
      expect(parsed.searchParams.get('application_only')).toBe('true')
      expect(parsed.searchParams.get('start')).toBe('2026-09-30')
      expect(init).toEqual({ headers: { Accept: 'application/json' }, signal: undefined })
      expect(JSON.stringify([url, init])).not.toMatch(/region|district|movedInDate|householdSize/)
    }
  })

  it('loads every public page before personal exclusions so an entirely hidden first page cannot stop the list', async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      const page = Number(new URL(url, 'http://localhost').searchParams.get('page'))
      return { ok: true, json: async () => ({ items: [{ id: `page-${page}` }], total: 501, page, page_size: 100 }) }
    })
    vi.stubGlobal('fetch', fetchMock)

    const rows = await getCalendarNotices('2026-10-01', '2026-12-31', undefined, true)
    expect(rows.map((notice) => notice.id)).toEqual(['page-1', 'page-2', 'page-3', 'page-4', 'page-5', 'page-6'])
    expect(fetchMock).toHaveBeenCalledTimes(6)
    for (const [url, init] of fetchMock.mock.calls) {
      const parsed = new URL(String(url), 'http://localhost')
      expect(parsed.searchParams.get('cap_only')).toBe('true')
      expect([...parsed.searchParams.keys()].sort()).toEqual(['application_only', 'cap_only', 'end', 'exclude_public_rental', 'page', 'page_size', 'start'])
      expect(init.headers).toEqual({ Accept: 'application/json' })
    }
  })

  it('queries historical results across every page without sending applicant conditions', async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      const params = new URL(url, 'http://localhost').searchParams
      const page = Number(params.get('page'))
      return { ok: true, json: async () => ({ items: [{ id: `official-result-${page}` }], total: 101, page, page_size: 100 }) }
    })
    vi.stubGlobal('fetch', fetchMock)
    const rows = await getCalendarNotices('2026-07-06', '2026-10-03', undefined, false, 'results')
    expect(rows.map((notice) => notice.id)).toEqual(['official-result-1', 'official-result-2'])
    for (const [url, init] of fetchMock.mock.calls) {
      const params = new URL(String(url), 'http://localhost').searchParams
      expect(params.get('view')).toBe('results')
      expect(params.get('application_only')).toBe('true')
      expect(params.get('exclude_public_rental')).toBe('true')
      expect([...params.keys()].sort()).toEqual(['application_only', 'end', 'exclude_public_rental', 'page', 'page_size', 'start', 'view'])
      expect(init).toEqual({ headers: { Accept: 'application/json' }, signal: undefined })
    }
  })
})
