import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { EligibilityBrief, EligibilityDetails } from './EligibilityDetails'
import { evaluateNotice } from './evaluation'
import { deriveRank, rankUnitComparisons, type EligibilityResult } from './eligibility'
import { setEvaluationToday } from './factTimeline'
import { EMPTY_PROFILE, type LocalProfile, type Notice } from './types'
import officialSources from './fixtures/private-ranking-official-v15.json'

// The fixtures retain the current official rank clauses, hashes and tables.
// Hyangnam prices also retain their exact page-8 supply-table rows; its wrapped
// numeric columns must not be replaced with inferred unit-name areas.
const sources = officialSources as unknown as Notice[]
const today = '2026-10-11', now = Date.parse(`${today}T00:00:00Z`)
const profile = (patch: Partial<LocalProfile> = {}): LocalProfile => ({
  ...EMPTY_PROFILE, region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590',
  movedInDate: '2023-01-01', accountType: 'comprehensive', accountConversionUnclear: false,
  privateRankBaseDate: '2009-07-02', privateDepositKrw: '3000000', privateDepositAsOfDate: '2026-10-02',
  factChanges: { bank_private: { mode: 'never_changed', date: '' } }, ...patch,
})
const empty: EligibilityResult = { status: 'review', reasons: [] }
beforeEach(() => setEvaluationToday(today))
afterEach(() => setEvaluationToday(null))

function render(item: Notice, facts: LocalProfile, cached = false) {
  const snapshot = cached ? evaluateNotice(item, facts, today, now) : undefined
  return {
    brief: renderToStaticMarkup(<EligibilityBrief notice={item} profile={facts} result={empty} snapshot={snapshot} onProfile={() => {}} />),
    details: renderToStaticMarkup(<EligibilityDetails notice={item} profile={facts} snapshot={snapshot} onProfile={() => {}} />),
  }
}

