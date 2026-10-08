import { deriveHousehold } from './household'
import type { LocalProfile, OwnershipFact } from './types'

export const OWNERSHIP_LAW_URL = 'https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joNo=0053&joBrNo=00&lsiSeq=286965&urlMode=lsScJoRltInfoR'
export const OWNERSHIP_EFFECTIVE_DATE = '2026-06-15'
export interface OwnershipContext {
  criterionDate: string | null
  assessmentDate?: string
  supplyType?: string
  publicRental?: boolean
}
export interface PropertyOwnershipDecision {
  id: string
  counted: boolean | null
  clause: number | null
  detail: string
  missingFields: (keyof OwnershipFact)[]
  evidenceUrl: string
}
export interface OwnershipDecision {
  value: boolean | null
  countedHomes: number | null
  detail: string
  properties: PropertyOwnershipDecision[]
  profileField?: keyof LocalProfile
}
function date(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const [y, m, d] = value.split('-').map(Number), result = new Date(Date.UTC(y, m - 1, d))
  return result.getUTCFullYear() === y && result.getUTCMonth() === m - 1 && result.getUTCDate() === d ? result : null
}
function n(value: string): number | null { return /^\d+(?:\.\d+)?$/.test(value) && Number.isFinite(Number(value)) ? Number(value) : null }
function koreanToday(): string { return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()) }
function age(birth: string, cutoff: string): number | null {
  const b = date(birth), c = date(cutoff)
  return !b || !c || b > c ? null : c.getUTCFullYear() - b.getUTCFullYear() - (cutoff.slice(5) < birth.slice(5) ? 1 : 0)
}
function addMonths(start: string, months: number): string | null {
  const d = date(start)
  if (!d) return null
  const target = d.getUTCMonth() + months, y = d.getUTCFullYear() + Math.floor(target / 12), m = target % 12
  return new Date(Date.UTC(y, m, Math.min(d.getUTCDate(), new Date(Date.UTC(y, m + 1, 0)).getUTCDate()))).toISOString().slice(0, 10)
}
function outcome(fact: OwnershipFact, counted: boolean | null, clause: number | null, detail: string, missingFields: (keyof OwnershipFact)[] = []): PropertyOwnershipDecision {
  return { id: fact.id, counted, clause, detail, missingFields, evidenceUrl: OWNERSHIP_LAW_URL }
}
interface Clause { number: number; matches: boolean | null; detail: string; missing: (keyof OwnershipFact)[] }
const yes = (number: number, detail: string): Clause => ({ number, matches: true, detail, missing: [] })
const no = (number: number): Clause => ({ number, matches: false, detail: '', missing: [] })
const need = (number: number, detail: string, ...missing: (keyof OwnershipFact)[]): Clause => ({ number, matches: null, detail, missing })
function timedCompletion(fact: OwnershipFact, field: 'disposedDate' | 'registerCorrectedDate', today: string, clause: number): Clause {
  if (!date(fact.notificationDate)) return need(clause, '부적격 통보일을 입력하면 법정 3개월 기한을 계산합니다.', 'notificationDate')
  const limit = addMonths(fact.notificationDate, 3)!
  const completion = fact[field]
  if (!date(completion)) return need(clause, `법정 기한 ${limit}까지 실제 ${field === 'disposedDate' ? '처분' : '공부 정리'}를 마친 날짜가 필요합니다.`, field)
  if (completion > today) return need(clause, `${completion}은 아직 지나지 않았습니다. 예정된 ${field === 'disposedDate' ? '처분' : '공부 정리'}는 완료로 인정하지 않습니다.`, field)
  return completion >= fact.notificationDate && completion <= limit ? yes(clause, `부적격 통보 ${fact.notificationDate} → 실제 완료 ${completion}: 3개월 기한 ${limit} 이내`) : no(clause)
}
function officialPrice(fact: OwnershipFact, cutoff: string, clause: number): Clause | null {
  if (fact.valueBasis !== 'annex1_official') return need(clause, '시세 대신 별표 1에 따라 산정한 공시가격·분양권 가격이 필요합니다.', 'valueBasis', 'officialValueKrw')
  if (n(fact.officialValueKrw) === null) return need(clause, '별표 1 기준의 공식 주택가격을 입력하세요.', 'officialValueKrw')
  if (!date(fact.valueAsOfDate) || fact.valueAsOfDate > cutoff) return need(clause, '공고 기준일에 적용되는 공식 가격의 기준일을 입력하세요.', 'valueAsOfDate')
  return null
}
/** All twelve Article 53 paths compare factual evidence; no self-certified exception switch. */
export function evaluatePropertyOwnership(fact: OwnershipFact, context: OwnershipContext, ownedCount: number | null): PropertyOwnershipDecision {
  const cutoff = context.criterionDate, today = context.assessmentDate || koreanToday()
  if (!cutoff || !date(cutoff) || cutoff < OWNERSHIP_EFFECTIVE_DATE) return outcome(fact, null, null, '이 공고 기준일의 적용 법령·경과조치를 확인해야 합니다.')
  if (fact.propertyKind === 'officetel') return outcome(fact, false, null, '건축물 구분이 오피스텔인 보유 사실은 이 아파트 주택 소유 판정에 포함하지 않습니다.')
  if (fact.propertyKind === 'unknown') return outcome(fact, null, null, '보유한 주택·권리의 종류를 선택하세요.', ['propertyKind'])
  if (fact.ownerRelation === 'unknown' || fact.ownerRelation === 'other') return outcome(fact, null, null, '소유자와 신청자의 법정 세대관계를 확인해야 합니다.', ['ownerRelation'])
  if (fact.standardResidentialBuilding === true && (fact.abandonedOrDestroyedOrNonResidential === true || fact.oldLawUnauthorized === true)) return outcome(fact, null, null, '일반 허가·신고 주택 입력과 폐가·다른 용도·무허가 건물 입력이 서로 다릅니다. 현재 건축물 상태를 바로잡으세요.', ['standardResidentialBuilding', 'abandonedOrDestroyedOrNonResidential', 'oldLawUnauthorized'])
  if (!date(fact.acquiredDate)) return outcome(fact, null, null, '공고 기준일의 보유 여부를 비교할 실제 취득일을 입력하세요.', ['acquiredDate'])
  if (fact.acquiredDate > cutoff) return outcome(fact, false, null, `취득일 ${fact.acquiredDate}은 공고 기준일 ${cutoff} 뒤입니다.`)
  if (fact.disposedDate && !date(fact.disposedDate)) return outcome(fact, null, null, '실제 처분일의 날짜 형식을 확인하세요.', ['disposedDate'])
  if (date(fact.disposedDate) && fact.disposedDate < fact.acquiredDate) return outcome(fact, null, null, '처분일이 취득일보다 빠릅니다. 취득·처분일을 다시 확인하세요.', ['acquiredDate', 'disposedDate'])
  if (date(fact.disposedDate) && fact.disposedDate <= cutoff && fact.disposedDate <= today) return outcome(fact, false, null, `공고 기준일 이전 ${fact.disposedDate}에 실제 처분했습니다.`)
  const kind = ['presale_right', 'occupancy_right'].includes(fact.propertyKind) ? fact.underlyingPropertyKind : fact.propertyKind
  const area = n(fact.areaSqm), capital = ['11', '28', '41'].includes(fact.propertyRegionCode.slice(0, 2))
  const clauses: Clause[] = []
  const oneHome = (number: number, detail: string): Clause => ownedCount === null
    ? need(number, '공유지분 보유 항목들이 같은 한 주택인지 여러 주택인지 확인되지 않아 세대의 주택 수를 확정할 수 없습니다. 한 주택 보유 예외는 원문과 실제 소유 자료를 확인해야 합니다.')
    : yes(number, detail)
  // 1: only inherited shared title, completed disposal after official notification.
  if (fact.acquisitionMethod === 'inheritance' && fact.ownedShare !== false) clauses.push(fact.inheritedShare === true && fact.ownedShare === true ? timedCompletion(fact, 'disposedDate', today, 1) : need(1, '상속으로 취득한 공유지분인지 입력하세요.', 'inheritedShare', 'ownedShare'))
  // 2: non-capital rural detached dwelling + residence/move and one statutory alternative.
  if (kind === 'detached' && fact.propertyRegionCode && !capital && (fact.outsideUrbanArea !== false || fact.inMyeon !== false)) {
    if (fact.outsideUrbanArea !== true && fact.inMyeon !== true) clauses.push(need(2, '수도권 외 도시지역 밖 또는 면 지역에 있는 단독주택인지 입력하세요.', 'outsideUrbanArea', 'inMyeon'))
    else if (fact.ownerPreviouslyResided !== true || fact.movedToOtherConstructionArea !== true) clauses.push(fact.ownerPreviouslyResided === false || fact.movedToOtherConstructionArea === false ? no(2) : need(2, '그 주택건설지역에서 거주하다 다른 주택건설지역으로 이주했는지 입력하세요. 상속은 피상속인의 거주 사실을 포함합니다.', 'ownerPreviouslyResided', 'movedToOtherConstructionArea'))
    else {
      const oldEnough = age(fact.buildingApprovalDate, cutoff)
      if ((oldEnough !== null && oldEnough >= 20) || (area !== null && area <= 85) || (fact.firstRegisteredDomicile === true && fact.fromAscendantOrSpouse === true)) clauses.push(yes(2, '수도권 외 농촌 단독주택의 지역·거주·이주 및 법정 주택 요건을 충족합니다.'))
      else if ((oldEnough === null && !fact.buildingApprovalDate) || area === null || fact.firstRegisteredDomicile === null || fact.fromAscendantOrSpouse === null) clauses.push(need(2, '사용승인일·전용면적 또는 최초 등록기준지에서 직계존속·배우자로부터 이전받은 사실을 입력하세요.', 'buildingApprovalDate', 'areaSqm', 'firstRegisteredDomicile', 'fromAscendantOrSpouse'))
    }
  }
  // 3: completed sale or completed disposal within notice period by individual developer.
  if (fact.builderForSale === true) clauses.push(fact.saleCompleted === true ? yes(3, '개인주택사업자가 분양 목적으로 건설한 주택의 분양을 완료했습니다.') : timedCompletion(fact, 'disposedDate', today, 3))
  else if (fact.acquisitionMethod === 'construction' && fact.builderForSale === null) clauses.push(need(3, '개인주택사업자로 분양 목적으로 건설했는지 입력하세요.', 'builderForSale'))
  // 4: statutory employee dormitory housing, not any employer-owned dwelling.
  if (fact.governmentEmployeeHousingPolicy === true || fact.individualBusinessRegistered === true && fact.employeeDormitoryUnderHousingAct === true) clauses.push(yes(4, '법 제5조 제3항의 근로자 숙소 건설 또는 정부시책 근로자 공급 주택에 해당합니다.'))
  else if (fact.employeeDormitoryUnderHousingAct === true && fact.individualBusinessRegistered === null) clauses.push(need(4, '세무서 개인사업자 등록 사실을 입력하세요.', 'individualBusinessRegistered'))
  // 5: the entire household owns one dwelling/right only.
  if (area !== null && area <= 20 && (ownedCount === 1 || ownedCount === null)) clauses.push(oneHome(5, `세대가 보유한 유일한 주택·권리는 전용 ${area}㎡로 20㎡ 이하입니다.`))
  // 6: oldest ancestor carve-out excludes elder-parent and public-rental supply.
  if (['ascendant', 'spouse_ascendant'].includes(fact.ownerRelation) && !context.publicRental && !/노부모|elder.?parent/i.test(context.supplyType || '')) {
    const years = age(fact.ownerDateOfBirth, cutoff)
    clauses.push(years === null ? need(6, '직계존속 소유자의 생년월일을 입력하세요.', 'ownerDateOfBirth') : years >= 60 ? yes(6, `공고 기준일의 직계존속 소유자 만 나이는 ${years}세로 60세 이상입니다.`) : no(6))
  }
  // 7: completed demolition/register correction, not an intended future action.
  const right = ['presale_right', 'occupancy_right'].includes(fact.propertyKind)
  if (!right && fact.abandonedOrDestroyedOrNonResidential === true) clauses.push(timedCompletion(fact, 'registerCorrectedDate', today, 7))
  else if (!right && fact.abandonedOrDestroyedOrNonResidential === null && fact.standardResidentialBuilding !== true) clauses.push(need(7, '허가·신고된 일반 주거용 건축물인지 입력하세요. 폐가·멸실·다른 용도라면 추가 사실을 비교합니다.', 'standardResidentialBuilding'))
  // 8: proof of legality under the former Building Act is necessary.
  if (!right && fact.oldLawUnauthorized === true) clauses.push(fact.lawfulAtConstructionEvidence === true ? yes(8, '종전 건축법 적용 무허가건물이며 건축 당시 적법성 증빙을 보유했습니다.') : fact.lawfulAtConstructionEvidence === false ? no(8) : need(8, '건축 당시 법령상 적법한 건물임을 증명하는 자료가 있는지 입력하세요.', 'lawfulAtConstructionEvidence'))
  else if (!right && fact.oldLawUnauthorized === null && fact.standardResidentialBuilding !== true) clauses.push(need(8, '일반 허가·신고 주택이 아니라면 종전 건축법 무허가 여부를 입력하세요.', 'oldLawUnauthorized'))
  // 9: official appraisal basis, underlying legal type and household-wide count.
  if (!context.publicRental && (ownedCount === 1 || ownedCount === null) && area !== null && area <= 85) {
    const limit = kind === 'apartment' ? capital ? 160_000_000 : 100_000_000 : capital ? 500_000_000 : 300_000_000
    if (kind === 'unknown') clauses.push(need(9, '분양권·입주권의 실제 주택 종류를 입력하세요.', 'underlyingPropertyKind'))
    else if ((kind !== 'apartment' || area <= 60) && ['apartment', 'detached', 'multi_family', 'row_house', 'urban_small'].includes(kind)) {
      if (!fact.propertyRegionCode) clauses.push(need(9, '보유 주택 소재 시도를 선택하세요. 수도권 가격 기준이 다릅니다.', 'propertyRegionCode'))
      else {
        const priceGap = officialPrice(fact, cutoff, 9)
        clauses.push(priceGap || (n(fact.officialValueKrw)! <= limit ? oneHome(9, `세대의 유일한 주택·권리 전용 ${area}㎡, 별표 1 가격 ${Number(fact.officialValueKrw).toLocaleString('ko-KR')}원이 ${capital ? '수도권' : '비수도권'} 법정 한도 ${limit.toLocaleString('ko-KR')}원 이내입니다.`) : no(9)))
      }
    }
  }
  // 10: original direct recipient of residual first-come right; resale excluded.
  if (['presale_right', 'occupancy_right'].includes(fact.propertyKind) && fact.acquisitionMethod === 'first_come') clauses.push(fact.originalResidualFirstCome === true ? yes(10, '법정 선정 이후 잔여주택을 선착순으로 직접 공급받은 분양권등입니다. 전매 매수에 해당하지 않습니다.') : fact.originalResidualFirstCome === false ? no(10) : need(10, '법정 잔여주택을 선착순으로 직접 공급받았는지 입력하세요.', 'originalResidualFirstCome'))
  // 11: rental-deposit loss + auction of that same rented dwelling.
  if (!context.publicRental && (fact.acquisitionMethod === 'auction' || fact.auctionAcquisition === true) && area !== null && area <= 85) {
    if (fact.unpaidRentalDeposit === null) clauses.push(need(11, '살던 임차주택의 보증금을 돌려받지 못하고 경매·공매로 취득했는지 입력하세요.', 'unpaidRentalDeposit'))
    else if (fact.unpaidRentalDeposit === true && fact.auctionAcquisition === true) {
      const limit = capital ? 300_000_000 : 150_000_000
      if (!fact.propertyRegionCode) clauses.push(need(11, '경매 취득 주택의 소재 시도를 선택하세요.', 'propertyRegionCode'))
      else clauses.push(officialPrice(fact, cutoff, 11) || (n(fact.officialValueKrw)! <= limit ? yes(11, '임차보증금 미반환 주택을 경매·공매로 취득했고 면적·공식 가격 한도를 충족합니다.') : no(11)))
    } else if (fact.unpaidRentalDeposit === true && fact.auctionAcquisition === null) clauses.push(need(11, '임차주택 자체를 경매·공매로 취득한 사실을 입력하세요.', 'auctionAcquisition'))
  }
  // 12: applicant's first purchase of the previously rented non-apartment in 2024.
  if (fact.ownerRelation === 'applicant' && fact.acquiredDate >= '2024-01-01' && fact.acquiredDate <= '2024-12-31' && ['detached', 'multi_family', 'row_house'].includes(kind) && area !== null && area <= 60) {
    if (!fact.propertyRegionCode) clauses.push(need(12, '취득 주택의 소재 시도를 선택하세요.', 'propertyRegionCode'))
    else if (fact.firstEverAcquisition === null) clauses.push(need(12, '생애 최초 주택 취득이었는지 입력하세요.', 'firstEverAcquisition'))
    else if (fact.firstEverAcquisition === true) {
      const price = n(fact.acquisitionPriceKrw), start = date(fact.tenantResidenceStartDate), acquisition = date(fact.acquiredDate)!
      if (price === null) clauses.push(need(12, '부동산 거래신고 취득가격을 입력하세요.', 'acquisitionPriceKrw'))
      else if (price <= (capital ? 300_000_000 : 200_000_000)) {
        if (!start) clauses.push(need(12, '취득 전 임차인으로 거주하기 시작한 날짜를 입력하세요.', 'tenantResidenceStartDate'))
        else {
          const previousDay = new Date(acquisition.getTime() - 86_400_000).toISOString().slice(0, 10)
          clauses.push(addMonths(fact.tenantResidenceStartDate, 12)! <= previousDay ? yes(12, '2024년 생애 최초 임차주택 취득이며 면적·신고가격과 취득 전날까지 1년 거주를 충족합니다.') : no(12))
        }
      }
    }
  }
  const matched = clauses.find((clause) => clause.matches === true)
  if (matched) return outcome(fact, false, matched.number, `제53조 제${matched.number}호: ${matched.detail}`)
  const undecided = clauses.filter((clause) => clause.matches === null)
  if (fact.acquisitionMethod === 'unknown') undecided.unshift(need(1, '취득 경위를 입력하면 상속 지분·선착순 최초 공급·경매 취득의 법정 예외를 비교합니다.', 'acquisitionMethod'))
  if (area === null) undecided.unshift(need(5, '전용면적을 입력하면 20㎡ 이하·소형저가 주택 예외를 비교할 수 있습니다.', 'areaSqm'))
  if (undecided.length) return outcome(fact, null, undecided[0].number, undecided.map((clause) => clause.detail).join(' '), [...new Set(undecided.flatMap((clause) => clause.missing))])
  return outcome(fact, true, null, '입력한 보유 사실은 지원하는 제53조 예외에 해당하지 않아 주택 소유로 계산합니다.')
}

