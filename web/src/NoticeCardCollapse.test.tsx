import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { NoticeCard } from './App'
import { evaluateNotice, type NoticeEvaluation } from './evaluation'
import type { EligibilityReason } from './eligibility'
import { EMPTY_PROFILE, type LocalProfile, type Notice } from './types'

const profile: LocalProfile = { ...EMPTY_PROFILE, region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590', movedInDate: '2020-01-01', dateOfBirth: '1990-01-01' }
const notice: Notice = {
  id: 'fold-card', title: '더샵 동인센트리체', category: 'apt', housing_kind: 'private', source: 'cheongyak_home', provider: '공식 공급기관', address: '대구광역시 중구', region_code: '27', region_name: '대구광역시', announcement_date: '2026-10-02', official_url: 'https://www.applyhome.co.kr/official', price_cap_status: 'no', updated_at: null, version: 1,
  events: [{ kind: 'first_priority', label: '1순위', start_date: '2026-10-13', end_date: '2026-10-13' }],
  prices: [{ unit_type: '084', price_kind: 'sale', amount_krw: 588000000, verification: 'official' }],
  rules: [{ kind: 'applicant_regions', effect: 'metadata', regions: [{ region_code: '27', region_name: '대구광역시' }, { region_code: '47', region_name: '경상북도' }], scope_complete: true, exceptions: [], verification: 'official', evidence_url: 'https://www.applyhome.co.kr/official' }], rules_complete: true,
}
const render = (item: Notice, person = profile, evaluation?: NoticeEvaluation) => renderToStaticMarkup(<NoticeCard notice={item} profile={person} demoMode={false} today="2026-10-09" viewStart="2026-10-09" viewEnd="2026-10-31" decision={{ area: 'unknown', closedUnits: [], reason: null }} now={Date.parse('2026-10-09T01:00:00Z')} onProfile={() => {}} evaluation={evaluation} />)

describe('whole notice default disclosure', () => {
  it('keeps an outside-region notice compact with official data inside a closed disclosure', () => {
    const html = render(notice)
    const disclosure = html.match(/<details class="notice-content-fold"[^>]*>/)?.[0]
    expect(disclosure).toContain('data-collapsible="true"')
    expect(disclosure).not.toContain('open=')
    const preview = html.split('<details')[0]
    expect(preview).toContain('더샵 동인센트리체')
    expect(preview).toContain('대구광역시 중구')
    expect(preview).toContain('내 조건으로 신청 불가')
    expect(preview).toContain('https://www.applyhome.co.kr/official')
    expect(preview).toContain('호갱노노')
    expect(preview).toContain('aria-label="신청 불가 이유"')
    expect(preview).toContain('신청 가능한 지역')
    expect(preview).toContain('내 거주지 경기도 화성시는 이 공고의 대구광역시 · 경상북도 신청 범위 밖입니다.')
    expect(preview).not.toContain('price-row')
    expect(html).toContain('5억 8,800만원')
    expect(html).toContain('접수 일정·가격·근거 펼치기')
  })

  it('keeps incomplete personal facts expanded rather than marking them unavailable', () => {
    const html = render({ ...notice, rules: [{ kind: 'age_min', value: 19, verification: 'official' }] }, EMPTY_PROFILE)
    expect(html.match(/<details class="notice-content-fold"[^>]*>/)?.[0]).toContain('open=""')
    expect(html).not.toContain('data-collapsible="true"')
    expect(html).not.toContain('notice-card notice-unavailable')
    expect(html.split('<details')[0]).not.toContain('신청 불가 이유')
  })

  it('shows distinct factual mismatches before the fold without repeating source paragraphs', () => {
    const evaluation = evaluateNotice(notice, profile, '2026-10-09', Date.parse('2026-10-09T01:00:00Z'))
    const first: EligibilityReason = { status: 'fail', category: 'condition', label: '부모 만 나이', detail: '내 입력 60세 · 공고 요구 >= 65세', evidenceText: '첫 번째 인용' }
    const facts: EligibilityReason[] = [first, { ...first, evidenceText: '다른 주택형의 같은 조항' },
      { status: 'fail', category: 'condition', label: '미성년 자녀 수', detail: '내 입력 0명 · 공고 요구 >= 2명' },
      { status: 'fail', category: 'condition', label: '혼인 상태', detail: '입력 미혼 · 인정 혼인 중' },
      { status: 'fail', category: 'condition', label: '기관 추천', detail: '추천 대상에 해당하지 않는다고 입력했습니다.' },
      { status: 'review', category: 'source_gap', label: '공고 조항', detail: '서비스가 원문 검토를 완료하지 못했습니다.' }]
    const html = render(notice, profile, { ...evaluation, summary: { status: 'mismatch', reasons: facts }, supplies: [] })
    const preview = html.split('<details')[0]
    expect(preview.match(/내 입력 60세/g)).toHaveLength(1)
    expect(preview).toContain('내 입력 0명 · 공고 요구 &gt;= 2명')
    expect(preview).toContain('입력 미혼 · 인정 혼인 중')
    expect(preview).toContain('외 1개 불일치 · 펼쳐서 확인')
    expect(preview).not.toContain('추천 대상에 해당하지')
    expect(preview).not.toContain('원문 검토를 완료하지')
    expect(html.match(/<details class="notice-content-fold"[^>]*>/)?.[0]).not.toContain('open=')
  })

  it('shows the verified competition closure reason while leaving its source proof in the fold', () => {
    const evaluation = evaluateNotice(notice, profile, '2026-10-09', Date.parse('2026-10-09T01:00:00Z'))
    const reason = '기타지역 1순위 · 모든 일반공급 주택형이 해당지역 1순위에서 마감됐습니다.'
    const html = render(notice, profile, { ...evaluation, summary: { status: 'review', reasons: [] }, supplies: [],
      decision: { area: 'other', closedUnits: ['084'], allApplicationsUnavailable: true, reason } })
    const preview = html.split('<details')[0]
    expect(preview).toContain('기타지역 배정 기회 종료')
    expect(preview).toContain(reason)
    expect(html.match(/<details class="notice-content-fold"[^>]*>/)?.[0]).not.toContain('open=')
  })

  it('keeps a mixed notice expanded when a supply remains possible', () => {
    const item: Notice = { ...notice, rules: [
      { kind: 'age_min', value: 19, verification: 'official', supply_type: '일반공급' },
      { kind: 'recommendation', value: true, verification: 'official', supply_type: '기관추천 특별공급' },
      { kind: 'offered_supplies', effect: 'metadata', verification: 'official', supplies: [
        { unit_type: '084', supply_type: '일반공급', supply_count: 2, verification: 'official' },
        { unit_type: '084', supply_type: '기관추천 특별공급', supply_count: 1, verification: 'official' },
      ] },
    ] }
    const person: LocalProfile = { ...profile, recommendationStatus: 'none' }
    const evaluation = evaluateNotice(item, person, '2026-10-09', Date.parse('2026-10-09T01:00:00Z'))
    expect(evaluation.summary.status).toBe('possible')
    expect(evaluation.supplies.some((supply) => supply.result.status === 'mismatch')).toBe(true)
    const html = render(item, person, evaluation)
    expect(html.match(/<details class="notice-content-fold"[^>]*>/)?.[0]).toContain('open=""')
    expect(html.split('<details')[0]).not.toContain('신청 불가 이유')
  })

  it('uses the verified detail page for the numbered phase', () => {
    const html = render({ ...notice, title: '천안 아이파크 시티 2단지(2회차)' })
    expect(html).toContain('https://hogangnono.com/apt/ghL9c')
    expect(html).toContain('rel="noopener noreferrer"')
  })
})
