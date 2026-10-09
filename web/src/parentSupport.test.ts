import { beforeEach, describe, expect, it } from 'vitest'
import { getEvaluationToday, setEvaluationToday } from './factTimeline'
import { resolveParentSupport } from './parentSupport'
import { getParentSupportHistoryGroups, getProfileHistoryTarget, getProfileQuestionModel } from './profileQuestionModel'
import { evaluateRule } from './qualification'
import { migrateProfile } from './profile'
import { EMPTY_PROFILE, createHouseholdMember, createOwnershipFact, emptyPointsFamilyFact, type LocalProfile, type Notice, type NoticeRule } from './types'

const parent = (id = 'parent-1') => ({ ...createHouseholdMember(id), relation: 'applicant_parent' as const, register: 'applicant' as const, dateOfBirth: '1950-03-01', ownsHome: false })
const base = (part: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, hasSpouse: false, maritalStatus: 'single', applicantOnRegister: true, householdMembersComplete: true, householdMembers: [parent()], pointsFamily: { 'parent-1': { ...emptyPointsFamilyFact(), registeredSince: '2020-01-01', spouseOwnsHome: false } }, factChanges: { household: { mode: 'known', date: '2020-01-01' }, points: { mode: 'known', date: '2020-01-01' } }, ...part })
const rule = (kind: string, value: boolean | number = false, date = '2026-09-30'): NoticeRule => ({ kind, value, verification: 'official', evidence_url: 'https://example.com/notice.pdf', criterion_date: date, supply_type: '노부모부양 특별공급' })
const notice = (rules: NoticeRule[] = []): Notice => ({ id: 'parent-notice', title: '공식 공고', category: 'apt', source: 'cheongyak_home', provider: '청약홈', address: null, region_code: null, region_name: null, announcement_date: '2026-09-30', official_url: null, price_cap_status: 'unknown', events: [], prices: [], rules, updated_at: null, version: 1, offered_supplies: [{ supply_type: '노부모부양 특별공급', unit_type: '084', supply_count: 1, verification: 'official' }] })

