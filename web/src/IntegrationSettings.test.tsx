import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { consumeIntegrationEntry, IntegrationSettings } from './IntegrationSettings'

afterEach(() => vi.unstubAllGlobals())

function browser(hash: string, search = '') {
  const replaceState = vi.fn()
  const storage = { setItem: vi.fn(), getItem: vi.fn() }
  const value = { location: { pathname: '/calendar', search, hash }, history: { state: { page: 1 }, replaceState }, localStorage: storage, sessionStorage: storage }
  vi.stubGlobal('window', value)
  return { value: value as unknown as Window, replaceState, storage }
}

describe('private hosted settings entry', () => {
  it('consumes the encoded fragment credential and scrubs it without storage or a query credential', () => {
    const fake = browser('#api-settings&admin=fictional%2Badmin%2Ftoken%3D', '?view=month')
    expect(consumeIntegrationEntry(fake.value)).toEqual({ token: 'fictional+admin/token=' })
    expect(fake.replaceState).toHaveBeenCalledTimes(1)
    expect(fake.replaceState).toHaveBeenCalledWith({ page: 1 }, '', '/calendar?view=month#api-settings')
    expect(fake.storage.setItem).not.toHaveBeenCalled()
    expect(fake.storage.getItem).not.toHaveBeenCalled()
  })

  it('opens the plain public settings fragment without an authentication credential', () => {
    const fake = browser('#api-settings')
    expect(consumeIntegrationEntry(fake.value)).toEqual({ token: null })
    expect(fake.replaceState).not.toHaveBeenCalled()
  })

  it('scrubs an empty credential instead of leaving an owner parameter in the address', () => {
    const fake = browser('#api-settings&admin=')
    expect(consumeIntegrationEntry(fake.value)).toEqual({ token: '' })
    expect(fake.replaceState).toHaveBeenCalledTimes(1)
    expect(fake.replaceState).toHaveBeenCalledWith({ page: 1 }, '', '/calendar#api-settings')
  })

  it('never treats query parameters or another section as an owner credential', () => {
    const fake = browser('#coverage&admin=fictional-admin', '?admin=fictional-query')
    expect(consumeIntegrationEntry(fake.value)).toBeNull()
    expect(fake.replaceState).not.toHaveBeenCalled()
    const plain = browser('#api-settings', '?admin=fictional-query')
    expect(consumeIntegrationEntry(plain.value)).toEqual({ token: null })
  })

  it('keeps ordinary rendering closed and free of local setup commands', () => {
    const html = renderToStaticMarkup(<IntegrationSettings />)
    expect(html).toContain('id="api-settings"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).not.toContain('integration-admin-token')
    expect(html).not.toMatch(/docker compose|git pull|\.env/)
  })
})
