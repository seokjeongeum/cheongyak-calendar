import { describe, expect, it } from 'vitest'
import { deriveHousehold } from './household'
import { createHouseholdMember, createOwnershipFact, EMPTY_PROFILE, type HouseholdMember, type LocalProfile } from './types'
import { migrateProfile } from './profile'
import { evaluateHouseholdOwnership } from './ownership'
const cutoff = '2026-09-30'
const profile = (extra: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, applicantOnRegister: true, hasSpouse: false, applicantOwnsHome: false, householdMembersComplete: true, householdSnapshotDate: cutoff, ...extra })
const member = (relation: HouseholdMember['relation'], register: HouseholdMember['register'], id = `${relation}-${register}`): HouseholdMember => ({ ...createHouseholdMember(id), relation, register, ownsHome: false })
describe('Article 2 family roster scope, effective2026-06-15', () => {
  it('includes the applicant and legal spouse at separate addresses', () => {
    const scope = deriveHousehold(profile({ hasSpouse: true, spouseSameRegister: false, spouseOwnsHome: false }), cutoff)
    expect(scope).toMatchObject({ complete: true, legalCount: 2 })
    expect(scope.members.find((item) => item.id === 'spouse')).toMatchObject({ included: true })
    expect(scope.members.find((item) => item.id === 'spouse')?.reason).toContain('주소·등본이 달라도')
  })
  it('includes both spouses parents/grandparents on either register', () => {
    const members = ['applicant_parent', 'applicant_grandparent', 'spouse_parent', 'spouse_grandparent'].flatMap((relation) => [member(relation as HouseholdMember['relation'], 'applicant'), member(relation as HouseholdMember['relation'], 'spouse')])
    const scope = deriveHousehold(profile({ hasSpouse: true, spouseSameRegister: false, householdMembers: members }), cutoff)
    expect(scope).toMatchObject({ complete: true, legalCount: 10 })
    expect(scope.members.every((person) => person.included)).toBe(true)
  })
  it('includes applicant descendants and their spouses in either register', () => {
    const relatives = ['applicant_child', 'applicant_grandchild', 'descendant_spouse'].map((relation) => member(relation as HouseholdMember['relation'], 'spouse'))
    expect(deriveHousehold(profile({ hasSpouse: true, spouseSameRegister: false, householdMembers: relatives }), cutoff).legalCount).toBe(5)
  })
  it('includes a spouse descendant only on the actual applicant register', () => {
    const child = member('spouse_child', 'spouse')
    const base = profile({ hasSpouse: true, spouseSameRegister: false, householdMembers: [child] })
    expect(deriveHousehold(base, cutoff).members.find((item) => item.id === child.id)?.included).toBe(false)
    expect(deriveHousehold({ ...base, householdMembers: [{ ...child, register: 'applicant' }] }, cutoff).legalCount).toBe(3)
    expect(deriveHousehold({ ...base, spouseSameRegister: true }, cutoff).legalCount).toBe(3)
    expect(deriveHousehold({ ...base, spouseSameRegister: null }, cutoff).complete).toBe(false)
  })
  it('excludes siblings, unrelated residents and separate-register relatives', () => {
    const scope = deriveHousehold(profile({ householdMembers: [member('sibling', 'applicant'), member('unrelated', 'applicant'), member('applicant_parent', 'separate')] }), cutoff)
    expect(scope).toMatchObject({ complete: true, legalCount: 1 })
    expect(scope.members.slice(1).every((person) => person.included === false)).toBe(true)
  })
  it('keeps missing applicant registration, missing scope facts and duplicateIDs incomplete', () => {
    for (const extra of [{ applicantOnRegister: null }, { applicantOnRegister: false }, { hasSpouse: null }, { householdMembersComplete: null }, { householdSnapshotDate: '' }]) expect(deriveHousehold(profile(extra), cutoff).complete).toBe(false)
    const relative = member('applicant_parent', 'unknown')
    expect(deriveHousehold(profile({ householdMembers: [relative] }), cutoff)).toMatchObject({ complete: false, profileField: 'householdMembers' })
    expect(deriveHousehold(profile({ householdMembers: [member('applicant_child', 'applicant', 'applicant')] }), cutoff).complete).toBe(false)
  })
  it('requires exact earlier-date composition confirmation and does not promote general unchanged', () => {
    const current = profile({ householdSnapshotDate: '2026-10-04', householdCompositionUnchanged: true })
    expect(deriveHousehold(current, cutoff)).toMatchObject({ complete: false, profileField: 'householdSnapshotDate' })
    expect(deriveHousehold({ ...current, householdHistoryConfirmations: [{ criterionDate: '2026-09-29', unchanged: true }] }, cutoff).complete).toBe(false)
    expect(deriveHousehold({ ...current, householdHistoryConfirmations: [{ criterionDate: cutoff, unchanged: true }] }, cutoff).complete).toBe(true)
    expect(deriveHousehold({ ...current, householdHistoryConfirmations: [{ criterionDate: cutoff, unchanged: false }] }, cutoff).complete).toBe(false)
  })
  it('requires continuity when comparing a later cutoff than a roster snapshot', () => {
    expect(deriveHousehold(profile({ householdSnapshotDate: '2026-09-01' }), cutoff).complete).toBe(false)
    expect(deriveHousehold(profile({ householdSnapshotDate: '2026-09-01', householdCompositionUnchanged: true }), cutoff).complete).toBe(true)
  })
  it('keeps legal scope count separate from both legacy and income counts', () => {
    expect(deriveHousehold(profile({ householdSize: '99', incomeHouseholdSize: '7' }), cutoff).legalCount).toBe(1)
  })
  it('cannot turn v3 legal-scope selfanswers into a v4 roster', () => {
    const former = migrateProfile({ ...EMPTY_PROFILE, version: 3, householdScopeKnown: true, familyOnRegister: false, householdSize: '4', applicantOwnsHome: false, hasSpouse: false, householdMembersComplete: true })
    expect(former).toMatchObject({ version: 5, householdMembersComplete: null, householdMembers: [], householdSnapshotDate: '', householdSize: '4', incomeHouseholdSize: '', applicantOwnsHome: false, hasSpouse: false })
    expect(deriveHousehold(former, cutoff).complete).toBe(false)
  })
})
describe('ownership is linked to exact roster members', () => {
  const property = { ...createOwnershipFact('property'), ownerMemberId: 'parent', ownerRelation: 'ascendant' as const, propertyKind: 'apartment' as const, areaSqm: '84', acquiredDate: '2020-01-01', acquisitionMethod: 'purchase' as const, standardResidentialBuilding: true }
  const context = { criterionDate: cutoff, assessmentDate: '2026-10-04', supplyType: '일반공급' }
  it('uses the linked parent DOB for general exemption but not elder-parent supply', () => {
    const person = profile({ householdMembers: [{ ...member('applicant_parent', 'applicant', 'parent'), dateOfBirth: '1950-01-01', ownsHome: true }], ownershipFactsKnown: true, ownershipFacts: [property] })
    expect(evaluateHouseholdOwnership(person, context).value).toBe(true)
    expect(evaluateHouseholdOwnership(person, { ...context, supplyType: '노부모부양 특별공급' }).value).toBe(false)
  })
  it('excludes an exact sibling property but refuses a former broad parent owner', () => {
    const sibling = profile({ householdMembers: [{ ...member('sibling', 'applicant', 'parent'), ownsHome: true }], ownershipFactsKnown: true, ownershipFacts: [property] })
    expect(evaluateHouseholdOwnership(sibling, context)).toMatchObject({ value: true, countedHomes: 0 })
    expect(evaluateHouseholdOwnership({ ...sibling, ownershipFacts: [{ ...property, ownerMemberId: '' }] }, context)).toMatchObject({ value: null, profileField: 'ownershipFacts' })
  })
  it('asks the actual unknown relative ownership question and rejects inconsistent DOBs', () => {
    const person = profile({ householdMembers: [{ ...member('applicant_parent', 'applicant', 'parent'), ownsHome: null }] })
    expect(evaluateHouseholdOwnership(person, context)).toMatchObject({ value: null, profileField: 'householdMembers' })
    expect(evaluateHouseholdOwnership({ ...person, householdMembers: [{ ...person.householdMembers[0], dateOfBirth: '1950-01-01', ownsHome: true }], ownershipFactsKnown: true, ownershipFacts: [{ ...property, ownerDateOfBirth: '1970-01-01' }] }, context).value).toBeNull()
  })
})

describe('complete property list is not a substitute for missing member ownership facts', () => {
  const context = { criterionDate: cutoff, supplyType: '일반공급' }
  it('keeps an unentered applicant or family ownership unknown even when the list was acknowledged complete', () => {
    expect(evaluateHouseholdOwnership(profile({ applicantOwnsHome: null, ownershipFactsKnown: true, ownershipFacts: [] }), context)).toMatchObject({ value: null, profileField: 'applicantOwnsHome' })
    const parent = { ...member('applicant_parent', 'applicant', 'parent'), ownsHome: null }
    expect(evaluateHouseholdOwnership(profile({ householdMembers: [parent], ownershipFactsKnown: true, ownershipFacts: [] }), context)).toMatchObject({ value: null, profileField: 'householdMembers' })
  })
})
