import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { HouseholdFields } from './HouseholdFields'
import { createHouseholdMember, EMPTY_PROFILE, type LocalProfile } from './types'

const profile = (extra: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, maritalStatus: 'single', hasSpouse: false, applicantOnRegister: true, ...extra })
const render = (value: LocalProfile, historyNeeded = false) => renderToStaticMarkup(<HouseholdFields profile={value} onChange={() => {}} today="2026-10-09" notices={[]} historyNeeded={historyNeeded} />)
const relative = { ...createHouseholdMember('parent'), relation: 'applicant_parent' as const, register: 'applicant' as const, ownsHome: false }

describe('factual household questions', () => {
  it('omits the baseline applicant-registration question and keeps actual exceptions editable', () => {
    const normal = render(profile({ applicantOnRegister: null, additionalFamilyPresence: false }))
    expect(normal).not.toContain('본인이 주민등록등본에 등재되어 있나요?')
    expect(normal).toContain('주택 보유를 함께 확인할 사람 · 1명')
    const exceptional = render(profile({ applicantOnRegister: false, additionalFamilyPresence: false }))
    expect(exceptional).toContain('type="checkbox" checked=""')
    expect(exceptional).toContain('주민등록 말소 또는 본인 등본 없음')
    expect(exceptional).toContain('이 공고에서 인정하는 예외 신청·세대 증빙 범위')
  })
  it('asks whether another family member exists instead of asking to confirm completeness', () => {
    const html = render(profile())
    expect(html).toContain('본인·배우자 외 등본에 함께 있는 가족이 있나요?')
    expect(html).toContain('data-profile-field="additionalFamilyPresence"')
    expect(html).not.toContain('data-profile-field="householdMembersComplete"')
    expect(html).not.toContain('빠짐없이')
    expect(html).not.toContain('빠진 가족')
  })
  it('shows an applicant-only scope immediately after the concrete no-family answer', () => {
    const html = render(profile({ additionalFamilyPresence: false, householdMembersComplete: null }))
    expect(html).toContain('주택 보유를 함께 확인할 사람 · 1명')
    expect(html).not.toContain('입력하세요. 있다면')
  })
  it('uses family entries without asking an extra family presence or completeness question', () => {
    const html = render(profile({ householdMembers: [relative], householdMembersComplete: null, additionalFamilyPresence: null }))
    expect(html).toContain('주택 보유를 함께 확인할 사람 · 2명')
    expect(html).toContain('본인의 부모')
    expect(html).not.toContain('본인·배우자 외 등본에 함께 있는 가족이 있나요?')
    expect(html).not.toContain('빠짐없이')
    expect(html).not.toContain('빠진 가족')
  })
  it('keeps unresolved relation or register inputs available', () => {
    const html = render(profile({ householdMembers: [{ ...relative, register: 'unknown' }] }))
    expect(html).toContain('관계·등본 정보 입력 필요')
    expect(html).toContain('어느 주민등록등본에 함께 있나요?')
    expect(html).toContain('이 가족이 주택·분양권·입주권·공유지분을 보유하나요?')
    expect(html).not.toContain('주택 보유를 함께 확인할 사람 · 2명')
  })
  it('lets a stored family birth date be corrected in its original family entry', () => {
    const html = render(profile({ householdMembers: [{ ...relative, dateOfBirth: '1966-01-01' }] }))
    expect(html).toContain('가족 생년월일 수정 · 1966-01-01')
    expect(html).toContain('가족 1 생년월일')
    expect(html).toContain('type="date" max="2026-10-09" value="1966-01-01"')
    expect(html).not.toContain(' required=')
  })
  it('does not require a birth date to derive an otherwise complete family scope', () => {
    const html = render(profile({ householdMembers: [relative] }))
    expect(html).toContain('가족 생년월일 · 선택')
    expect(html).toContain('주택 보유를 함께 확인할 사람 · 2명')
    expect(html).not.toContain(' required=')
  })
  it('opens the original household history input when a parent condition needs it', () => {
    expect(render(profile())).not.toContain('data-fact-group="household"')
    const html = render(profile(), true)
    expect(html).toContain('data-fact-group="household"')
    expect(html.match(/가족 구성·등본 관계 마지막 변경일/g)).toHaveLength(1)
    expect(html).not.toContain('data-fact-group="parent_support"')
  })
})
