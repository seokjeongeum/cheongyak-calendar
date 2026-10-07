import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { demoNotices } from './demo'
import { selectionOpportunity } from './opportunity'
import { OpportunityPanel } from './OpportunityPanel'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule, type OfferedSupply } from './types'
import { setEvaluationToday } from './factTimeline'

setEvaluationToday('2026-10-07')
const source = 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000468&pblancNo=2026000468&atchmnflSeqNo=1990183&atchmnflSn=2'
const special = ['기관추천 특별공급', '다자녀가구 특별공급', '신혼부부 특별공급', '노부모부양 특별공급', '생애최초 특별공급', '신생아 특별공급']
// Positive supply counts from the official Hangang document, page 5. In
// particular, 123㎡ has only 다자녀/노부모 special supply; 146㎡ has none.
const inventory = [
  ['074.9845', [7, 7, 10, 2, 5, 7, 32]],
  ['084.9947A', [15, 14, 22, 4, 10, 15, 69]],
  ['084.8542B', [4, 4, 6, 1, 3, 4, 18]],
  ['084.8894C', [3, 4, 6, 1, 2, 3, 18]],
  ['123.7781', [0, 4, 0, 1, 0, 0, 30]],
  ['146.8598P', [0, 0, 0, 0, 0, 0, 2]],
] as const
const offered: OfferedSupply[] = inventory.flatMap(([unit, counts]) => [...special, '일반공급'].map((supply, i) => ({ supply_type: supply, unit_type: unit, supply_count: counts[i], verification: 'official', evidence_url: source })))
const regions: NoticeRule = { kind: 'applicant_regions', effect: 'metadata', verification: 'official', criterion_date: '2026-10-02', evidence_url: source, regions: [{ region_code: '41', region_name: '경기도' }, { region_code: '11', region_name: '서울특별시' }, { region_code: '28', region_name: '인천광역시' }], local_priority: { region_code: '41830', region_name: '경기도 양평군', min_months: 0 }, priority_division: 'regional' }
const profile = (extra: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, region: '서울특별시', regionCode: '11', district: '강남구', districtCode: '11680', movedInDate: '2010-01-01', cityMovedInDate: '2010-01-01', districtMovedInDate: '2010-01-01', ...extra })
const notice = (extra: Partial<Notice> = {}): Notice => ({ ...demoNotices(new Date('2026-10-07T12:00:00+09:00'))[0], id: 'hangang', title: '쌍용 더 플래티넘 한강', source: 'cheongyak_home', housing_kind: 'private', application_method: 'apt_ranked', announcement_date: '2026-10-02', official_url: source, offered_supplies: offered, rules: [regions], selection_methods: [], winning_scores: [], ...extra })
const allocation = (extra: Partial<NoticeRule> = {}): NoticeRule => ({ kind: 'regional_allocation', effect: 'metadata', verification: 'official', evidence_url: source, allocation_method: 'region_priority', ...extra })

