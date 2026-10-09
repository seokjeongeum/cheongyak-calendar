import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { EligibilityBrief, EligibilityDetails } from './EligibilityDetails'
import { beginEvaluationRevision, eligibilityCombinations, noticeEligibilitySummary } from './eligibility'
import { setEvaluationToday } from './factTimeline'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'

const evidence = 'https://www.applyhome.co.kr/official/notice.pdf'
const rule = (kind: string, value: NoticeRule['value'], supply_type?: string): NoticeRule => ({ kind, value, supply_type, verification: 'official', evidence_url: evidence, evidence_text: '공식 원문의 신청 조건' })
const notice = (rules: NoticeRule[] = [rule('age_min', 19, '일반공급'), rule('parent_age_min', 65, '노부모부양 특별공급')]): Notice => ({
  id: 'collapse', title: '공식 모집공고', category: 'apt', source: 'cheongyak_home', provider: '공급기관', address: null, region_code: null, region_name: null,
  announcement_date: '2026-10-08', official_url: evidence, price_cap_status: 'no', events: [], prices: [], rules, rules_complete: true,
  offered_supplies: [{ supply_type: '일반공급', unit_type: '084', supply_count: 12, verification: 'official' }, ...['074', '084'].map((unit_type) => ({ supply_type: '노부모부양 특별공급', unit_type, supply_count: 1, verification: 'official' as const }))], updated_at: null, version: 1,
})
const profile = (patch: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, dateOfBirth: '1990-01-01', parentDateOfBirth: '1966-01-01', ...patch })
const collapsed = (html: string): string[] => [...html.matchAll(/<details class="[^"]*qualification-supply-collapse">[\s\S]*?<\/details>/g)].map((match) => match[0]!)
const brief = (item: Notice, person: LocalProfile) => renderToStaticMarkup(<EligibilityBrief notice={item} profile={person} result={noticeEligibilitySummary(item, person)} onProfile={() => {}} />)
const detailed = (item: Notice, person: LocalProfile) => renderToStaticMarkup(<EligibilityDetails notice={item} profile={person} onProfile={() => {}} />)

beforeEach(() => { setEvaluationToday('2026-10-09'); beginEvaluationRevision() })
afterEach(() => setEvaluationToday(null))

describe('failed supply paths are initially collapsed', () => {
  it('keeps the brief name, outcome and offered units visible while hiding failure evidence by default', () => {
    const item = notice(), person = profile()
    expect(eligibilityCombinations(item, person).map((scope) => scope.result.status)).toEqual(['possible', 'mismatch', 'mismatch'])
    const html = brief(item, person), failed = collapsed(html)
    expect(failed).toHaveLength(1)
    expect(failed[0].split('>')[0]).not.toMatch(/\bopen\b/)
    const summary = failed[0].split('</summary>')[0]
    expect(summary).toContain('노부모부양 특별공급')
    expect(summary).toContain('내 조건으로 신청 불가')
    expect(summary).toContain('074 · 모집 1세대 / 084 · 모집 1세대')
    expect(summary).not.toContain('불일치 · 부모 만 나이')
    expect(failed[0].split('</summary>')[1]).toContain('불일치 · 부모 만 나이')
    expect(failed[0]).toContain('60세')
    expect(failed[0]).toContain('&gt;= 65세')
    expect(failed[0]).toContain(`href="${evidence}"`)
    expect(html).toContain('<section class="qualification-supply-brief qualification-possible"')
    expect(html.replace(failed[0], '')).not.toContain('불일치 · 부모 만 나이')
  })

  it('also collapses detailed failure paths and keeps possible supply details open', () => {
    const html = detailed(notice(), profile()), failed = collapsed(html)
    expect(failed).toHaveLength(1)
    expect(failed[0].split('>')[0]).not.toMatch(/\bopen\b/)
    expect(failed[0].split('</summary>')[0]).toContain('074 · 084')
    expect(failed[0].split('</summary>')[1]).toContain('불일치 · 부모 만 나이')
    expect(failed[0]).toContain(`href="${evidence}"`)
    expect(html).toContain('<section class="qualification-section qualification-supply"><div class="qualification-section-head"><h5>일반공급')
    expect(html.replace(failed[0], '')).not.toContain('불일치 · 부모 만 나이')
  })

  it('leaves incomplete supply paths expanded instead of treating missing input as failure', () => {
    const item = notice(), person = profile({ parentDateOfBirth: '' })
    expect(collapsed(brief(item, person))).toHaveLength(0)
    const html = detailed(item, person)
    expect(collapsed(html)).toHaveLength(0)
    expect(html).toContain('<h5>노부모부양 특별공급')
    expect(html).toContain('부모 만 나이 입력하기')
  })

  it('retains the blocking common fact inside each expanded failure even after common evidence deduplication', () => {
    const item = notice([rule('age_min', 40), rule('age_min', 19, '일반공급'), rule('parent_age_min', 65, '노부모부양 특별공급')])
    const person = profile({ parentDateOfBirth: '1950-01-01' })
    for (const render of [brief, detailed]) {
      const failed = collapsed(render(item, person))
      expect(failed).toHaveLength(2)
      expect(failed.every((section) => section.split('</summary>')[1].includes('불일치 · 공고 기준 만 나이'))).toBe(true)
      expect(failed.reduce((expanded, section) => expanded.replace(section, ''), render(item, person))).not.toContain('불일치 · 공고 기준 만 나이')
    }
  })

  it('keeps official selection closure evidence in a collapsed general path', () => {
    const item = notice(), person = profile(), decision = { area: 'other' as const, closedUnits: ['084'], reason: null }
    const html = renderToStaticMarkup(<EligibilityBrief notice={item} profile={person} decision={decision} result={noticeEligibilitySummary(item, person, decision)} onProfile={() => {}} />)
    const general = collapsed(html).find((section) => section.split('</summary>')[0].includes('일반공급'))!
    expect(general).toContain('기타지역 1순위 접수 마감')
    expect(general).toContain('접수가 종료')
  })
})
