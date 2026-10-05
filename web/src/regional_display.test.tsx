import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { NoticeCard } from './App'
import { EligibilityBrief, EligibilityDetails, NoticeRegionDecision, noticeRegionGroups } from './EligibilityDetails'
import { conditionSourceStatus, eligibilityCombinations, evaluateEligibility, officialOfferedSupplies } from './eligibility'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule, type OfferedSupply } from './types'

const evidence = 'https://www.applyhome.co.kr/official.pdf'
const cutoff = '2026-10-02'
const now = Date.parse('2026-10-05T00:00:00Z')
const jeju: LocalProfile = { ...EMPTY_PROFILE, region: '제주특별자치도', regionCode: '50', district: '제주시', districtCode: '50110', movedInDate: '2026-02-01', districtMovedInDate: '2026-02-01', cityMovedInDate: '2026-02-01' }
function rule(kind: string, extra: Partial<NoticeRule> = {}): NoticeRule {
  return { kind, verification: 'official', evidence_url: evidence, criterion_date: cutoff, ...extra }
}
function supply(supply_type: string, unit_type = '59A', supply_count = 1): OfferedSupply {
  return { supply_type, unit_type, supply_count, verification: 'official', evidence_url: evidence }
}
function notice(rules: NoticeRule[] = [], patch: Partial<Notice> = {}): Notice {
  return { id: 'regional-ui', title: '실제 모집 공고', category: 'apt', housing_kind: 'private', source: 'cheongyak_home', provider: '사업자', address: '제주특별자치도 제주시', region_code: '50', region_name: '제주특별자치도', announcement_date: cutoff, official_url: evidence, price_cap_status: 'no',
    events: [{ kind: 'first_priority', label: '1순위', start_date: '2026-10-12', end_date: '2026-10-12' }], prices: [{ unit_type: '59A', price_kind: 'sale_max', amount_krw: 310000000, verification: 'official' }], rules, rules_complete: false, updated_at: null, version: 1, ...patch }
}
const jejuRegion = rule('applicant_regions', { effect: 'metadata', regions: [{ region_code: '50', region_name: '제주특별자치도' }], local_priority: { region_code: '50', region_name: '제주특별자치도', min_months: 12 }, exceptions: [] })
const renderRegion = (item: Notice, profile: LocalProfile = jeju) => renderToStaticMarkup(<NoticeRegionDecision notice={item} profile={profile} onProfile={() => {}} />)
const renderBrief = (item: Notice, profile: LocalProfile = jeju) => renderToStaticMarkup(<EligibilityBrief notice={item} profile={profile} result={evaluateEligibility(item, profile)} onProfile={() => {}} onDetails={() => {}} />)

describe('official region decision on every notice card', () => {
  it('shows other-region priority with actual residence and cutoff comparison', () => {
    const html = renderRegion(notice([jejuRegion], { offered_supplies: [supply('일반공급')] }))
    expect(html).toContain('class="notice-region-decision" data-region-status="other"')
    expect(html).toContain('<strong>기타지역</strong>')
    expect(html).toContain('8개월')
    expect(html).toContain('12개월')
    expect(html).toContain(cutoff)
    const local = renderRegion(notice([jejuRegion]), { ...jeju, movedInDate: '2025-10-02', districtMovedInDate: '2025-10-02', cityMovedInDate: '2025-10-02' })
    expect(local).toContain('data-region-status="local"')
  })
  it('keeps application admission separate from local/other allocation', () => {
    const item = notice([jejuRegion])
    const outside = renderRegion(item, { ...jeju, region: '서울특별시', regionCode: '11', district: '중구', districtCode: '11140' })
    expect(outside).toContain('data-region-status="outside"')
    expect(outside).toContain('<strong>신청지역 밖</strong>')
    const noDivision = renderRegion(notice([rule('applicant_regions', { effect: 'metadata', regions: [{ region_code: '50', region_name: '제주특별자치도' }], priority_division: 'none' })]))
    expect(noDivision).toContain('data-region-status="not_divided"')
    expect(noDivision).toContain('<strong>신청지역 충족</strong>')
  })
  it('shows supply-specific geography when the actual offered types differ', () => {
    const item = notice([
      rule('applicant_regions', { effect: 'metadata', supply_type: '일반공급', unrestricted: true, priority_division: 'none' }),
      rule('applicant_regions', { effect: 'metadata', supply_type: '노부모부양 특별공급', regions: [{ region_code: '11', region_name: '서울특별시' }], priority_division: 'none' }),
    ], { offered_supplies: [supply('일반공급'), supply('노부모부양 특별공급', '74A')] })
    expect(noticeRegionGroups(item, jeju).map((group) => group.decision.status)).toEqual(['not_divided', 'outside'])
    const html = renderRegion(item)
    expect(html.match(/class="notice-region-decision notice-region-scope"/g)).toHaveLength(2)
    expect(html).toContain('일반공급 · 59A')
    expect(html).toContain('노부모부양 특별공급 · 74A')
  })
  it('distinguishes missing personal geography from unavailable official geography', () => {
    expect(renderRegion(notice([jejuRegion]), EMPTY_PROFILE)).toContain('data-region-status="missing_input"')
    expect(renderRegion(notice([jejuRegion]), EMPTY_PROFILE)).toContain('입력하기')
    expect(renderRegion(notice([]))).toContain('data-region-status="source_gap"')
    const html = renderToStaticMarkup(<NoticeCard notice={notice([])} profile={EMPTY_PROFILE} demoMode={false} today="2026-10-05" viewStart="2026-10-05" viewEnd="2026-10-31" decision={{ area: 'unknown', closedUnits: [], reason: null }} now={now} onOverride={() => {}} onProfile={() => {}} />)
    expect(html).not.toContain('notice-unavailable')
    expect(html).toContain('class="price-row"')
    expect(html).toContain('3억 1,000만원')
  })
})

