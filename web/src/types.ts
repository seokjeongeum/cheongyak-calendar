export type PriceCapStatus = 'yes' | 'no' | 'unknown' | 'not_applicable'
export type Verification = 'official' | 'ai_unverified' | 'auto_unverified' | 'unknown' | string

export interface NoticeEvent {
  kind: string
  label: string
  start_date: string
  end_date: string | null
  audience?: string | null
}

export interface NoticePrice {
  unit_type: string
  source?: string | null
  area_sqm?: number | null
  exclusive_area_sqm?: number | null
  area_basis?: 'exclusive' | 'supply' | 'unknown' | string
  price_kind: string
  amount_krw?: number | null
  monthly_krw?: number | null
  basis_label?: string | null
  verification?: Verification | null
  evidence_url?: string | null
  evidence_text?: string | null
  application_fee_krw?: number | null
}

export interface NoticeRule {
  id?: string
  unit_type?: string | null
  supply_type?: string | null
  kind: string
  operator?: string | null
  value?: string | number | boolean | null
  verification?: Verification | null
  evidence_url?: string | null
  evidence_text?: string | null
  text?: string | null
  region_code?: string | null
  region_name?: string | null
  [key: string]: unknown
}

export type ApplicationMethod = 'apt_ranked' | 'unranked_after' | 'optional_supply' | 'cancelled_resupply' | 'first_come' | 'officetel' | 'unknown'

export interface OfferedSupply {
  supply_type: string
  unit_type?: string | null
  supply_count?: number | null
  verification: Verification
  evidence_url?: string | null
  evidence_text?: string | null
  evidence_page?: number | null
  document_hash?: string | null
  criterion_date?: string | null
}

export interface ResidenceHistoryFact {
  criterionDate: string
  region: string
  district: string
  regionCode: string
  districtCode: string
  movedInDate: string
  districtMovedInDate: string
  cityMovedInDate: string
}

export type ResidenceArea = 'local' | 'other_gyeonggi' | 'other' | 'unknown'
export type SubscriptionRank = 'unknown' | 'first' | 'second'

export interface NoticeCompetition {
  source: string
  unit_type: string
  model_no?: string | null
  rank: number | null
  residence_area: ResidenceArea
  residence_area_label: string | null
  supply_type?: string
  supply_type_label?: string | null
  resident_priority?: string | null
  supply_count: number | null
  application_count: number | null
  competition_rate: string
  result_status: 'local_first_closed' | 'first_closed' | 'open' | 'unknown'
  result_text: string | null
  evidence_url: string | null
  verification: Verification
  observed_at: string | null
}

export interface CompetitionCollection {
  proof_invalidated?: boolean
  status: string
  last_attempt_at: string | null
  last_success_at: string | null
  complete: boolean
  unit_types: string[]
  evidence_url?: string | null
  message?: string | null
}

export interface ContractSchedule {
  status: 'fixed' | 'range' | 'ongoing' | 'unknown'
  start_date: string | null
  end_date: string | null
  verification: Verification
  source?: string | null
  evidence_url?: string | null
  evidence_text?: string | null
  evidence_page?: number | null
  document_hash?: string | null
}

export interface Notice {
  selection_methods?: NoticeRule[]
  winning_scores?: WinningScore[]
  contract_schedule?: ContractSchedule | null
  id: string
  title: string
  category: string
  application_method?: ApplicationMethod
  application_method_evidence?: { verification: Verification; source?: string | null; evidence_url?: string | null; evidence_text?: string | null; document_hash?: string | null; criterion_date?: string | null } | null
  housing_kind?: 'private' | 'national' | 'unknown' | 'not_applicable'
  housing_kind_evidence?: { verification: Verification; source?: string | null; evidence_url?: string | null; evidence_text?: string | null } | null
  rank_applicability?: { status: 'applicable' | 'not_applicable' | 'unknown'; account_required: boolean | null; reason?: string; verification: Verification; evidence_url?: string | null; evidence_text?: string | null; document_hash?: string | null } | null
  offered_supplies?: OfferedSupply[] | null
  qualification_context?: { public_housing: boolean | null; speculation_zone: boolean | null; subscription_overheated: boolean | null; weakened_area: boolean | null; capital_region: boolean | null; rule_effective_date?: string | null; [key: string]: unknown }
  source: string
  sources?: string[]
  correction_of_external_id?: string | null
  correction_of_id?: string | null
  provider: string
  address: string | null
  region_code: string | null
  region_name: string | null
  announcement_date: string | null
  sort_date?: string | null
  application_end_date?: string | null
  official_url: string | null
  price_cap_status: PriceCapStatus
  events: NoticeEvent[]
  prices: NoticePrice[]
  rules: NoticeRule[]
  rules_complete?: boolean
  updated_at: string | null
  version: number
  competitions?: NoticeCompetition[]
  competition?: CompetitionCollection
}