describe('opportunity respects each official supply scope', () => {
  it('never creates unit/supply combinations by merging the Hangang inventory', () => {
    const value = selectionOpportunity(notice(), profile())
    const actualPairs = new Set(offered.filter((supply) => (supply.supply_count || 0) > 0).map((supply) => `${supply.supply_type}:${supply.unit_type}`))
    const displayedPairs = value.rows.flatMap((row) => row.supplyTypes.flatMap((supply) => row.units.map((unit) => `${supply}:${unit}`)))
    expect(new Set(displayedPairs)).toEqual(actualPairs)
    expect(displayedPairs).toHaveLength(actualPairs.size)
    expect(value.rows.find((row) => row.supplyTypes.includes('신생아 특별공급'))?.units).not.toContain('123.7781')
    expect(value.rows.find((row) => row.supplyTypes.includes('다자녀가구 특별공급'))?.units).toContain('123.7781')
    const html = renderToStaticMarkup(<OpportunityPanel value={value} onProfile={() => {}} />)
    expect(html).toContain('신생아 특별공급<br/>주택형 074.9845')
  })

  it('describes a region classification without claiming special-supply eligibility', () => {
    const value = selectionOpportunity(notice(), profile())
    expect(value.rows).toHaveLength(7)
    expect(value.rows.every((row) => row.detail.includes('신청 자격은 별도로 확인'))).toBe(true)
    expect(value.rows.some((row) => row.detail.includes('자격은 확인'))).toBe(false)
    expect(value.rows[0].detail).toContain('거주지의 지역 구분은 기타지역')
  })

  it('does not inherit a general-supply allocation into special supply', () => {
    const value = selectionOpportunity(notice({ selection_methods: [allocation()] }), profile())
    const general = value.rows.find((row) => row.supplyTypes.includes('일반공급'))!
    expect(general.label).toContain('해당지역 우선')
    expect(value.rows.filter((row) => row.supplyTypes.some((supply) => special.includes(supply))).every((row) => row.label.includes('확인 필요'))).toBe(true)

    const shared = selectionOpportunity(notice({ selection_methods: [allocation({ supply_types: ['다자녀가구 특별공급', '노부모부양 특별공급'] })] }), profile())
    expect(shared.rows.filter((row) => row.label.includes('해당지역 우선')).map((row) => row.supplyTypes[0])).toEqual(['다자녀가구 특별공급', '노부모부양 특별공급'])
    expect(shared.rows.find((row) => row.supplyTypes.includes('일반공급'))?.label).toContain('확인 필요')
  })

  it('shows recommendation and each special selection order without a blanket same-rank claim', () => {
    const methods = [
      allocation({ supply_type: '기관추천 특별공급', allocation_method: 'institution_recommendation' }),
      allocation({ supply_type: '신혼부부 특별공급', selection_order: ['소득구분', '순위', '지역', '미성년 자녀수', '추첨'], evidence_page: 15 }),
      allocation({ supply_type: '신생아 특별공급', selection_order: ['소득구분', '지역', '추첨'], evidence_page: 20 }),
    ]
    const value = selectionOpportunity(notice({ selection_methods: methods }), profile())
    expect(value.rows.find((row) => row.supplyTypes.includes('기관추천 특별공급'))).toMatchObject({ label: '추천기관 우선순위로 선정', limited: false, evidenceUrl: source })
    const newlywed = value.rows.find((row) => row.supplyTypes.includes('신혼부부 특별공급'))!
    expect(newlywed.detail).toContain('소득구분 → 순위 → 지역 → 미성년 자녀수 → 추첨')
    expect(newlywed.detail).not.toContain('같은 순위에서는')
    expect(value.rows.find((row) => row.supplyTypes.includes('신생아 특별공급'))?.detail).toContain('소득구분 → 지역 → 추첨')
    const local = selectionOpportunity(notice({ selection_methods: methods }), profile({ region: '경기도', regionCode: '41', district: '양평군', districtCode: '41830' }))
    expect(local.rows.find((row) => row.supplyTypes.includes('신혼부부 특별공급'))).toMatchObject({ label: '해당지역 우선 선정', limited: false })
    expect(local.rows.find((row) => row.supplyTypes.includes('신생아 특별공급'))?.detail).toContain('소득구분 → 지역 → 추첨')
    expect(renderToStaticMarkup(<OpportunityPanel value={local} onProfile={() => {}} />)).toContain('공식 근거 20쪽 ↗')
  })

  it('retains the mixed Gyeonggi quota, carry-forward and later-stage exception', () => {
    const quota = allocation({ supply_type: '다자녀가구 특별공급', allocation_method: 'regional_quota', regional_shares: [{ residence_area: 'local_and_other_gyeonggi', label: '경기도 양평군 및 경기도', percent: 50 }, { residence_area: 'other', label: '서울특별시·인천광역시', percent: 50 }], local_share_percent: null, local_region: { region_name: '경기도 양평군', region_code: '41830' }, local_priority_within_first_quota: true, unsuccessful_applicants_advance: true, local_priority_in_remaining_quota: false, selection_order: ['지역', '배점', '미성년 자녀수', '청약신청자 연령', '추첨'], evidence_page: 13 })
    const n = notice({ rules: [regions, { ...regions, supply_type: '다자녀가구 특별공급', other_gyeonggi: { region_code: '41', region_name: '경기도' } }], selection_methods: [quota] })
    for (const person of [profile(), profile({ region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590' }), profile({ region: '경기도', regionCode: '41', district: '양평군', districtCode: '41830' })]) {
      const row = selectionOpportunity(n, person).rows.find((entry) => entry.supplyTypes.includes('다자녀가구 특별공급'))!
      expect(row.limited).toBe(false)
      expect(row.detail).toContain('경기도 양평군 및 경기도 50%')
      expect(row.detail).toContain('서울특별시·인천광역시 50%')
      expect(row.detail).toContain('해당지역(경기도 양평군)을 먼저 선정')
      expect(row.detail).toContain('낙첨자는 다음 지역 배정에 다시 포함')
      expect(row.detail).toContain('그 배정에서는 해당지역 우선을 적용하지 않습니다')
      expect(row.detail).not.toContain('공식 배정 50%')
      expect(row.evidencePage).toBe(13)
    }
    const historical = profile({ movedInDate: '2026-10-05', cityMovedInDate: '2026-10-05', districtMovedInDate: '2026-10-05', residenceHistory: [{ criterionDate: '2026-10-02', region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590', movedInDate: '2010-01-01', cityMovedInDate: '2010-01-01', districtMovedInDate: '2010-01-01' }] })
    expect(selectionOpportunity(n, historical).rows.find((entry) => entry.supplyTypes.includes('다자녀가구 특별공급'))?.label).toBe('기타경기 · 지역별 배정')
  })

  it('keeps manual regional selection distinct from an official regional finding', () => {
    const value = selectionOpportunity(notice({ rules: [] }), EMPTY_PROFILE, 'other')
    expect(value.rows).toHaveLength(1)
    expect(value.rows[0].supplyTypes).toEqual(['일반공급'])
    expect(value.rows[0].detail).toContain('직접 선택한 기타지역 기준')
    expect(value.rows[0].detail).not.toContain('거주지의 지역 구분')
  })

  it('shows the official newlywed third-stage exception instead of making rank universal', () => {
    const method = allocation({ supply_type: '신혼부부 특별공급', local_region: { region_name: '경기도 양평군', region_code: '41830' }, selection_order: ['소득구분', '순위', '지역', '미성년 자녀수', '추첨'], selection_stage_exceptions: [{ stage_number: 3, selection_order: ['지역', '추첨'], rank_applies: false, evidence_page: 15, evidence_text: '3단계에서 경쟁이 있는 경우 순위와 관계없이 해당지역 거주자(양평군 거주자)에게 우선공급하고, 경쟁이 있는 경우 추첨으로 선정' }], evidence_page: 15 })
    for (const person of [profile(), profile({ region: '경기도', regionCode: '41', district: '양평군', districtCode: '41830' })]) {
      const value = selectionOpportunity(notice({ selection_methods: [method] }), person)
      const row = value.rows.find((entry) => entry.supplyTypes.includes('신혼부부 특별공급'))!
      expect(row.detail).toContain('기본 선정 순서: 소득구분 → 순위 → 지역 → 미성년 자녀수 → 추첨')
      expect(row.detail).toContain('3단계 선정 순서: 지역 → 추첨')
      expect(row.detail).toContain('순위와 관계없이 해당지역(경기도 양평군)을 먼저 선정하고, 경쟁 시 추첨')
      expect(row.evidencePage).toBe(15)
    }
    const undocumented = { ...method, selection_stage_exceptions: [{ stage_number: 3, selection_order: ['지역', '추첨'], rank_applies: false }] }
    expect(selectionOpportunity(notice({ selection_methods: [undocumented] }), profile()).rows.find((entry) => entry.supplyTypes.includes('신혼부부 특별공급'))?.detail).not.toContain('3단계')
  })

  it('does not choose one of conflicting official selection orders arbitrarily', () => {
    const first = allocation({ supply_type: '신혼부부 특별공급', selection_order: ['소득구분', '지역', '추첨'] })
    const value = selectionOpportunity(notice({ selection_methods: [first, { ...first, selection_order: ['지역', '소득구분', '추첨'] }] }), profile())
    expect(value.rows.find((row) => row.supplyTypes.includes('신혼부부 특별공급'))?.label).toContain('확인 필요')
  })
})
