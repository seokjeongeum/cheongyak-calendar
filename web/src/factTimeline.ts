import type { FactChangeGroup, LocalProfile, Notice, NoticeRule } from './types'

let evaluationToday: string | null = null
function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number), date = new Date(Date.UTC(year, month - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
}
/** Each worker fixes the day for one evaluation revision. No browser state is read. */
export function setEvaluationToday(today?: string | null): void {
  if (today != null && !validDate(today)) throw new Error('Invalid evaluation date')
  evaluationToday = today || null
}
export function getEvaluationToday(): string { return evaluationToday || new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10) }
export const FACT_GROUP_ANCHORS: Record<FactChangeGroup, keyof LocalProfile> = {
  household: 'householdSnapshotDate', household_head: 'isHouseholdHead', domestic_residence: 'domesticResidenceFactsAsOfDate', restrictions: 'applicationRestrictionsAsOfDate', overseas: 'overseasFactsAsOfDate', military: 'militaryFactsAsOfDate', income_tax: 'incomeTaxFactsAsOfDate', income: 'monthlyIncomeKrw', assets: 'assetsKrw', bank_private: 'privateDepositAsOfDate', bank_national: 'nationalPaymentsAsOfDate', bank_account: 'currentAccountUsedForWinning', citizenship: 'citizenship', employment: 'employed', parent_support: 'parentSupportSince', marital: 'maritalStatus', children: 'children', pregnancy: 'pregnant', points: 'pointsFamily', provider_employee: 'providerEmployeeOrRelatedFamily', ownership: 'ownershipFacts',
}

export const FACT_GROUP_FIELDS: Partial<Record<FactChangeGroup, readonly (keyof LocalProfile)[]>> = {
  household: ['applicantOnRegister', 'hasSpouse', 'spouseSameRegister', 'householdMembers', 'householdMembersComplete', 'additionalFamilyPresence', 'maritalStatus'],
  household_head: ['isHouseholdHead'], domestic_residence: ['currentlyDomesticResident'],
  restrictions: ['applicationRestrictionFacts', 'restrictedFromApplying', 'ineligibleRestrictionActive', 'resaleRestrictionActive', 'rewinningRestrictionActive'],
  overseas: ['overseasContinuousDays', 'overseasOnlyApplicantForLivelihood'],
  military: ['militaryCurrentlyServing', 'militaryServiceYears'],
  income_tax: ['employed', 'incomeTaxPaidWithinPastYear', 'taxYears'],
  income: ['incomeHouseholdSize', 'annualIncomeKrw', 'monthlyIncomeKrw', 'dualIncome'],
  assets: ['assetsKrw', 'officialNetAssetsKrw', 'realEstateKrw', 'vehicleKrw'],
  bank_private: ['accountType', 'privateRankBaseDate', 'privateDepositKrw'],
  bank_national: ['accountType', 'nationalRankBaseDate', 'nationalRecognizedPayments', 'nationalRecognizedAmountKrw'],
  bank_account: ['accountType', 'currentAccountUsedForWinning', 'currentAccountFirstWinningDate'],
  citizenship: ['citizenship'], employment: ['employed', 'relocatedWorker'],
  parent_support: ['parentSameRegister', 'parentOwnsHome', 'parentSpouseOwnsHome', 'parentSupportSince'],
  marital: ['maritalStatus', 'hasSpouse', 'marriageDate', 'plannedMarriage', 'raisesChildWithoutSpouse', 'hasDeFactoPartner'],
  children: ['hasChildren', 'children'], pregnancy: ['pregnant', 'expectedChildren'], points: ['pointsFamily', 'pointsFamilyComplete', 'pointsHomelessSince', 'spouseAccountPresent', 'spouseAccountBaseDate'],
  provider_employee: ['providerEmployeeOrRelatedFamily', 'providerPurchaseApproval'],
  ownership: ['applicantOwnsHome', 'spouseOwnsHome', 'familyOwnsHome', 'ownershipFactsKnown', 'ownershipFacts', 'ownershipPropertyCounts'],
}

