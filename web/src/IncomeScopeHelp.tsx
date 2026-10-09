import { memo, useMemo, useState } from 'react'
import type { Notice, NoticeRule } from './types'

interface IncomeScopeSource {
  title: string
  supplies: string[]
  date: string | null
  url: string | null
  page?: number
  scope: string
  income: string
  minimumTableSize: number | null
}

const HYANGNAM_HASH = 'b5668bcd00f9606b110b21c9703fdce3994f5f690b43299fadeaf9ed2a73c61e'
const A17_HASH = 'f591455563e503427c61699da3823b2029aa8ba24e3d09d84478ce01686d10e0'

// These two scope paragraphs were reviewed in the full official documents in
// api/tests/fixtures. An exact hash and supply match are required: neither the
// address nor a similar project name establishes the same income scope.
function reviewedScope(rule: NoticeRule): Pick<IncomeScopeSource, 'scope' | 'income' | 'url' | 'page'> | null {
  const supply = rule.supply_type || ''
  if (rule.document_hash === HYANGNAM_HASH && ['신혼부부 특별공급', '생애최초 특별공급', '신생아 특별공급'].includes(supply)) {
    return {
      scope: '무주택세대구성원 전원으로 산정. 단, 임신 중인 태아는 태아 수만큼 인정하되, 공급신청자의 직계존속(공급신청자의 배우자의 직계존속을 포함)은 입주자모집공고일을 기준으로 최근 1년 이상 계속하여 공급신청자 또는 그 배우자와 같은 세대별 주민등록표에 등재되어 있는 경우에만 포함',
      income: '가구원수에 포함되는 가구원 중 만19세 이상인 성년자(세대주인 미성년자(자녀양육, 형제자매 부양) 포함). 단, 세대원의 실종 등으로 소득파악이 불가능한 경우에는 주민등록표등본 말소를 확인하고 소득산정 대상에서 제외',
      url: 'https://xn--q20b245acmc65au2puno.com/data/gongo_re.pdf',
      page: supply.startsWith('신혼') ? 18 : supply.startsWith('생애') ? 22 : 24,
    }
  }
  if (rule.document_hash === A17_HASH && ['신혼부부(신혼희망타운)', '예비신혼부부(신혼희망타운)', '한부모가족(신혼희망타운)'].includes(supply)) {
    return {
      scope: supply.startsWith('예비')
        ? '청약 시 제출한 ‘혼인으로 구성될 세대’에 해당하는 자 전원. 임신 중인 태아도 태아의 수만큼 가구원수로 산정'
        : '‘무주택세대구성원’에 해당하는 자 전원. 임신 중인 태아도 태아의 수만큼 가구원수로 산정. 신청자 또는 (예비)배우자의 주민등록표등본에 등재되지 아니한 신청자의 직계존비속은 인정하지 아니함.',
      income: '위 ‘가구원수 적용 기준’에 따라 산정된 가구원 중 만 19세 이상 무주택세대구성원 전원의 합산 소득. 단, 세대원의 실종, 별거 등으로 소득파악이 불가능한 경우에는 주민등록표등본 말소를 확인하고 소득산정 대상에서 제외',
      url: 'https://apply.lh.or.kr/lhapply/lhFile.do?fileid=68807314',
      page: 12,
    }
  }
  return null
}

function text(value: unknown): string {
  if (typeof value === 'string') return value.replace(/\s+/g, ' ').trim()
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const source = value as Record<string, unknown>
    return text(source.evidence_text) || text(source.text) || text(source.description)
  }
  return ''
}

function safeUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) ? value : null
  } catch { return null }
}

function excerpt(value: string, start: RegExp, end: RegExp): string {
  const match = start.exec(value)
  if (!match) return ''
  const body = value.slice(match.index)
  const stop = end.exec(body.slice(match[0].length))
  return stop ? body.slice(0, match[0].length + stop.index).trim() : body.trim()
}

function scopeFromEvidence(rule: NoticeRule): { scope: string; income: string } {
  const evidence = [rule.evidence_text, rule.table_evidence_text].map(text).filter(Boolean).join(' ')
  const declared = text(rule.household_scope)
  const scope = text(rule.household_scope_evidence_text) || text(rule.income_household_scope_evidence_text) || text(rule.household_scope_text) || (/^[a-z_]+$/i.test(declared) ? '' : declared)
    || excerpt(evidence, /(?:\(?가구원\s*수\s*산정\s*기준\)?|<가구원\s*수\s*적용\s*기준>|가구원\s*수는)/, /(?:\(?월평균\s*소득산정\s*대상\)?|<가구당\s*월평균소득액\s*산정기준>|■\s*자산기준)/)
  const income = text(rule.income_scope_evidence_text) || text(rule.income_sum_scope)
    || excerpt(evidence, /(?:\(?월평균\s*소득산정\s*대상\)?|<가구당\s*월평균소득액\s*산정기준>)/, /(?:※\s*\(월평균소득\)|■\s*\(중요\)|■\s*자산기준|•\s*기준\s*초과)/)
  return { scope, income }
}

function incomeRules(rules: NoticeRule[], parent?: NoticeRule): NoticeRule[] {
  const result: NoticeRule[] = []
  for (const raw of rules) {
    if (raw.effect === 'waiver') continue
    const inherited = parent ? Object.fromEntries(Object.entries(parent).filter(([key]) => !['conditions', 'exceptions', 'kind', 'value', 'operator', 'effect'].includes(key))) : {}
    const rule: NoticeRule = { ...inherited, ...raw }
    if (['monthly_income_max_krw', 'shinhee_income', 'income_max_krw', 'income_household_scope'].includes(rule.kind)) result.push(rule)
    for (const key of ['conditions', 'exceptions']) {
      const children = rule[key]
      if (Array.isArray(children)) result.push(...incomeRules(children.filter((child): child is NoticeRule => !!child && typeof child === 'object' && typeof child.kind === 'string'), rule))
    }
  }
  return result
}

