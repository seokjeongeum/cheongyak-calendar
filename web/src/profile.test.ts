import { afterEach, describe, expect, it, vi } from 'vitest'
import { EMPTY_PROFILE, createOwnershipFact } from './types'
import {
  LEGACY_PROFILE_STORAGE_KEY, PROFILE_STORAGE_KEY, migrateProfile, readProfile,
  selectDistrict, selectProvince, updateProfileFacts,
} from './profile'

afterEach(() => vi.unstubAllGlobals())

describe('versioned browser profile migration', () => {
  it('preserves v1 factual residence and amounts without inventing qualification facts', () => {
    const result = migrateProfile({
      region: '경기도', district: '수원시 영통구', movedInDate: '2018-03-15', householdSize: '3',
      annualIncomeKrw: '60,000,000', assetsKrw: '120000000', homeless: true,
      subscriptionMonths: '120', subscriptionRank: 'first', specialEligibility: true, specialCategory: '신혼부부',
    })
    expect(result).toMatchObject({
      version: 5, region: '경기도', regionCode: '41', district: '수원시', districtCode: '41110',
      movedInDate: '2018-03-15', districtMovedInDate: '', cityMovedInDate: '', householdSize: '3',
      annualIncomeKrw: '60000000', assetsKrw: '120000000', regionNeedsReview: false,
      privateRankBaseDate: '', nationalRankBaseDate: '', accountType: 'unknown',
      applicantOwnsHome: null, spouseOwnsHome: null, familyOwnsHome: null,
      maritalStatus: 'unknown', recommendationStatus: 'unknown',
    })
    for (const legacy of ['homeless', 'subscriptionMonths', 'subscriptionRank', 'specialEligibility', 'specialCategory']) {
      expect(Object.hasOwn(result, legacy)).toBe(false)
    }
  })

  it('requires re-selection for a nonexact district and preserves the former text for explanation', () => {
    const result = migrateProfile({ region: '경기도', district: '영통구', movedInDate: '2020-01-01' })
    expect(result).toMatchObject({ region: '경기도', regionCode: '41', district: '영통구', districtCode: '', regionNeedsReview: true, movedInDate: '2020-01-01', districtMovedInDate: '' })
  })

  it('does not move a former merged province or split district into an assumed new territory', () => {
    expect(migrateProfile({ region: '광주광역시', district: '북구' })).toMatchObject({ regionCode: '', districtCode: '', regionNeedsReview: true })
    expect(migrateProfile({ region: '인천광역시', district: '중구' })).toMatchObject({ regionCode: '28', districtCode: '', regionNeedsReview: true })
  })

  it('restores v2 facts and children while removing obsolete self-assessments and unknown fields', () => {
    const result = migrateProfile({ ...EMPTY_PROFILE, region: '서울특별시', district: '종로구', regionCode: 'bogus', districtCode: 'bogus',
      districtMovedInDate: '2020-07-01', privateRankBaseDate: '2017-04-01', nationalRankBaseDate: '2018-02-01',
      privateDepositKrw: '3,000,000', nationalRecognizedAmountKrw: '24,000,000', nationalRecognizedPayments: '48',
      children: [{ dateOfBirth: '2020-05-10', adopted: true }, { dateOfBirth: '2024-04-02' }, null, { adopted: false }],
      applicantOwnsHome: false, hasSpouse: true, spouseOwnsHome: false, dualIncome: true,
      subscriptionRank: 'first', specialEligibility: false, accidentalServerId: 'never-copy',
    })
    expect(result).toMatchObject({ regionCode: '11', districtCode: '11110', districtMovedInDate: '2020-07-01',
      privateRankBaseDate: '2017-04-01', nationalRankBaseDate: '2018-02-01', privateDepositKrw: '3000000',
      nationalRecognizedAmountKrw: '24000000', nationalRecognizedPayments: '48', applicantOwnsHome: false,
      hasSpouse: true, spouseOwnsHome: false, dualIncome: true,
      children: [{ dateOfBirth: '2020-05-10', adopted: true }, { dateOfBirth: '2024-04-02', adopted: null }],
    })
    expect(Object.hasOwn(result, 'accidentalServerId')).toBe(false)
    expect(Object.hasOwn(result, 'subscriptionRank')).toBe(false)
    expect(Object.hasOwn(result, 'specialEligibility')).toBe(false)
  })

  it('does not accept invalid boolean facts, enums, or monetary values from stored JSON', () => {
    const result = migrateProfile({ ...EMPTY_PROFILE, applicantOwnsHome: 'false', hasSpouse: 1,
      accountType: 'first', maritalStatus: 'yes', recommendationStatus: 'approved',
      privateDepositKrw: '-3000000', annualIncomeKrw: '60 million', assetsKrw: '9007199254740992',
    })
    expect(result).toMatchObject({ applicantOwnsHome: null, hasSpouse: null, accountType: 'unknown',
      maritalStatus: 'unknown', recommendationStatus: 'unknown', privateDepositKrw: '', annualIncomeKrw: '', assetsKrw: '' })
  })

  it('uses independent child lists for empty or malformed profiles', () => {
    const first = migrateProfile(null)
    first.children.push({ dateOfBirth: '2020-01-01', adopted: false })
    expect(migrateProfile([]).children).toEqual([])
    expect(EMPTY_PROFILE.children).toEqual([])
  })

  it('migrates v2 facts without promoting its ownership exception answer or unversioned ownership list', () => {
    const former = { ...EMPTY_PROFILE, version: 2, applicantOwnsHome: true, ownershipException: true, ownershipFactsKnown: true, ownershipFacts: [createOwnershipFact('old')], privateDepositKrw: '3,000,000', region: '경기도', district: '수원시' }
    expect(migrateProfile(former)).toMatchObject({ version: 5, applicantOwnsHome: true, ownershipException: null, ownershipFactsKnown: null, ownershipFacts: [], privateDepositKrw: '3000000', regionCode: '41', districtCode: '41110' })
  })

  it('restores only sanitized v3 ownership facts and retains independent lists', () => {
    const stored = { ...EMPTY_PROFILE, ownershipFactsKnown: true, ownershipFacts: [{ ...createOwnershipFact('current'), officialValueKrw: '100,000,000', applicantSecret: 'drop', ownerRelation: 'wrong', lawfulAtConstructionEvidence: 'yes' }] }
    const result = migrateProfile(stored)
    expect(result.ownershipFacts).toHaveLength(1)
    expect(result.ownershipFacts[0]).toMatchObject({ officialValueKrw: '100000000', ownerRelation: 'unknown', lawfulAtConstructionEvidence: null })
    expect(Object.hasOwn(result.ownershipFacts[0], 'applicantSecret')).toBe(false)
    result.ownershipFacts.push(createOwnershipFact('new'))
    expect(migrateProfile(stored).ownershipFacts).toHaveLength(1)
  })

  it('reads the current browser profile in preference to the legacy storage key', () => {
    const values = new Map([
      [PROFILE_STORAGE_KEY, JSON.stringify({ ...EMPTY_PROFILE, region: '서울특별시', district: '종로구' })],
      [LEGACY_PROFILE_STORAGE_KEY, JSON.stringify({ region: '경기도', district: '수원시' })],
    ])
    const getItem = vi.fn((key: string) => values.get(key) || null)
    vi.stubGlobal('localStorage', { getItem })
    expect(readProfile()).toMatchObject({ region: '서울특별시', districtCode: '11110', version: 5 })
    expect(getItem).toHaveBeenCalledWith(PROFILE_STORAGE_KEY)
    expect(getItem).not.toHaveBeenCalledWith(LEGACY_PROFILE_STORAGE_KEY)
  })

  it('migrates the legacy browser key and recovers safely from broken JSON', () => {
    const getItem = vi.fn((key: string) => key === LEGACY_PROFILE_STORAGE_KEY ? JSON.stringify({ region: '경기도', district: '수원시' }) : null)
    vi.stubGlobal('localStorage', { getItem })
    expect(readProfile()).toMatchObject({ regionCode: '41', districtCode: '41110', version: 5 })
    vi.stubGlobal('localStorage', { getItem: () => 'not-json' })
    expect(readProfile()).toEqual(EMPTY_PROFILE)
  })
})

