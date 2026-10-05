import type { Notice } from './types'

function isoAfter(days: number, from: Date): string {
  const next = new Date(from)
  next.setUTCDate(next.getUTCDate() + days)
  return next.toISOString().slice(0, 10)
}

export function demoNotices(from = new Date()): Notice[] {
  const today = new Date(from.toLocaleString('en-US', { timeZone: 'Asia/Seoul' }))
  const date = (days: number) => isoAfter(days, today)
  const updated = today.toISOString()
  return [
    {
      id: 'demo-1', title: '[화면 예시] 서울 A지구 공공분양', category: '공공분양', source: 'DEMO', provider: '화면 예시',
      address: '서울특별시 강동구', region_code: '11', region_name: '서울특별시', announcement_date: date(-3), official_url: null,
      price_cap_status: 'yes', updated_at: updated, version: 1,
      events: [
        { kind: 'special', label: '특별공급', start_date: date(4), end_date: date(4), audience: '특별공급' },
        { kind: 'first', label: '1순위 접수', start_date: date(5), end_date: date(6), audience: '1순위' },
        { kind: 'result', label: '당첨자 발표', start_date: date(19), end_date: date(19) },
      ],
      prices: [
        { unit_type: '59A', area_sqm: 59.8, price_kind: 'sale', amount_krw: 589000000, basis_label: '주택형별 최고 분양금액', verification: 'official', evidence_text: '화면 구성용 예시 가격' },
        { unit_type: '59B', area_sqm: 59.9, price_kind: 'sale', amount_krw: 602000000, basis_label: '주택형별 최고 분양금액', verification: 'official', evidence_text: '화면 구성용 예시 가격' },
        { unit_type: '84A', area_sqm: 84.7, price_kind: 'sale', amount_krw: 778000000, basis_label: '주택형별 최고 분양금액', verification: 'official', evidence_text: '화면 구성용 예시 가격' },
      ],
      rules_complete: true,
      rules: [
        { kind: 'residence_months', value: 12, verification: 'official', evidence_text: '화면 예시: 모집공고일 기준 서울 거주 12개월 이상', region_name: '서울특별시' },
        { kind: 'homeless', value: true, verification: 'official', evidence_text: '화면 예시: 무주택 세대구성원' },
        { kind: 'subscription_months', value: 24, verification: 'official', evidence_text: '화면 예시: 청약통장 가입 24개월 이상' },
      ],
    },
    {
      id: 'demo-2', title: '[화면 예시] 인천 검단 B블록 민간분양', category: '민간분양', source: 'DEMO', provider: '화면 예시',
      address: '인천광역시 서구', region_code: '28', region_name: '인천광역시', announcement_date: date(-2), official_url: null,
      price_cap_status: 'yes', updated_at: updated, version: 1,
      events: [
        { kind: 'special', label: '특별공급', start_date: date(8), end_date: date(8), audience: '특별공급' },
        { kind: 'first', label: '1순위 접수', start_date: date(9), end_date: date(9), audience: '1순위' },
      ],
      prices: [
        { unit_type: '74A', area_sqm: 74.4, price_kind: 'sale', amount_krw: 487000000, basis_label: '주택형별 최고 분양금액', verification: 'official' },
        { unit_type: '84A', area_sqm: 84.9, price_kind: 'sale', amount_krw: 541000000, basis_label: '주택형별 최고 분양금액', verification: 'official' },
        { unit_type: '84B', area_sqm: 84.8, price_kind: 'sale', amount_krw: null, basis_label: '가격 미공개', verification: 'unknown' },
      ],
      rules_complete: false, rules: [{ kind: 'unparsed', verification: 'ai_unverified', evidence_text: '화면 예시: 해당 지역 거주자 우선' }],
    },
    {
      id: 'demo-3', title: '[화면 예시] 경기 화성 C지구 민간임대', category: 'private_rental', source: 'DEMO', provider: '화면 예시',
      address: '경기도 화성시', region_code: '41', region_name: '경기도', announcement_date: date(-1), official_url: null,
      price_cap_status: 'not_applicable', updated_at: updated, version: 1,
      events: [{ kind: 'application', label: '청약 접수', start_date: date(13), end_date: date(17) }],
      prices: [
        { unit_type: '36A', area_sqm: 36.2, price_kind: 'rental', amount_krw: 43000000, monthly_krw: 221000, basis_label: '임대보증금 / 월 임대료', verification: 'official' },
        { unit_type: '44A', area_sqm: 44.1, price_kind: 'rental', amount_krw: 62000000, monthly_krw: 268000, basis_label: '임대보증금 / 월 임대료', verification: 'official' },
      ],
      rules_complete: false, rules: [],
    },
    {
      id: 'demo-4', title: '[화면 예시] 부산 D단지 민간분양', category: '민간분양', source: 'DEMO', provider: '화면 예시',
      address: '부산광역시 연제구', region_code: '26', region_name: '부산광역시', announcement_date: date(2), official_url: null,
      price_cap_status: 'unknown', updated_at: updated, version: 1,
      events: [{ kind: 'application', label: '청약 접수', start_date: date(21), end_date: date(23) }],
      prices: [
        { unit_type: '59A', area_sqm: 59.7, price_kind: 'sale', amount_krw: 497000000, basis_label: '공고문 추출 가격', verification: 'ai_unverified', evidence_text: '화면 구성용 자동 추출 예시' },
        { unit_type: '84A', area_sqm: 84.6, price_kind: 'sale', amount_krw: 698000000, basis_label: '공고문 추출 가격', verification: 'ai_unverified', evidence_text: '화면 구성용 자동 추출 예시' },
      ],
      rules_complete: false, rules: [],
    },
  ]
}