export interface NoticesResponse {
  items: Notice[]
  total: number
  page: number
  page_size: number
}

export interface CoverageSource {
  source: string
  status: string
  message?: string | null
  last_attempt_at?: string | null
  last_success_at?: string | null
  record_count?: number | null
}

export interface CoverageResponse {
  sources: CoverageSource[]
}

export type AccountType = 'unknown' | 'comprehensive' | 'savings' | 'deposit' | 'installment' | 'none'
export type MaritalStatus = 'unknown' | 'single' | 'married' | 'engaged' | 'divorced' | 'widowed'
export interface ChildFact { dateOfBirth: string; adopted: boolean | null; adoptionDate?: string }

export type HouseholdRelation = 'applicant_parent' | 'applicant_grandparent' | 'spouse_parent' | 'spouse_grandparent' | 'applicant_child' | 'applicant_grandchild' | 'descendant_spouse' | 'spouse_child' | 'spouse_grandchild' | 'sibling' | 'unrelated' | 'unknown'
export type HouseholdRegister = 'applicant' | 'spouse' | 'both' | 'separate' | 'unknown'
export interface HouseholdMember {
  id: string
  relation: HouseholdRelation
  register: HouseholdRegister
  dateOfBirth: string
  ownsHome: boolean | null
  previouslyOwnedHome: boolean | null
}
export function createHouseholdMember(id = ''): HouseholdMember { return { id, relation: 'unknown', register: 'unknown', dateOfBirth: '', ownsHome: null, previouslyOwnedHome: null } }
export interface HouseholdHistoryConfirmation { criterionDate: string; unchanged: boolean | null }
export type RestrictionScope = 'applicant' | 'household' | 'applicant_spouse'
export interface ApplicationRestrictionFacts { ineligibleRestrictionActive: boolean | null; resaleRestrictionActive: boolean | null; rewinningRestrictionActive: boolean | null; asOfDate: string; historyConfirmations: HouseholdHistoryConfirmation[] }
export interface ProjectApplicationHistory { winning: boolean | null; contract: boolean | null; additionalResident: boolean | null; winningScope: RestrictionScope | 'unknown'; contractScope: RestrictionScope | 'unknown'; asOfDate: string; historyConfirmations: HouseholdHistoryConfirmation[] }

