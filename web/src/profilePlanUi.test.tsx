import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ApplicationFactsFields } from './ApplicationFactsFields'
import { FactChangeFields } from './FactChangeFields'
import { OwnershipFields } from './OwnershipFields'
import { ProfileDialog } from './ProfileDialog'
import { getElderParentQuestionState, getProfileHistoryTarget, getProfileQuestionModel } from './profileQuestionModel'
import { EMPTY_PROFILE, createHouseholdMember, createOwnershipFact, type LocalProfile, type Notice, type NoticeRule } from './types'

const today = '2026-10-07', supply = '노부모부양 특별공급'
const rule = (kind: string, extra: Partial<NoticeRule> = {}): NoticeRule => ({ kind, value: true, verification: 'official', criterion_date: '2026-09-23', evidence_url: 'https://example.com/notice.pdf', ...extra })
const notice = (rules: NoticeRule[], extra: Partial<Notice> = {}): Notice => ({ id: 'official', title: '공식 공고', category: 'public_sale', source: 'lh', provider: 'LH', address: null, region_code: null, region_name: null, announcement_date: '2026-09-23', official_url: 'https://example.com/notice.pdf', price_cap_status: 'unknown', events: [], prices: [], rules, updated_at: null, version: 1, ...extra })
const profile: LocalProfile = { ...EMPTY_PROFILE, parentDateOfBirth: '1966-01-01', maritalStatus: 'single', hasSpouse: false, applicantOnRegister: true, householdMembersComplete: true }
const elderNotice = (rules: NoticeRule[] = [rule('parent_age_min', { value: 65, supply_type: supply })], units = ['084']): Notice => notice(rules, { offered_supplies: units.map((unit_type) => ({ supply_type: supply, unit_type, supply_count: 1, verification: 'official' })) })
const projectRule = rule('original_project_contract_ownership', { scope: 'applicant', project_id: 'LH-INCHEON-GAJEONG2-B2', value: false })
const residenceHtml = (condition: NoticeRule, value: LocalProfile = profile) => renderToStaticMarkup(<ApplicationFactsFields profile={value} onChange={() => {}} today={today} notices={[notice([condition])]} section="residence" />)

