import { describe, expect, it } from 'vitest'
import { competitionDecision, competitionEventAvailable, competitionRateLabel, competitionRowLabel, competitionUnitKey, residenceArea, competitionClosureProof, historicalCompetitionValid, resultCompetitionDecision, resultCompetitionRows } from './competition'
import { applyCompetitionEligibility, eligibilityCombinations, evaluateEligibility } from './eligibility'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeCompetition, type NoticeRule } from './types'
const unchangedFacts = { bank_private: { mode: 'never_changed' as const, date: '' }, bank_national: { mode: 'never_changed' as const, date: '' }, children: { mode: 'never_changed' as const, date: '' }, military: { mode: 'never_changed' as const, date: '' } }

const now = Date.parse('2026-10-01T01:00:00Z')
const observed = '2026-10-01T00:59:00Z'
const profile: LocalProfile = { ...EMPTY_PROFILE, factChanges: unchangedFacts, region: '서울특별시', accountType: 'comprehensive', accountConversionUnclear: false, privateRankBaseDate: '2020-01-01', privateDepositKrw: '3000000', restrictedFromApplying: false }
const RANK_RULES: NoticeRule[] = [
  { kind: 'account_type', allowed_values: ['comprehensive', 'deposit', 'installment'], purpose: 'first_rank', verification: 'official', evidence_text: '공식 민영 통장 종류' },
  { kind: 'private_rank_months', value: 12, purpose: 'first_rank', rank_rules_complete: true, verification: 'official', evidence_text: '공식 공고 1순위 인정기간' },
  { kind: 'deposit_min_krw', value: 3000000, purpose: 'first_rank', verification: 'official', evidence_text: '공식 해당 지역·면적의 예치금액' },
]
const applicantScope = (): NoticeRule => ({ kind: 'applicant_regions', effect: 'metadata', verification: 'official', evidence_url: 'https://www.applyhome.co.kr/notice', evidence_text: '서울·경기·인천 거주자 신청 가능', regions: [{ region_code: '11', region_name: '서울특별시' }, { region_code: '41', region_name: '경기도' }, { region_code: '28', region_name: '인천광역시' }] })
const first = { kind: 'first_priority', label: '1순위', audience: '기타지역', start_date: '2026-10-01', end_date: '2026-10-01' }
function row(unit: string, patch: Partial<NoticeCompetition> = {}): NoticeCompetition {
  return { source: 'cheongyak_competition', unit_type: unit, rank: 1, residence_area: 'local', residence_area_label: '해당지역',
    supply_count: 10, application_count: 20, competition_rate: '2.00', result_status: 'local_first_closed',
    result_text: '1순위 해당지역 마감(청약 접수 종료)', evidence_url: 'https://www.applyhome.co.kr/competition',
    verification: 'official', observed_at: observed, ...patch }
}
function notice(patch: Partial<Notice> = {}): Notice {
  return { id: 'closed', title: '공식 공고', category: 'apt', source: 'cheongyak_home', provider: '사업자',
    address: '경기도 성남시', region_code: '41', region_name: '경기도 성남시', announcement_date: '2026-09-25',
    official_url: 'https://www.applyhome.co.kr/notice', price_cap_status: 'yes', events: [first], prices: [],
    housing_kind: 'private', housing_kind_evidence: { verification: 'official', evidence_url: 'https://www.applyhome.co.kr/notice', evidence_text: '민영주택' },
    updated_at: observed, version: 1, competitions: [row('59A'), row('84A')],
    competition: { status: 'ok', last_attempt_at: observed, last_success_at: observed, complete: true, unit_types: ['59A', '84A'] }, ...patch, rules: [...RANK_RULES, ...(patch.rules || [])] }
}
const decide = (housing = notice(), home = profile, area: 'local' | 'other' | 'other_gyeonggi' | 'unknown' = 'other') =>
  competitionDecision(housing, home, '2026-10-01', area, now)