export type OwnerRelation = 'applicant' | 'spouse' | 'ascendant' | 'spouse_ascendant' | 'descendant' | 'other' | 'unknown'
export type PropertyKind = 'apartment' | 'detached' | 'multi_family' | 'row_house' | 'urban_small' | 'presale_right' | 'occupancy_right' | 'officetel' | 'unknown'
/** One record per dwelling/right. Shares of the same dwelling are one record. */
export interface OwnershipFact {
  id: string
  ownerMemberId: string
  ownerRelation: OwnerRelation
  ownerDateOfBirth: string
  propertyKind: PropertyKind
  underlyingPropertyKind: PropertyKind
  areaSqm: string
  officialValueKrw: string
  valueBasis: 'unknown' | 'annex1_official' | 'market'
  valueAsOfDate: string
  acquisitionPriceKrw: string
  propertyRegionCode: string
  acquiredDate: string
  disposedDate: string
  acquisitionMethod: 'unknown' | 'purchase' | 'inheritance' | 'gift' | 'construction' | 'auction' | 'first_come'
  inheritedShare: boolean | null
  ownedShare: boolean | null
  notificationDate: string
  buildingApprovalDate: string
  outsideUrbanArea: boolean | null
  inMyeon: boolean | null
  ownerPreviouslyResided: boolean | null
  movedToOtherConstructionArea: boolean | null
  firstRegisteredDomicile: boolean | null
  fromAscendantOrSpouse: boolean | null
  builderForSale: boolean | null
  saleCompleted: boolean | null
  individualBusinessRegistered: boolean | null
  employeeDormitoryUnderHousingAct: boolean | null
  governmentEmployeeHousingPolicy: boolean | null
  standardResidentialBuilding: boolean | null
  abandonedOrDestroyedOrNonResidential: boolean | null
  registerCorrectedDate: string
  oldLawUnauthorized: boolean | null
  lawfulAtConstructionEvidence: boolean | null
  originalResidualFirstCome: boolean | null
  unpaidRentalDeposit: boolean | null
  auctionAcquisition: boolean | null
  firstEverAcquisition: boolean | null
  tenantResidenceStartDate: string
}
export function createOwnershipFact(id = ''): OwnershipFact {
  return { id, ownerMemberId: '', ownerRelation: 'unknown', ownerDateOfBirth: '', propertyKind: 'unknown', underlyingPropertyKind: 'unknown', areaSqm: '', officialValueKrw: '', valueBasis: 'unknown', valueAsOfDate: '', acquisitionPriceKrw: '', propertyRegionCode: '', acquiredDate: '', disposedDate: '', acquisitionMethod: 'unknown', inheritedShare: null, ownedShare: null, notificationDate: '', buildingApprovalDate: '', outsideUrbanArea: null, inMyeon: null, ownerPreviouslyResided: null, movedToOtherConstructionArea: null, firstRegisteredDomicile: null, fromAscendantOrSpouse: null, builderForSale: null, saleCompleted: null, individualBusinessRegistered: null, employeeDormitoryUnderHousingAct: null, governmentEmployeeHousingPolicy: null, standardResidentialBuilding: null, abandonedOrDestroyedOrNonResidential: null, registerCorrectedDate: '', oldLawUnauthorized: null, lawfulAtConstructionEvidence: null, originalResidualFirstCome: null, unpaidRentalDeposit: null, auctionAcquisition: null, firstEverAcquisition: null, tenantResidenceStartDate: '' }
}

export type FactChangeGroup = 'household' | 'household_head' | 'domestic_residence' | 'restrictions' | 'overseas' | 'military' | 'income_tax' | 'income' | 'assets' | 'bank_private' | 'bank_national' | 'citizenship' | 'employment' | 'parent_support' | 'marital' | 'children' | 'pregnancy' | 'points' | 'provider_employee' | 'ownership'
export interface FactChange { mode: 'known' | 'never_changed' | 'unknown'; date: string }
export type ApplicationHistoryEventKind = 'winning' | 'reserve_winning' | 'contract' | 'additional_resident_contract'
export interface ApplicationHistoryEvent { id: string; personId: string; projectId: string; eventKind: ApplicationHistoryEventKind; eventDate: string; specialSupply?: boolean | null }