describe('province and district selections maintain separate residence dates', () => {
  const profile = migrateProfile({ ...EMPTY_PROFILE, region: '경기도', district: '수원시 영통구', movedInDate: '2010-01-01', districtMovedInDate: '2020-07-01', cityMovedInDate: '2015-03-01', annualIncomeKrw: '60000000', privateRankBaseDate: '2015-01-01' })

  it('resets both geographic clocks when the province changes and preserves unrelated facts', () => {
    expect(selectProvince(profile, '11')).toMatchObject({ region: '서울특별시', regionCode: '11',
      district: '', districtCode: '', movedInDate: '', districtMovedInDate: '', cityMovedInDate: '', regionNeedsReview: false,
      annualIncomeKrw: '60000000', privateRankBaseDate: '2015-01-01' })
    expect(profile).toMatchObject({ region: '경기도', movedInDate: '2010-01-01', districtMovedInDate: '2015-03-01', legacyDistrict: { code: '41117', movedInDate: '2020-07-01' } })
  })

  it('resets only the local clock when the selected city or district changes', () => {
    expect(selectDistrict(profile, '41113')).toMatchObject({ district: '수원시', districtCode: '41110',
      regionCode: '41', movedInDate: '2010-01-01', districtMovedInDate: '2015-03-01', cityMovedInDate: '2015-03-01', annualIncomeKrw: '60000000' })
  })

  it('does not accept a district from another province or keep its stale local date', () => {
    expect(selectDistrict(profile, '11110')).toMatchObject({ district: '', districtCode: '', districtMovedInDate: '', cityMovedInDate: '', regionCode: '41', movedInDate: '2010-01-01' })
  })

  it('clears the city clock on a move to a different city and transfers a parent city date to its child selection', () => {
    expect(selectDistrict(profile, '41597')).toMatchObject({ district: '화성시', districtMovedInDate: '', cityMovedInDate: '', movedInDate: '2010-01-01' })
    const parent = { ...profile, district: '수원시', districtCode: '41110', districtMovedInDate: '2015-03-01', cityMovedInDate: '' }
    expect(selectDistrict(parent, '41117')).toMatchObject({ district: '수원시', cityMovedInDate: '2015-03-01', districtMovedInDate: '2015-03-01' })
  })

  it('restores the known city continuity date when selecting a child district’s parent city', () => {
    expect(selectDistrict(profile, '41110')).toMatchObject({ district: '수원시', districtCode: '41110', districtMovedInDate: '2015-03-01', movedInDate: '2010-01-01' })
  })
})