export function incomeScopeSources(notices: Notice[]): IncomeScopeSource[] {
  const grouped = new Map<string, IncomeScopeSource>()
  for (const notice of notices) {
    for (const rule of incomeRules(notice.rules)) {
      // An AI excerpt and an income ceiling alone do not establish which
      // relatives are counted. Show only an official family-scope paragraph.
      if (rule.verification !== 'official' || rule.effect === 'waiver') continue
      const reviewed = reviewedScope(rule)
      const extracted = scopeFromEvidence(rule)
      const scope = extracted.scope || reviewed?.scope || ''
      const income = extracted.income || reviewed?.income || ''
      const date = text(rule.criterion_date) || notice.announcement_date
      const url = safeUrl(rule.household_scope_evidence_url) || safeUrl(reviewed?.url) || safeUrl(rule.evidence_url) || safeUrl(notice.official_url)
      const pageValue = rule.household_scope_evidence_page ?? reviewed?.page ?? rule.evidence_page
      const page = typeof pageValue === 'number' && Number.isInteger(pageValue) && pageValue > 0 ? pageValue : undefined
      const minimumTableSize = typeof rule.min_household_size === 'number' && rule.min_household_size > 0 ? rule.min_household_size : null
      const key = JSON.stringify([notice.id, date, scope, income, url, page, minimumTableSize])
      const supply = rule.supply_type || '공고 공통'
      const existing = grouped.get(key)
      if (existing) { if (!existing.supplies.includes(supply)) existing.supplies.push(supply); continue }
      grouped.set(key, { title: notice.title, supplies: [supply], date, scope, income, url, page, minimumTableSize })
    }
  }
  return [...grouped.values()]
}

function Source({ source }: { source: IncomeScopeSource }) {
  const url = source.url && source.page ? `${source.url.split('#')[0]}#page=${source.page}` : source.url
  return <div className="income-scope-source">
    <h5>{source.title}</h5>
    <p className="field-help">{source.supplies.join(' · ')} · 기준일 {source.date || '공고 기준일 미확보'}</p>
    {source.scope ? <><p className="field-help"><strong>인원에 포함하는 가족</strong></p><blockquote>{source.scope}</blockquote></>
      : <p className="field-help">서비스의 원문 검토 부족: 소득 한도만으로는 인원에 포함할 가족을 확정할 수 없습니다. 별도 등본 배우자 세대·직계존속의 합가기간·태아 포함 여부를 정한 조항은 아직 확보하지 못했습니다.</p>}
    {source.income && <><p className="field-help"><strong>소득을 합산하는 대상</strong></p><blockquote>{source.income}</blockquote></>}
    {source.minimumTableSize !== null && <p className="field-help">소득표는 {source.minimumTableSize}인 이하를 같은 구간으로 비교합니다. 실제 인정 인원이 2명이면 입력은 2명입니다.</p>}
    {url && <a href={url} target="_blank" rel="noopener noreferrer">공식 소득 산정 근거{source.page ? ` ${source.page}쪽` : ''} ↗</a>}
  </div>
}

export const IncomeScopeHelp = memo(function IncomeScopeHelp({ notices }: { notices: Notice[] }) {
  const sources = useMemo(() => incomeScopeSources(notices), [notices])
  const [expanded, setExpanded] = useState(false)
  return <section className="question-group income-scope-help" aria-label="소득 산정 가구원 수 기준">
    <h4>소득표에서 한도를 고르는 실제 가구원 수입니다</h4>
    <p className="field-help">신청자를 포함해 공고가 인정하는 가족을 셉니다. 배우자는 등본이 분리되어 있어도 포함되는지 확인하고, 부모·자녀는 등본과 합가기간 등 해당 공급유형의 범위를 적용합니다. 태아는 공고가 포함하는 경우에만 태아 수만큼 더합니다.</p>
    <p className="field-help">주택 보유 확인 가족 수와 청약가점의 부양가족 수는 각각 다른 기준입니다. 소득이 없는 자녀도 가구원 수에는 포함될 수 있으며, 소득 합산 대상은 공고가 정한 연령·조사 범위로 따로 정합니다.</p>
    <p className="field-help">‘3인 이하’ 소득표를 쓰는 2인 가구는 2명을 입력합니다. 세 사람으로 늘려 입력하지 않습니다. 공급유형마다 포함하는 가족이 다르면 아래 근거에 맞는 인원으로 비교해야 합니다.</p>
    {sources.length ? <>
      {sources.slice(0, 3).map((source, index) => <Source key={index} source={source} />)}
      {sources.length > 3 && <><button type="button" className="text-button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? '추가 근거 접기' : `다른 소득 산정 근거 ${sources.length - 3}개 보기`}</button>{expanded && sources.slice(3).map((source, index) => <Source key={index} source={source} />)}</>}
    </> : <p className="field-help">현재 공고 자료에서 공식 소득 산정 가족 범위를 확보하지 못했습니다. 각 공고의 해당 공급유형 ‘가구원 수 산정 기준’과 ‘월평균소득 산정 대상’ 조항이 기준이며, 위 가족 목록만으로 인원을 확정하지 않습니다.</p>}
  </section>
})