export interface PointsFamilyFact {
  registeredSince: string
  unmarried: boolean | null
  spouseOwnsHome: boolean | null
  overseasExcluded: boolean | null
  grandchildrenParentsAbsent: boolean | null
}
export function emptyPointsFamilyFact(): PointsFamilyFact { return { registeredSince: '', unmarried: null, spouseOwnsHome: null, overseasExcluded: null, grandchildrenParentsAbsent: null } }
export interface WinningScore {
  unit_type: string; residence_area: ResidenceArea; min_score: number; max_score?: number; average_score?: number
  house_manage_no: string; notice_no: string; supply_type: string; rank: number; selection_path: string
  verification: Verification; criterion_date?: string | null; observed_at?: string; collection_status?: string
  evidence_url?: string; evidence_location?: string; document_hash?: string
}
export interface LocalProfile {
  version: 5
  pointsFamily: Record<string, PointsFamilyFact>
  pointsFamilyComplete: boolean | null
  pointsHomelessSince: string
  spouseAccountPresent: boolean | null
  spouseAccountBaseDate: string
  factChanges: Partial<Record<FactChangeGroup, FactChange>>
  legacyDistrict?: { code: string; name: string; movedInDate: string }
  factSnapshots?: { group: FactChangeGroup; date: string; values: Record<string, unknown> }[]
  applicationHistoryPresence: boolean | null
  applicationHistoryComplete: boolean | null
  applicationHistoryPeople: string[]
  applicationHistoryEvents: ApplicationHistoryEvent[]
  region: string
  district: string
  regionCode: string
  districtCode: string
  districtScopeSpecific?: boolean
  regionNeedsReview: boolean
  movedInDate: string
  districtMovedInDate: string
  cityMovedInDate: string
  residenceHistory?: ResidenceHistoryFact[]
  intendedContractDate?: string
  currentlyDomesticResident?: boolean | null
  domesticResidenceFactsAsOfDate?: string
  domesticResidenceHistoryConfirmations?: HouseholdHistoryConfirmation[]
  providerEmployeeOrRelatedFamily?: boolean | null
  providerPurchaseApproval?: boolean | null
  /** Migration-only former legal household size; never used for eligibility. */
  householdSize: string
  incomeHouseholdSize: string
  applicantOnRegister: boolean | null
  householdMembers: HouseholdMember[]
  householdMembersComplete: boolean | null
  householdSnapshotDate: string
  householdCompositionUnchanged: boolean | null
  householdHistoryConfirmations: HouseholdHistoryConfirmation[]
  dateOfBirth: string
  isHouseholdHead: boolean | null
  hasSpouse: boolean | null
  spouseSameRegister: boolean | null
  familyOnRegister: boolean | null
  householdScopeKnown: boolean | null
  applicantOwnsHome: boolean | null
  spouseOwnsHome: boolean | null
  familyOwnsHome: boolean | null
  ownershipException: boolean | null
  ownershipFactsKnown: boolean | null
  ownershipFacts: OwnershipFact[]
  applicantPreviouslyOwnedHome: boolean | null
  spousePreviouslyOwnedHome: boolean | null
  spousePremarriageOwnershipDisposed?: boolean | null
  familyPreviouslyOwnedHome: boolean | null
  accountType: AccountType
  privateRankBaseDate: string
  nationalRankBaseDate: string
  privateDepositKrw: string
  privateDepositAsOfDate: string
  privateDepositMaintained: boolean | null
  nationalRecognizedPayments: string
  nationalRecognizedAmountKrw: string
  nationalPaymentsAsOfDate: string
  accountConversionUnclear: boolean | null
  previousWinning: boolean | null
  previousWinningDate: string
  restrictedFromApplying: boolean | null
  projectApplicationHistory: Record<string, ProjectApplicationHistory>
  citizenship: 'korean' | 'foreign' | 'unknown'
  overseasContinuousDays: string
  overseasFactsAsOfDate: string
  overseasOnlyApplicantForLivelihood: boolean | null
  overseasFactsHistoryConfirmations: HouseholdHistoryConfirmation[]
  ineligibleRestrictionActive: boolean | null
  resaleRestrictionActive: boolean | null
  rewinningRestrictionActive: boolean | null
  applicationRestrictionFacts: Partial<Record<RestrictionScope, ApplicationRestrictionFacts>>
  applicationRestrictionsAsOfDate: string
  applicationRestrictionsHistoryConfirmations: HouseholdHistoryConfirmation[]
  specialWinning: boolean | null
  annualIncomeKrw: string
  assetsKrw: string
  monthlyIncomeKrw: string
  officialNetAssetsKrw?: string
  plannedMarriage?: boolean | null
  raisesChildWithoutSpouse?: boolean | null
  hasDeFactoPartner?: boolean | null
  realEstateKrw: string
  vehicleKrw: string
  dualIncome: boolean | null
  maritalStatus: MaritalStatus
  marriageDate: string
  hasChildren: boolean | null
  children: ChildFact[]
  pregnant: boolean | null
  expectedChildren: string
  taxYears: string
  employed: boolean | null
  incomeTaxPaidWithinPastYear?: boolean | null
  incomeTaxFactsAsOfDate?: string
  incomeTaxFactsHistoryConfirmations?: HouseholdHistoryConfirmation[]
  parentDateOfBirth: string
  parentSupportSince: string
  parentSameRegister: boolean | null
  parentOwnsHome: boolean | null
  parentSpouseOwnsHome?: boolean | null
  recommendationReason: string
  recommendationStatus: 'unknown' | 'none' | 'pending' | 'confirmed'
  relocatedWorker: boolean | null
  militaryCurrentlyServing: boolean | null
  militaryServiceYears: string
  militaryFactsAsOfDate?: string
  militaryFactsHistoryConfirmations?: HouseholdHistoryConfirmation[]
  // v1 fields are migration-only; no new diagnosis may treat them as facts.
  homeless?: boolean | null
  subscriptionMonths?: string
  subscriptionRank?: SubscriptionRank
  specialEligibility?: boolean | null
  specialCategory?: string
}

