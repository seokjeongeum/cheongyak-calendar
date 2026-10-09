import { EMPTY_PROFILE, createOwnershipFact, createHouseholdMember, type LocalProfile, type OwnershipFact, type HouseholdMember, type HouseholdHistoryConfirmation, type ProjectApplicationHistory, type ApplicationRestrictionFacts, type RestrictionScope, type FactChangeGroup, type ApplicationHistoryEvent } from './types'
import { districtOptions, provinceOptions, resolveLegacyRegion, parentCityCode } from './regions'
import { parseDate } from './qualification'
import { FACT_GROUP_FIELDS } from './factTimeline'

export const PROFILE_STORAGE_KEY = 'cheongyak-profile-v5'
export const V4_PROFILE_STORAGE_KEY = 'cheongyak-profile-v4'
export const V3_PROFILE_STORAGE_KEY = 'cheongyak-profile-v3'
export const V2_PROFILE_STORAGE_KEY = 'cheongyak-profile-v2'
export const LEGACY_PROFILE_STORAGE_KEY = 'cheongyak-profile-v1'
const MONEY_FIELDS = ['annualIncomeKrw', 'assetsKrw', 'monthlyIncomeKrw', 'officialNetAssetsKrw', 'realEstateKrw', 'vehicleKrw', 'privateDepositKrw', 'nationalRecognizedAmountKrw'] as const
const LEGACY_FIELDS = ['homeless', 'subscriptionRank', 'subscriptionMonths', 'specialEligibility', 'specialCategory']

export function normalizeMoney(value: unknown): string | null {
  if (value === '') return ''
  if (typeof value !== 'string' && typeof value !== 'number') return null
  const text = String(value).trim()
  if (!/^\d+(?:,\d{3})*$/.test(text)) return null
  const digits = text.replaceAll(',', '').replace(/^0+(?=\d)/, '')
  return Number.isSafeInteger(Number(digits)) ? digits : null
}
export function formatMoney(value: string): string { return /^\d+$/.test(value) ? value.replace(/\B(?=(\d{3})+(?!\d))/g, ',') : value }

const bool = (value: unknown): boolean | null => typeof value === 'boolean' ? value : null
const scope = (value: unknown): RestrictionScope | 'unknown' => ['applicant', 'household', 'applicant_spouse'].includes(String(value)) ? value as RestrictionScope : 'unknown'
function history(value: unknown): HouseholdHistoryConfirmation[] {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object' && typeof item.criterionDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(item.criterionDate)).map((item) => ({ criterionDate: item.criterionDate, unchanged: bool(item.unchanged) })) : []
}