describe('official competition closure', () => {
  it('marks all officially closed units unavailable without removing them for confirmed other-region first priority', () => {
    expect(decide().allApplicationsUnavailable).toBe(true)
    expect(decide().closedUnits).toEqual(['59A', '84A'])
    expect(decide().reason).toContain('모든 일반공급 주택형')
  })

  it('keeps partial closure and all prices', () => {
    const housing = notice({ competitions: [row('59A'), row('84A', { result_status: 'open', competition_rate: '(△57)' })] })
    expect(decide(housing).allApplicationsUnavailable).toBe(false)
    expect(decide(housing).closedUnits).toEqual(['59A'])
  })

  it('matches official unit formatting and preserves partial-evidence badges without hiding', () => {
    const housing = notice({ competitions: [row('059.9442A')],
      competition: { ...notice().competition!, status: 'partial', complete: false, unit_types: ['0599442A', '0849442A'] } })
    expect(competitionUnitKey('059.9442 A')).toBe('0599442A')
    expect(decide(housing).closedUnits).toEqual(['0599442A'])
    expect(decide(housing).allApplicationsUnavailable).toBe(false)
  })

  it.each(['first_closed', 'open', 'unknown'] as const)('does not infer local closure from %s or high ratios', (status) => {
    expect(decide(notice({ competitions: [row('59A', { result_status: status, competition_rate: '120.00' }), row('84A')] })).allApplicationsUnavailable).toBe(false)
  })

  it.each(['local', 'other_gyeonggi', 'unknown'] as const)('keeps %s applicants', (area) => {
    expect(decide(notice(), profile, area).allApplicationsUnavailable).toBe(false)
  })

  it('keeps missing dates, unknown classification and old self-assessed rank', () => {
    expect(decide(notice(), { ...EMPTY_PROFILE, factChanges: unchangedFacts, subscriptionRank: 'first' }).allApplicationsUnavailable).toBe(false)
    expect(decide(notice(), { ...profile, privateRankBaseDate: '' }).allApplicationsUnavailable).toBe(false)
    expect(decide(notice({ housing_kind: 'unknown' })).allApplicationsUnavailable).toBe(false)
  })

  it('keeps missing, incomplete, failed, stale, and future-dated result collections', () => {
    const base = notice()
    for (const patch of [undefined, { ...base.competition!, complete: false }, { ...base.competition!, status: 'error' },
      { ...base.competition!, last_success_at: '2026-09-30T18:59:59Z', last_attempt_at: '2026-09-30T18:59:59Z' },
      { ...base.competition!, last_success_at: '2026-10-01T01:10:00Z', last_attempt_at: '2026-10-01T01:10:00Z' },
      { ...base.competition!, unit_types: [] }]) {
      expect(decide(notice({ competition: patch })).allApplicationsUnavailable).toBe(false)
    }
    expect(decide(notice({ competitions: [row('59A', { observed_at: '2026-10-01T01:10:00Z' }), row('84A')] })).allApplicationsUnavailable).toBe(false)
    expect(decide(notice({ competitions: [row('59A', { verification: 'ai_unverified' }), row('84A')] })).allApplicationsUnavailable).toBe(false)
  })

  it('keeps a possible future special supply and marks only blocked general events unavailable', () => {
    const special = { kind: 'special', label: '특별공급', start_date: '2026-10-05', end_date: '2026-10-05' }
    const housing = notice({ events: [first, special] })
    const decision = decide(housing)
    expect(decision.allApplicationsUnavailable).toBe(false)
    expect(competitionEventAvailable(first, housing, profile, decision)).toBe(false)
    expect(competitionEventAvailable(special, housing, profile, decision)).toBe(true)
    expect(decide(housing, { ...profile, specialEligibility: false }).allApplicationsUnavailable).toBe(false)
    const ruledSpecial = notice({ events: [first, special], rules_complete: true, rules: [{ kind: 'children_min', value: 2, child_age_max: 19, supply_type: '다자녀 특별공급', verification: 'official', evidence_text: '공식 미성년 자녀 2명 요건' }] })
    expect(decide(ruledSpecial, { ...profile, hasChildren: false, pregnant: false }).allApplicationsUnavailable).toBe(true)
  })

  it('preserves a remaining unknown special type even when another offered special mismatches', () => {
    const housing = notice({ rules_complete: true, events: [first, { kind: 'special', label: '특별공급', start_date: '2026-10-05', end_date: '2026-10-05' }], rules: [
      { kind: 'children_min', value: 2, child_age_max: 19, supply_type: '다자녀 특별공급', verification: 'official', evidence_text: '공식 자녀 요건' },
      { kind: 'special_eligibility', value: '기관추천', supply_type: '기관추천 특별공급', verification: 'official', evidence_text: '공식 기관추천 모집' },
    ] })
    expect(decide(housing, { ...profile, hasChildren: false, pregnant: false }).allApplicationsUnavailable).toBe(false)
  })

  it('keeps a notice when an offered special supply has no verified reception schedule', () => {
    const housing = notice({ rules: [{ kind: 'special_eligibility', value: '기관추천', supply_type: '기관추천 특별공급', verification: 'official', evidence_text: '공식 기관추천 모집' }] })
    expect(decide(housing).allApplicationsUnavailable).toBe(false)
  })

  it('applies live closure only to units with their own confirmed first rank', () => {
    const housing = notice({ rules: [{ kind: 'deposit_min_krw', value: 8000000, unit_type: '84A', purpose: 'first_rank', verification: 'official', evidence_text: '84A 공고 예치금 기준' }] })
    const decision = decide(housing)
    expect(decision.closedUnits).toEqual(['59A'])
    expect(decision.allApplicationsUnavailable).toBe(false)
    expect(competitionEventAvailable(first, housing, profile, decision)).toBe(true)
  })

  it('reopens an excluded notice after a corrected official result', () => {
    expect(decide().allApplicationsUnavailable).toBe(true)
    expect(decide(notice({ competitions: [row('59A', { result_status: 'open' }), row('84A')] })).allApplicationsUnavailable).toBe(false)
  })
})