describe('v4 exact family/profile migration and isolation', () => {
  it('preserves v3 residence/account/amount/ownership facts without inventing a family roster', () => {
    const former = { ...EMPTY_PROFILE, version: 3, region: '경기도', district: '수원시', hasSpouse: true, spouseSameRegister: false, householdScopeKnown: true, familyOnRegister: true, householdSize: '4', applicantOwnsHome: false, spouseOwnsHome: true, privateRankBaseDate: '2009-03-01', privateDepositKrw: '5,000,000', privateDepositAsOfDate: '2026-09-30', ownershipFactsKnown: true, ownershipFacts: [{ ...createOwnershipFact('spouse-house'), ownerRelation: 'spouse', propertyKind: 'apartment', acquiredDate: '2022-01-01' }, { ...createOwnershipFact('old-parent'), ownerRelation: 'ascendant', ownerDateOfBirth: '1950-01-01' }], householdMembersComplete: true, householdMembers: [{ id: 'do-not-promote', relation: 'applicant_parent', register: 'applicant' }] }
    const next = migrateProfile(former)
    expect(next).toMatchObject({ version: 5, hasSpouse: true, spouseSameRegister: false, householdScopeKnown: null, familyOnRegister: null, householdSize: '4', incomeHouseholdSize: '', privateRankBaseDate: '2009-03-01', privateDepositKrw: '5000000', privateDepositAsOfDate: '2026-09-30', ownershipFactsKnown: true, householdMembersComplete: null, householdMembers: [], householdHistoryConfirmations: [] })
    expect(next.ownershipFacts).toEqual(expect.arrayContaining([expect.objectContaining({ id: 'spouse-house', ownerMemberId: 'spouse', acquiredDate: '2022-01-01' }), expect.objectContaining({ id: 'old-parent', ownerMemberId: '', ownerDateOfBirth: '1950-01-01' })]))
  })
  it('restores only sanitized named-free member facts and keeps income size independent', () => {
    const stored = { ...EMPTY_PROFILE, applicantOnRegister: true, incomeHouseholdSize: '5', householdMembersComplete: true, householdSnapshotDate: '2026-09-30', householdMembers: [{ id: 'parent', relation: 'applicant_parent', register: 'spouse', dateOfBirth: '1950-03-01', ownsHome: false, previouslyOwnedHome: 'no', name: 'never-copy' }, { id: 'bad', relation: 'dependent', register: 'foreign', ownsHome: 'yes' }], householdHistoryConfirmations: [{ criterionDate: '2026-09-29', unchanged: true }, null, { criterionDate: 'yesterday', unchanged: true }] }
    const next = migrateProfile(stored)
    expect(next.householdMembers[0]).toEqual({ id: 'parent', relation: 'applicant_parent', register: 'spouse', dateOfBirth: '1950-03-01', ownsHome: false, previouslyOwnedHome: null })
    expect(next.householdMembers[1]).toMatchObject({ relation: 'unknown', register: 'unknown', ownsHome: null })
    expect(next.householdHistoryConfirmations).toEqual([{ criterionDate: '2026-09-29', unchanged: true }])
    expect(next.incomeHouseholdSize).toBe('5')
    next.householdMembers.push({ id: 'new', relation: 'sibling', register: 'applicant', dateOfBirth: '', ownsHome: null, previouslyOwnedHome: null })
    expect(migrateProfile(stored).householdMembers).toHaveLength(2)
  })
  it('keeps project and scope records exact and discards unrecognized personal fields', () => {
    const next = migrateProfile({ ...EMPTY_PROFILE, projectApplicationHistory: { '2026000323': { winning: false, contract: false, additionalResident: false, winningScope: 'applicant', contractScope: 'applicant', asOfDate: '2026-10-01', historyConfirmations: [], name: 'drop' }, other: { winning: false } }, applicationRestrictionFacts: { applicant: { ineligibleRestrictionActive: false, resaleRestrictionActive: 'false', rewinningRestrictionActive: null, asOfDate: '2026-10-01', historyConfirmations: [{ criterionDate: '2026-09-30', unchanged: true }] }, all: { ineligibleRestrictionActive: false } }, citizenship: 'eligible', overseasContinuousDays: '0' })
    expect(Object.keys(next.projectApplicationHistory)).toEqual(['2026000323'])
    expect(Object.hasOwn(next.projectApplicationHistory['2026000323'], 'name')).toBe(false)
    expect(next.applicationRestrictionFacts).toEqual({ applicant: { ineligibleRestrictionActive: false, resaleRestrictionActive: null, rewinningRestrictionActive: null, asOfDate: '2026-10-01', historyConfirmations: [{ criterionDate: '2026-09-30', unchanged: true }] } })
    expect(next.citizenship).toBe('unknown')
    next.projectApplicationHistory['2026000323'].winning = true
    expect(EMPTY_PROFILE.projectApplicationHistory).toEqual({})
  })
})