/** Previous self-assessments do not become verified ownership exceptions. */
export function migrateProfile(value: unknown): LocalProfile {
  const next: LocalProfile = { ...EMPTY_PROFILE, factChanges: {}, applicationHistoryPeople: [], applicationHistoryAbsencePeople: [], applicationHistoryEvents: [], factSnapshots: [], children: [], ownershipFacts: [], householdMembers: [], householdHistoryConfirmations: [], applicationRestrictionsHistoryConfirmations: [], overseasFactsHistoryConfirmations: [], projectApplicationHistory: {}, applicationRestrictionFacts: {}, residenceHistory: [], militaryFactsHistoryConfirmations: [], incomeTaxFactsHistoryConfirmations: [], domesticResidenceHistoryConfirmations: [] }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return next
  const stored = value as Record<string, unknown>
  if (stored.version === 5 && stored.ownershipPropertyCounts && typeof stored.ownershipPropertyCounts === 'object' && !Array.isArray(stored.ownershipPropertyCounts)) {
    next.ownershipPropertyCounts = Object.fromEntries(Object.entries(stored.ownershipPropertyCounts).filter(([id, value]) => id.length > 0 && id.length <= 120 && !/[\u0000-\u001f]/.test(id) && typeof value === 'string' && (/^\d+$/.test(value) && Number.isSafeInteger(Number(value)) || value === '')))
  }
  if (stored.version === 2 || stored.version === 3 || stored.version === 4 || stored.version === 5) {
    for (const key of Object.keys(EMPTY_PROFILE) as (keyof LocalProfile)[]) {
      const candidate = stored[key]
      const initial = EMPTY_PROFILE[key]
      if (initial === null && (candidate === null || typeof candidate === 'boolean')) Object.assign(next, { [key]: candidate })
      else if (typeof initial === 'string' && typeof candidate === 'string') Object.assign(next, { [key]: candidate })
      else if (typeof initial === 'boolean' && typeof candidate === 'boolean') Object.assign(next, { [key]: candidate })
    }
    if (Array.isArray(stored.children)) next.children = stored.children.filter((item) => item && typeof item === 'object' && typeof item.dateOfBirth === 'string').map((item) => ({ dateOfBirth: item.dateOfBirth, adopted: typeof item.adopted === 'boolean' ? item.adopted : null, adoptionDate: typeof item.adoptionDate === 'string' && parseDate(item.adoptionDate) ? item.adoptionDate : '' }))
    if (!['unknown', 'comprehensive', 'savings', 'deposit', 'installment', 'none'].includes(next.accountType)) next.accountType = 'unknown'
    if (!['unknown', 'single', 'married', 'engaged', 'divorced', 'widowed'].includes(next.maritalStatus)) next.maritalStatus = 'unknown'
    if (!['unknown', 'none', 'pending', 'confirmed'].includes(next.recommendationStatus)) next.recommendationStatus = 'unknown'
    if ((stored.version === 3 || stored.version === 4 || stored.version === 5) && Array.isArray(stored.ownershipFacts)) next.ownershipFacts = stored.ownershipFacts.filter((item) => !!item && typeof item === 'object' && !Array.isArray(item)).map((item, index) => {
      const fact = createOwnershipFact(`property-${index + 1}`)
      for (const key of Object.keys(fact) as (keyof OwnershipFact)[]) {
        const candidate = item[key]
        if (fact[key] === null && (typeof candidate === 'boolean' || candidate === null)) Object.assign(fact, { [key]: candidate })
        else if (typeof fact[key] === 'string' && typeof candidate === 'string') Object.assign(fact, { [key]: candidate })
      }
      if (!['applicant', 'spouse', 'ascendant', 'spouse_ascendant', 'descendant', 'other', 'unknown'].includes(fact.ownerRelation)) fact.ownerRelation = 'unknown'
      const kinds = ['apartment', 'detached', 'multi_family', 'row_house', 'urban_small', 'presale_right', 'occupancy_right', 'officetel', 'unknown']
      if (!kinds.includes(fact.propertyKind)) fact.propertyKind = 'unknown'
      if (!kinds.includes(fact.underlyingPropertyKind)) fact.underlyingPropertyKind = 'unknown'
      if (!['unknown', 'annex1_official', 'market'].includes(fact.valueBasis)) fact.valueBasis = 'unknown'
      if (!['unknown', 'purchase', 'inheritance', 'gift', 'construction', 'auction', 'first_come'].includes(fact.acquisitionMethod)) fact.acquisitionMethod = 'unknown'
      if (stored.version === 3) fact.ownerMemberId = ['applicant', 'spouse'].includes(fact.ownerRelation) ? fact.ownerRelation : ''
      for (const key of ['officialValueKrw', 'acquisitionPriceKrw'] as const) fact[key] = normalizeMoney(fact[key]) ?? ''
      return fact
    })
    if (stored.version !== 3 && stored.version !== 4 && stored.version !== 5) { next.ownershipFactsKnown = null; next.ownershipFacts = []; next.privateDepositAsOfDate = ''; next.privateDepositMaintained = null; next.nationalPaymentsAsOfDate = ''; next.militaryCurrentlyServing = null; next.militaryServiceYears = '' }
  } else {
    for (const key of ['region', 'district', 'movedInDate', 'householdSize', 'annualIncomeKrw', 'assetsKrw'] as const) {
      if (typeof stored[key] === 'string') next[key] = stored[key]
    }
  }
  if (stored.version === 4 || stored.version === 5) {
    if (Array.isArray(stored.householdMembers)) next.householdMembers = stored.householdMembers.filter((item) => !!item && typeof item === 'object' && !Array.isArray(item)).map((item, index) => {
      const member = createHouseholdMember(`family-${index + 1}`)
      for (const key of Object.keys(member) as (keyof HouseholdMember)[]) {
        const candidate = item[key]
        if (member[key] === null && (candidate === null || typeof candidate === 'boolean')) Object.assign(member, { [key]: candidate })
        else if (typeof member[key] === 'string' && typeof candidate === 'string') Object.assign(member, { [key]: candidate })
      }
      if (!['applicant_parent', 'applicant_grandparent', 'spouse_parent', 'spouse_grandparent', 'applicant_child', 'applicant_grandchild', 'descendant_spouse', 'spouse_child', 'spouse_grandchild', 'sibling', 'unrelated', 'unknown'].includes(member.relation)) member.relation = 'unknown'
      if (!['applicant', 'spouse', 'both', 'separate', 'unknown'].includes(member.register)) member.register = 'unknown'
      return member
    })
    next.householdHistoryConfirmations = history(stored.householdHistoryConfirmations)
    next.applicationRestrictionsHistoryConfirmations = history(stored.applicationRestrictionsHistoryConfirmations)
    next.overseasFactsHistoryConfirmations = history(stored.overseasFactsHistoryConfirmations)
    next.militaryFactsHistoryConfirmations = history(stored.militaryFactsHistoryConfirmations)
    next.incomeTaxFactsHistoryConfirmations = history(stored.incomeTaxFactsHistoryConfirmations)
    next.domesticResidenceHistoryConfirmations = history(stored.domesticResidenceHistoryConfirmations)
    if (Array.isArray(stored.residenceHistory)) next.residenceHistory = stored.residenceHistory.filter((entry) => !!entry && typeof entry === 'object' && !Array.isArray(entry) && typeof entry.criterionDate === 'string' && parseDate(entry.criterionDate)).map((entry) => {
      const identity = resolveLegacyRegion(typeof entry.region === 'string' ? entry.region : '', typeof entry.district === 'string' ? entry.district : '')
      return { criterionDate: entry.criterionDate, region: identity.region, district: identity.district, regionCode: identity.regionCode, districtCode: identity.districtCode, movedInDate: typeof entry.movedInDate === 'string' && parseDate(entry.movedInDate) ? entry.movedInDate : '', districtMovedInDate: typeof entry.districtMovedInDate === 'string' && parseDate(entry.districtMovedInDate) ? entry.districtMovedInDate : '', cityMovedInDate: typeof entry.cityMovedInDate === 'string' && parseDate(entry.cityMovedInDate) ? entry.cityMovedInDate : '' }
    })
    if (stored.projectApplicationHistory && typeof stored.projectApplicationHistory === 'object' && !Array.isArray(stored.projectApplicationHistory)) for (const [project, raw] of Object.entries(stored.projectApplicationHistory)) {
      if (!/^(?:\d{10}|LH-[A-Z0-9-]{1,64})$/.test(project) || !raw || typeof raw !== 'object' || Array.isArray(raw)) continue
      const entry = raw as Record<string, unknown>
      next.projectApplicationHistory[project] = { winning: bool(entry.winning), contract: bool(entry.contract), additionalResident: bool(entry.additionalResident), winningScope: scope(entry.winningScope), contractScope: scope(entry.contractScope), asOfDate: typeof entry.asOfDate === 'string' ? entry.asOfDate : '', historyConfirmations: history(entry.historyConfirmations) } satisfies ProjectApplicationHistory
    }
    if (stored.applicationRestrictionFacts && typeof stored.applicationRestrictionFacts === 'object' && !Array.isArray(stored.applicationRestrictionFacts)) for (const [key, raw] of Object.entries(stored.applicationRestrictionFacts)) {
      if (scope(key) === 'unknown' || !raw || typeof raw !== 'object' || Array.isArray(raw)) continue
      const entry = raw as Record<string, unknown>
      next.applicationRestrictionFacts[key as RestrictionScope] = { ineligibleRestrictionActive: bool(entry.ineligibleRestrictionActive), resaleRestrictionActive: bool(entry.resaleRestrictionActive), rewinningRestrictionActive: bool(entry.rewinningRestrictionActive), asOfDate: typeof entry.asOfDate === 'string' ? entry.asOfDate : '', historyConfirmations: history(entry.historyConfirmations) } satisfies ApplicationRestrictionFacts
    }
    if (!['korean', 'foreign', 'unknown'].includes(next.citizenship)) next.citizenship = 'unknown'
  } else {
    // Old broad legal-scope answers cannot establish an exact family roster.
    next.householdMembersComplete = null; next.householdMembers = []; next.householdSnapshotDate = ''; next.householdCompositionUnchanged = null; next.householdHistoryConfirmations = []; next.applicantOnRegister = stored.applicantOnRegister === false ? false : null
    next.incomeHouseholdSize = ''; next.householdScopeKnown = null; next.familyOnRegister = null
  }
  if (stored.version === 5) {
    const groups: FactChangeGroup[] = ['household', 'household_head', 'domestic_residence', 'restrictions', 'overseas', 'military', 'income_tax', 'income', 'assets', 'bank_private', 'bank_national', 'bank_account', 'citizenship', 'employment', 'parent_support', 'marital', 'children', 'pregnancy', 'points', 'provider_employee', 'ownership']
    if (stored.factChanges && typeof stored.factChanges === 'object' && !Array.isArray(stored.factChanges)) for (const [group, raw] of Object.entries(stored.factChanges)) {
      if (!groups.includes(group as FactChangeGroup) || !raw || typeof raw !== 'object' || Array.isArray(raw)) continue
      const change = raw as Record<string, unknown>
      if (['known', 'never_changed', 'unknown'].includes(String(change.mode))) next.factChanges[group as FactChangeGroup] = { mode: change.mode as 'known' | 'never_changed' | 'unknown', date: typeof change.date === 'string' && parseDate(change.date) ? change.date : '' }
    }
    next.applicationHistoryPresence = bool(stored.applicationHistoryPresence)
    next.applicationHistoryComplete = bool(stored.applicationHistoryComplete)
    if (Array.isArray(stored.applicationHistoryPeople)) next.applicationHistoryPeople = [...new Set(stored.applicationHistoryPeople.filter((person): person is string => typeof person === 'string' && !!person))]
    if (Array.isArray(stored.applicationHistoryAbsencePeople)) next.applicationHistoryAbsencePeople = [...new Set(stored.applicationHistoryAbsencePeople.filter((person): person is string => typeof person === 'string' && !!person && person.length <= 128 && !/[\u0000-\u001f]/.test(person)))]
    if (Array.isArray(stored.applicationHistoryEvents)) next.applicationHistoryEvents = stored.applicationHistoryEvents.filter((event) => event && typeof event === 'object' && typeof event.id === 'string' && typeof event.personId === 'string' && typeof event.projectId === 'string' && ['winning', 'reserve_winning', 'contract', 'additional_resident_contract'].includes(event.eventKind)).map((event) => ({ id: event.id, personId: event.personId, projectId: event.projectId, eventKind: event.eventKind, eventDate: typeof event.eventDate === 'string' && parseDate(event.eventDate) ? event.eventDate : '', specialSupply: bool(event.specialSupply) } as ApplicationHistoryEvent))
    if (next.applicationHistoryPresence === false || next.applicationHistoryComplete === true && next.applicationHistoryEvents.length > 0) next.applicationHistoryAbsencePeople = [...new Set([...next.applicationHistoryAbsencePeople, ...next.applicationHistoryPeople.filter((person) => !next.applicationHistoryEvents.some((event) => event.personId === person))])]
    if (stored.legacyDistrict && typeof stored.legacyDistrict === 'object' && !Array.isArray(stored.legacyDistrict)) {
      const legacy = stored.legacyDistrict as Record<string, unknown>
      if (typeof legacy.code === 'string' && typeof legacy.name === 'string') next.legacyDistrict = { code: legacy.code, name: legacy.name, movedInDate: typeof legacy.movedInDate === 'string' ? legacy.movedInDate : '' }
    }
    if (Array.isArray(stored.factSnapshots)) next.factSnapshots = stored.factSnapshots.filter((snapshot) => snapshot && typeof snapshot === 'object' && groups.includes(snapshot.group) && typeof snapshot.date === 'string' && parseDate(snapshot.date) && snapshot.values && typeof snapshot.values === 'object' && !Array.isArray(snapshot.values)).map((snapshot) => ({ group: snapshot.group, date: snapshot.date, values: Object.fromEntries(Object.entries(snapshot.values).filter(([key]) => Object.hasOwn(EMPTY_PROFILE, key))) }))
  }
  if (stored.pointsFamily && typeof stored.pointsFamily === 'object' && !Array.isArray(stored.pointsFamily)) next.pointsFamily = Object.fromEntries(Object.entries(stored.pointsFamily).filter(([, value]) => value && typeof value === 'object' && !Array.isArray(value)).map(([id, value]) => { const row = value as Record<string, unknown>; return [id, { registeredSince: typeof row.registeredSince === 'string' && parseDate(row.registeredSince) ? row.registeredSince : '', unmarried: bool(row.unmarried), spouseOwnsHome: bool(row.spouseOwnsHome), overseasExcluded: bool(row.overseasExcluded), grandchildrenParentsAbsent: bool(row.grandchildrenParentsAbsent) }] }))
  // A stale identity stays unresolved rather than silently selecting another parent.
  if (next.parentSupportMemberId && (next.parentSupportMemberId.length > 128 || /[\u0000-\u001f]/.test(next.parentSupportMemberId))) next.parentSupportMemberId = ''
  if (next.currentAccountFirstWinningDate && !parseDate(next.currentAccountFirstWinningDate)) next.currentAccountFirstWinningDate = ''
  if (next.currentAccountFactsAsOfDate && !parseDate(next.currentAccountFactsAsOfDate)) next.currentAccountFactsAsOfDate = ''
  if (next.factChanges.children && !next.factChanges.pregnancy) next.factChanges.pregnancy = { ...next.factChanges.children }
  next.factSnapshots = [...(next.factSnapshots || []), ...(next.factSnapshots || []).filter((snapshot) => snapshot.group === 'children' && Object.hasOwn(snapshot.values, 'pregnant') && !next.factSnapshots?.some((existing) => existing.group === 'pregnancy' && existing.date === snapshot.date)).map((snapshot) => ({ ...snapshot, group: 'pregnancy' as const, values: Object.fromEntries(['pregnant', 'expectedChildren'].filter((key) => Object.hasOwn(snapshot.values, key)).map((key) => [key, snapshot.values[key]])) }))]
  for (const key of MONEY_FIELDS) next[key] = normalizeMoney(next[key] ?? '') ?? ''
  next.ownershipException = null
  const resolved = resolveLegacyRegion(next.region, next.district)
  next.region = resolved.region
  next.district = resolved.district
  next.regionCode = resolved.regionCode
  next.districtCode = resolved.districtCode
  next.regionNeedsReview = resolved.needsReview
  const parent = parentCityCode(next.districtCode)
  if (parent && !(stored.version === 5 && next.districtScopeSpecific)) {
    next.legacyDistrict = { code: next.districtCode, name: next.district, movedInDate: next.districtMovedInDate }
    next.districtCode = parent
    next.district = districtOptions(next.regionCode).find((option) => option.code === parent)?.name || ''
    // Only an explicitly recorded parent-city date proves earlier continuity.
    next.districtMovedInDate = next.cityMovedInDate || ''
  }
  // Unrecognized keys and legacy answers are never serialized into the new profile.
  for (const key of LEGACY_FIELDS) delete (next as unknown as Record<string, unknown>)[key]
  return next
}
export function readProfile(): LocalProfile {
  try { return migrateProfile(JSON.parse(localStorage.getItem(PROFILE_STORAGE_KEY) || localStorage.getItem(V4_PROFILE_STORAGE_KEY) || localStorage.getItem(V3_PROFILE_STORAGE_KEY) || localStorage.getItem(V2_PROFILE_STORAGE_KEY) || localStorage.getItem(LEGACY_PROFILE_STORAGE_KEY) || 'null')) }
  catch { return { ...EMPTY_PROFILE, factChanges: {}, factSnapshots: [], applicationHistoryPeople: [], applicationHistoryEvents: [], children: [], ownershipFacts: [], householdMembers: [], householdHistoryConfirmations: [], applicationRestrictionsHistoryConfirmations: [], overseasFactsHistoryConfirmations: [], projectApplicationHistory: {}, applicationRestrictionFacts: {}, residenceHistory: [], militaryFactsHistoryConfirmations: [], incomeTaxFactsHistoryConfirmations: [], domesticResidenceHistoryConfirmations: [] } }
}
export function selectProvince(profile: LocalProfile, code: string): LocalProfile {
  const option = provinceOptions().find((item) => item.code === code)
  return { ...profile, regionCode: option?.code || '', region: option?.name || '', district: '', districtCode: '', movedInDate: '', districtMovedInDate: '', cityMovedInDate: '', legacyDistrict: undefined, districtScopeSpecific: false, regionNeedsReview: false }
}
export function selectDistrict(profile: LocalProfile, code: string, options: { preserveOrdinaryDistrict?: boolean } = {}): LocalProfile {
  const normalized = options.preserveOrdinaryDistrict ? code : parentCityCode(code) || code
  const option = districtOptions(profile.regionCode, { includeOrdinaryDistricts: true }).find((item) => item.code === normalized)
  const nextCity = option?.parentCityCode || option?.code
  const previousCity = parentCityCode(profile.districtCode) || profile.districtCode
  const cityStart = nextCity && nextCity === previousCity ? parentCityCode(profile.districtCode) ? profile.cityMovedInDate : profile.districtMovedInDate : ''
  return { ...profile, legacyDistrict: nextCity === previousCity ? profile.legacyDistrict : undefined, districtScopeSpecific: !!option?.parentCityCode && !!options.preserveOrdinaryDistrict, districtCode: option?.code || '', district: option?.name || '', districtMovedInDate: option && !option.parentCityCode && nextCity === previousCity ? cityStart : '', cityMovedInDate: cityStart, regionNeedsReview: false }
}