export function evaluateHouseholdOwnership(profile: LocalProfile, context: OwnershipContext): OwnershipDecision {
  if (!context.criterionDate || !date(context.criterionDate)) return { value: null, countedHomes: null, properties: [], detail: '주택 보유를 비교할 공식 자격 기준일이 아직 확인되지 않았습니다.' }
  const scope = deriveHousehold(profile, context.criterionDate)
  if (!scope.complete) return { value: null, countedHomes: null, properties: [], detail: scope.reviewDetail || '가족 관계와 등본 위치를 입력하세요.', profileField: scope.profileField }
  const members = scope.members.filter((member) => member.included === true)
  const knownOwners = members.map((member) => member.ownsHome)
  if (profile.ownershipFactsKnown !== true) {
    if (knownOwners.every((owns) => owns === false)) return { value: true, countedHomes: 0, properties: [], detail: `계산된 확인 대상 ${members.length}명(${members.map((member) => member.label).join(', ')})의 주택·분양권·입주권 미보유 사실을 입력했습니다.` }
    const missing = members.find((member) => member.ownsHome === null)
    return { value: null, countedHomes: null, properties: [], detail: knownOwners.includes(true) ? '보유한 주택·권리를 소유한 가족과 연결하고 면적·취득 경위를 입력하면 법정 예외를 자동 비교합니다.' : `${missing?.label || '확인 대상 가족'}의 주택·권리 보유 사실을 입력하세요.`, profileField: knownOwners.includes(true) ? 'ownershipFacts' : missing?.id === 'applicant' ? 'applicantOwnsHome' : missing?.id === 'spouse' ? 'spouseOwnsHome' : 'householdMembers' }
  }
  const linkedFacts: OwnershipFact[] = []
  for (const fact of profile.ownershipFacts) {
    // The only unambiguous migration links are applicant and spouse themselves.
    const memberId = fact.ownerMemberId || (['applicant', 'spouse'].includes(fact.ownerRelation) ? fact.ownerRelation : '')
    const member = scope.members.find((person) => person.id === memberId)
    if (!member) return { value: null, countedHomes: null, properties: [], detail: `주택·권리 ${fact.id || '항목'}의 소유자를 위 가족 목록에서 선택하세요. 예전 ‘부모·자녀’ 답변만으로 어느 가족의 소유인지 확정하지 않습니다.`, profileField: 'ownershipFacts' }
    if (member.included === false) continue
    if (member.dateOfBirth && fact.ownerDateOfBirth && member.dateOfBirth !== fact.ownerDateOfBirth) return { value: null, countedHomes: null, properties: [], detail: `${member.label}의 가족 목록과 주택 소유 항목의 생년월일이 다릅니다. 입력을 바로잡으세요.`, profileField: 'ownershipFacts' }
    linkedFacts.push({ ...fact, ownerMemberId: member.id, ownerRelation: member.ownerRelation, ownerDateOfBirth: member.dateOfBirth || fact.ownerDateOfBirth })
  }
  const missingOwner = members.find((member) => member.ownsHome === true && !linkedFacts.some((fact) => fact.ownerMemberId === member.id))
  if (missingOwner) return { value: null, countedHomes: null, properties: [], detail: `${missingOwner.label}의 주택·권리 보유를 입력했지만 연결된 소유 항목이 없습니다. 추가하거나 보유 사실을 바로잡으세요.`, profileField: 'ownershipFacts' }
  const unknownOwner = members.find((member) => member.ownsHome === null && !linkedFacts.some((fact) => fact.ownerMemberId === member.id))
  if (unknownOwner) return { value: null, countedHomes: null, properties: [], detail: `${unknownOwner.label}의 주택·권리 보유 사실을 입력하세요. 다른 가족의 소유 목록만으로 이 사람의 미보유를 확정하지 않습니다.`, profileField: unknownOwner.id === 'applicant' ? 'applicantOwnsHome' : unknownOwner.id === 'spouse' ? 'spouseOwnsHome' : 'householdMembers' }
  const activeFacts = linkedFacts.filter((fact) => fact.propertyKind !== 'officetel' && (!context.criterionDate || !date(fact.acquiredDate) || fact.acquiredDate <= context.criterionDate) && !(context.criterionDate && date(fact.disposedDate) && fact.disposedDate <= context.criterionDate))
  // Separate owners' shares may describe one physical dwelling. Without a
  // dwelling identity, neither collapse those records nor call them two homes.
  // A sole-title dwelling alongside a shared dwelling already proves >1 home.
  const countAtCutoff = activeFacts.length > 1 && activeFacts.every((fact) => fact.ownedShare === true) ? null : activeFacts.length
  const decisions = linkedFacts.map((fact) => evaluatePropertyOwnership(fact, context, countAtCutoff))
  const counted = decisions.filter((decision) => decision.counted === true).length, pending = decisions.some((decision) => decision.counted === null)
  return { value: counted > 0 ? false : pending ? null : true, countedHomes: pending ? null : counted, properties: decisions, detail: decisions.length ? decisions.map((decision) => decision.detail).join(' / ') : `계산된 확인 대상 ${members.length}명의 보유 주택·권리가 없습니다.`, profileField: pending ? 'ownershipFacts' : undefined }
}
