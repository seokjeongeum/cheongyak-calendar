import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { consumeIntegrationEntry, editIntegrationKey, integrationKeyStatus, IntegrationSettings } from './IntegrationSettings'
import type { IntegrationSettingsResponse } from './api'

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

const service = (name: string, configured = false, usesShared = false): IntegrationSettingsResponse['services'][number] => ({ name, label: name, key_url: 'https://www.data.go.kr/', configured, uses_shared_key: usesShared, storage: 'server' })
const common = service('DATA_GO_KR_API_KEY', true)

describe('one public-data key and optional provider overrides', () => {
  it('removes an empty edit without submitting a deletion of the saved key', () => {
    expect(editIntegrationKey({ LH_API_KEY: 'new-key', MYHOME_API_KEY: 'other-key' }, 'LH_API_KEY', '')).toEqual({ MYHOME_API_KEY: 'other-key' })
    expect(editIntegrationKey({}, 'LH_API_KEY', '   ')).toEqual({})
  })

  it('preserves an explicit delete until it is cancelled or replaced', () => {
    expect(editIntegrationKey({ LH_API_KEY: '', MYHOME_API_KEY: 'other-key' }, 'MYHOME_API_KEY', 'changed')).toEqual({ LH_API_KEY: '', MYHOME_API_KEY: 'changed' })
    expect(editIntegrationKey({ LH_API_KEY: '' }, 'LH_API_KEY', '')).toEqual({})
    expect(editIntegrationKey({ LH_API_KEY: '' }, 'LH_API_KEY', 'replacement')).toEqual({ LH_API_KEY: 'replacement' })
  })

  it('previews a shared key for unconfigured providers before saving it', () => {
    expect(integrationKeyStatus(service('LH_API_KEY'), service('DATA_GO_KR_API_KEY'), { DATA_GO_KR_API_KEY: 'fictional-key' })).toBe('공통 키 사용 예정')
  })

  it('marks effective shared configurations as common usage instead of an individual key', () => {
    expect(integrationKeyStatus(service('LH_API_KEY', true, true), common, {})).toBe('공통 키 사용')
  })

  it('preserves a configured provider override when the common key is changed or deleted', () => {
    const own = service('LH_API_KEY', true)
    expect(integrationKeyStatus(own, common, { DATA_GO_KR_API_KEY: 'replacement' })).toBe('기관별 키 연결됨')
    expect(integrationKeyStatus(own, common, { DATA_GO_KR_API_KEY: '' })).toBe('기관별 키 연결됨')
  })

  it('shows fallback to the common key only after an explicit override deletion', () => {
    expect(integrationKeyStatus(service('LH_API_KEY', true), common, { LH_API_KEY: '' })).toBe('별도 키 삭제 · 공통 키 사용 예정')
    expect(integrationKeyStatus(service('LH_API_KEY', true, true), common, { DATA_GO_KR_API_KEY: '' })).toBe('공통 키 삭제 예정')
  })

  it('keeps Gemini independent from public-data key changes', () => {
    expect(integrationKeyStatus(service('GEMINI_API_KEY'), common, { DATA_GO_KR_API_KEY: 'replacement' })).toBe('키 미설정')
    expect(integrationKeyStatus(service('GEMINI_API_KEY', true), common, { GEMINI_API_KEY: '' })).toBe('키 삭제 예정')
  })
})
