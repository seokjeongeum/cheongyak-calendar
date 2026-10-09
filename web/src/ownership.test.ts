import { describe, expect, it } from 'vitest'
import { createOwnershipFact, EMPTY_PROFILE, type OwnershipFact } from './types'
import { setEvaluationToday } from './factTimeline'
import { evaluatePropertyOwnership, evaluateHouseholdOwnership, ownershipInventoryComplete, ownershipMemberInventoryComplete } from './ownership'
const context = { criterionDate: '2026-09-30', assessmentDate: '2026-10-04', supplyType: '일반공급' }
const fact = (extra: Partial<OwnershipFact> = {}) => ({ ...createOwnershipFact('dwelling-1'), ownerRelation: 'applicant' as const, propertyKind: 'apartment' as const, areaSqm: '84', propertyRegionCode: '41', acquiredDate: '2020-01-01', acquisitionMethod: 'purchase' as const, abandonedOrDestroyedOrNonResidential: false, oldLawUnauthorized: false, ...extra })
const evaluate = (extra: Partial<OwnershipFact>, count = 1, ctx = context) => evaluatePropertyOwnership(fact(extra), ctx, count)
describe('Article 53 twelve factual exceptions, effective 2026-06-15', () => {
  it('1 requires inherited share actually disposed within three calendar months', () => {
    expect(evaluate({ acquisitionMethod: 'inheritance', ownedShare: true, inheritedShare: true, notificationDate: '2026-09-01', disposedDate: '2026-10-03' })).toMatchObject({ counted: false, clause: 1 })
    expect(evaluate({ acquisitionMethod: 'inheritance', ownedShare: true, inheritedShare: true, notificationDate: '2026-09-01', disposedDate: '2026-11-01' })).toMatchObject({ counted: null, clause: 1 })
    expect(evaluate({ acquisitionMethod: 'inheritance', ownedShare: true, inheritedShare: true, notificationDate: '2026-06-01', disposedDate: '2026-10-03' }).counted).toBe(true)
  })
  it('1 uses exact month-end deadline and rejects a disposal before notification', () => {
    const ctx = { ...context, criterionDate: '2026-06-15', assessmentDate: '2026-07-01' }
    expect(evaluate({ acquisitionMethod: 'inheritance', inheritedShare: true, ownedShare: true, notificationDate: '2026-03-31', disposedDate: '2026-06-30' }, 1, ctx).clause).toBe(1)
    expect(evaluate({ acquisitionMethod: 'inheritance', inheritedShare: true, ownedShare: true, notificationDate: '2026-09-30', disposedDate: '2026-09-29' })).toMatchObject({ counted: false, clause: null })
  })
  it('2 requires non-capital rural detached residence and move plus one qualifying alternative', () => {
    expect(evaluate({ propertyKind: 'detached', propertyRegionCode: '47', outsideUrbanArea: true, ownerPreviouslyResided: true, movedToOtherConstructionArea: true })).toMatchObject({ counted: false, clause: 2 })
    expect(evaluate({ propertyKind: 'detached', propertyRegionCode: '41', outsideUrbanArea: true, ownerPreviouslyResided: true, movedToOtherConstructionArea: true, officialValueKrw: '700000000', valueBasis: 'annex1_official', valueAsOfDate: '2026-04-30' }).counted).toBe(true)
    expect(evaluate({ propertyKind: 'detached', propertyRegionCode: '47', outsideUrbanArea: true, ownerPreviouslyResided: true, movedToOtherConstructionArea: null }).counted).toBeNull()
  })
  it('3 requires completed developer sale or timely actual disposal', () => {
    expect(evaluate({ acquisitionMethod: 'construction', builderForSale: true, saleCompleted: true })).toMatchObject({ counted: false, clause: 3 })
    expect(evaluate({ acquisitionMethod: 'construction', builderForSale: true, saleCompleted: false, notificationDate: '2026-09-01', disposedDate: '' }).counted).toBeNull()
  })
  it('4 recognizes statutory employee housing, not a business-registration claim alone', () => {
    expect(evaluate({ individualBusinessRegistered: true, employeeDormitoryUnderHousingAct: true })).toMatchObject({ counted: false, clause: 4 })
    expect(evaluate({ governmentEmployeeHousingPolicy: true })).toMatchObject({ counted: false, clause: 4 })
    expect(evaluate({ individualBusinessRegistered: true }).counted).toBe(true)
  })
  it('5 recognizes only one household dwelling/right with area at most20', () => {
    expect(evaluate({ areaSqm: '20' })).toMatchObject({ counted: false, clause: 5 })
    expect(evaluate({ areaSqm: '20' }, 2).counted).toBe(true)
  })
  it('6 ancestor aged60 is exempt generally but counted for elder-parent/public-rental', () => {
    const owner = { ownerRelation: 'ascendant' as const, ownerDateOfBirth: '1966-09-30' }
    expect(evaluate(owner)).toMatchObject({ counted: false, clause: 6 })
    expect(evaluate(owner, 1, { ...context, supplyType: '노부모부양 특별공급' }).counted).toBe(true)
    expect(evaluatePropertyOwnership(fact(owner), { ...context, publicRental: true }, 1).counted).toBe(true)
    expect(evaluate({ ...owner, ownerDateOfBirth: '1966-10-01' }).counted).toBe(true)
  })
  it('7 requires actual correction within3months; a planned correction stays pending', () => {
    expect(evaluate({ abandonedOrDestroyedOrNonResidential: true, notificationDate: '2026-09-01', registerCorrectedDate: '2026-10-03' })).toMatchObject({ counted: false, clause: 7 })
    expect(evaluate({ abandonedOrDestroyedOrNonResidential: true, notificationDate: '2026-09-01', registerCorrectedDate: '2026-10-10' }).counted).toBeNull()
  })
  it('8 requires former-law lawful-construction proof', () => {
    expect(evaluate({ oldLawUnauthorized: true, lawfulAtConstructionEvidence: true })).toMatchObject({ counted: false, clause: 8 })
    expect(evaluate({ oldLawUnauthorized: true, lawfulAtConstructionEvidence: null }).counted).toBeNull()
    expect(evaluate({ oldLawUnauthorized: true, lawfulAtConstructionEvidence: false }).counted).toBe(true)
  })
  it('9 compares type-specific area/price, official basis and household count', () => {
    const price = { areaSqm: '60', valueBasis: 'annex1_official' as const, officialValueKrw: '160000000', valueAsOfDate: '2026-04-30' }
    expect(evaluate(price)).toMatchObject({ counted: false, clause: 9 })
    expect(evaluate({ ...price, officialValueKrw: '160000001' }).counted).toBe(true)
    expect(evaluate({ ...price, valueBasis: 'market' }).counted).toBeNull()
    expect(evaluate({ ...price, propertyKind: 'multi_family', areaSqm: '85', officialValueKrw: '500000000' })).toMatchObject({ counted: false, clause: 9 })
    expect(evaluate(price, 2).counted).toBe(true)
    expect(evaluatePropertyOwnership(fact(price), { ...context, publicRental: true }, 1).counted).toBe(true)
  })
  it('10 requires an original residual first-come right, excluding resale', () => {
    expect(evaluate({ propertyKind: 'presale_right', underlyingPropertyKind: 'apartment', acquisitionMethod: 'first_come', originalResidualFirstCome: true })).toMatchObject({ counted: false, clause: 10 })
    expect(evaluate({ propertyKind: 'presale_right', underlyingPropertyKind: 'apartment', acquisitionMethod: 'purchase', originalResidualFirstCome: true }).counted).toBe(true)
  })
  it('11 requires unpaiddeposit+auction and area/value; publicrental excluded', () => {
    const auction = { acquisitionMethod: 'auction' as const, unpaidRentalDeposit: true, auctionAcquisition: true, officialValueKrw: '300000000', valueBasis: 'annex1_official' as const, valueAsOfDate: '2026-04-30' }
    expect(evaluate(auction)).toMatchObject({ counted: false, clause: 11 })
    expect(evaluate({ ...auction, areaSqm: '85.01' }).counted).toBe(true)
    expect(evaluatePropertyOwnership(fact(auction), { ...context, publicRental: true }, 1).counted).toBe(true)
  })
  it('12 requires2024first-ever tenant purchase and onefull year through prior day', () => {
    const tenant = { propertyKind: 'multi_family' as const, acquiredDate: '2024-03-01', areaSqm: '60', firstEverAcquisition: true, acquisitionPriceKrw: '300000000', tenantResidenceStartDate: '2023-02-28', officialValueKrw: '600000000', valueBasis: 'annex1_official' as const, valueAsOfDate: '2026-04-30' }
    expect(evaluate(tenant)).toMatchObject({ counted: false, clause: 12 })
    expect(evaluate({ ...tenant, tenantResidenceStartDate: '2023-03-01' }).counted).toBe(true)
    expect(evaluate({ ...tenant, acquiredDate: '2025-01-01' }).counted).toBe(true)
    expect(evaluate({ ...tenant, propertyKind: 'apartment' }).counted).toBe(true)
  })
  it('does not apply current law before its effective date or misread dates', () => {
    expect(evaluate({}, 1, { ...context, criterionDate: '2026-06-14' }).counted).toBeNull()
    expect(evaluate({ acquiredDate: '2026-02-30' }).counted).toBeNull()
    expect(evaluate({ disposedDate: '2019-12-01' }).counted).toBeNull()
    expect(evaluate({ disposedDate: '2026-09-01' }).counted).toBe(false)
  })
  it('compares announcement ownership, not future acquisition', () => {
    expect(evaluate({ acquiredDate: '2026-10-01' }).counted).toBe(false)
    expect(evaluate({ propertyKind: 'officetel' }).counted).toBe(false)
  })
  it('normal residential building facts settle general ownership without asking all obscure exception paths', () => {
    const normal = { ...createOwnershipFact('ordinary'), ownerRelation: 'applicant' as const, propertyKind: 'apartment' as const, areaSqm: '84', acquiredDate: '2025-01-01', acquisitionMethod: 'purchase' as const, standardResidentialBuilding: true }
    expect(evaluatePropertyOwnership(normal, context, 1)).toMatchObject({ counted: true, missingFields: [] })
  })
  it('unknown acquisition method is a factual question, not a definitive owned decision', () => {
    expect(evaluate({ acquisitionMethod: 'unknown' })).toMatchObject({ counted: null, missingFields: ['acquisitionMethod'] })
  })
})
describe('household ownership factual completeness', () => {
  const person = { ...EMPTY_PROFILE, applicantOnRegister: true, hasSpouse: false, householdMembersComplete: true, householdSnapshotDate: context.criterionDate, applicantOwnsHome: true, ownershipFactsKnown: true, ownershipFacts: [fact()] }
  it('uses facts and never promotes legacy ownershipException', () => {
    expect(evaluateHouseholdOwnership({ ...person, ownershipException: true }, context).value).toBe(false)
    expect(evaluateHouseholdOwnership({ ...person, ownershipFactsKnown: null, ownershipException: false }, context).value).toBeNull()
  })
  it('preserves a specific extra fact question and legal source', () => {
    const result = evaluateHouseholdOwnership({ ...person, ownershipFacts: [fact({ areaSqm: '59' })] }, context)
    expect(result.value).toBeNull()
    expect(result.properties[0].missingFields).toContain('valueBasis')
    expect(result.profileField).toBe('ownershipFacts')
  })
  it('does not claim ownership list complete if knownheldproperty hasnoentry', () => {
    expect(evaluateHouseholdOwnership({ ...person, ownershipFacts: [] }, context).value).toBeNull()
    expect(evaluateHouseholdOwnership({ ...person, ownershipFactsKnown: null, applicantOwnsHome: false, ownershipFacts: [] }, context).value).toBe(true)
    expect(evaluateHouseholdOwnership({ ...person, ownershipFactsKnown: null, applicantOwnsHome: false }, context).value).toBeNull()
  })
  it('treats each rawhousehold dwellingasone foronehouseholdonly exceptions', () => {
    const small = fact({ areaSqm: '20' })
    expect(evaluateHouseholdOwnership({ ...person, ownershipFacts: [small, { ...small, id: 'second' }] }, context).value).toBe(false)
  })
  it('reviews shared owner records that may describe one 20sqm household dwelling', () => {
    const small = fact({ areaSqm: '20', ownedShare: true })
    const profile = { ...person, hasSpouse: true, maritalStatus: 'married' as const, spouseOwnsHome: true,
      ownershipFacts: [small, { ...small, id: 'spouse-share', ownerRelation: 'spouse' as const, ownerMemberId: 'spouse' }] }
    const result = evaluateHouseholdOwnership(profile, context)
    expect(result).toMatchObject({ value: null, countedHomes: null, profileField: 'ownershipFacts' })
    expect(result.properties.every((property) => property.counted === null && property.clause === 5)).toBe(true)
    expect(result.detail).toContain('같은 한 주택인지 여러 주택인지')
  })
  it('reviews sole low-price exemption when shared records lack physical dwelling identity', () => {
    const small = fact({ areaSqm: '60', ownedShare: true, valueBasis: 'annex1_official', officialValueKrw: '160000000', valueAsOfDate: '2026-04-30' })
    const profile = { ...person, hasSpouse: true, maritalStatus: 'married' as const, spouseOwnsHome: true,
      ownershipFacts: [small, { ...small, id: 'spouse-share', ownerRelation: 'spouse' as const, ownerMemberId: 'spouse' }] }
    const result = evaluateHouseholdOwnership(profile, context)
    expect(result).toMatchObject({ value: null, countedHomes: null })
    expect(result.properties.every((property) => property.counted === null && property.clause === 9)).toBe(true)
    expect(evaluateHouseholdOwnership({ ...profile, ownershipFacts: profile.ownershipFacts.map((property) => ({ ...property, officialValueKrw: '160000001' })) }, context).value).toBe(false)
  })
  it('keeps counted ordinary shared homes and separate sole-title homes definitive', () => {
    const ordinary = fact({ ownedShare: true })
    expect(evaluateHouseholdOwnership({ ...person, ownershipFacts: [ordinary, { ...ordinary, id: 'second' }] }, context).value).toBe(false)
    const small = fact({ areaSqm: '20', ownedShare: true })
    expect(evaluateHouseholdOwnership({ ...person, ownershipFacts: [small, { ...small, id: 'sole-title', ownedShare: false }] }, context).value).toBe(false)
  })
  it('preserves the 60-plus ancestor exemption despite shared dwelling ambiguity', () => {
    const parents = ['parent-1', 'parent-2'].map((id) => ({ id, relation: 'applicant_parent' as const, register: 'applicant' as const, dateOfBirth: '1950-01-01', ownsHome: true, previouslyOwnedHome: null }))
    const properties = parents.map((parent) => fact({ id: `${parent.id}-share`, ownerMemberId: parent.id, ownerRelation: 'ascendant', ownerDateOfBirth: parent.dateOfBirth, ownedShare: true, areaSqm: '20' }))
    const result = evaluateHouseholdOwnership({ ...person, applicantOwnsHome: false, householdMembers: parents, ownershipFacts: properties }, context)
    expect(result).toMatchObject({ value: true, countedHomes: 0 })
    expect(result.properties.every((property) => property.counted === false && property.clause === 6)).toBe(true)
  })
  it('requires factual records for every declared owner group, not a different exempt parent only', () => {
    const parent = fact({ ownerMemberId: 'parent', ownerRelation: 'ascendant', ownerDateOfBirth: '1950-01-01' })
    const result = evaluateHouseholdOwnership({ ...person, householdMembers: [{ id: 'parent', relation: 'applicant_parent', register: 'applicant', dateOfBirth: '1950-01-01', ownsHome: true, previouslyOwnedHome: null }], ownershipFacts: [parent] }, context)
    expect(result).toMatchObject({ value: null, profileField: 'ownershipFacts' })
    expect(result.detail).toContain('본인')
  })
})

