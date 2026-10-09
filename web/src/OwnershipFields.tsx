import { MoneyInput } from './MoneyInput'
import { deriveHousehold } from './household'
import { provinceOptions } from './regions'
import { getProfileQuestionModel } from './profileQuestionModel'
import { createOwnershipFact, type LocalProfile, type Notice, type OwnershipFact, type PropertyKind } from './types'

const KINDS: [PropertyKind, string][] = [['unknown', '종류 선택'], ['apartment', '아파트'], ['detached', '단독주택'], ['multi_family', '다세대주택'], ['row_house', '연립주택'], ['urban_small', '도시형 생활주택'], ['presale_right', '분양권'], ['occupancy_right', '입주권'], ['officetel', '오피스텔']]
const NO_NOTICES: Notice[] = []
const ANNEX_ONE_URL = 'https://www.law.go.kr/법령/주택공급에관한규칙'
const OFFICIAL_PRICE_URL = 'https://www.realtyprice.kr/notice/main/mainBody.htm'

function OfficialPriceHelp({ rights }: { rights: boolean }) {
  return <div className="field-help">
    <p>별표 1은 청약 가점의 무주택기간 등 산정 기준입니다. 여기의 공식 가격은 소형·저가주택 등 법정 무주택 예외의 가격 한도와 비교할 금액입니다.</p>
    {rights ? <p>분양권·입주권: 원래 공급계약서의 공급가격을 입력하세요. 발코니 확장 등 선택품목 가격과 전매 프리미엄은 포함하지 않습니다. 가격 적용일은 해당 공급계약일입니다.</p> : <>
      <p>현재 보유 중이거나 공고일 후 처분한 주택: 공고일에 가장 가까운 날에 공시된 주택공시가격을 사용합니다. 아파트·연립·다세대는 공동주택가격, 단독주택은 개별주택가격을 확인하세요.</p>
      <p>공고일 전에 처분한 주택: 처분일 전에 공시된 가격 중 처분일에 가장 가까운 가격을 사용합니다. 가격 적용일에는 선택한 가격의 공시일을 입력하세요. 공시가격 산정기준일인 1월 1일과 구분합니다.</p>
      <p>2007년 9월 1일 전에 처분했다면 그날 이전에 공시된 가격 중 2007년 9월 1일에 가장 가까운 가격을 적용합니다.</p>
    </>}
    <p>매매가·KB시세를 이 가격으로 대신하지 않습니다. 2024년 생애 최초 임차주택 취득 예외의 거래신고 가격은 아래 취득 신고가격에 입력합니다. 공공주택의 자산 심사는 해당 공고의 별도 평가 기준을 따릅니다.</p>
    <p><a href={ANNEX_ONE_URL} target="_blank" rel="noopener noreferrer">주택공급 규칙 별표 1 · 제53조</a> · <a href={OFFICIAL_PRICE_URL} target="_blank" rel="noopener noreferrer">부동산공시가격알리미</a></p>
  </div>
}

function Fact({ label, value, onChange }: { label: string; value: boolean | null; onChange: (value: boolean | null) => void }) {
  return <fieldset className="radio-field"><legend>{label}</legend><div>{([[true, '예'], [false, '아니요'], [null, '모름']] as const).map(([answer, text]) => <button type="button" key={text} aria-pressed={value === answer} className={value === answer ? 'chosen' : ''} onClick={() => onChange(answer)}>{text}</button>)}</div></fieldset>
}