describe('region classification only from verified priority rules', () => {
  const rule = (patch: Partial<NoticeRule> = {}): NoticeRule => ({ kind: 'residence_region', effect: 'priority', verification: 'official', region_name: '경기도 성남시', evidence_text: '성남시 해당지역 우선공급', ...patch })
  it('does not infer a region group from address or province alone', () => {
    expect(residenceArea(notice(), { ...profile, region: '경기도', district: '' })).toBe('unknown')
    expect(residenceArea(notice({ rules: [rule()] }), { ...profile, region: '경기도', district: '' })).toBe('unknown')
    expect(residenceArea(notice({ rules: [rule()] }), { ...profile, region: '경기도', district: '수원시' })).toBe('unknown')
  })

  it('uses explicit province/city priority and supports manual confirmation', () => {
    const housing = notice({ rules: [rule(), applicantScope()] })
    expect(residenceArea(housing, { ...profile, region: '경기도', district: '성남시', movedInDate: '2020-01-01' })).toBe('local')
    expect(residenceArea(housing, { ...profile, movedInDate: '2020-01-01' })).toBe('other')
    expect(residenceArea(housing, profile, 'unknown')).toBe('unknown')
    expect(residenceArea(housing, profile, 'other_gyeonggi')).toBe('other_gyeonggi')
  })

  it('uses a verified distinct other-Gyeonggi group', () => {
    const housing = notice({ rules: [rule(), rule({ kind: 'residence_area', region_name: '경기도', value: 'other_gyeonggi' })] })
    expect(residenceArea(housing, { ...profile, region: '경기도', district: '수원시' })).toBe('other_gyeonggi')
  })

  it('keeps unverified scopes and city residence duration uncertain', () => {
    expect(residenceArea(notice({ rules: [rule({ verification: 'ai_unverified' })] }), profile)).toBe('unknown')
    const housing = notice({ rules: [rule({ kind: 'residence_months', value: 12 })] })
    expect(residenceArea(housing, { ...profile, region: '경기도', district: '성남시', movedInDate: '2020-01-01' })).toBe('unknown')
  })

  it('uses other-region first reception only inside the official applicant scope', () => {
    const housing = notice({ rules: [rule({ kind: 'residence_months', region_name: '서울특별시', value: 12 }), applicantScope()] })
    expect(residenceArea(housing, { ...profile, movedInDate: '2026-07-01' })).toBe('other')
    expect(residenceArea(housing, { ...profile, movedInDate: '2020-01-01' })).toBe('local')
    expect(residenceArea(housing, profile)).toBe('unknown')
  })
})

describe('competition display preserves source meaning', () => {
  it('distinguishes unpublished rate, shortage, and numeric ratio', () => {
    expect(competitionRateLabel('-')).toBe('미공개')
    expect(competitionRateLabel('(△57)')).toBe('미달 57세대')
    expect(competitionRateLabel('1.10')).toBe('1.10')
    expect(competitionRowLabel(row('59A', { result_status: 'first_closed' }))).toBe('1순위 마감')
    expect(competitionRowLabel(row('59A', { result_status: 'open' }))).toBe('접수 중')
    expect(competitionRowLabel(row('59A', { result_status: 'unknown', result_text: '청약 접수 종료' }))).toBe('청약 접수 종료')
  })
})