beforeEach(() => setEvaluationToday('2026-10-09'))
describe('identity-linked parent support facts', () => {
  it('reuses one unambiguous ancestor without applying old separate parent answers', () => {
    const profile = base({ parentDateOfBirth: '1966-01-01', parentSameRegister: false, parentOwnsHome: true, parentSpouseOwnsHome: true, parentSupportSince: '2026-10-08' })
    const found = resolveParentSupport(profile, '2026-09-30')
    expect(found.mode).toBe('linked')
    expect(found.facts.parent_age_min.value).toBe('1950-03-01')
    expect(found.facts.parent_same_register.value).toBe(true)
    expect(found.facts.parent_support_months_min.value).toBe('2020-01-01')
    expect(found.facts.parent_owns_home.value).toBe(false)
    expect(found.facts.parent_spouse_owns_home.value).toBe(false)
    for (const condition of [rule('parent_age_min', 65), rule('parent_same_register', true), rule('parent_support_months_min', 36), rule('parent_owns_home'), rule('parent_spouse_owns_home')]) expect(evaluateRule(condition, profile, notice([condition])).status).toBe('pass')
  })
  it('requires an explicit choice among parents and keeps each spouse answer with that parent', () => {
    const other = { ...parent('parent-2'), dateOfBirth: '1966-01-01', ownsHome: true }
    const profile = base({ householdMembers: [parent(), other], pointsFamily: { 'parent-1': { ...emptyPointsFamilyFact(), spouseOwnsHome: false }, 'parent-2': { ...emptyPointsFamilyFact(), spouseOwnsHome: true } }, parentDateOfBirth: '1950-03-01', parentOwnsHome: false })
    expect(evaluateRule(rule('parent_age_min', 65), profile, notice())).toMatchObject({ status: 'review', profileField: 'parentSupportMemberId' })
    const selected = { ...profile, parentSupportMemberId: 'parent-2' }
    expect(evaluateRule(rule('parent_age_min', 65), selected, notice()).status).toBe('fail')
    expect(resolveParentSupport(selected).facts.parent_spouse_owns_home.value).toBe(true)
    expect(resolveParentSupport({ ...selected, parentSupportMemberId: 'deleted-parent' }).mode).toBe('selection')
    expect(migrateProfile(selected).parentSupportMemberId).toBe('parent-2')
  })
  it('reuses an exact linked owner birth date and asks for correction when birth dates conflict', () => {
    const property = { ...createOwnershipFact('same-owner'), ownerMemberId: 'parent-1', ownerDateOfBirth: '1950-03-01' }
    const missingBirth = base({ householdMembers: [{ ...parent(), dateOfBirth: '' }], ownershipFacts: [property] })
    expect(resolveParentSupport(missingBirth).facts.parent_age_min.value).toBe('1950-03-01')
    expect(evaluateRule(rule('parent_age_min', 65), missingBirth, notice()).status).toBe('pass')
    const conflict = { ...missingBirth, ownershipFacts: [property, { ...property, id: 'same-owner-second-home', ownerDateOfBirth: '1966-01-01' }] }
    expect(resolveParentSupport(conflict).facts.parent_age_min.value).toBe('')
    expect(evaluateRule(rule('parent_age_min', 65), conflict, notice())).toMatchObject({ status: 'review', category: 'missing_input' })
  })
  it('does not turn unknown ownership into no ownership from another owner or an empty inventory', () => {
    const unknown = base({ householdMembers: [{ ...parent(), ownsHome: null }], ownershipFactsKnown: true, ownershipFacts: [createOwnershipFact('another-owner')] })
    expect(resolveParentSupport(unknown).facts.parent_owns_home.value).toBeNull()
    expect(evaluateRule(rule('parent_owns_home'), unknown, notice())).toMatchObject({ status: 'review', category: 'missing_input', profileField: 'householdMembers' })
    const disposed = { ...createOwnershipFact('disposed-only'), ownerMemberId: 'parent-1', propertyKind: 'apartment' as const, acquiredDate: '2020-01-01', disposedDate: '2026-10-01' }
    const partialInventory = { ...unknown, ownershipFacts: [disposed] }
    expect(resolveParentSupport(partialInventory).facts.parent_owns_home.value).toBeNull()
    const active = { ...disposed, id: 'active-home', disposedDate: '' }
    expect(resolveParentSupport({ ...partialInventory, ownershipFacts: [disposed, active, createOwnershipFact('unknown-details')] }, '2026-09-30').facts.parent_owns_home.value).toBe(true)
  })
  it('reconstructs this owner’s dated holding and disposal without the 60-year ownership exemption', () => {
    const property = { ...createOwnershipFact('owned-home'), ownerMemberId: 'parent-1', ownerRelation: 'ascendant' as const, propertyKind: 'apartment' as const, acquiredDate: '2020-01-01', disposedDate: '2026-10-01' }
    const profile = base({ ownershipFactsKnown: true, ownershipFacts: [property], factChanges: {} })
    expect(evaluateRule(rule('parent_owns_home', false, '2026-09-30'), profile, notice()).status).toBe('fail')
    expect(evaluateRule(rule('parent_owns_home', false, '2026-10-02'), profile, notice()).status).toBe('pass')
  })
  it('uses continuous register dates for same-register history while keeping spouse-only dates separate', () => {
    const profile = base({ factChanges: {} })
    expect(evaluateRule(rule('parent_same_register', true), profile, notice()).status).toBe('pass')
    expect(evaluateRule(rule('parent_support_months_min', 36), profile, notice()).status).toBe('pass')
    const separated = base({ hasSpouse: true, maritalStatus: 'married', spouseSameRegister: false, householdMembers: [{ ...parent(), register: 'spouse' }] })
    expect(resolveParentSupport(separated).facts.parent_support_months_min.value).toBe('')
    expect(evaluateRule(rule('parent_same_register', true), separated, notice()).status).toBe('fail')
  })
  it('routes actual historical gaps to existing household or points dates and removes the blanket group', () => {
    const profile = base({ factChanges: {}, pointsFamily: { 'parent-1': { ...emptyPointsFamilyFact(), spouseOwnsHome: false } } })
    const rules = [rule('parent_same_register', true), rule('parent_owns_home'), rule('parent_spouse_owns_home')], model = getProfileQuestionModel([notice(rules)], getEvaluationToday())
    expect(getParentSupportHistoryGroups(profile, model).sort()).toEqual(['household', 'points'])
    expect(getProfileHistoryTarget('parentSameRegister', profile, model)).toBe('household')
    expect(getProfileHistoryTarget('parentSpouseOwnsHome', profile, model)).toBe('points')
    expect(evaluateRule(rules[0], profile, notice())).toMatchObject({ category: 'past_fact', historyGroup: 'household', profileField: 'householdSnapshotDate' })
    expect(getParentSupportHistoryGroups(base(), model)).toEqual([])
    expect(getProfileHistoryTarget('parentSupportSince', base(), model)).toBeUndefined()
  })
})
