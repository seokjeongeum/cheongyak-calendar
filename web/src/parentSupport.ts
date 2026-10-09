import { factsAtDate, getEvaluationToday } from './factTimeline'
import { householdMemberLabel } from './household'
import { ownershipMemberInventoryComplete } from './ownership'
import type { FactChangeGroup, HouseholdMember, LocalProfile } from './types'

export const PARENT_RULE_KINDS = ['parent_age_min', 'parent_same_register', 'parent_support_months_min', 'parent_owns_home', 'parent_spouse_owns_home'] as const
export type ParentRuleKind = typeof PARENT_RULE_KINDS[number]
export interface ParentSupportFact {
  value: string | boolean | null
  temporalKnown: boolean
  profileField: keyof LocalProfile
  historyGroup?: FactChangeGroup
  detail?: string
}
export interface ParentSupportFacts {
  mode: 'linked' | 'legacy' | 'selection'
  member?: HouseholdMember
  label: string
  candidates: HouseholdMember[]
  facts: Record<ParentRuleKind, ParentSupportFact>
}
function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [y, m, d] = value.split('-').map(Number), parsed = new Date(Date.UTC(y, m - 1, d))
  return parsed.getUTCFullYear() === y && parsed.getUTCMonth() === m - 1 && parsed.getUTCDate() === d
}
export function isParentRule(kind: string): kind is ParentRuleKind { return (PARENT_RULE_KINDS as readonly string[]).includes(kind) }
export function parentSupportCandidates(profile: LocalProfile): HouseholdMember[] {
  return profile.householdMembers.filter((member) => ['applicant_parent', 'applicant_grandparent', 'spouse_parent', 'spouse_grandparent'].includes(member.relation))
}
function sameRegister(profile: LocalProfile, member?: HouseholdMember): boolean | null {
  if (!member || member.register === 'unknown') return null
  if (['applicant', 'both'].includes(member.register)) return true
  if (member.register === 'separate') return false
  return profile.spouseSameRegister
}
function fact(value: ParentSupportFact['value'], profileField: keyof LocalProfile, temporalKnown = true, historyGroup?: FactChangeGroup, detail?: string): ParentSupportFact {
  return { value, profileField, temporalKnown, historyGroup, detail }
}
/** Family identities, rather than similar dates or relationship labels, link reused facts. */
export function resolveParentSupport(profile: LocalProfile, cutoff = getEvaluationToday()): ParentSupportFacts {
  const candidates = parentSupportCandidates(profile), explicit = profile.parentSupportMemberId || ''
  const matches = explicit ? candidates.filter((member) => member.id === explicit) : candidates.length === 1 ? candidates : []
  const member = matches.length === 1 ? matches[0] : undefined
  if (!member) {
    const legacy = !explicit && candidates.length === 0
    return { mode: legacy ? 'legacy' : 'selection', label: legacy ? '부양 대상 부모·조부모' : '부양 대상 선택', candidates, facts: {
      parent_age_min: fact(legacy ? profile.parentDateOfBirth : '', legacy ? 'parentDateOfBirth' : 'parentSupportMemberId'),
      parent_same_register: fact(legacy ? profile.parentSameRegister : null, legacy ? 'parentSameRegister' : 'parentSupportMemberId'),
      parent_support_months_min: fact(legacy ? profile.parentSupportSince : '', legacy ? 'parentSupportSince' : 'parentSupportMemberId'),
      parent_owns_home: fact(legacy ? profile.parentOwnsHome : null, legacy ? 'parentOwnsHome' : 'parentSupportMemberId'),
      parent_spouse_owns_home: fact(legacy ? profile.parentSpouseOwnsHome ?? null : null, legacy ? 'parentSpouseOwnsHome' : 'parentSupportMemberId'),
    } }
  }
  const index = profile.householdMembers.findIndex((row) => row.id === member.id), label = householdMemberLabel(member, index)
  const birthDates = new Set([member.dateOfBirth, ...profile.ownershipFacts.filter((item) => item.ownerMemberId === member.id).map((item) => item.ownerDateOfBirth)].filter((value) => !!value))
  const birth = birthDates.size === 1 && validDate([...birthDates][0]) ? [...birthDates][0] : ''
  const household = factsAtDate(profile, 'household', cutoff, { date: profile.householdSnapshotDate, confirmations: profile.householdHistoryConfirmations, unchangedSince: profile.householdCompositionUnchanged === true })
  const historicalMember = household.profile.householdMembers.find((row) => row.id === member.id)
  const currentSame = sameRegister(profile, member), historicalSame = household.known ? sameRegister(household.profile, historicalMember) : currentSame
  const points = factsAtDate(profile, 'points', cutoff)
  const currentPoints = profile.pointsFamily[member.id], historicalPoints = points.profile.pointsFamily[member.id]
  // A continuous start on the applicant's register is already a dated fact.
  // A date on a separate spouse register does not prove applicant support.
  const supportSince = currentSame === true && validDate(currentPoints?.registeredSince || '') ? currentPoints!.registeredSince : ''
  const continuousAtCutoff = !!supportSince && supportSince <= cutoff && supportSince <= getEvaluationToday()
  let owns = household.known ? historicalMember?.ownsHome ?? null : member.ownsHome
  let ownershipKnown = household.known && !!historicalMember
  let ownershipField: keyof LocalProfile = 'householdMembers'
  const properties = profile.ownershipFacts.filter((item) => item.ownerMemberId === member.id && item.propertyKind !== 'officetel')
  const validLifecycle = (item: typeof properties[number]) => item.propertyKind !== 'unknown' && validDate(item.acquiredDate) && item.acquiredDate <= getEvaluationToday() && (!item.disposedDate || validDate(item.disposedDate) && item.disposedDate >= item.acquiredDate && item.disposedDate <= getEvaluationToday())
  const datedProperties = properties.length > 0 && properties.every(validLifecycle)
  const active = properties.some((item) => validLifecycle(item) && item.acquiredDate <= cutoff && !(item.disposedDate && item.disposedDate <= cutoff))
  if (active || datedProperties) {
    if (active || ownershipMemberInventoryComplete(profile, member.id)) { owns = active; ownershipKnown = true; ownershipField = 'ownershipFacts' }
  }
  const ownershipHistory = factsAtDate(profile, 'ownership', cutoff)
  if (!ownershipKnown && ownershipHistory.known) {
    const knownProperties = ownershipHistory.profile.ownershipFacts.filter((item) => item.ownerMemberId === member.id && item.propertyKind !== 'officetel')
    const snapshotActive = knownProperties.some((item) => validLifecycle(item) && item.acquiredDate <= cutoff && !(item.disposedDate && item.disposedDate <= cutoff))
    if (snapshotActive || knownProperties.length && knownProperties.every(validLifecycle) && ownershipMemberInventoryComplete(ownershipHistory.profile, member.id, cutoff)) {
      owns = snapshotActive; ownershipKnown = true; ownershipField = 'ownershipFacts'
    }
  }
  return { mode: 'linked', member, label, candidates, facts: {
    parent_age_min: fact(birth, 'householdMembers', true, undefined, birthDates.size > 1 ? '가족 목록과 같은 소유자에게 연결된 생년월일이 서로 다릅니다. 실제 생년월일로 수정하세요.' : undefined),
    parent_same_register: fact(continuousAtCutoff ? true : historicalSame, 'householdMembers', household.known || continuousAtCutoff, 'household', '가족 목록의 등본 위치와 연속 등재일을 재사용합니다.'),
    parent_support_months_min: fact(supportSince, 'parentSupportSince', true, undefined, '이 가족의 연속 등본 등재일을 부양 시작일로 함께 사용합니다.'),
    parent_owns_home: fact(owns, ownershipField, ownershipKnown, ownershipField === 'ownershipFacts' ? 'ownership' : 'household', '선택한 가족의 보유 사실과 연결된 취득·처분 이력을 재사용합니다. 60세 이상 소유 예외로 보유 사실을 지우지 않습니다.'),
    parent_spouse_owns_home: fact(historicalPoints?.spouseOwnsHome ?? null, 'pointsFamily', points.known, 'points', '같은 가족의 가점용 배우자 보유 사실을 재사용합니다. 다른 가족의 답변은 대신 적용하지 않습니다.'),
  } }
}