describe('actual inventory and one source notice', () => {
  it('retains special-only stock with no invented general supply or zero-count types', () => {
    const item = notice([], { offered_supplies: [supply('생애최초 특별공급'), supply('생애최초 특별공급', '74A', 1), supply('일반공급', '59A', 0)] })
    expect(officialOfferedSupplies(item)).toHaveLength(2)
    expect(eligibilityCombinations(item).map((combo) => combo.supplyType)).toEqual(['생애최초 특별공급', '생애최초 특별공급'])
    const brief = renderBrief(item)
    expect(brief).toContain('공식 모집 유형')
    expect(brief).toContain('모집 1세대')
    expect(brief).not.toContain('일반공급')
    expect(brief).not.toContain('공고 조건 정리 중')
    const detail = renderToStaticMarkup(<EligibilityDetails notice={item} profile={jeju} onProfile={() => {}} />)
    expect(detail).toContain('공식 모집 주택형·공급유형')
    expect(detail).toContain('74A')
  })
  it('uses explicit empty inventory without resurrecting events or stale metadata', () => {
    const item = notice([rule('offered_supplies', { effect: 'metadata', supplies: [supply('일반공급')] })], { offered_supplies: [] })
    expect(officialOfferedSupplies(item)).toEqual([])
    expect(eligibilityCombinations(item)).toEqual([])
    expect(renderBrief(item)).not.toContain('qualification-supply-brief')
    expect(eligibilityCombinations(notice([], { offered_supplies: null }))).not.toHaveLength(0)
  })
  it('shows the three actual A17 types when their conditions are still unavailable', () => {
    const types = ['신혼부부(신혼희망타운)', '예비신혼부부(신혼희망타운)', '한부모가족(신혼희망타운)']
    const item = notice([], { offered_supplies: types.map((type) => supply(type)), housing_kind: 'national' })
    const html = renderBrief(item)
    for (const type of types) expect(html).toContain(type)
    expect(html).not.toContain('일반공급')
    expect(html.match(/class="qualification-gap-note"/g)).toHaveLength(1)
  })
  it('has no empty general diagnosis for unread notices, and shows specific failed stages and remaining topics', () => {
    const item = notice([
      rule('document_diagnostics', { effect: 'metadata', diagnostics: [{ stage: 'discovery', code: 'found', status: 'ok', message: '공고문 확인' }, { stage: 'decode', code: 'conversion_error', status: 'error', message: '첨부 문서의 텍스트 변환에 실패했습니다.', evidence_url: evidence }] }),
      rule('condition_coverage', { effect: 'metadata', scopes: [{ supply_type: '일반공급', complete: false, topics: [{ topic: '거주지역', status: 'verified', required: true }, { topic: '소득·자산', status: 'partial', required: true, reason: '금액표의 분기 조건 확인 필요' }, { topic: '납입 횟수', status: 'not_applicable', required: true }] }] }),
    ])
    expect(conditionSourceStatus(item).topics.map((topic) => topic.label)).toEqual(['소득·자산'])
    expect(renderBrief(item)).not.toContain('qualification-supply-brief')
    const detail = renderToStaticMarkup(<EligibilityDetails notice={item} profile={jeju} onProfile={() => {}} />)
    expect(detail.match(/class="qualification-source-gap"/g)).toHaveLength(1)
    expect(detail).toContain('문서 형식 변환·텍스트 추출')
    expect(detail).toContain('금액표의 분기 조건 확인 필요')
    expect(detail).not.toContain('공고 조건 정리 중')
  })
})