describe('competition closure in unit and supply eligibility', () => {
  const applicant: LocalProfile = { ...profile, applicantOnRegister: true, hasSpouse: false, applicantOwnsHome: false, householdMembersComplete: true, householdMembers: [], householdSnapshotDate: '2026-09-25', householdCompositionUnchanged: true }
  function housing(patch: Partial<Notice> = {}): Notice {
    return notice({ events: [first, { kind: 'special', label: '특별공급', start_date: '2026-09-20', end_date: '2026-09-20' }], rules_complete: true, rules: [
      { kind: 'homeless', value: true, verification: 'official', evidence_text: '무주택 일반공급', supply_type: '일반공급' },
      { kind: 'homeless', value: true, verification: 'official', evidence_text: '무주택 특별공급', supply_type: '신혼부부 특별공급' },
    ], ...patch })
  }

  it('blocks a closed unit general supply while preserving open units and special supply', () => {
    const housingNotice = housing({ competitions: [row('59A'), row('84A', { result_status: 'open' })] })
    const decision = decide(housingNotice, applicant)
    const combos = eligibilityCombinations(housingNotice, applicant, decision)
    const closed = combos.find((combo) => combo.unitType === '59A' && combo.supplyType === '일반공급')!.result
    expect(closed.status).toBe('mismatch')
    expect(closed.reasons.find((reason) => reason.label === '기타지역 1순위 접수 마감')?.evidenceUrl).toBe(row('59A').evidence_url)
    expect(closed.reasons.find((reason) => reason.label === '기타지역 1순위 접수 마감')?.evidenceText).toBe(row('59A').result_text)
    expect(combos.find((combo) => combo.unitType === '84A' && combo.supplyType === '일반공급')!.result.status).toBe('possible')
    expect(combos.filter((combo) => combo.supplyType === '신혼부부 특별공급').map((combo) => combo.result.status)).toEqual(['review'])
  })

  it('never shows a possible whole-notice summary when the restored notice is fully closed', () => {
    const housingNotice = housing({ rules: [{ kind: 'homeless', value: true, verification: 'official', evidence_text: '공식 무주택 조건' }] })
    const base = evaluateEligibility(housingNotice, applicant)
    expect(base.status).toBe('possible')
    expect(applyCompetitionEligibility(base, housingNotice, decide(housingNotice, applicant)).status).toBe('mismatch')
    const combos = eligibilityCombinations(housingNotice, applicant, decide(housingNotice, applicant))
    expect(combos.filter((combo) => combo.supplyType === '일반공급').every((combo) => combo.result.status === 'mismatch')).toBe(true)
    expect(combos.filter((combo) => combo.supplyType === '전체 공급').every((combo) => combo.result.status !== 'possible')).toBe(true)
  })

  it('keeps unknown-region, stale, and failed results out of eligibility blocking', () => {
    const fresh = housing()
    const stale = housing({ competition: { ...fresh.competition!, last_success_at: '2026-09-30T18:59:59Z', last_attempt_at: '2026-09-30T18:59:59Z' } })
    const failed = housing({ competition: { ...fresh.competition!, status: 'error' } })
    for (const [housingNotice, decision] of [[fresh, decide(fresh, applicant, 'unknown')], [stale, decide(stale, applicant)], [failed, decide(failed, applicant)]] as const) {
      expect(eligibilityCombinations(housingNotice, applicant, decision).filter((combo) => combo.supplyType === '일반공급').map((combo) => combo.result.status)).toEqual(['possible', 'possible'])
    }
  })
})