const GROUPS: Record<string, FactChangeGroup> = {
  homeless: 'ownership', ownership_count_max: 'ownership',
  household_head: 'household_head', domestic_residence: 'domestic_residence', citizenship: 'citizenship',
  overseas_residence: 'overseas', military_currently_serving: 'military', military_service_years: 'military',
  applying_restriction: 'restrictions', income_tax_paid_within_past_year: 'income_tax', first_home_tax_activity: 'income_tax', tax_years_min: 'income_tax',
  monthly_income_max_krw: 'income', income_max_krw: 'income', shinhee_income: 'income', dual_income: 'income',
  assets_max_krw: 'assets', real_estate_max_krw: 'assets', real_estate_assets_max_krw: 'assets', shinhee_assets: 'assets',
  deposit_min_krw: 'bank_private', recognized_payments_min: 'bank_national', recognized_amount_min_krw: 'bank_national',
  account_unused_after_winning: 'bank_account',
  marital_status: 'marital', marriage_months_max: 'marital', planned_marriage: 'marital', single_parent_family: 'marital', first_home_family: 'marital',
  children_min: 'children', newborn_children_min: 'children', pregnant: 'pregnancy',
  employed: 'employment', relocated_worker: 'employment', parent_same_register: 'parent_support', parent_owns_home: 'parent_support', parent_spouse_owns_home: 'parent_support', parent_support_months_min: 'parent_support',
  provider_employee_restriction: 'provider_employee',
}
export function factGroupForRule(rule: NoticeRule): FactChangeGroup | undefined { return GROUPS[rule.kind] }

export interface FactDateDecision { known: boolean; profile: LocalProfile; source: 'current' | 'unchanged' | 'snapshot' | 'legacy' | 'unknown' }
export function factsAtDate(profile: LocalProfile, group: FactChangeGroup, date: string | null, legacy?: { date: string; confirmations?: { criterionDate: string; unchanged: boolean | null }[]; unchangedSince?: boolean }): FactDateDecision {
  if (!date || !validDate(date)) return { known: false, profile, source: 'unknown' }
  if (date >= getEvaluationToday()) return { known: true, profile, source: 'current' }
  const snapshot = profile.factSnapshots?.find((item) => item.group === group && item.date === date && Object.keys(item.values).length > 0)
  if (snapshot) {
    const values = Object.fromEntries((FACT_GROUP_FIELDS[group] || []).filter((field) => Object.hasOwn(snapshot.values, field)).map((field) => [field, snapshot.values[field]]))
    // Newly added facts must not inherit today's value into an older snapshot.
    if (group === 'household' && !Object.hasOwn(snapshot.values, 'additionalFamilyPresence')) values.additionalFamilyPresence = null
    if (group === 'household' && !Object.hasOwn(snapshot.values, 'householdMembersComplete')) values.householdMembersComplete = null
    if (group === 'ownership' && !Object.hasOwn(snapshot.values, 'ownershipPropertyCounts')) values.ownershipPropertyCounts = {}
    if (group === 'bank_account') {
      if (!Object.hasOwn(snapshot.values, 'currentAccountUsedForWinning')) values.currentAccountUsedForWinning = null
      if (!Object.hasOwn(snapshot.values, 'currentAccountFirstWinningDate')) values.currentAccountFirstWinningDate = ''
    }
    if (group === 'ownership' && !Object.hasOwn(snapshot.values, 'ownershipFactsKnown')) values.ownershipFactsKnown = null
    return { known: true, profile: { ...profile, ...values }, source: 'snapshot' }
  }
  const change = profile.factChanges?.[group]
  if (change?.mode === 'never_changed' || change?.mode === 'known' && validDate(change.date) && change.date <= date && change.date <= getEvaluationToday()) return { known: true, profile, source: 'unchanged' }
  // A former observation date proves this exact date only. It is never a
  // change date, and an explicit unknown/new change supersedes old answers.
  if (!change && legacy && (legacy.date === date || legacy.confirmations?.some((item) => item.criterionDate === date && item.unchanged === true) || legacy.unchangedSince === true && validDate(legacy.date) && legacy.date <= date)) return { known: true, profile, source: 'legacy' }
  return { known: false, profile, source: 'unknown' }
}

/** Contract conditions are a preview of today's facts, never a future fact assertion. */
export function contractEvaluationDate(_notice: Notice): string { return getEvaluationToday() }