export function OwnershipFields({ profile, onChange, today, notices = NO_NOTICES }: { profile: LocalProfile; onChange: (value: LocalProfile) => void; today: string; notices?: Notice[] }) {
  const patch = (id: string, part: Partial<OwnershipFact>) => onChange({ ...profile, ownershipFacts: profile.ownershipFacts.map((fact) => fact.id === id ? { ...fact, ...part } : fact) })
  const household = deriveHousehold(profile)
  const projectRules = getProfileQuestionModel(notices, today).restrictionRules.filter(({ rule }) => rule.kind === 'original_project_contract_ownership' && typeof rule.project_id === 'string')
  const projects = [...new Map(projectRules.map(({ rule, notice }) => [String(rule.project_id), { id: String(rule.project_id), title: notice.title }])).values()]
  const hasProjectContract = profile.applicationHistoryEvents.some((event) => ['contract', 'additional_resident_contract'].includes(event.eventKind) && projects.some((project) => project.id === event.projectId))
  const hasOwnership = household.members.some((member) => member.included !== false && member.ownsHome === true)
  if (!hasOwnership && !profile.ownershipFacts.length && !hasProjectContract) return null
  return <section className="question-group ownership-facts" data-profile-field="ownershipFacts">
    <h4>소유한 주택·권리의 사실</h4><p className="field-help">예외 인정 여부는 앱이 공고별로 비교합니다. 현재 보유하거나 공고 기준일 전후에 처분한 주택·권리를 각각 추가하세요. 같은 주택의 공유지분은 한 항목으로 입력합니다.</p>
    {household.members.filter((member) => member.included !== false && (member.ownsHome === true || profile.ownershipPropertyCounts?.[member.id] !== undefined)).map((member) => <label key={member.id} data-profile-field="ownershipPropertyCounts">현재 {member.label}의 주택·분양권·입주권 수 (호)<input type="number" inputMode="numeric" min="0" step="1" value={profile.ownershipPropertyCounts?.[member.id] || ''} onChange={(event) => onChange({ ...profile, ownershipPropertyCounts: { ...profile.ownershipPropertyCounts, [member.id]: event.target.value } })} /><span className="field-help">오피스텔은 제외합니다. 같은 주택의 공유지분은 1호이며, 처분한 주택은 현재 수에 포함하지 않습니다. 입력한 수와 연결된 취득·처분 항목을 함께 비교합니다.</span></label>)}
    {profile.ownershipFacts.map((item, index) => {
      const date = (key: keyof OwnershipFact, label: string) => <label>{label}<input type="date" max={today} value={item[key] as string} onChange={(event) => patch(item.id, { [key]: event.target.value })} /></label>
      const fact = (key: keyof OwnershipFact, label: string) => <Fact label={label} value={item[key] as boolean | null} onChange={(value) => patch(item.id, { [key]: value })} />
      const money = (key: keyof OwnershipFact, label: string) => <MoneyInput label={label} value={item[key] as string} onChange={(value) => patch(item.id, { [key]: value })} />
      const rights = ['presale_right', 'occupancy_right'].includes(item.propertyKind)
      const buildingKind = rights ? item.underlyingPropertyKind : item.propertyKind
      return <section className="ownership-item" key={item.id} aria-label={`소유 항목 ${index + 1}`}>
        <div className="ownership-item-heading"><h5>주택·권리 {index + 1}</h5><button type="button" className="text-button" onClick={() => onChange({ ...profile, ownershipFactsKnown: null, ownershipFacts: profile.ownershipFacts.filter((other) => other.id !== item.id) })}>항목 {index + 1} 삭제</button></div>
        <label>이 주택·권리를 소유한 사람<select value={item.ownerMemberId || (['applicant', 'spouse'].includes(item.ownerRelation) ? item.ownerRelation : '')} onChange={(event) => { const owner = household.members.find((member) => member.id === event.target.value); patch(item.id, { ownerMemberId: owner?.id || '', ownerRelation: owner?.ownerRelation || 'unknown', ownerDateOfBirth: owner?.dateOfBirth || '' }) }}><option value="">위 가족 목록에서 소유자 선택</option>{household.members.map((member) => <option key={member.id} value={member.id}>{member.label}{member.included === false ? ' · 이 세대의 확인 대상에서 제외' : ''}</option>)}</select></label>
        {['ascendant', 'spouse_ascendant'].includes(item.ownerRelation) && date('ownerDateOfBirth', '소유한 부모·조부모 생년월일')}
        <label>주택·권리 종류<select value={item.propertyKind} onChange={(event) => patch(item.id, { propertyKind: event.target.value as PropertyKind })}>{KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        {rights && <label>해당 권리의 주택 종류<select value={item.underlyingPropertyKind} onChange={(event) => patch(item.id, { underlyingPropertyKind: event.target.value as PropertyKind })}>{KINDS.filter(([value]) => !['presale_right', 'occupancy_right', 'officetel'].includes(value)).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
        <label>주거 전용면적 (㎡)<input type="number" min="0" step="0.0001" inputMode="decimal" value={item.areaSqm} onChange={(event) => patch(item.id, { areaSqm: event.target.value })} /></label>
        <label>주택이 있는 시도<select value={item.propertyRegionCode} onChange={(event) => patch(item.id, { propertyRegionCode: event.target.value })}><option value="">지역 선택</option>{provinceOptions().map((option) => <option key={option.code} value={option.code}>{option.name}</option>)}</select></label>
        {date('acquiredDate', rights ? '권리 취득일 (분양권은 공급계약일)' : '취득일 (등기·신고 기준)')}{date('disposedDate', '처분 완료일 (현재 보유하면 비워두세요)')}
        {!!projects.length && <><label>최초 공급 사업 · 이 주택·권리의 계약 사업<select value={item.projectId || ''} onChange={(event) => patch(item.id, { projectId: event.target.value })}><option value="">사업 선택 · 해당 없으면 비워두세요</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.title} · {project.id}</option>)}{item.projectId && !projects.some((project) => project.id === item.projectId) && <option value={item.projectId}>기존 입력 · {item.projectId}</option>}</select></label><p className="field-help">이 항목이 해당 사업의 공급계약으로 취득한 주택·권리일 때 선택하세요. 계약일이 같아도 다른 주택은 선택하지 않습니다.</p></>}
        <label>취득 경위<select value={item.acquisitionMethod} onChange={(event) => patch(item.id, { acquisitionMethod: event.target.value as OwnershipFact['acquisitionMethod'] })}>{[['unknown', '경위 선택'], ['purchase', '매매'], ['inheritance', '상속'], ['gift', '증여'], ['construction', '직접 건설'], ['auction', '경매·공매'], ['first_come', '잔여주택 선착순 최초 공급']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        {fact('ownedShare', '전체 소유가 아니라 공유지분을 보유했나요?')}
        {item.acquisitionMethod === 'inheritance' && <>{fact('inheritedShare', '상속으로 공유지분을 취득했나요?')}{date('notificationDate', '사업주체의 부적격 통보를 받은 날 (통보 전이면 비워두세요)')}</>}
        <details className="additional-questions"><summary>공식 가격과 취득가격</summary>{money('officialValueKrw', '무주택 예외 판정용 공식 가격 (원)')}<label>평가가격의 기준<select value={item.valueBasis} onChange={(event) => patch(item.id, { valueBasis: event.target.value as OwnershipFact['valueBasis'] })}><option value="unknown">기준 선택</option><option value="annex1_official">공고·주택공급 규칙 별표 1 기준 가격</option><option value="market">매매가·시세 (공식 평가가격으로 사용하지 않음)</option></select></label><OfficialPriceHelp rights={rights} />{date('valueAsOfDate', rights ? '가격 적용일 · 원래 공급계약일' : '가격 적용일 · 선택한 주택가격 공시일')}{money('acquisitionPriceKrw', '취득 신고가격 (원)')}</details>
        {buildingKind === 'detached' && <details className="additional-questions"><summary>단독주택의 건축·거주 이력</summary>{date('buildingApprovalDate', '사용승인일')}{fact('outsideUrbanArea', '토지이용계획상 도시지역 밖에 있나요?')}{fact('inMyeon', '행정구역상 면에 있나요?')}{fact('ownerPreviouslyResided', '소유자가 해당 주택건설지역에서 거주했나요?')}{fact('movedToOtherConstructionArea', '그 후 다른 주택건설지역으로 이주했나요?')}{fact('firstRegisteredDomicile', '소유자의 최초 등록기준지에 지어진 주택인가요?')}{fact('fromAscendantOrSpouse', '직계존속 또는 배우자로부터 상속 등으로 이전받았나요?')}</details>}
        {item.acquisitionMethod === 'construction' && <details className="additional-questions" open><summary>개인 건설·근로자 숙소의 사실</summary>{fact('builderForSale', '개인주택사업자로서 분양을 목적으로 직접 건설했나요?')}{fact('saleCompleted', '건설한 주택의 분양을 모두 완료했나요?')}{date('notificationDate', '부적격 통보일')}{fact('individualBusinessRegistered', '세무서에 개인사업자로 등록되어 있나요?')}{fact('employeeDormitoryUnderHousingAct', '주택법 제5조제3항에 따라 소속 근로자 숙소로 건설했나요?')}</details>}
        {fact('governmentEmployeeHousingPolicy', '정부 시책으로 근로자에게 공급한 사업계획 승인 주택을 공급받았나요?')}
        {rights && item.acquisitionMethod === 'first_come' && fact('originalResidualFirstCome', '일반공급 후 남은 주택을 사업주체에게 선착순으로 처음 공급받았나요?')}
        {item.acquisitionMethod === 'auction' && <details className="additional-questions" open><summary>거주하던 임차주택의 경매·공매 취득</summary>{fact('auctionAcquisition', '경매 또는 공매로 취득했나요?')}{fact('unpaidRentalDeposit', '돌려받지 못한 보증금이 있는 임차주택을 취득했나요?')}</details>}
        {item.acquiredDate >= '2024-01-01' && item.acquiredDate <= '2024-12-31' && <details className="additional-questions" open><summary>2024년 거주하던 임차주택 취득</summary>{fact('firstEverAcquisition', '생애 처음 취득한 주택인가요?')}{date('tenantResidenceStartDate', '취득 전에 임차인으로 거주하기 시작한 날')}</details>}
        {fact('standardResidentialBuilding', '건축물대장상 허가·신고된 일반 주택이고 실제로도 주거용인가요?')}
        {item.standardResidentialBuilding !== true && <details className="additional-questions" open={item.standardResidentialBuilding === false}><summary>건축물 공부·실제 이용 상태</summary>{fact('abandonedOrDestroyedOrNonResidential', '공부상 주택이지만 폐가·멸실 또는 다른 용도로 사용되고 있나요?')}{item.abandonedOrDestroyedOrNonResidential === true && <>{date('notificationDate', '부적격 통보일')}{date('registerCorrectedDate', '멸실 또는 실제 용도로 공부 정리를 완료한 날')}</>}{fact('oldLawUnauthorized', '종전 건축법상 허가·신고 없이 지어진 건물인가요?')}{item.oldLawUnauthorized === true && fact('lawfulAtConstructionEvidence', '건축 당시 법령상 적법한 건물이었음을 확인할 자료가 있나요?')}</details>}
      </section>
    })}
    <button type="button" className="add-fact" onClick={() => onChange({ ...profile, ownershipFactsKnown: null, ownershipFacts: [...profile.ownershipFacts, createOwnershipFact(crypto.randomUUID())] })}>주택·권리 추가</button>
  </section>
}