describe('factual ownership counts instead of completion confirmations', () => {
  const today = '2026-10-09'
  const stable = { household: { mode: 'never_changed' as const, date: '' } }
  const person = { ...EMPTY_PROFILE, applicantOnRegister: true, hasSpouse: false, householdMembersComplete: true, applicantOwnsHome: true, ownershipFactsKnown: null, factChanges: stable, ownershipFacts: [fact({ areaSqm: '20' })], ownershipPropertyCounts: { applicant: '1' } }
  const ctx = { ...context, assessmentDate: today }

  it('accepts one declared dwelling with linked dated facts without an all-added checkbox', () => {
    setEvaluationToday(today)
    expect(ownershipInventoryComplete(person)).toBe(true)
    expect(evaluateHouseholdOwnership(person, ctx)).toMatchObject({ value: true, countedHomes: 0 })
    expect(evaluateHouseholdOwnership({ ...person, ownershipFactsKnown: false }, ctx).value).toBe(true)
  })

  it('does not grant one-home exceptions from one row when another declared home is missing', () => {
    setEvaluationToday(today)
    const missing = { ...person, ownershipPropertyCounts: { applicant: '2' } }
    expect(ownershipInventoryComplete(missing)).toBe(false)
    expect(evaluateHouseholdOwnership(missing, ctx)).toMatchObject({ value: null, profileField: 'ownershipFacts' })
    expect(evaluateHouseholdOwnership({ ...missing, ownershipFactsKnown: true }, ctx).value).toBeNull()
    expect(evaluateHouseholdOwnership({ ...missing, ownershipFacts: [person.ownershipFacts[0], { ...person.ownershipFacts[0], id: 'second' }] }, ctx).value).toBe(false)
  })

  it('reconstructs an earlier owned home from a complete current zero and a real disposal', () => {
    setEvaluationToday(today)
    const disposed = { ...person, applicantOwnsHome: false, ownershipPropertyCounts: { applicant: '0' }, ownershipFacts: [fact({ disposedDate: '2026-10-05' })] }
    expect(ownershipInventoryComplete(disposed)).toBe(true)
    expect(evaluateHouseholdOwnership(disposed, { ...ctx, criterionDate: '2026-10-02' }).value).toBe(false)
    expect(evaluateHouseholdOwnership(disposed, { ...ctx, criterionDate: today }).value).toBe(true)
    expect(ownershipMemberInventoryComplete(disposed, 'applicant', '2026-10-02')).toBe(false)
  })

  it('validates historical snapshot counts on their own day and current counts on today', () => {
    setEvaluationToday(today)
    const snapshot = { ...person, ownershipFacts: [fact({ disposedDate: '2026-10-05' })] }
    expect(evaluateHouseholdOwnership(snapshot, { ...ctx, criterionDate: '2026-10-02', inventoryDate: '2026-10-02' }).value).toBe(false)
    expect(evaluateHouseholdOwnership(snapshot, { ...ctx, criterionDate: '2026-10-02' }).value).toBeNull()
  })

  it('keeps another person’s unknown ownership unresolved, even with a declared zero', () => {
    setEvaluationToday(today)
    const unknown = { ...person, hasSpouse: true, maritalStatus: 'married' as const, spouseOwnsHome: null, ownershipPropertyCounts: { applicant: '1', spouse: '0' } }
    expect(ownershipInventoryComplete(unknown)).toBe(false)
    expect(evaluateHouseholdOwnership(unknown, ctx)).toMatchObject({ value: null, profileField: 'spouseOwnsHome' })
  })

  it('keeps a shared household dwelling unresolved until physical identity is known', () => {
    setEvaluationToday(today)
    const shared = { ...person, hasSpouse: true, maritalStatus: 'married' as const, spouseOwnsHome: true, ownershipPropertyCounts: { applicant: '1', spouse: '1' }, ownershipFacts: [{ ...person.ownershipFacts[0], ownedShare: true }, { ...person.ownershipFacts[0], id: 'spouse-share', ownerRelation: 'spouse' as const, ownerMemberId: 'spouse', ownedShare: true }] }
    expect(ownershipInventoryComplete(shared)).toBe(true)
    expect(evaluateHouseholdOwnership(shared, ctx)).toMatchObject({ value: null, countedHomes: null })
  })
})