export const EMPTY_PROFILE: LocalProfile = {
  version: 5, pointsFamily: {}, pointsFamilyComplete: null, pointsHomelessSince: '', spouseAccountPresent: null, spouseAccountBaseDate: '', factChanges: {}, factSnapshots: [], applicationHistoryPresence: null, applicationHistoryComplete: null, applicationHistoryPeople: [], applicationHistoryEvents: [], region: '', district: '', regionCode: '', districtCode: '', districtScopeSpecific: false, regionNeedsReview: false,
  movedInDate: '', districtMovedInDate: '', cityMovedInDate: '', residenceHistory: [], intendedContractDate: '', currentlyDomesticResident: null, domesticResidenceFactsAsOfDate: '', domesticResidenceHistoryConfirmations: [], providerEmployeeOrRelatedFamily: null, providerPurchaseApproval: null, householdSize: '', incomeHouseholdSize: '', applicantOnRegister: null, householdMembers: [], householdMembersComplete: null, householdSnapshotDate: '', householdCompositionUnchanged: null, householdHistoryConfirmations: [], dateOfBirth: '',
  isHouseholdHead: null, hasSpouse: null, spouseSameRegister: null, familyOnRegister: null,
  householdScopeKnown: null, applicantOwnsHome: null, spouseOwnsHome: null, familyOwnsHome: null,
  ownershipException: null, ownershipFactsKnown: null, ownershipFacts: [], applicantPreviouslyOwnedHome: null, spousePreviouslyOwnedHome: null, spousePremarriageOwnershipDisposed: null,
  familyPreviouslyOwnedHome: null, accountType: 'unknown', privateRankBaseDate: '', nationalRankBaseDate: '',
  privateDepositKrw: '', privateDepositAsOfDate: '', privateDepositMaintained: null, nationalRecognizedPayments: '', nationalRecognizedAmountKrw: '', nationalPaymentsAsOfDate: '',
  accountConversionUnclear: null, previousWinning: null, previousWinningDate: '',
  restrictedFromApplying: null, projectApplicationHistory: {}, citizenship: 'unknown', overseasContinuousDays: '', overseasFactsAsOfDate: '', overseasOnlyApplicantForLivelihood: null, overseasFactsHistoryConfirmations: [], ineligibleRestrictionActive: null, resaleRestrictionActive: null, rewinningRestrictionActive: null, applicationRestrictionFacts: {}, applicationRestrictionsAsOfDate: '', applicationRestrictionsHistoryConfirmations: [], specialWinning: null,
  annualIncomeKrw: '', assetsKrw: '', monthlyIncomeKrw: '', officialNetAssetsKrw: '', plannedMarriage: null, raisesChildWithoutSpouse: null, hasDeFactoPartner: null, realEstateKrw: '', vehicleKrw: '',
  dualIncome: null, maritalStatus: 'unknown', marriageDate: '', hasChildren: null, children: [], pregnant: null,
  expectedChildren: '', taxYears: '', employed: null, incomeTaxPaidWithinPastYear: null, incomeTaxFactsAsOfDate: '', incomeTaxFactsHistoryConfirmations: [], parentDateOfBirth: '', parentSupportSince: '',
  parentSameRegister: null, parentOwnsHome: null, parentSpouseOwnsHome: null, recommendationReason: '', recommendationStatus: 'unknown',
  relocatedWorker: null, militaryCurrentlyServing: null, militaryServiceYears: '', militaryFactsAsOfDate: '', militaryFactsHistoryConfirmations: [],
}