describe('precise profile questions for reviewed conditions', () => {
  it('stops parent followups only after all positive offered scopes have an unavoidable official age failure', () => {
    const rows = [elderNotice(undefined, ['084', '123'])]
    const model = getProfileQuestionModel(rows, today)
    const result = getElderParentQuestionState(profile, model)
    expect(result.stopped).toBe(true)
    expect(getElderParentQuestionState(profile, model)).toBe(result)
    expect(result.detail).toContain('다른 공급유형')
    expect(getElderParentQuestionState({ ...profile, parentDateOfBirth: '1950-01-01' }, model).stopped).toBe(false)
    const mixed = elderNotice([rule('parent_age_min', { value: 65, supply_type: supply, unit_type: '084' }), rule('parent_age_min', { value: 55, supply_type: supply, unit_type: '123' })], ['084', '123'])
    expect(getElderParentQuestionState(profile, getProfileQuestionModel([mixed], today)).stopped).toBe(false)
  })

  it('keeps questions for an allowed alternative, an official exception, or an unverified minimum', () => {
    const alternatives = rule('any', { supply_type: supply, conditions: [{ kind: 'parent_age_min', value: 65 }, { kind: 'parent_age_min', value: 55 }] })
    const exception = rule('parent_age_min', { value: 65, supply_type: supply, exceptions: [{ kind: 'parent_age_min', value: 55 }] })
    const candidate = rule('parent_age_min', { value: 65, supply_type: supply, verification: 'auto_unverified' })
    for (const condition of [alternatives, exception, candidate]) expect(getElderParentQuestionState(profile, getProfileQuestionModel([elderNotice([condition])], today)).stopped).toBe(false)
    const required = rule('all', { supply_type: supply, conditions: [{ kind: 'parent_age_min', value: 65 }, { kind: 'parent_same_register', value: true }] })
    expect(getElderParentQuestionState(profile, getProfileQuestionModel([elderNotice([required])], today)).stopped).toBe(true)
  })
  it('respects a rule limited to different supply types when deciding whether to stop questions', () => {
    const rows = [elderNotice([rule('parent_age_min', { value: 65, supply_types: ['기관추천 특별공급'] })])]
    expect(getElderParentQuestionState(profile, getProfileQuestionModel(rows, today)).stopped).toBe(false)
    const applicable = [elderNotice([rule('parent_age_min', { value: 65, supply_types: [supply] })])]
    expect(getElderParentQuestionState(profile, getProfileQuestionModel(applicable, today)).stopped).toBe(true)
  })

  it('keeps facts shared with another supply route and ignores zero-unit offers', () => {
    const shared = elderNotice([rule('parent_age_min', { value: 65, supply_type: supply }), rule('parent_owns_home', { value: false, supply_type: '일반공급' })])
    shared.offered_supplies!.push({ supply_type: '일반공급', unit_type: '084', supply_count: 2, verification: 'official' })
    expect(getElderParentQuestionState(profile, getProfileQuestionModel([shared], today)).stopped).toBe(false)
    const onlyElder = elderNotice([rule('parent_age_min', { value: 65, supply_type: supply }), rule('parent_owns_home', { value: false })])
    expect(getElderParentQuestionState(profile, getProfileQuestionModel([onlyElder], today)).stopped).toBe(true)
    const unavailable = { ...elderNotice(), offered_supplies: [{ supply_type: supply, unit_type: '084', supply_count: 0, verification: 'official' }] }
    const model = getProfileQuestionModel([unavailable], today)
    expect(model.elderParentScopes).toHaveLength(0)
    expect(getElderParentQuestionState(profile, model).stopped).toBe(false)
  })

  it('keeps the birth date editable and other supplies visible after the parent route fails', () => {
    const html = renderToStaticMarkup(<ProfileDialog profile={profile} onChange={() => {}} onClose={() => {}} today={today} notices={[elderNotice(), notice([rule('income_tax_years_min', { value: 5, supply_type: '생애최초 특별공급' })])]} initialField="parentDateOfBirth" />)
    expect(html).toContain('data-profile-field="parentDateOfBirth"')
    expect(html).toContain('노부모부양의 추가 질문을 멈췄습니다')
    for (const field of ['parentSameRegister', 'parentSupportSince', 'parentOwnsHome', 'parentSpouseOwnsHome']) expect(html).not.toContain(`data-profile-field="${field}"`)
    expect(html).toContain('data-profile-field="taxYears"')
    expect(html).toContain('data-profile-field="children"')
  })

  it('connects the actual support start and head change to dated fields', () => {
    const supported = { ...profile, parentDateOfBirth: '1950-01-01', parentSupportSince: '2020-01-01' }
    const model = getProfileQuestionModel([elderNotice([rule('parent_age_min', { value: 65, supply_type: supply }), rule('parent_support_months_min', { value: 36, supply_type: supply })])], today)
    expect(getProfileHistoryTarget('parentSupportSince', profile, model)).toBeUndefined()
    expect(getProfileHistoryTarget('parentSupportSince', supported, model)).toBeUndefined()
    const headModel = getProfileQuestionModel([notice([rule('household_head')])], today)
    expect(getProfileHistoryTarget('isHouseholdHead', profile, headModel)).toBeUndefined()
    expect(getProfileHistoryTarget('isHouseholdHead', { ...profile, isHouseholdHead: true }, headModel)).toBe('household_head')
    const html = renderToStaticMarkup(<ProfileDialog profile={supported} onChange={() => {}} onClose={() => {}} today={today} notices={[elderNotice([rule('parent_age_min', { value: 65, supply_type: supply }), rule('parent_support_months_min', { value: 36, supply_type: supply })])]} initialField="parentSupportSince" />)
    expect(html).toContain('저장된 부양 대상')
    expect(html).toContain('2020-01-01')
    expect(html).toContain('이 부양 대상을 가족으로 연결')
    expect(html).not.toContain('data-fact-group="parent_support"')
    const head = renderToStaticMarkup(<FactChangeFields profile={{ ...profile, factChanges: { household_head: { mode: 'known', date: '2022-01-01' } } }} onChange={() => {}} today={today} group="household_head" label="세대주 여부" />)
    expect(head).toContain('세대주 상태 변경일')
    expect(head).toContain('type="date"')
    expect(head).toContain('value="2022-01-01"')
  })

  it('shows an overseas exception only when the official threshold and exception allow it', () => {
    const days = { ...profile, overseasContinuousDays: '100' }
    expect(residenceHtml(rule('overseas_residence', { max_continuous_days: 90 }), days)).not.toContain('overseasOnlyApplicantForLivelihood')
    expect(residenceHtml(rule('overseas_residence', { max_continuous_days: 365, livelihood_exception: true }), days)).not.toContain('overseasOnlyApplicantForLivelihood')
    expect(residenceHtml(rule('overseas_residence', { max_continuous_days: 90, livelihood_exception: true }), days)).toContain('overseasOnlyApplicantForLivelihood')
    const currentAbroad = rule('overseas_residence', { max_continuous_days: 90, livelihood_exception: true, livelihood_exception_requires_family: true, currently_abroad_only: true, value_basis: 'continuous_days_including_reentry_within_7_days' })
    expect(residenceHtml(currentAbroad, days)).not.toContain('overseasOnlyApplicantForLivelihood')
    expect(residenceHtml(currentAbroad, { ...days, hasSpouse: true, maritalStatus: 'married' })).toContain('overseasOnlyApplicantForLivelihood')
    const unrelated = { ...createHouseholdMember('roommate'), relation: 'unrelated' as const, register: 'applicant' as const }
    expect(residenceHtml(currentAbroad, { ...days, householdMembers: [unrelated] })).not.toContain('overseasOnlyApplicantForLivelihood')
    expect(residenceHtml(currentAbroad, { ...days, currentlyDomesticResident: true })).not.toContain('data-profile-field="overseasContinuousDays"')
    expect(getProfileQuestionModel([notice([currentAbroad])], today).needsDomestic).toBe(true)
    expect(residenceHtml(currentAbroad, days)).toContain('7일 안에 같은 국가')
  })

  it('reuses common history for original-project ownership without asking unrelated family history', () => {
    const family = { ...profile, hasSpouse: true, maritalStatus: 'married' as const, applicationHistoryPresence: true }
    const html = renderToStaticMarkup(<ApplicationFactsFields profile={family} onChange={() => {}} today={today} notices={[notice([projectRule]), notice([projectRule], { id: 'same-project' })]} section="restrictions" />)
    expect(html).toContain('LH-INCHEON-GAJEONG2-B2')
    expect(html.match(/위 사람 중 당첨·예비당첨 또는 주택 공급계약 이력이 있는 사람이 있나요\?/g)).toHaveLength(1)
    expect(html).toContain('확인 대상: 본인.')
    expect(html).not.toContain('확인 대상: 본인 · 배우자')
    expect(html).toContain('최초 공고 당첨 이력만으로 주택 소유를 판단하지 않습니다')
  })

  it('links the actual property to the original project and exposes entry after a contract even if the current ownership answer is false', () => {
    const contracted: LocalProfile = { ...profile, applicantOwnsHome: false, applicationHistoryEvents: [{ id: 'contract', personId: 'applicant', projectId: 'LH-INCHEON-GAJEONG2-B2', eventKind: 'contract', eventDate: '2026-05-01' }] }
    const empty = renderToStaticMarkup(<OwnershipFields profile={contracted} onChange={() => {}} today={today} notices={[notice([projectRule])]} />)
    expect(empty).toContain('주택·권리 추가')
    const item = { ...createOwnershipFact('right'), projectId: 'LH-INCHEON-GAJEONG2-B2', propertyKind: 'presale_right' as const, acquiredDate: '2026-05-01' }
    const html = renderToStaticMarkup(<OwnershipFields profile={{ ...contracted, ownershipFacts: [item] }} onChange={() => {}} today={today} notices={[notice([projectRule])]} />)
    expect(html).toContain('최초 공급 사업 · 이 주택·권리의 계약 사업')
    expect(html).toContain('권리 취득일 (분양권은 공급계약일)')
    expect(html).toContain('계약일이 같아도 다른 주택은 선택하지 않습니다')
    expect(html).toContain('value="LH-INCHEON-GAJEONG2-B2" selected')
  })
})
