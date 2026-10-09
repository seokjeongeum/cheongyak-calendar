import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { residenceArea } from './competition'
import { NoticeRegionDecision } from './EligibilityDetails'
import { applicantRegionEligibility, regionDecision } from './qualification'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'

const hash = '09d15961d3307e8c0fb398bd3d60fc7818e441e18f907afc0b77bd273a832600'
const url = 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000471&pblancNo=2026000471&atchmnflSeqNo=1995080&atchmnflSn=3'
const districts = [['12210', '동구'], ['12240', '서구'], ['12270', '남구'], ['12300', '북구'], ['12330', '광산구']]
function notice(mappingHash = hash): Notice {
  const scope: NoticeRule = {
    kind: 'applicant_regions', effect: 'metadata', verification: 'official', scope_complete: true,
    document_hash: hash, criterion_date: '2026-10-08', evidence_url: url,
    regions: [{ region_code: '12', region_name: '전남광주통합특별시' }],
    source_regions: [{ region_code: '29', region_name: '기존 광주광역시' }, { region_code: '46', region_name: '기존 전라남도' }],
    priority_applicable: true,
    local_priority: {
      region_code: '29', region_name: '기존 광주광역시', min_months: 12,
      regions: districts.map(([region_code, name]) => ({ region_code, region_name: `전남광주통합특별시 ${name}` })),
      mapping_evidence: { document_hash: mappingHash, evidence_url: url, evidence_page: 1, evidence_text: '전남광주통합특별시 북구 서구 남구 동구 광산구 → 기존 광주광역시' },
    },
  }
  return { id: 'official-merged-territory', title: '한양립스 에듀포레(조합원 취소분)', category: 'apt', source: 'cheongyak_home', provider: '공급기관', address: null, region_code: null, region_name: null, announcement_date: '2026-10-08', official_url: url, document_hash: hash, price_cap_status: 'no', events: [], prices: [], rules: [scope], updated_at: null, version: 1 }
}
const profile = (part: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, region: '전남광주통합특별시', regionCode: '12', district: '동구', districtCode: '12210', movedInDate: '2023-01-01', districtMovedInDate: '2023-01-01', ...part })

describe('the exact official former-territory crosswalk', () => {
  it.each(districts)('recognizes mapped district %s with a sufficient continuous stay', (districtCode, district) => {
    const person = profile({ district, districtCode })
    expect(applicantRegionEligibility(notice(), person)?.status).toBe('pass')
    expect(regionDecision(notice(), person).status).toBe('local')
    expect(residenceArea(notice(), person)).toBe('local')
  })
  it('admits a former Jeonnam county without extending former Gwangju priority to it', () => {
    const person = profile({ district: '진도군', districtCode: '12860' })
    expect(applicantRegionEligibility(notice(), person)?.status).toBe('pass')
    expect(regionDecision(notice(), person).status).toBe('other')
    expect(residenceArea(notice(), person)).toBe('other')
  })
  it('asks for the district when the province alone cannot establish former-territory priority', () => {
    const result = regionDecision(notice(), profile({ district: '', districtCode: '' }))
    expect(result.status).toBe('missing_input')
    expect(result.reasons.some((reason) => reason.profileField === 'districtCode')).toBe(true)
  })
  it('does not assume a short stay in one district disproves a longer stay across the mapped union', () => {
    const person = profile({ districtMovedInDate: '2026-09-01' })
    const result = regionDecision(notice(), person)
    expect(result.status).toBe('source_gap')
    expect(result.reasons.some((reason) => reason.category === 'past_fact' && reason.detail.includes('여러 구 사이의 이동 전 기간'))).toBe(true)
    expect(result.reason).not.toContain('선택한 거주지와 공식 신청 지역 조건이 다릅니다')
    const html = renderToStaticMarkup(NoticeRegionDecision({ notice: notice(), profile: person, onProfile: () => {} }))
    expect(html).toContain('과거 거주 이력 확인 필요')
    expect(html).not.toContain('선택한 거주지와 공식 신청 지역 조건이 다릅니다')
    expect(html).not.toContain('공식 해당지역 연속 거주 이력 입력하기')
  })
  it('keeps a proven applicant outside the official union outside', () => {
    const person = profile({ region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590' })
    expect(regionDecision(notice(), person).status).toBe('outside')
  })
  it('rejects a crosswalk whose file hash differs from the current regional source', () => {
    expect(regionDecision(notice('changed-document'), profile()).status).toBe('source_gap')
  })
  it('does not award a 25-year military local exception without its official recommendation fact', () => {
    const item = notice()
    item.rules[0] = { ...item.rules[0], regions: [{ region_code: '41', region_name: '경기도' }, { region_code: '11', region_name: '서울특별시' }, { region_code: '28', region_name: '인천광역시' }], local_priority: { region_code: '28', region_name: '인천광역시', min_months: 0 }, exceptions: [
      { kind: 'military_service_years', min_years: 10, currently_serving: true, residence_area: 'other' },
      { kind: 'military_service_years', min_years: 25, currently_serving: true, residence_area: 'local', recommendation_required: true, recommendation_authority: '국방부(국군복지단)' },
    ] }
    const person = profile({ region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590', militaryCurrentlyServing: true, militaryServiceYears: '25', factChanges: { military: { mode: 'never_changed', date: '' } } })
    const result = regionDecision(item, person)
    expect(result.status).toBe('source_gap')
    expect(result.reason).toContain('국방부(국군복지단) 추천')
    expect(regionDecision(item, { ...person, militaryServiceYears: '10' }).status).toBe('other')
  })
})