describe('family fact changes invalidate composition snapshots centrally', () => {
  const current = { ...EMPTY_PROFILE, applicantOnRegister: true, hasSpouse: false, maritalStatus: 'single' as const, householdMembersComplete: true, householdSnapshotDate: '2026-09-30', householdCompositionUnchanged: true, householdHistoryConfirmations: [{ criterionDate: '2026-09-23', unchanged: true }], previousWinning: false }
  it('synchronizes an explicit legal spouse fact and invalidates older confirmations', () => {
    expect(updateProfileFacts(current, { hasSpouse: true }, '2026-10-04')).toMatchObject({ hasSpouse: true, maritalStatus: 'married', householdMembersComplete: null, householdSnapshotDate: '2026-10-04', householdCompositionUnchanged: null, householdHistoryConfirmations: [], previousWinning: false })
  })
  it('also resets snapshots when the marital-status question changes spouse presence', () => {
    expect(updateProfileFacts(current, { maritalStatus: 'married' }, '2026-10-04')).toMatchObject({ hasSpouse: true, maritalStatus: 'married', householdMembersComplete: null, householdHistoryConfirmations: [] })
    expect(updateProfileFacts({ ...current, hasSpouse: true, maritalStatus: 'married' }, { maritalStatus: 'divorced' }, '2026-10-04')).toMatchObject({ hasSpouse: false, maritalStatus: 'divorced', householdMembersComplete: null, householdHistoryConfirmations: [] })
  })
  it('does not invent never-married status when a former spouse fact becomes false', () => {
    expect(updateProfileFacts({ ...current, hasSpouse: true, maritalStatus: 'married' }, { hasSpouse: false }, '2026-10-04').maritalStatus).toBe('unknown')
    for (const status of ['engaged', 'divorced', 'widowed'] as const) expect(updateProfileFacts({ ...current, hasSpouse: null, maritalStatus: status }, { hasSpouse: false }, '2026-10-04').maritalStatus).toBe(status)
  })
  it('keeps unchanged answers and unrelated edits from wiping valid snapshots', () => {
    for (const part of [{ hasSpouse: false }, { annualIncomeKrw: '60000000' }]) expect(updateProfileFacts(current, part, '2026-10-04')).toMatchObject({ householdMembersComplete: true, householdSnapshotDate: '2026-09-30', householdHistoryConfirmations: current.householdHistoryConfirmations })
  })
  it('rechecks family-wide query records after composition changes while preserving applicant-only facts', () => {
    const query = { ineligibleRestrictionActive: false, resaleRestrictionActive: false, rewinningRestrictionActive: false, asOfDate: '2026-09-30', historyConfirmations: [{ criterionDate: '2026-09-23', unchanged: true }] }
    const next = updateProfileFacts({ ...current, applicationRestrictionFacts: { applicant: query, household: query, applicant_spouse: query } }, { hasSpouse: true }, '2026-10-04')
    expect(next.applicationRestrictionFacts.applicant).toEqual(query)
    expect(next.applicationRestrictionFacts.household).toMatchObject({ asOfDate: '', historyConfirmations: [], rewinningRestrictionActive: null })
    expect(next.applicationRestrictionFacts.applicant_spouse).toMatchObject({ asOfDate: '', historyConfirmations: [] })
  })
})

