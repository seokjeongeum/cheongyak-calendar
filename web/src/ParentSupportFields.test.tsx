import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ParentSupportFields } from './ParentSupportFields'
import { getProfileQuestionModel } from './profileQuestionModel'
import { EMPTY_PROFILE, createHouseholdMember, emptyPointsFamilyFact, type LocalProfile, type Notice } from './types'

const today = '2026-10-09'
const notice: Notice = { id: 'parent', title: '공식 공고', category: 'apt', source: 'cheongyak_home', provider: '청약홈', address: null, region_code: null, region_name: null, announcement_date: '2026-09-30', official_url: 'https://example.com/notice.pdf', price_cap_status: 'unknown', events: [], prices: [], rules: ['parent_age_min', 'parent_same_register', 'parent_support_months_min', 'parent_owns_home', 'parent_spouse_owns_home'].map((kind) => ({ kind, value: kind === 'parent_age_min' ? 65 : kind === 'parent_support_months_min' ? 36 : kind === 'parent_same_register', verification: 'official', supply_type: '노부모부양 특별공급' })), offered_supplies: [{ supply_type: '노부모부양 특별공급', unit_type: '084', supply_count: 1, verification: 'official' }], updated_at: null, version: 1 }
const profile: LocalProfile = { ...EMPTY_PROFILE, householdMembers: [{ ...createHouseholdMember('parent-1'), relation: 'applicant_parent', register: 'applicant', dateOfBirth: '1950-01-01', ownsHome: false }], pointsFamily: { 'parent-1': { ...emptyPointsFamilyFact(), registeredSince: '2020-01-01', spouseOwnsHome: false } }, factChanges: { household: { mode: 'known', date: '2020-01-01' }, points: { mode: 'known', date: '2020-01-01' } } }
const render = (value: LocalProfile) => renderToStaticMarkup(<ParentSupportFields profile={value} onChange={() => {}} today={today} model={getProfileQuestionModel([notice], today)} />)

describe('parent support questions reuse common inputs', () => {
  it('shows existing facts without repeating four ownership/register/date questions', () => {
    const html = render(profile)
    expect(html).toContain('기존 입력 재사용')
    expect(html).toContain('1950-01-01')
    expect(html).toContain('2020-01-01')
    expect(html).not.toContain('type="date"')
    expect(html).not.toContain('<fieldset')
    expect(html).not.toContain('data-fact-group=')
  })
  it('asks only the missing actual continuous start and missing canonical family facts', () => {
    const missingStart = render({ ...profile, pointsFamily: { 'parent-1': { ...profile.pointsFamily['parent-1'], registeredSince: '' } } })
    expect(missingStart).toContain('부양 시작일 · 본인')
    expect(missingStart.match(/type="date"/g)).toHaveLength(1)
    expect(missingStart).not.toContain('<fieldset')
    const missing = render({ ...profile, householdMembers: [{ ...profile.householdMembers[0], dateOfBirth: '', ownsHome: null }], pointsFamily: {} })
    expect(missing).toContain('이 가족의 생년월일')
    expect(missing).toContain('이 가족이 주택·분양권·입주권·공유지분을 보유하나요?')
  })
  it('stops followups when the selected parent is definitely younger than the official minimum', () => {
    const html = render({ ...profile, householdMembers: [{ ...profile.householdMembers[0], dateOfBirth: '1966-01-01', ownsHome: null }], pointsFamily: {} })
    expect(html).toContain('노부모부양의 추가 질문을 멈췄습니다')
    expect(html).not.toContain('<fieldset')
    expect(html).not.toContain('data-fact-group=')
    expect(html).not.toContain('부양 시작일:')
  })
  it('exposes the original household/points history only for unresolved past facts', () => {
    const html = render({ ...profile, factChanges: {}, pointsFamily: { 'parent-1': { ...profile.pointsFamily['parent-1'], registeredSince: '' } } })
    expect(html).toContain('가족 구성·등본 관계 변경일')
    expect(html).toContain('가점 가족 소유 사실 변경일')
    expect(html).not.toContain('data-fact-group="parent_support"')
    expect(html).not.toContain('부모 부양·소유 상태 마지막 변경일')
  })
})