describe('document-backed closure proofs and historical result interest', () => {
  const allocation = (patch: Partial<NoticeRule> = {}): NoticeRule => ({
    kind: 'regional_allocation', effect: 'metadata', verification: 'official', supply_type: '일반공급',
    allocation_method: 'all_local_first', local_share_percent: 100,
    local_region: { region_code: '41210', region_name: '경기도 광명시', min_months: 24 },
    evidence_url: 'https://static.applyhome.co.kr/official-gwangmyeong.pdf',
    evidence_text: '일반공급 전량 해당지역 거주자 우선공급 후 잔여세대 기타지역 공급', document_hash: 'reviewed-official-hash', ...patch,
  })
  function gwangmyeong(patch: Partial<Notice> = {}): Notice {
    return notice({ ...patch, competitions: [
      row('059.9742A', { result_status: 'first_closed', result_text: '1순위 마감(청약 접수 종료)', supply_count: 10, application_count: 36, competition_rate: '3.60' }),
      row('059.9742A', { residence_area: 'other', application_count: 93, competition_rate: '-', result_status: 'first_closed', result_text: '1순위 마감(청약 접수 종료)' }),
      row('059.7421B', { result_status: 'open', result_text: '청약 접수중', supply_count: 42, application_count: 46, competition_rate: '1.10' }),
      row('059.7421B', { residence_area: 'other', result_status: 'open', result_text: '청약 접수중', application_count: 189, competition_rate: '-' }),
    ], competition: { ...notice().competition!, unit_types: ['059.9742A', '059.7421B'], ...(patch.competition || {}) }, rules: [allocation(), ...(patch.rules || [])] })
  }
  it('marks 59A unavailable from the official Gwangmyeong proof while retaining 59B at 1.10', () => {
    const housing = gwangmyeong()
    const decision = resultCompetitionDecision(housing, EMPTY_PROFILE, 'other', now)
    expect(decision.closedUnits).toEqual(['059.9742A'])
    expect(decision.allApplicationsUnavailable).toBe(false)
    expect(decision.closureProofs?.[0]).toMatchObject({ kind: 'all_local_first_exhausted',
      allocationEvidenceUrl: allocation().evidence_url, competitionEvidenceUrl: row('').evidence_url })
    expect(resultCompetitionRows(housing, decision).map((item) => item.unit_type)).toEqual(['059.9742A', '059.9742A', '059.7421B', '059.7421B'])
    expect(resultCompetitionRows(housing, decision, false)).toHaveLength(4)
    expect(competitionClosureProof(housing, '059.7421B', 'results', now)).toBeNull()
  })
  it('keeps a general 1순위 마감 unless every allocation/count requirement is confirmed', () => {
    const base = gwangmyeong()
    const changes: Partial<NoticeRule>[] = [
      { verification: 'ai_unverified' }, { allocation_method: 'regional_quota' }, { local_share_percent: 30 },
      { supply_type: '신혼부부 특별공급' }, { local_region: undefined }, { evidence_url: null }, { evidence_text: null },
      { unit_type: '84A' },
    ]
    for (const patch of changes) {
      const housing = { ...base, rules: [allocation(patch)] }
      expect(competitionClosureProof(housing, '059.9742A', 'results', now)).toBeNull()
    }
    for (const patch of [
      { application_count: 9 }, { application_count: null }, { supply_count: 0 }, { supply_count: null },
      { result_status: 'unknown' as const, result_text: '청약 접수 종료' },
      { result_status: 'first_closed' as const, result_text: '청약 접수 종료' },
      { rank: 2 }, { verification: 'ai_unverified' }, { supply_type: 'special', supply_type_label: '특별공급' },
    ]) {
      const housing = { ...base, competitions: [{ ...base.competitions![0], ...patch }] }
      expect(competitionClosureProof(housing, '059.9742A', 'results', now)).toBeNull()
    }
  })
  it('does not combine applicant and allocation facts from different document revisions', () => {
    const housing = gwangmyeong({ rules: [{ ...applicantScope(), document_hash: 'different-current-hash' }] })
    expect(competitionClosureProof(housing, '059.9742A', 'results', now)).toBeNull()
  })
  it('uses the six-hour gate only for schedule closure, not historical interest or account rank', () => {
    const base = gwangmyeong()
    const old = '2026-09-20T01:00:00Z'
    const historical = { ...base, competitions: base.competitions!.map((item) => ({ ...item, observed_at: old })),
      competition: { ...base.competition!, status: 'error', last_attempt_at: observed, last_success_at: old, message: '최근 공개 화면 재조회 실패', proof_invalidated: false } }
    expect(competitionDecision(historical, profile, '2026-10-01', 'other', now).closedUnits).toEqual([])
    expect(resultCompetitionDecision(historical, EMPTY_PROFILE, 'other', now).closedUnits).toEqual(['059.9742A'])
    for (const status of ['running', 'pending', 'disabled', 'error']) {
      expect(resultCompetitionDecision({ ...historical, competition: { ...historical.competition, status } }, EMPTY_PROFILE, 'other', now).closedUnits).toEqual(['059.9742A'])
    }
  })
  it('restores invalidated historical proofs until a successful corrected snapshot', () => {
    const base = gwangmyeong()
    for (const status of ['pending', 'running', 'error']) {
      const housing = { ...base, competition: { ...base.competition!, status, proof_invalidated: true } }
      expect(historicalCompetitionValid(housing)).toBe(false)
      expect(resultCompetitionDecision(housing, profile, 'other', now).closedUnits).toEqual([])
    }
    const legacy = { ...base, competition: { ...base.competition!, status: 'pending', message: '공고 변경 후 경쟁률 재확인 대기' } }
    expect(historicalCompetitionValid(legacy)).toBe(false)
    const reopened = { ...base, competitions: base.competitions!.map((item) => ({ ...item, result_status: 'open' as const, result_text: '청약 접수중' })) }
    expect(resultCompetitionDecision(reopened, profile, 'other', now).closedUnits).toEqual([])
  })
  it('does not hide unknown, local, or separately assigned other-Gyeonggi areas', () => {
    const housing = gwangmyeong()
    for (const area of ['unknown', 'local', 'other_gyeonggi'] as const) {
      expect(resultCompetitionDecision(housing, profile, area, now).closedUnits).toEqual([])
    }
    expect(resultCompetitionDecision(housing, profile, undefined, now).closedUnits).toEqual([])
  })
  it('retains a special-supply result in a fully closed general-supply notice', () => {
    const housing = notice({ competitions: [row('59A'), row('84A'), row('59A', { supply_type: 'special', supply_type_label: '신혼부부 특별공급' })] })
    const decision = resultCompetitionDecision(housing, profile, 'other', now)
    expect(decision.allApplicationsUnavailable).toBe(false)
    expect(resultCompetitionRows(housing, decision)).toHaveLength(3)
    expect(resultCompetitionRows(housing, decision).at(-1)?.supply_type).toBe('special')
  })
})

