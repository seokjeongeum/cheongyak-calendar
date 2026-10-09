import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { NoticeCard } from './App'
import { EMPTY_PROFILE, type LocalProfile, type Notice } from './types'

const profile: LocalProfile = { ...EMPTY_PROFILE, region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590', movedInDate: '2020-01-01', dateOfBirth: '1990-01-01' }
const notice: Notice = {
  id: 'fold-card', title: '더샵 동인센트리체', category: 'apt', housing_kind: 'private', source: 'cheongyak_home', provider: '공식 공급기관', address: '대구광역시 중구', region_code: '27', region_name: '대구광역시', announcement_date: '2026-10-02', official_url: 'https://www.applyhome.co.kr/official', price_cap_status: 'no', updated_at: null, version: 1,
  events: [{ kind: 'first_priority', label: '1순위', start_date: '2026-10-13', end_date: '2026-10-13' }],
  prices: [{ unit_type: '084', price_kind: 'sale', amount_krw: 588000000, verification: 'official' }],
  rules: [{ kind: 'applicant_regions', effect: 'metadata', regions: [{ region_code: '27', region_name: '대구광역시' }, { region_code: '47', region_name: '경상북도' }], scope_complete: true, exceptions: [], verification: 'official', evidence_url: 'https://www.applyhome.co.kr/official' }], rules_complete: true,
}
const render = (item: Notice, person = profile) => renderToStaticMarkup(<NoticeCard notice={item} profile={person} demoMode={false} today="2026-10-09" viewStart="2026-10-09" viewEnd="2026-10-31" decision={{ area: 'unknown', closedUnits: [], reason: null }} now={Date.parse('2026-10-09T01:00:00Z')} onProfile={() => {}} />)

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
    expect(preview).not.toContain('price-row')
    expect(html).toContain('5억 8,800만원')
    expect(html).toContain('접수 일정·가격·근거 펼치기')
  })

  it('keeps incomplete personal facts expanded rather than marking them unavailable', () => {
    const html = render({ ...notice, rules: [{ kind: 'age_min', value: 19, verification: 'official' }] }, EMPTY_PROFILE)
    expect(html.match(/<details class="notice-content-fold"[^>]*>/)?.[0]).toContain('open=""')
    expect(html).not.toContain('data-collapsible="true"')
    expect(html).not.toContain('notice-card notice-unavailable')
  })

  it('uses an apartment-name search and retains the numbered phase in the external link', () => {
    const html = render({ ...notice, title: '천안 아이파크 시티 2단지(2회차)' })
    expect(html).toContain(`https://hogangnono.com/search?q=${encodeURIComponent('천안 아이파크 시티 2단지')}`)
    expect(html).toContain('rel="noopener noreferrer"')
  })
})