describe('rank explanations from current official clauses', () => {
  for (const item of sources) {
    it(`${item.title}: explains differing deposits beside the passed 207 months and account type`, () => {
      const facts = profile(), rank = deriveRank(item, facts)
      expect(rank).toMatchObject({ rank: 'unknown', label: '민영주택 1순위 확인 필요' })
      expect(rank.reasons.find((reason) => reason.label === '민영 순위 인정기간')).toMatchObject({ status: 'pass', input: '207개월' })
      expect(rank.reasons.find((reason) => reason.label === '민영주택 예치금')).toMatchObject({ category: 'selection' })
      expect(rankUnitComparisons(item, facts).some((comparison) => comparison.reasons.some((reason) => reason.status === 'fail'))).toBe(true)
      for (const cached of [false, true]) {
        const { brief, details } = render(item, facts, cached)
        const summary = brief.split('class="qualification-account-summary"')[1].split('class="qualification-unit-ranks"')[0]
        expect(summary).toContain('민영 순위 인정기간 충족')
        expect(summary).toContain('통장 종류 충족')
        expect(summary).toContain('주택형의 전용면적별 예치금 기준이 다릅니다')
        expect(summary).toContain('그 밖의 지역 · &gt;= 2,000,000원')
        expect(summary).toContain('불일치 · 민영주택 예치금: 그 밖의 지역 · &gt;= 5,000,000원')
        expect(summary).toContain('내 입력 3,000,000원')
        expect(summary).not.toContain('충족 · 통장 종류:')
        const section = details.split('qualification-rank-section')[1].split('</section>')[0]
        expect(section).toContain('민영주택 1순위 확인 필요')
        expect(section).toContain('추가 확인 필요 · 민영주택 예치금')
        expect(section).toContain('면적별 청약통장 조건')
        expect(section).toContain('불일치 · 민영주택 예치금')
        expect(section).toContain(item.prices.at(-1)!.unit_type)
        expect(section.match(/충족 · 통장 종류/g)).toHaveLength(1)
      }
    })
  }

  it('connects an empty common deposit to one input while retaining every area-tier amount', () => {
    const { brief } = render(sources[0], profile({ privateDepositKrw: '' }))
    const summary = brief.split('class="qualification-account-summary"')[1].split('class="qualification-unit-ranks"')[0]
    expect(summary.match(/민영주택 예치금 입력하기/g)).toHaveLength(1)
    expect(summary).toContain('내 입력 부족 · 민영주택 예치금')
    for (const amount of ['2,000,000원', '4,000,000원', '5,000,000원']) expect(summary).toContain(amount)
  })

  it('confirms rank without a unit-selection question only when every actual unit passes its own official tier', () => {
    for (const item of sources) {
      const facts = profile({ privateDepositKrw: '6000000' })
      expect(deriveRank(item, facts)).toMatchObject({ rank: 'first', status: 'possible' })
      const { brief, details } = render(item, facts, true)
      const summary = brief.split('class="qualification-account-summary"')[1].split('class="qualification-supply-overview"')[0]
      expect(summary).toContain('민영주택 1순위 조건 충족')
      expect(summary).not.toContain('qualification-account-pending')
      expect(details).toContain('면적별 청약통장 조건')
      expect(deriveRank(item, profile({ privateDepositKrw: '4000000' })).rank).toBe('unknown')
      expect(deriveRank({ ...item, prices: item.prices.map((price, index) => index === item.prices.length - 1 ? { ...price, exclusive_area_sqm: null } : price) }, facts).rank).toBe('unknown')
      const missingUnit = { ...item, offered_supplies: [{ supply_type: '일반공급', unit_type: 'missing-official-unit', supply_count: 1, verification: 'official' as const }] }
      expect(deriveRank(missingUnit, facts).rank).toBe('unknown')
    }
  })

  it('shows the actual missing official exclusive area next to the rank label rather than only passing facts', () => {
    const item = { ...sources[0], prices: sources[0].prices.map((price) => ({ ...price, exclusive_area_sqm: null })) }
    const { brief, details } = render(item, profile())
    expect(deriveRank(item, profile()).rank).toBe('unknown')
    const summary = brief.split('class="qualification-account-summary"')[1].split('class="qualification-unit-ranks"')[0]
    expect(summary).toContain('서비스 원문 검토 부족 · 민영주택 예치금')
    expect(summary).toContain('공식 전용면적을 확인해야 예치금 표와 비교')
    expect(details.match(/서비스 원문 검토 부족 · 민영주택 예치금/g)).toHaveLength(1)
    const section = details.split('qualification-rank-section')[1].split('</section>')[0]
    expect(section).toContain('공급면적을 대신 사용하지 않습니다')
  })

  it('reuses the existing deposit history input once and does not claim today is an older balance', () => {
    const facts = profile({ factChanges: {}, privateDepositAsOfDate: today })
    const { brief } = render(sources[0], facts)
    const summary = brief.split('class="qualification-account-summary"')[1].split('class="qualification-unit-ranks"')[0]
    expect(summary).toContain('과거 사실 미확인')
    expect(summary.match(/민영 통장 잔액 변경일 입력하기/g)).toHaveLength(1)
    expect(deriveRank(sources[0], facts).rank).toBe('unknown')
  })

  it('generalizes to another name, hash, date, URL, unit labels and deposit amounts', () => {
    const cutoff = '2026-10-10', url = 'https://official.example/new-apartment.pdf', hash = 'f'.repeat(64)
    const item: Notice = { ...sources[0], id: 'future-source', title: '새 공고', announcement_date: cutoff, official_url: url,
      document_hash: hash, prices: [{ unit_type: 'new-small', exclusive_area_sqm: 80, price_kind: 'sale_max' }, { unit_type: 'new-large', exclusive_area_sqm: 120, price_kind: 'sale_max' }],
      rules: sources[0].rules.map((rule) => ({ ...rule, criterion_date: cutoff, document_hash: hash, evidence_url: url,
        ...(rule.kind === 'deposit_min_krw' ? { deposit_table: [{ max_area_sqm: 90, amounts_krw: { seoul_busan: 3700000, other_metropolitan: 3500000, other: 3100000 } }, { max_area_sqm: null, amounts_krw: { seoul_busan: 6800000, other_metropolitan: 6300000, other: 6100000 } }] } : {}) })),
    }
    const facts = profile({ privateDepositKrw: '3500000', privateDepositAsOfDate: cutoff })
    const { brief, details } = render(item, facts, true)
    expect(brief).toContain('3,100,000원')
    expect(brief).toContain('6,100,000원')
    expect(brief).toContain('new-small')
    expect(brief).toContain('new-large')
    expect(details).toContain(url)
    expect(details).toContain(cutoff)
    expect(details).not.toContain('2026000468')
    expect(deriveRank(item, facts, 'new-small').rank).toBe('first')
    expect(deriveRank(item, facts, 'new-large')).toMatchObject({ rank: 'unknown', status: 'mismatch' })
  })

  it('explains an unknown rank by its actual failed document stage and missing item', () => {
    const url = 'https://city.example/new-notice'
    const diagnostic = { kind: 'document_diagnostics', effect: 'metadata', verification: 'official' as const, diagnostics: [
      { stage: 'discovery', status: 'resolved', message: '이전 실패 문구', evidence_url: url },
      { stage: 'discovery', status: 'error', code: 'official_page_failed', message: '공식 공고 페이지 응답 503', evidence_url: url, missing_items: ['현재 모집공고문의 첨부 주소'] },
    ] }
    const item: Notice = { ...sources[0], category: 'public_rental', housing_kind: 'unknown', housing_kind_evidence: undefined, rules: [diagnostic], prices: [], official_url: url }
    expect(deriveRank(item, profile())).toMatchObject({ rank: 'unknown', reasons: [{
      category: 'source_gap', detail: '공고문 찾기 · 공식 공고 페이지 응답 503 미확보 항목: 현재 모집공고문의 첨부 주소', evidenceUrl: url,
    }] })
    const { brief, details } = render(item, profile(), true)
    expect(brief).toContain('공식 공고 페이지 응답 503')
    expect(details.split('qualification-rank-section')[1].split('</section>')[0]).toContain('현재 모집공고문의 첨부 주소')
    expect(brief).not.toContain('이전 실패 문구')
    expect(brief).not.toContain('통장 종류 입력하기')
  })
})