describe('v5 facts and common application history', () => {
  it('keeps v4 observation dates without turning them into a change date or global no history', () => {
    const former = { ...EMPTY_PROFILE, version: 4, currentlyDomesticResident: true, domesticResidenceFactsAsOfDate: '2026-09-28', householdSnapshotDate: '2026-09-30', previousWinning: false, projectApplicationHistory: { '2026000323': { winning: true, contract: false, additionalResident: false, winningScope: 'applicant', contractScope: 'applicant', asOfDate: '2026-09-28', historyConfirmations: [] } } }
    const next = migrateProfile(former)
    expect(next).toMatchObject({ version: 5, domesticResidenceFactsAsOfDate: '2026-09-28', householdSnapshotDate: '2026-09-30', factChanges: {}, applicationHistoryPresence: null, applicationHistoryComplete: null, applicationHistoryEvents: [], applicationHistoryPeople: [] })
    expect(next.projectApplicationHistory['2026000323']).toEqual(former.projectApplicationHistory['2026000323'])
  })
  it('collapses an ordinary district only with its explicitly recorded parent-city continuity', () => {
    expect(migrateProfile({ ...EMPTY_PROFILE, version: 4, region: '경기도', district: '화성시 동탄구', districtMovedInDate: '2020-01-01', cityMovedInDate: '2010-02-01' })).toMatchObject({ district: '화성시', districtCode: '41590', districtMovedInDate: '2010-02-01', legacyDistrict: { code: '41597', name: '화성시 동탄구', movedInDate: '2020-01-01' } })
    expect(migrateProfile({ ...EMPTY_PROFILE, version: 4, region: '경기도', district: '수원시 영통구', districtMovedInDate: '2020-01-01', cityMovedInDate: '' }).districtMovedInDate).toBe('')
  })
  it('round-trips independent changes and exact common history with unknown extra fields dropped', () => {
    const stored = { ...EMPTY_PROFILE, factChanges: { citizenship: { mode: 'never_changed', date: '' }, military: { mode: 'known', date: '2020-01-01' }, bad: { mode: 'known', date: '2020-01-01' } }, applicationHistoryPresence: true, applicationHistoryComplete: true, applicationHistoryPeople: ['applicant', 'applicant', 'parent'], applicationHistoryEvents: [{ id: 'event', personId: 'parent', projectId: '2026000323', eventKind: 'winning', eventDate: '2023-01-01', specialSupply: true, name: 'drop' }], factSnapshots: [{ group: 'military', date: '2025-01-01', values: { militaryCurrentlyServing: true, militaryServiceYears: '10', secret: 'drop' } }] }
    const next = migrateProfile(stored)
    expect(next.factChanges).toEqual({ citizenship: { mode: 'never_changed', date: '' }, military: { mode: 'known', date: '2020-01-01' } })
    expect(next.applicationHistoryPeople).toEqual(['applicant', 'parent'])
    expect(next.applicationHistoryEvents).toEqual([{ id: 'event', personId: 'parent', projectId: '2026000323', eventKind: 'winning', eventDate: '2023-01-01', specialSupply: true }])
    expect(next.factSnapshots).toEqual([{ group: 'military', date: '2025-01-01', values: { militaryCurrentlyServing: true, militaryServiceYears: '10' } }])
  })
  it('preserves a known old factual snapshot before a current edit and never invents a change date', () => {
    const previous = { ...EMPTY_PROFILE, militaryCurrentlyServing: true, militaryServiceYears: '10', militaryFactsAsOfDate: '2026-09-28', factChanges: { military: { mode: 'known' as const, date: '2016-01-01' } } }
    const current = updateProfileFacts(previous, { militaryCurrentlyServing: false }, '2026-10-05')
    expect(current.factChanges.military).toEqual({ mode: 'unknown', date: '' })
    expect(current.factSnapshots).toContainEqual({ group: 'military', date: '2026-09-28', values: { militaryCurrentlyServing: true, militaryServiceYears: '10' } })
    expect(current.militaryFactsAsOfDate).toBe('2026-10-05')
  })
})
