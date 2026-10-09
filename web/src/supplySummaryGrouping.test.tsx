import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { EligibilityBrief, comparedConditionsLabel } from './EligibilityDetails'
import { supplySummaries, type EligibilityReason, type EligibilityCombination } from './eligibility'
import { EMPTY_PROFILE, type Notice } from './types'
const notice: Notice = { id: 'official', title: '공고', category: 'apt', source: 'cheongyak_home', provider: '공식 기관', address: null, region_code: null, region_name: null, announcement_date: '2026-10-02', official_url: 'https://example.go.kr/doc', price_cap_status: 'unknown', events: [], prices: [], rules: [], updated_at: null, version: 1 }
const reason = (part: Partial<EligibilityReason> = {}): EligibilityReason => ({ status: 'review', category: 'missing_input', label: '특별공급 당첨 이력', detail: '실제 당첨 사건을 입력하세요.', profileField: 'applicationHistoryEvents', criterionDate: '2026-10-02', evidenceUrl: 'https://example.go.kr/doc', ...part })
const combo = (unitType: string, reasons: EligibilityReason[], status: 'review' | 'mismatch' = 'review'): EligibilityCombination => ({ supplyType: '생애최초 특별공급', unitType, result: { status, reasons } })
describe('identical supply comparisons across housing units', () => {
  it('groups identical facts despite repeated source paragraphs and preserves detailed combinations', () => {
    const combinations = [combo('074.9845', [reason({ evidenceText: '첫째 주택형 공통 요건' })]), combo('084.9947A', [reason({ evidenceText: '둘째 주택형 공통 요건' })])]
    const summaries = supplySummaries(notice, EMPTY_PROFILE, undefined, combinations)
    expect(summaries).toHaveLength(1)
    expect(summaries[0].unitTypes).toEqual(['074.9845', '084.9947A'])
    expect(combinations[1].result.reasons[0].evidenceText).toBe('둘째 주택형 공통 요건')
    const html = renderToStaticMarkup(<EligibilityBrief result={{ status: 'review', reasons: [] }} notice={notice} profile={EMPTY_PROFILE} snapshot={{ supplies: summaries } as never} onProfile={() => {}} />)
    expect(html.match(/<strong>생애최초 특별공급<\/strong>/g)).toHaveLength(1)
    expect(html).toContain('074.9845 · 084.9947A')
  })
  it('keeps different unit requirements and actual outcomes separate', () => {
    const combinations = [combo('59A', [reason({ requirement: '<= 60㎡' })]), combo('84A', [reason({ requirement: '<= 85㎡' })]), combo('104A', [{ ...reason(), status: 'fail', detail: '전용면적 제한 초과' }], 'mismatch')]
    expect(supplySummaries(notice, EMPTY_PROFILE, undefined, combinations)).toHaveLength(3)
  })
  it('counts a missing factual input once when more than one citation proves the same requirement', () => {
    expect(comparedConditionsLabel({ status: 'review', reasons: [reason({ evidenceText: '문단 A' }), reason({ evidenceText: '문단 B' })] })).toBe('내 입력 1개 필요')
  })
})
