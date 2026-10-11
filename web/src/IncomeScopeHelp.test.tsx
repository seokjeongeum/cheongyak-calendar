import { readFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { IncomeScopeHelp, incomeScopeSources } from './IncomeScopeHelp'
import type { Notice, NoticeRule } from './types'

const fixture = JSON.parse(readFileSync(new URL('../../api/tests/fixtures/hyangnam-regional-v9.json', import.meta.url), 'utf8')) as {
  document_hash: string; document_url: string; payload: { title: string; announcement_date: string; official_url: string }; pages: { page: number; text: string }[]
}
const familyFixture = (JSON.parse(readFileSync(new URL('../../api/tests/fixtures/public-v5.json', import.meta.url), 'utf8')) as typeof fixture[])
  .find(item => item.pages.some(page => page.text.includes('<가구원수 적용 기준>')))!
const notice = (rules: NoticeRule[], extra: Partial<Notice> = {}): Notice => ({
  id: 'income-notice', title: '공식 소득 공고', category: 'apt', source: 'applyhome', provider: '공식 기관',
  address: null, region_code: null, region_name: null, announcement_date: '2026-10-02', official_url: 'https://example.org/notice',
  price_cap_status: 'unknown', events: [], prices: [], rules, updated_at: null, version: 1, ...extra,
})
const income = (extra: Partial<NoticeRule> = {}): NoticeRule => ({ kind: 'monthly_income_max_krw', verification: 'official', supply_type: '생애최초 특별공급', min_household_size: 3, ...extra })
const render = (items: Notice[]) => renderToStaticMarkup(<IncomeScopeHelp notices={items} />)

describe('income household scope explanation', () => {
  it('explains the actual count, separate income-sum scope and table bands without another confirmation', () => {
    const html = render([])
    expect(html).toContain('신청자를 포함해 공고가 인정하는 가족')
    expect(html).toContain('배우자는 등본이 분리되어 있어도')
    expect(html).toContain('주택 보유 확인 가족 수와 청약가점의 부양가족 수')
    expect(html).toContain('소득이 없는 자녀도 가구원 수에는 포함될 수')
    expect(html).toContain('2인 가구는 2명을 입력')
    expect(html).toContain('현재 공고 자료에서 공식 소득 산정 가족 범위를 확보하지 못했습니다')
    expect(html).not.toContain('<input')
    expect(html).not.toContain('확인했나요')
  })

  it('uses the current official scope paragraph and its page, without a project catalog', () => {
    const paragraph = fixture.pages.find(page => page.page === 22)!
    const scope: NoticeRule = { kind: 'income_household_scope', verification: 'official', supply_type: '생애최초 특별공급', document_hash: fixture.document_hash,
      evidence_text: paragraph.text, evidence_url: fixture.document_url, evidence_page: paragraph.page }
    const row = notice([income({ document_hash: fixture.document_hash }), scope], fixture.payload)
    const source = incomeScopeSources([row])[0]
    const original = fixture.pages.find((page) => page.page === source.page)!.text.replace(/\s+/g, ' ')
    expect(incomeScopeSources([row])).toHaveLength(1)
    expect(source.page).toBe(22)
    expect(source.url).toBe(fixture.document_url)
    expect(original).toContain(source.scope)
    expect(original).toContain(source.income)
    const html = render([row])
    expect(html).toContain('향남역 그로브 스위첸')
    expect(html).toContain('생애최초 특별공급 · 기준일 2026-10-02')
    expect(html).toContain('최근 1년 이상 계속하여')
    expect(html).toContain('태아는 태아 수만큼 인정')
    expect(html).toContain('만19세 이상인 성년자')
    expect(html).toContain('#page=22')
    expect(render([notice([income({ document_hash: fixture.document_hash })], fixture.payload)])).not.toContain('최근 1년 이상 계속하여')
    const corrected = notice([income({ document_hash: 'corrected-document' }), scope], { ...fixture.payload, document_hash: 'corrected-document' })
    expect(render([corrected])).not.toContain('최근 1년 이상 계속하여')
  })

  it('preserves the actual shared family-scope table and its family labels', () => {
    const paragraph = familyFixture.pages.find(page => page.text.includes('<가구원수 적용 기준>'))!
    const supplies = ['신혼부부(신혼희망타운)', '예비신혼부부(신혼희망타운)', '한부모가족(신혼희망타운)']
    const rules = supplies.flatMap(supply => [
      income({ kind: 'shinhee_income', document_hash: familyFixture.document_hash, supply_type: supply }),
      { kind: 'income_household_scope', verification: 'official', document_hash: familyFixture.document_hash, supply_type: supply,
        evidence_text: paragraph.text, evidence_url: familyFixture.document_url, evidence_page: paragraph.page },
    ])
    const sources = incomeScopeSources([notice(rules, familyFixture.payload)])
    expect(sources).toHaveLength(1)
    expect(sources[0].supplies).toEqual(supplies)
    expect(sources[0].scope).toContain('주민등록표등본에 등재되지 아니한')
    expect(sources[0].scope).toContain('예비신혼부부 청약 시 제출한 ‘혼인으로 구성될 세대’')
    expect(sources[0].income).toContain('만 19세 이상 무주택세대구성원 전원의 합산 소득')
    expect(sources[0].url).toBe(familyFixture.document_url)
    expect(sources[0].page).toBe(paragraph.page)
  })

  it('generalizes the same source clauses across new names, document hashes, URLs and page positions', () => {
    const paragraph = fixture.pages.find(page => page.page === 22)!
    const variants = [
      { title: fixture.payload.title, hash: fixture.document_hash, url: fixture.document_url, page: 22 },
      { title: '새봄신도시 새 공고', hash: 'brand-new-document-hash', url: 'https://example.org/new-application.pdf', page: 91 },
    ]
    for (const variant of variants) {
      const row = notice([
        income({ document_hash: variant.hash, criterion_date: '2027-02-03' }),
        { kind: 'income_household_scope', verification: 'official', supply_type: '생애최초 특별공급', document_hash: variant.hash,
          criterion_date: '2027-02-03', evidence_text: paragraph.text, evidence_url: variant.url, evidence_page: variant.page },
      ], { title: variant.title, document_hash: variant.hash, announcement_date: '2027-02-03' })
      const sources = incomeScopeSources([row])
      expect(sources).toHaveLength(1)
      expect(sources[0].scope).toContain('최근 1년 이상 계속하여')
      expect(sources[0].income).toContain('만19세 이상인 성년자')
      expect(sources[0].minimumTableSize).toBe(3)
      const html = render([row])
      expect(html).toContain(variant.title)
      expect(html).toContain(`${variant.url}#page=${variant.page}`)
      expect(html).toContain('기준일 2027-02-03')
    }
  })

  it('does not borrow a different supply or cutoff scope for an income ceiling', () => {
    const rule = income({ document_hash: 'current-document', criterion_date: '2027-02-03' })
    const unrelated: NoticeRule[] = [
      { kind: 'income_household_scope', verification: 'official', supply_type: '신혼부부 특별공급', document_hash: 'current-document', criterion_date: '2027-02-03', household_scope: '다른 유형 가족 범위' },
      { kind: 'income_household_scope', verification: 'official', supply_type: '생애최초 특별공급', document_hash: 'current-document', criterion_date: '2026-02-03', household_scope: '과거 공고 가족 범위' },
    ]
    const sources = incomeScopeSources([notice([rule, ...unrelated])])
    expect(sources.find(source => source.date === '2027-02-03' && source.supplies.includes('생애최초 특별공급'))?.scope).toBe('')
  })

  it('reads actual scope metadata and document paragraphs while rejecting unverified evidence', () => {
    const rule = income({ household_scope: { evidence_text: '신청자와 배우자, 공고의 자녀를 포함합니다.' }, income_sum_scope: '공고가 정한 성년자 소득의 합계', household_scope_evidence_url: 'https://example.org/document.pdf', household_scope_evidence_page: 7, criterion_date: '2026-09-30' })
    const html = render([notice([rule])])
    expect(html).toContain('신청자와 배우자, 공고의 자녀를 포함합니다.')
    expect(html).toContain('공고가 정한 성년자 소득의 합계')
    expect(html).toContain('기준일 2026-09-30')
    expect(html).toContain('https://example.org/document.pdf#page=7')
    expect(render([notice([{ ...rule, verification: 'ai_unverified' }])])).not.toContain('공고의 자녀를 포함합니다.')
    const raw = income({ table_evidence_text: '소득표 3인 이하 <가구원수 적용 기준> 임신 중인 태아도 태아의 수만큼 산정 <가구당 월평균소득액 산정기준> 만19세 이상 합산 소득 ■ (중요) 소득조사' })
    const source = incomeScopeSources([notice([raw])])[0]
    expect(source.scope).toBe('<가구원수 적용 기준> 임신 중인 태아도 태아의 수만큼 산정')
    expect(source.income).toBe('<가구당 월평균소득액 산정기준> 만19세 이상 합산 소득')
  })

  it('finds nested income alternatives, inherits source scope and deduplicates unit rows', () => {
    const parent: NoticeRule = { kind: 'any', verification: 'official', supply_type: '생애최초 특별공급', criterion_date: '2026-09-30', household_scope: '신청자와 공고가 정한 가족', evidence_url: 'https://example.org/scope.pdf', conditions: [income({ verification: undefined }), { kind: 'real_estate_max_krw', value: 331000000 }] }
    const sources = incomeScopeSources([notice([parent, { ...parent, unit_type: '084A' }])])
    // Child verification explicitly undefined is not official; source scope
    // belongs to a nested rule only when it is inherited or verified itself.
    expect(sources).toHaveLength(0)
    const inherited = { ...parent, conditions: [{ kind: 'monthly_income_max_krw', min_household_size: 3 }, { kind: 'real_estate_max_krw' }] }
    const verified = incomeScopeSources([notice([inherited, { ...inherited, unit_type: '084A' }])])
    expect(verified).toHaveLength(1)
    expect(verified[0].date).toBe('2026-09-30')
    expect(verified[0].scope).toBe('신청자와 공고가 정한 가족')
  })

  it('does not infer a family scope from an income ceiling and displays the exact service gap', () => {
    const html = render([notice([income({ evidence_text: '전년도 가구원수별 월평균소득의 160% 이하', household_scope: 'official_income_household', household_scope_evidence_url: 'javascript:alert(1)', evidence_url: 'javascript:alert(2)' })])])
    expect(html).toContain('서비스의 원문 검토 부족')
    expect(html).toContain('별도 등본 배우자 세대·직계존속의 합가기간·태아 포함 여부')
    expect(html).toContain('실제 인정 인원이 2명이면 입력은 2명')
    expect(html).not.toContain('href="javascript:')
    expect(html).not.toContain('official_income_household')
  })

  it('limits initial source rendering and offers the remaining deduplicated scopes on demand', () => {
    const items = Array.from({ length: 15 }, (_, index) => notice([income({ household_scope: `공식 가족 범위 ${index}` }), income({ household_scope: `공식 가족 범위 ${index}`, unit_type: '084A' })], { id: `notice-${index}`, title: `공고 ${index}` }))
    const html = render(items)
    expect((html.match(/class="income-scope-source"/g) || [])).toHaveLength(3)
    expect(html).toContain('다른 소득 산정 근거 12개 보기')
    expect(html).not.toContain('<h5>공고 14</h5>')
  })
})
