import { useEffect, useState } from 'react'
import { ExternalLink, KeyRound, X } from 'lucide-react'
import { getIntegrationSettings, saveIntegrationSettings, type IntegrationSettingsResponse } from './api'

const COMMON_KEY = 'DATA_GO_KR_API_KEY'
const GEMINI_KEY = 'GEMINI_API_KEY'
type IntegrationService = IntegrationSettingsResponse['services'][number]

/** Blank edits leave the saved key alone; only the Delete action adds ''. */
export function editIntegrationKey(previous: Record<string, string>, name: string, value: string): Record<string, string> {
  const next = { ...previous }
  if (value.trim()) next[name] = value
  else delete next[name]
  return next
}

export function integrationKeyStatus(service: IntegrationService, common: IntegrationService | undefined, keys: Record<string, string>): string {
  const ownDraft = keys[service.name]
  const commonDraft = keys[COMMON_KEY]
  const commonAvailable = commonDraft === undefined ? !!common?.configured : !!commonDraft.trim()
  if (service.name === COMMON_KEY) {
    if (ownDraft === '') return '공통 키 삭제 예정'
    if (ownDraft) return '공통 키 변경 예정'
    return service.configured ? '공통 키 연결됨' : '키 미설정'
  }
  if (service.name === GEMINI_KEY) {
    if (ownDraft === '') return '키 삭제 예정'
    if (ownDraft) return '키 변경 예정'
    return service.configured ? '키 연결됨' : '키 미설정'
  }
  if (ownDraft === '') return commonAvailable ? '별도 키 삭제 · 공통 키 사용 예정' : '별도 키 삭제 예정'
  if (ownDraft) return '기관별 키 변경 예정'
  if (service.configured && !service.uses_shared_key) return '기관별 키 연결됨'
  if (commonDraft === '') return '공통 키 삭제 예정'
  if (commonDraft) return '공통 키 사용 예정'
  return service.uses_shared_key || commonAvailable ? '공통 키 연결됨' : '키 미설정'
}

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

