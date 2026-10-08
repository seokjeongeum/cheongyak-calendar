import { useEffect, useState } from 'react'
import { ExternalLink, KeyRound, X } from 'lucide-react'
import { getIntegrationSettings, saveIntegrationSettings, type IntegrationSettingsResponse } from './api'

/** Consume the private entry credential before loading settings or following links. */
export function consumeIntegrationEntry(browser: Pick<Window, 'location' | 'history'>): { token: string | null } | null {
  const [route, ...parameters] = browser.location.hash.slice(1).split('&')
  if (route !== 'api-settings') return null
  const fragment = new URLSearchParams(parameters.join('&'))
  const token = fragment.get('admin')
  if (fragment.has('admin')) {
    browser.history.replaceState(browser.history.state, '', `${browser.location.pathname}${browser.location.search}#api-settings`)
  }
  return { token }
}

export function IntegrationSettings() {
  const [open, setOpen] = useState(false)
  const [settings, setSettings] = useState<IntegrationSettingsResponse | null>(null)
  const [token, setToken] = useState('')
  const [keys, setKeys] = useState<Record<string, string>>({})
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let mounted = true
    async function enterFromLink() {
      const entry = consumeIntegrationEntry(window)
      if (!entry) return
      setOpen(true)
      if (entry.token !== null) setToken(entry.token)
      setBusy(true); setError('')
      try {
        const result = await getIntegrationSettings()
        if (mounted) { setSettings(result); setConfirmed(result.gemini_unbilled_confirmed) }
      } catch {
        if (mounted) setError('연결 설정을 불러오지 못했습니다. 닫은 뒤 다시 열어주세요.')
      } finally { if (mounted) setBusy(false) }
    }
    void enterFromLink()
    window.addEventListener('hashchange', enterFromLink)
    return () => { mounted = false; window.removeEventListener('hashchange', enterFromLink) }
  }, [])

  useEffect(() => {
    if (open && window.location.hash === '#api-settings') document.getElementById('integration-form')?.scrollIntoView({ block: 'start' })
  }, [open])

  async function toggle() {
    if (open) { setOpen(false); setKeys({}); setToken(''); setMessage(''); setError(''); return }
    setOpen(true); setBusy(true); setError('')
    try {
      const result = await getIntegrationSettings()
      setSettings(result); setConfirmed(result.gemini_unbilled_confirmed)
    } catch { setError('연결 설정을 불러오지 못했습니다. 닫은 뒤 다시 열어주세요.') }
    finally { setBusy(false) }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage(''); setError('')
    try {
      const result = await saveIntegrationSettings(token.trim(), keys, confirmed)
      setSettings(result); setKeys({})
      setMessage('저장했습니다. 다음 수집부터 적용됩니다. 수집은 3시간마다 실행됩니다.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '저장하지 못했습니다.') }
    finally { setBusy(false) }
  }

  return <div className="integration-settings" id="api-settings">
    <button type="button" className="period-button" aria-expanded={open} aria-controls="integration-form" onClick={toggle}><KeyRound size={16} /> API 연결 설정 {open && <X size={15} />}</button>
    {open && <form id="integration-form" className="integration-form" style={{ scrollMarginTop: 90 }} onSubmit={save} aria-label="API 연결 설정">
      <h3>API 키 연결</h3><p>각 서비스에서 활용신청 후 일반 인증키(Decoding)를 입력하세요. 같은 공통 키도 서비스별 승인이 필요합니다. 키는 서버에 저장하며 저장된 원문을 화면에 다시 보내지 않습니다.</p>
      {busy && !settings && <p role="status">설정을 불러오는 중입니다.</p>}
      {settings && <>
        <div className="integration-admin"><label htmlFor="integration-admin-token">관리자 인증키</label><input id="integration-admin-token" type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} placeholder="저장할 때만 필요합니다" disabled={busy} />
          <p>{settings.admin_initialized ? '관리자 연결 링크로 열면 바로 저장할 수 있습니다. 인증키는 이 화면을 닫을 때까지 유지하며 브라우저에 저장하지 않습니다.' : '관리자 연결이 아직 준비되지 않았습니다. 앱 관리자에게 연결 링크를 요청하세요.'}</p>
        </div>
        <div className="integration-services">{settings.services.map(service => <div className="integration-service" key={service.name}>
          <div className="integration-service-heading"><label htmlFor={`key-${service.name}`}>{service.label}</label><a href={service.key_url} target="_blank" rel="noopener noreferrer">{service.name === 'GEMINI_API_KEY' ? 'API 키 발급' : '활용신청·키 발급'} <ExternalLink size={13} /></a></div>
          <small>{service.configured ? '키 연결됨' : service.uses_shared_key ? '공통 키 사용' : '키 미설정'}{keys[service.name] === '' ? ' · 삭제 예정' : keys[service.name] ? ' · 변경 예정' : ''}</small>
          <div className="integration-key-row"><input id={`key-${service.name}`} type="password" autoComplete="off" spellCheck={false} value={keys[service.name] || ''} onChange={event => { setKeys(previous => ({ ...previous, [service.name]: event.target.value })); if (service.name === 'GEMINI_API_KEY') setConfirmed(false) }} placeholder={service.configured ? '변경할 때만 새 키 입력' : 'API 키 입력'} disabled={busy} /><button type="button" className="period-button" onClick={() => { setKeys(previous => ({ ...previous, [service.name]: '' })); if (service.name === 'GEMINI_API_KEY') setConfirmed(false) }} disabled={busy || (!service.configured && !keys[service.name])}>삭제</button></div>
        </div>)}</div>
        <label className="integration-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={busy} />Gemini 키가 청구를 사용하지 않는 Google 프로젝트의 키임을 확인했습니다.</label>
        <p>Gemini는 선택 사항입니다. 위 확인 없이는 호출하지 않습니다. 공개 공고문만 전송하며 무료 한도 초과 시 대기합니다.</p>
        <button type="submit" className="period-button" disabled={busy || !token.trim() || !settings.admin_initialized}>{busy ? '저장 중…' : '연결 설정 저장'}</button>
      </>}
      {message && <p role="status">{message}</p>}{error && <p role="alert" className="error-banner">{error}</p>}
    </form>}
  </div>
}