const SNAPSHOT_FIELDS: Partial<Record<FactChangeGroup, keyof LocalProfile>> = { household: 'householdSnapshotDate', domestic_residence: 'domesticResidenceFactsAsOfDate', restrictions: 'applicationRestrictionsAsOfDate', overseas: 'overseasFactsAsOfDate', military: 'militaryFactsAsOfDate', income_tax: 'incomeTaxFactsAsOfDate', bank_private: 'privateDepositAsOfDate', bank_national: 'nationalPaymentsAsOfDate', bank_account: 'currentAccountFactsAsOfDate' }

/** Preserve known old facts; an edit alone does not invent when the status changed. */
export function updateProfileFacts(profile: LocalProfile, part: Partial<LocalProfile>, today: string): LocalProfile {
  const changed = { ...part }
  if (part.accountType !== undefined && part.accountType !== profile.accountType) {
    changed.currentAccountUsedForWinning = null
    changed.currentAccountFirstWinningDate = ''
  }
  if (part.maritalStatus !== undefined && part.maritalStatus !== profile.maritalStatus) changed.hasSpouse = part.maritalStatus === 'unknown' ? null : part.maritalStatus === 'married'
  else if (part.hasSpouse !== profile.hasSpouse) {
    if (part.hasSpouse === true) changed.maritalStatus = 'married'
    else if (part.hasSpouse === false && profile.maritalStatus === 'married') changed.maritalStatus = 'unknown'
  }
  const changedKeys = Object.keys(changed).filter((key) => changed[key as keyof LocalProfile] !== profile[key as keyof LocalProfile]) as (keyof LocalProfile)[]
  const factChanges = { ...(part.factChanges || profile.factChanges) }
  const factSnapshots = [...(part.factSnapshots || profile.factSnapshots || [])]
  for (const [rawGroup, fields] of Object.entries(FACT_GROUP_FIELDS)) {
    const group = rawGroup as FactChangeGroup
    if (!fields.some((field) => changedKeys.includes(field))) continue
    const snapshotField = SNAPSHOT_FIELDS[group]
    const priorDate = snapshotField ? profile[snapshotField] : undefined
    if (typeof priorDate === 'string' && parseDate(priorDate) && !factSnapshots.some((snapshot) => snapshot.group === group && snapshot.date === priorDate)) factSnapshots.push({ group, date: priorDate, values: Object.fromEntries(fields.map((field) => [field, profile[field]])) })
    factChanges[group] = part.factChanges?.[group] && part.factChanges[group] !== profile.factChanges?.[group] ? part.factChanges[group]! : { mode: 'unknown', date: '' }
    if (snapshotField) Object.assign(changed, { [snapshotField]: today })
  }
  const compositionChanged = (['hasSpouse', 'spouseSameRegister', 'applicantOnRegister', 'maritalStatus', 'householdMembers', 'additionalFamilyPresence'] as const).some((key) => changedKeys.includes(key))
  if (!compositionChanged) return { ...profile, ...changed, factChanges, factSnapshots }
  const applicationRestrictionFacts = { ...profile.applicationRestrictionFacts }
  for (const scope of ['household', 'applicant_spouse'] as const) {
    const record = applicationRestrictionFacts[scope]
    if (record) applicationRestrictionFacts[scope] = { ...record, ineligibleRestrictionActive: null, resaleRestrictionActive: null, rewinningRestrictionActive: null, asOfDate: '', historyConfirmations: [] }
  }
  return { ...profile, ...changed, factChanges, factSnapshots, householdMembersComplete: null, householdSnapshotDate: today, householdCompositionUnchanged: null, householdHistoryConfirmations: [], applicationRestrictionFacts }
}

/** Browser only; a closing dialog flushes its latest local draft before unmount. */
export function saveProfile(profile: LocalProfile): void {
  try { localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile)) } catch { /* Private mode or full storage: keep the active draft. */ }
}