export function IntegrationSettings({ onSaved, onCollect }: { onSaved?: (adminToken: string) => void; onCollect?: (adminToken: string) => Promise<void> } = {}) {
  const [open, setOpen] = useState(false)
  const [settings, setSettings] = useState<IntegrationSettingsResponse | null>(null)
  const [token, setToken] = useState('')
  const [keys, setKeys] = useState<Record<string, string>>({})
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [collecting, setCollecting] = useState(false)
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
    let saved = false
    try {
      const result = await saveIntegrationSettings(token.trim(), keys, confirmed)
      setSettings(result); setKeys({})
      setMessage('설정을 서버에 저장했습니다.')
      saved = true
    } catch (reason) { setError(reason instanceof Error ? reason.message : '저장하지 못했습니다.') }
    finally { setBusy(false) }
    if (saved) {
      try { onSaved?.(token.trim()) }
      catch { setError('설정은 저장되었습니다. 수집 요청에 실패했습니다. 지금 수집 시작으로 다시 시도하세요.') }
    }
  }

  async function collect() {
    if (!onCollect) return
    setCollecting(true); setError('')
    try { await onCollect(token.trim()) }
    catch { setError('저장된 설정은 유지됩니다. 수집 요청에 실패했습니다. 잠시 후 다시 시도하세요.') }
    finally { setCollecting(false) }
  }

  const common = settings?.services.find(service => service.name === COMMON_KEY)
  const gemini = settings?.services.find(service => service.name === GEMINI_KEY)
  const publicServices = settings?.services.filter(service => service.name !== GEMINI_KEY) || []
  const overrides = publicServices.filter(service => service.name !== COMMON_KEY)
  function changeKey(name: string, value: string) {
    setKeys(previous => editIntegrationKey(previous, name, value))
    if (name === GEMINI_KEY) setConfirmed(false)
  }
  function keyCard(service: IntegrationService, label = service.label) {
    const ownConfigured = service.configured && !service.uses_shared_key
    const deleting = keys[service.name] === ''
    return <div className="integration-service" key={service.name}>
      <div className="integration-service-heading"><label htmlFor={`key-${service.name}`}>{label}</label>{service.name === GEMINI_KEY && <a href={service.key_url} target="_blank" rel="noopener noreferrer">API 키 발급 <ExternalLink size={13} /></a>}</div>
      <small>{integrationKeyStatus(service, common, keys)}</small>
      <div className="integration-key-row"><input id={`key-${service.name}`} type="password" autoComplete="off" spellCheck={false} value={keys[service.name] || ''} onChange={event => changeKey(service.name, event.target.value)} placeholder={ownConfigured ? '변경할 때만 새 키 입력' : 'API 키 입력'} disabled={busy} /><button type="button" className="period-button" onClick={() => { setKeys(previous => deleting ? editIntegrationKey(previous, service.name, '') : { ...previous, [service.name]: '' }); if (service.name === GEMINI_KEY) setConfirmed(false) }} disabled={busy || (!ownConfigured && !keys[service.name] && !deleting)}>{deleting ? '삭제 취소' : '삭제'}</button></div>
      {service.name === COMMON_KEY && <p>청약홈·마이홈·LH·iH·청약 경쟁률에 같은 인증키를 함께 사용합니다. 서비스별 활용신청 승인은 아래 링크에서 각각 확인하세요.</p>}
      {service.name === GEMINI_KEY && <><label className="integration-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={busy} />Gemini 키가 청구를 사용하지 않는 Google 프로젝트의 키임을 확인했습니다.</label><p>Gemini는 선택 사항입니다. 위 확인 없이는 호출하지 않습니다. 공개 공고문만 전송하며 무료 한도 초과 시 대기합니다.</p></>}
    </div>
  }

  return <div className="integration-settings" id="api-settings">
    <button type="button" className="period-button" aria-expanded={open} aria-controls="integration-form" onClick={toggle}><KeyRound size={16} /> API 연결 설정 {open && <X size={15} />}</button>
    {open && <form id="integration-form" className="integration-form" style={{ scrollMarginTop: 90 }} onSubmit={save} aria-label="API 연결 설정">
      <h3>API 키 연결</h3><p>공공데이터 일반 인증키(Decoding)는 한 번만 입력하세요. 키는 서버에 저장하며 저장된 원문을 화면에 다시 보내지 않습니다. 빈 입력은 기존 키를 유지하고, 삭제 버튼을 눌렀을 때만 삭제합니다.</p>
      {busy && !settings && <p role="status">설정을 불러오는 중입니다.</p>}
      {settings && <>
        <div className="integration-admin"><label htmlFor="integration-admin-token">관리자 인증키</label><input id="integration-admin-token" type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} placeholder="저장·수집할 때 필요합니다" disabled={busy || collecting} aria-describedby="integration-admin-help" />
          <p id="integration-admin-help">{settings.admin_initialized ? settings.admin_setup_url ? '관리자 인증키 확인 화면에서 INTEGRATIONS_ADMIN_BOOTSTRAP_TOKEN 값을 복사해 입력하세요. 이 화면을 닫으면 입력한 인증키를 지웁니다.' : '관리자 연결 링크로 열면 바로 저장할 수 있습니다. 인증키는 이 화면을 닫을 때까지 유지하며 브라우저에 저장하지 않습니다.' : '관리자 연결이 아직 준비되지 않았습니다. 앱 관리자에게 연결 링크를 요청하세요.'}{settings.admin_setup_url && <> <a href={settings.admin_setup_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">관리자 인증키 확인 <ExternalLink size={13} /></a></>}</p>
          {!token.trim() && <p className="integration-admin-required">저장·수집하려면 관리자 인증키를 입력하세요.</p>}
        </div>
        <div className="integration-services integration-primary-keys">{common && keyCard(common, '공공데이터 공통 인증키')}{gemini && keyCard(gemini)}</div>
        <div className="integration-provider-links" aria-label="공공데이터 서비스별 활용신청"><h4>서비스별 활용신청</h4>{publicServices.map(service => <div className="integration-provider" key={service.name} data-integration-provider={service.name}><div><strong>{service.name === COMMON_KEY ? '청약홈' : service.label}</strong><small>{integrationKeyStatus(service, common, keys)}</small></div><a href={service.key_url} target="_blank" rel="noopener noreferrer">활용신청·키 발급 <ExternalLink size={13} /></a></div>)}</div>
        {!!overrides.length && <details className="integration-overrides"><summary>기관별 다른 키 사용</summary><p>특정 기관에 다른 인증키가 필요한 경우에만 입력하세요. 기존 별도 키는 그대로 유지됩니다. 별도 키를 삭제하면 저장된 공통 키를 사용합니다.</p><div className="integration-services">{overrides.map(service => keyCard(service))}</div></details>}
        <div className="integration-actions"><button type="submit" className="period-button" disabled={busy || collecting || !token.trim() || !settings.admin_initialized}>{busy ? '저장 중…' : '연결 설정 저장'}</button>{onCollect && <button type="button" className="period-button" disabled={busy || collecting || !token.trim() || !settings.admin_initialized} onClick={collect}>{collecting ? '수집 요청 중…' : '지금 수집 시작'}</button>}</div>
      </>}
      {message && <p role="status">{message}</p>}{error && <p role="alert" className="error-banner">{error}</p>}
    </form>}
  </div>
}
