import type { HouseholdMember, HouseholdRelation, LocalProfile, OwnerRelation } from './types'
import { factsAtDate } from './factTimeline'

export const HOUSEHOLD_LAW_URL = 'https://www.law.go.kr/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1032749671'
export const HOUSEHOLD_RELATIONS: [HouseholdRelation, string][] = [
  ['unknown', '관계 선택'], ['applicant_parent', '본인의 부모'], ['applicant_grandparent', '본인의 조부모'],
  ['spouse_parent', '배우자의 부모'], ['spouse_grandparent', '배우자의 조부모'],
  ['applicant_child', '본인의 자녀'], ['applicant_grandchild', '본인의 손자녀'], ['descendant_spouse', '본인 자녀·손자녀의 배우자'],
  ['spouse_child', '배우자의 자녀'], ['spouse_grandchild', '배우자의 손자녀'], ['sibling', '형제자매'], ['unrelated', '동거인·그 밖의 관계'],
]
export interface HouseholdScopeMember {
  id: string
  label: string
  included: boolean | null
  reason: string
  ownerRelation: OwnerRelation
  dateOfBirth: string
  ownsHome: boolean | null
  previouslyOwnedHome: boolean | null
}
export interface HouseholdScope {
  complete: boolean
  members: HouseholdScopeMember[]
  legalCount: number | null
  reviewDetail?: string
  profileField?: keyof LocalProfile
}
function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [y, m, d] = value.split('-').map(Number), parsed = new Date(Date.UTC(y, m - 1, d))
  return parsed.getUTCFullYear() === y && parsed.getUTCMonth() === m - 1 && parsed.getUTCDate() === d
}
export function householdMemberLabel(member: HouseholdMember, index?: number): string {
  const relation = HOUSEHOLD_RELATIONS.find(([kind]) => kind === member.relation)?.[1] || '관계 미입력'
  return index === undefined ? relation : `${relation} · 가족 ${index + 1}`
}
export function ownerRelationForMember(relation: HouseholdRelation): OwnerRelation {
  if (['applicant_parent', 'applicant_grandparent'].includes(relation)) return 'ascendant'
  if (['spouse_parent', 'spouse_grandparent'].includes(relation)) return 'spouse_ascendant'
  if (['applicant_child', 'applicant_grandchild', 'descendant_spouse', 'spouse_child', 'spouse_grandchild'].includes(relation)) return 'descendant'
  return 'other'
}
function familyMember(profile: LocalProfile, member: HouseholdMember, index: number): HouseholdScopeMember {
  const base = { id: member.id, label: householdMemberLabel(member, index), ownerRelation: ownerRelationForMember(member.relation), dateOfBirth: member.dateOfBirth, ownsHome: member.ownsHome, previouslyOwnedHome: member.previouslyOwnedHome }
  if (member.relation === 'unknown') return { ...base, included: null, reason: '본인과의 가족 관계를 선택하면 포함 여부를 계산합니다.' }
  if (['sibling', 'unrelated'].includes(member.relation)) return { ...base, included: false, reason: '형제자매·동거인은 같은 등본에 있다는 이유로 주택 소유 확인 대상에 포함되지 않습니다.' }
  if (member.register === 'unknown') return { ...base, included: null, reason: '본인 또는 배우자의 등본에 함께 적혀 있는지 입력하세요.' }
  if (member.register === 'separate') return { ...base, included: false, reason: '본인·배우자 어느 쪽 등본에도 함께 있지 않아 이 세대의 주택 소유 확인 대상에 포함되지 않습니다.' }
  if ((member.relation.startsWith('spouse_') || ['spouse', 'both'].includes(member.register)) && profile.hasSpouse !== true) return { ...base, included: null, reason: '배우자 유무와 가족 관계·등본 위치가 서로 맞지 않습니다. 입력을 확인하세요.' }
  if (['spouse_child', 'spouse_grandchild'].includes(member.relation)) {
    if (['applicant', 'both'].includes(member.register) || member.register === 'spouse' && profile.spouseSameRegister === true) return { ...base, included: true, reason: '배우자의 자녀·손자녀는 본인과 같은 등본에 함께 있어 확인 대상에 포함됩니다.' }
    return profile.spouseSameRegister === null ? { ...base, included: null, reason: '배우자 등본이 본인 등본과 같은지 입력하면 배우자의 자녀 포함 여부를 계산합니다.' } : { ...base, included: false, reason: '배우자의 자녀·손자녀가 별도 배우자 등본에만 있어 본인의 확인 대상에 포함되지 않습니다.' }
  }
  return { ...base, included: true, reason: member.relation.includes('parent') ? '본인 또는 배우자의 부모·조부모가 본인·배우자 등본에 함께 있어 포함됩니다.' : '본인의 자녀·손자녀와 그 배우자가 본인·배우자 등본에 함께 있어 포함됩니다.' }
}
/** Derive the legal scope from family facts rather than a completeness affirmation. */
export function deriveHousehold(profile: LocalProfile, criterionDate?: string | null): HouseholdScope {
  const temporal = criterionDate ? factsAtDate(profile, 'household', criterionDate, { date: profile.householdSnapshotDate, confirmations: profile.householdHistoryConfirmations, unchangedSince: profile.householdCompositionUnchanged === true }) : null
  if (temporal?.known) profile = temporal.profile
  const members: HouseholdScopeMember[] = [{ id: 'applicant', label: '본인', included: true, reason: '청약 신청자 본인은 확인 대상입니다.', ownerRelation: 'applicant', dateOfBirth: profile.dateOfBirth, ownsHome: profile.applicantOwnsHome, previouslyOwnedHome: profile.applicantPreviouslyOwnedHome }]
  if (profile.hasSpouse === true) members.push({ id: 'spouse', label: '배우자', included: true, reason: '법률상 배우자는 주소·등본이 달라도 확인 대상에 포함됩니다.', ownerRelation: 'spouse', dateOfBirth: '', ownsHome: profile.spouseOwnsHome, previouslyOwnedHome: profile.spousePreviouslyOwnedHome })
  members.push(...(profile.householdMembers || []).map((member, index) => familyMember(profile, member, index)))
  const incomplete = (reviewDetail: string, profileField: keyof LocalProfile): HouseholdScope => ({ complete: false, members, legalCount: null, reviewDetail, profileField })
  if (profile.applicantOnRegister === false) return incomplete('주민등록 말소·등본 없음 상태가 저장되어 있습니다. 이 공고에서 인정하는 예외 신청·세대 증빙 범위를 확인해야 합니다.', 'applicantOnRegister')
  if (profile.hasSpouse === null) return incomplete('현재 법률상 배우자가 있는지 입력하세요. 배우자는 별도 주소여도 함께 확인합니다.', 'hasSpouse')
  if (profile.maritalStatus === 'married' && profile.hasSpouse === false || profile.maritalStatus === 'single' && profile.hasSpouse === true) return incomplete('혼인 상태와 배우자 유무가 서로 다릅니다. 현재 가족 구성에 맞게 수정하세요.', 'hasSpouse')
  if (!profile.householdMembers?.length) {
    if (profile.additionalFamilyPresence === true) return incomplete('본인·배우자 외 등본에 함께 있는 가족이 있다고 입력했습니다. 해당 가족의 관계와 등본 위치를 추가하세요.', 'householdMembers')
    // A saved empty roster with an earlier explicit complete answer already
    // records applicant/spouse only. Keep that fact without asking it again.
    if (profile.additionalFamilyPresence !== false && profile.householdMembersComplete !== true) return incomplete('본인·배우자 외 등본에 함께 있는 가족이 있는지 입력하세요. 있다면 관계와 등본 위치를 추가하면 포함 여부를 계산합니다.', 'additionalFamilyPresence')
  }
  const ids = members.map((member) => member.id)
  if (ids.some((id) => !id) || new Set(ids).size !== ids.length) return incomplete('가족 항목이 중복되거나 연결 정보가 잘못되었습니다. 해당 가족 항목을 다시 추가해 주세요.', 'householdMembers')
  if (members.some((member) => member.included === null)) return incomplete('가족 관계 또는 등본 위치가 미입력·불일치입니다. 각 가족의 포함 이유에 표시된 정보를 입력하세요.', 'householdMembers')
  if (criterionDate) {
    if (!validDate(criterionDate)) return incomplete('공고의 가족 구성 기준일이 확인되지 않았습니다.', 'householdSnapshotDate')
    if (!temporal?.known) return incomplete(`공고 기준일 ${criterionDate}의 가족 구성·등본 위치가 확인되지 않았습니다. 현재 구성으로 마지막 변경된 시점을 입력하면 그 이후 공고에 함께 적용합니다.`, 'householdSnapshotDate')
  }
  return { complete: true, members, legalCount: members.filter((member) => member.included).length }
}
