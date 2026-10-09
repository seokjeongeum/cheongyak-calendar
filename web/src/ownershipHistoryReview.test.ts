import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { factsAtDate, setEvaluationToday } from './factTimeline'
import { deriveHousehold } from './household'
import { evaluateRule } from './qualification'
import { EMPTY_PROFILE, createHouseholdMember, createOwnershipFact, type LocalProfile, type Notice, type NoticeRule } from './types'

const today = '2026-10-09', cutoff = '2026-09-30'
const condition: NoticeRule = { kind: 'homeless', value: true, verification: 'official', evidence_url: 'https://example.com/official.pdf', criterion_date: cutoff }
const notice: Notice = { id: 'recorded-history', title: '공식 과거 공고', category: 'apt', source: 'cheongyak_home', provider: '청약홈', address: null, region_code: null, region_name: null, announcement_date: cutoff, official_url: condition.evidence_url!, price_cap_status: 'unknown', events: [], prices: [], rules: [condition], updated_at: null, version: 1 }
const profile = (part: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, applicantOnRegister: true, hasSpouse: false, maritalStatus: 'single', applicantOwnsHome: false, additionalFamilyPresence: false, householdMembersComplete: null, ownershipPropertyCounts: { applicant: '0' }, factChanges: { household: { mode: 'never_changed', date: '' } }, ...part })
const home = (id: string, ownerMemberId = 'applicant') => ({ ...createOwnershipFact(id), ownerMemberId, ownerRelation: ownerMemberId === 'applicant' ? 'applicant' as const : 'ascendant' as const, propertyKind: 'apartment' as const, acquiredDate: '2020-01-01', disposedDate: '2026-10-05', areaSqm: '84', standardResidentialBuilding: true, acquisitionMethod: 'purchase' as const })
beforeEach(() => setEvaluationToday(today))
afterEach(() => setEvaluationToday(null))

describe('ownership inventory and roster facts use their recorded day', () => {
  it('compares historical one-home counts at the snapshot day after a later disposal', () => {
    const property = home('disposed')
    const recorded = profile({ ownershipFacts: [property], factSnapshots: [{ group: 'ownership', date: cutoff, values: { applicantOwnsHome: true, ownershipFacts: [property], ownershipPropertyCounts: { applicant: '1' } } }] })
    expect(evaluateRule(condition, recorded, notice)).toMatchObject({ status: 'fail' })
  })
  it('uses a former family member in both past household scope and past ownership inventory', () => {
    const parent = { ...createHouseholdMember('former-parent'), relation: 'applicant_parent' as const, register: 'applicant' as const, dateOfBirth: '1970-01-01', ownsHome: true }
    const property = { ...home('parent-home', parent.id), disposedDate: '', ownerDateOfBirth: parent.dateOfBirth }
    const recorded = profile({ factSnapshots: [
      { group: 'household', date: cutoff, values: { applicantOnRegister: true, hasSpouse: false, maritalStatus: 'single', householdMembers: [parent], additionalFamilyPresence: true, householdMembersComplete: null } },
      { group: 'ownership', date: cutoff, values: { applicantOwnsHome: false, ownershipFacts: [property], ownershipPropertyCounts: { applicant: '0', [parent.id]: '1' } } },
    ] })
    expect(deriveHousehold(recorded, cutoff)).toMatchObject({ complete: true, legalCount: 2 })
    expect(evaluateRule(condition, recorded, notice)).toMatchObject({ status: 'fail' })
  })
  it('uses an exact recorded ownership answer even when today’s ownership has not been entered', () => {
    const recorded = profile({ applicantOwnsHome: null, ownershipPropertyCounts: {}, factSnapshots: [{ group: 'ownership', date: cutoff, values: { applicantOwnsHome: false, ownershipFacts: [], ownershipPropertyCounts: { applicant: '0' } } }] })
    expect(evaluateRule(condition, recorded, notice)).toMatchObject({ status: 'pass' })
  })
  it('does not import today’s added roster absence or numeric count into an older snapshot', () => {
    const recorded = profile({ ownershipPropertyCounts: { applicant: '1' }, factSnapshots: [
      { group: 'household', date: cutoff, values: { applicantOnRegister: true, hasSpouse: false, maritalStatus: 'single', householdMembers: [], householdMembersComplete: null } },
      { group: 'ownership', date: cutoff, values: { applicantOwnsHome: true, ownershipFacts: [home('old-home')] } },
    ] })
    expect(factsAtDate(recorded, 'household', cutoff).profile.additionalFamilyPresence).toBeNull()
    expect(deriveHousehold(recorded, cutoff)).toMatchObject({ complete: false, profileField: 'additionalFamilyPresence' })
    expect(factsAtDate(recorded, 'ownership', cutoff).profile.ownershipPropertyCounts).toEqual({})
  })
  it('retains an earlier explicit empty family roster without a fresh completion answer', () => {
    const recorded = profile({ additionalFamilyPresence: true, factSnapshots: [{ group: 'household', date: cutoff, values: { applicantOnRegister: true, hasSpouse: false, maritalStatus: 'single', householdMembers: [], householdMembersComplete: true } }] })
    expect(deriveHousehold(recorded, cutoff)).toMatchObject({ complete: true, legalCount: 1 })
  })
  it('does not borrow today’s old-style inventory declaration for a partial past ownership snapshot', () => {
    const property = { ...home('small-home'), areaSqm: '20', disposedDate: '' }
    const recorded = profile({ applicantOwnsHome: true, ownershipFactsKnown: true, ownershipFacts: [property], ownershipPropertyCounts: { applicant: '1' }, factSnapshots: [{ group: 'ownership', date: cutoff, values: { applicantOwnsHome: true, ownershipFacts: [property] } }] })
    expect(evaluateRule(condition, recorded, notice)).toMatchObject({ status: 'review' })
  })
  it('does not borrow today’s old empty-roster declaration for an unconfirmed older empty roster', () => {
    const recorded = profile({ householdMembersComplete: true, factSnapshots: [{ group: 'household', date: cutoff, values: { applicantOnRegister: true, hasSpouse: false, maritalStatus: 'single', householdMembers: [] } }] })
    expect(deriveHousehold(recorded, cutoff)).toMatchObject({ complete: false, profileField: 'additionalFamilyPresence' })
  })
})