describe('positive applicant area before other-region grouping', () => {
  const dgu: NoticeRule = { ...applicantScope(), regions: [{ region_code: '27', region_name: '대구광역시' }, { region_code: '47', region_name: '경상북도' }],
    local_priority: { region_code: '27', region_name: '대구광역시', min_months: 6 } }
  it('does not turn a Hwaseong address into nationwide 기타지역 for Dongin', () => {
    const housing = notice({ region_code: '27', region_name: '대구광역시', rules: [dgu] })
    expect(residenceArea(housing, { ...profile, region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590', movedInDate: '2020-01-01' })).toBe('unknown')
    expect(residenceArea(housing, { ...profile, region: '경상북도', regionCode: '47', movedInDate: '2020-01-01' })).toBe('other')
    expect(residenceArea(housing, { ...profile, region: '대구광역시', regionCode: '27', movedInDate: '2020-01-01' })).toBe('local')
    expect(residenceArea(housing, { ...profile, region: '대구광역시', regionCode: '27', movedInDate: '2026-08-01' })).toBe('other')
    expect(residenceArea(housing, { ...profile, region: '대구광역시', regionCode: '27', movedInDate: '' })).toBe('unknown')
  })
  it('uses two-band local duration and city rather than declaring all 경기 applicants 기타경기', () => {
    const rule: NoticeRule = { ...applicantScope(), local_priority: { region_code: '41210', region_name: '경기도 광명시', min_months: 24 } }
    const housing = notice({ rules: [rule] })
    const local = { ...profile, region: '경기도', regionCode: '41', district: '광명시', districtCode: '41210', movedInDate: '2020-01-01' }
    expect(residenceArea(housing, { ...local, districtMovedInDate: '2020-01-01' })).toBe('local')
    expect(residenceArea(housing, { ...local, districtMovedInDate: '2026-08-01' })).toBe('other')
    expect(residenceArea(housing, { ...local, district: '화성시', districtCode: '41590' })).toBe('other')
    expect(residenceArea(housing, { ...local, districtMovedInDate: '', movedInDate: '2020-01-01' })).toBe('unknown')
  })
})
