import { memo, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ArrowRight, Check, Home, Info, LockKeyhole, MapPin, CalendarDays, Sparkles, Wallet, X } from 'lucide-react'
import { MoneyInput } from './MoneyInput'
import { HouseholdFields } from './HouseholdFields'
import { ApplicationFactsFields } from './ApplicationFactsFields'
import { deriveHousehold } from './household'
import { OwnershipFields } from './OwnershipFields'
import { districtOptions, provinceOptions, REGION_CATALOG_METADATA, parentCityCode, districtName } from './regions'
import { saveProfile, selectDistrict, selectProvince, updateProfileFacts } from './profile'
import type { FactChangeGroup, LocalProfile, Notice } from './types'
import { PointsFields } from './PointsFields'
import { ChildFactsFields } from './ChildFactsFields'
import { FactChangeFields } from './FactChangeFields'
import { getElderParentQuestionState, getProfileHistoryTarget, getProfileQuestionModel } from './profileQuestionModel'

const LAW = 'https://www.law.go.kr/법령/주택공급에관한규칙/'
// Step navigation changes visibility, not the facts inside the five forms.
// Preserve their rendered subtrees until a factual dependency changes.
const StepFacts = memo(function StepFacts({ children }: { profile: LocalProfile; notices: Notice[]; today: string; field?: keyof LocalProfile; children: ReactNode }) {
  return <>{children}</>
}, (a, b) => a.profile === b.profile && a.notices === b.notices && a.today === b.today && a.field === b.field)
function Fact({ label, value, onChange, help, field }: { label: string; value: boolean | null; onChange: (value: boolean | null) => void; help?: string; field?: keyof LocalProfile }) {
  return <fieldset className="radio-field" data-profile-field={field}><legend>{label}</legend>{help && <p className="field-help">{help}</p>}<div>{([[true, '예'], [false, '아니요'], [null, '모름']] as const).map(([answer, text]) => <button type="button" key={text} aria-pressed={value === answer} className={value === answer ? 'chosen' : ''} onClick={() => onChange(answer)}>{text}</button>)}</div></fieldset>
}
const FIELD_STEPS: Partial<Record<keyof LocalProfile, number>> = {
  pointsFamily: 2, pointsFamilyComplete: 2, pointsHomelessSince: 2, spouseAccountBaseDate: 2, spouseAccountPresent: 2, factChanges: 0, applicationHistoryPresence: 2, applicationHistoryEvents: 2, applicationHistoryPeople: 2, applicationHistoryComplete: 2, officialNetAssetsKrw: 3, plannedMarriage: 4, raisesChildWithoutSpouse: 4, hasDeFactoPartner: 4,
  incomeHouseholdSize: 3, householdSize: 1, applicantOnRegister: 1, householdMembers: 1, householdMembersComplete: 1, householdSnapshotDate: 1, householdCompositionUnchanged: 1, householdHistoryConfirmations: 1, isHouseholdHead: 1, hasSpouse: 1, spouseSameRegister: 1, familyOnRegister: 1, householdScopeKnown: 1,
  applicantOwnsHome: 1, spouseOwnsHome: 1, familyOwnsHome: 1, ownershipFacts: 1, ownershipFactsKnown: 1,
  applicantPreviouslyOwnedHome: 1, spousePreviouslyOwnedHome: 1, familyPreviouslyOwnedHome: 1,
  accountType: 2, privateRankBaseDate: 2, nationalRankBaseDate: 2, privateDepositKrw: 2,
  nationalRecognizedPayments: 2, nationalRecognizedAmountKrw: 2, accountConversionUnclear: 2,
  previousWinning: 2, previousWinningDate: 2, restrictedFromApplying: 2, projectApplicationHistory: 2, applicationRestrictionFacts: 2, applicationRestrictionsAsOfDate: 2, applicationRestrictionsHistoryConfirmations: 2, citizenship: 0, overseasContinuousDays: 0, overseasFactsAsOfDate: 0, overseasOnlyApplicantForLivelihood: 0, overseasFactsHistoryConfirmations: 0,
  privateDepositAsOfDate: 2, privateDepositMaintained: 2, nationalPaymentsAsOfDate: 2,
  militaryServiceYears: 0, militaryCurrentlyServing: 0, militaryFactsAsOfDate: 0, militaryFactsHistoryConfirmations: 0, residenceHistory: 0, intendedContractDate: 0, currentlyDomesticResident: 0, domesticResidenceFactsAsOfDate: 0, domesticResidenceHistoryConfirmations: 0, providerEmployeeOrRelatedFamily: 2, providerPurchaseApproval: 2,
  annualIncomeKrw: 3, assetsKrw: 3, monthlyIncomeKrw: 3, realEstateKrw: 3, vehicleKrw: 3, dualIncome: 3,
  dateOfBirth: 4, maritalStatus: 4, marriageDate: 4, hasChildren: 4, children: 4, pregnant: 4, expectedChildren: 4,
  specialWinning: 4, taxYears: 4, employed: 4, incomeTaxPaidWithinPastYear: 4, incomeTaxFactsAsOfDate: 4, incomeTaxFactsHistoryConfirmations: 4, spousePremarriageOwnershipDisposed: 1, parentSpouseOwnsHome: 4, parentDateOfBirth: 4, parentSupportSince: 4, parentSameRegister: 4,
  parentOwnsHome: 4, recommendationReason: 4, recommendationStatus: 4, relocatedWorker: 4,
}
export const ProfileDialog = memo(function ProfileDialog({ open = true, onDraft, profile: initialProfile, onChange: commitProfile, onClose: closeDialog, today, notices, initialField, initialHistoryGroup }: { open?: boolean; onDraft?: (profile: LocalProfile) => void; profile: LocalProfile; onChange: (value: LocalProfile) => void; onClose: () => void; today: string; notices: Notice[]; initialField?: keyof LocalProfile; initialHistoryGroup?: FactChangeGroup }) {
  const [profile, setDraft] = useState(initialProfile)
  const model = useMemo(() => getProfileQuestionModel(notices, today), [notices, today])
  const draftRef = useRef(profile)
  const commitRef = useRef(commitProfile)
  const closeRef = useRef(closeDialog)
  const dirtyRef = useRef(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  commitRef.current = commitProfile
  closeRef.current = closeDialog
  const flush = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null }
    if (!dirtyRef.current) return
    dirtyRef.current = false
    saveProfile(draftRef.current)
    commitRef.current(draftRef.current)
  }, [])
  const onChange = useCallback((value: LocalProfile) => {
    value = updateProfileFacts(draftRef.current, value, today)
    draftRef.current = value
    onDraft?.(value)
    dirtyRef.current = true
    setDraft(value)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(flush, 300)
  }, [flush, today, onDraft])
  const onClose = useCallback(() => { flush(); closeRef.current() }, [flush])
  useEffect(() => {
    window.addEventListener('pagehide', flush)
    return () => { window.removeEventListener('pagehide', flush); flush() }
  }, [flush])
  useEffect(() => { if (!open) { draftRef.current = initialProfile; setDraft(initialProfile) } }, [open, initialProfile])
  const [step, setStep] = useState(() => initialField ? FIELD_STEPS[initialField] || 0 : 0)
  useEffect(() => {
    if (!open) return
    setStep(initialField ? FIELD_STEPS[initialField] || 0 : 0)
  }, [initialField, open])
  useEffect(() => {
    // The requested step must be committed before focusing: hidden or inert
    // controls silently ignore focus even if they are already in the DOM.
    if (!open || !initialField || step !== (FIELD_STEPS[initialField] || 0)) return
    const frame = requestAnimationFrame(() => {
      const dialog = document.querySelector('.profile-dialog')
      const historyGroup = initialHistoryGroup || getProfileHistoryTarget(initialField, draftRef.current, model)
      const container = historyGroup && dialog?.querySelector(`[data-fact-group="${historyGroup}"]`) || dialog?.querySelector(`[data-profile-field="${initialField}"]`)
      for (let parent = container; parent; parent = parent.parentElement) { if (parent instanceof HTMLDetailsElement) parent.open = true }
      const input = historyGroup && container?.querySelector<HTMLElement>('input[type="date"]:not([disabled])') || container?.querySelector<HTMLElement>('input:not([disabled]),select:not([disabled]),button:not([disabled])')
      input?.focus({ preventScroll: true })
      container?.scrollIntoView({ block: 'nearest' })
    })
    return () => cancelAnimationFrame(frame)
  }, [initialField, initialHistoryGroup, open, model, step])
  useEffect(() => {
    if (!open) return
    const dialog = document.querySelector<HTMLElement>('.profile-dialog')
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const stopBackgroundScroll = (event: WheelEvent | TouchEvent) => {
      const target = event.target instanceof Element ? event.target : null
      if (!target?.closest('.dialog-body')) event.preventDefault()
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { onClose(); return }
      if (event.key === 'Tab' && dialog) {
        const controls = [...dialog.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href]')].filter((control) => control.getClientRects().length && !control.closest('[hidden]'))
        const first = controls[0], last = controls.at(-1)
        if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last?.focus({ preventScroll: true }) }
        else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first?.focus({ preventScroll: true }) }
      }
      if (['PageUp', 'PageDown', 'ArrowUp', 'ArrowDown', ' '].includes(event.key) && dialog && !dialog.contains(document.activeElement)) event.preventDefault()
    }
    document.addEventListener('keydown', handleKey)
    document.addEventListener('wheel', stopBackgroundScroll, { passive: false })
    document.addEventListener('touchmove', stopBackgroundScroll, { passive: false })
    return () => {
      document.removeEventListener('keydown', handleKey)
      document.removeEventListener('wheel', stopBackgroundScroll)
      document.removeEventListener('touchmove', stopBackgroundScroll)
      previousFocus?.focus({ preventScroll: true })
    }
  }, [onClose, open])
  const update = (part: Partial<LocalProfile>) => {
    const changed: Partial<LocalProfile> = { ...part }
    onChange(updateProfileFacts(profile, changed, today))
  }
  const fact = (key: keyof LocalProfile, label: string, help?: string) => <Fact field={key} label={label} value={profile[key] as boolean | null} onChange={(value) => update({ [key]: value })} help={help} />
  const date = (key: keyof LocalProfile, label: string, max = today) => <label data-profile-field={key}>{label}<input type="date" max={max} value={profile[key] as string} onChange={(event) => update({ [key]: event.target.value })} /></label>
  const number = (key: keyof LocalProfile, label: string) => <label data-profile-field={key}>{label}<input type="number" min="0" step="1" inputMode="numeric" value={profile[key] as string} onChange={(event) => update({ [key]: event.target.value })} /></label>
  const money = (key: keyof LocalProfile, label: string) => <div data-profile-field={key}><MoneyInput label={label} value={profile[key] as string} onChange={(value) => update({ [key]: value })} /></div>
  const needsPast = (kinds: string[]) => kinds.some((kind) => model.pastKinds.has(kind))
  const needsPastGroup = (group: FactChangeGroup) => model.pastGroups.has(group)
  const { needsDetailedDistrict, needsDomestic, needsProvider, elderParent, institution, relocation, needsMonthly, needsNetAssets, needsPlannedMarriage, needsSingleParent, needsProperty } = model
  const parentQuestions = useMemo(() => getElderParentQuestionState(profile, model), [profile, model])
  const firstHome = model.firstHome || profile.applicantPreviouslyOwnedHome === false
  const household = useMemo(() => deriveHousehold(profile), [profile])
  const steps = ['거주지', '세대·주택', '청약통장', '소득·자산', '특별공급']
  const stepContent = useMemo(() => [
<StepFacts profile={profile} notices={notices} today={today} field={initialField}><div className="step-icon"><MapPin size={22} /></div><h3>현재 거주지와 연속 거주 시작일</h3><p>시도와 시·군의 거주기간을 따로 비교합니다. 일반구는 상위 도시로 비교하고, 공고가 더 좁은 범위를 요구할 때만 구를 선택합니다.</p>
      {profile.regionNeedsReview && <div className="step-tip" role="status"><Info size={16} /> 기존 지역 ‘{profile.region} {profile.district}’을 정확히 이전할 수 없습니다. 현재 지역을 다시 선택해 주세요.</div>}
      <label data-profile-field="regionCode">현재 거주 지역<select value={profile.regionCode} onChange={(event) => onChange(selectProvince(profile, event.target.value))}><option value="">지역을 선택해 주세요</option>{provinceOptions().map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}</select></label>
      <label data-profile-field="districtCode">시·군·구<select value={profile.districtCode} disabled={!profile.regionCode} onChange={(event) => onChange(selectDistrict(profile, event.target.value, { preserveOrdinaryDistrict: needsDetailedDistrict }))}><option value="">시·군·구 선택</option>{districtOptions(profile.regionCode, { includeOrdinaryDistricts: needsDetailedDistrict }).map((item) => <option key={item.code} value={item.code}>{item.displayName}</option>)}</select></label>
      {date('movedInDate', '현재 시도 연속 거주 시작일')}
      {!!profile.districtCode && date('districtMovedInDate', parentCityCode(profile.districtCode) ? '공고가 명시한 구 연속 거주 시작일' : '현재 시·군 연속 거주 시작일')}{!!parentCityCode(profile.districtCode) && date('cityMovedInDate', `${districtName(parentCityCode(profile.districtCode)!)} 연속 거주 시작일`)}
      <p className="field-help">동탄구는 화성시, 영통구는 수원시의 연속 거주기간을 사용합니다. 기준일이 현재 지역 전입일보다 이전이면 이미 저장한 주소 이력만 비교하고, 기록이 없으면 당시 지역을 확인할 수 없다고 표시합니다.</p>
      {needsDomestic && <section className="question-group"><h4>공고의 국내 거주 조건</h4>{fact('currentlyDomesticResident', '현재 국내에 거주하나요?', '공고가 정한 국내 거주 여부입니다. 해당지역 우선권의 해외 체류 일수와 별도 비교합니다.')}<FactChangeFields profile={profile} onChange={onChange} today={today} group="domestic_residence" label="국내 거주 상태" needed={needsPastGroup('domestic_residence')} /></section>}
      <ApplicationFactsFields profile={profile} onChange={onChange} today={today} notices={notices} section="residence" />
      <a className="help-link" href={REGION_CATALOG_METADATA.sourceUrl} target="_blank" rel="noopener noreferrer">행정구역 기준 {REGION_CATALOG_METADATA.effectiveDate} · 행정안전부</a>
      <details className="additional-questions" open={initialField === 'militaryServiceYears' || initialField === 'militaryCurrentlyServing' || undefined}><summary>장기복무군인 거주 예외 관련 사실</summary>{fact('militaryCurrentlyServing', '현재 군인으로 복무 중인가요?')}{profile.militaryCurrentlyServing !== false && number('militaryServiceYears', '현재까지 군 복무한 기간 (년)')}<FactChangeFields profile={profile} onChange={onChange} today={today} group="military" label="군 복무 상태" needed={needsPastGroup('military')} /><p className="field-help">공고가 정한 복무기간·거주 예외와 비교합니다. 장기복무군인이라고 모든 공고의 해당지역 우선권이 생기는 것은 아닙니다.</p></details>
    </StepFacts>,
<StepFacts profile={profile} notices={notices} today={today} field={initialField}><div className="step-icon"><Home size={22} /></div><h3>세대 관계와 주택·권리 소유</h3>
      <div className="term-explanation"><strong>무주택 세대구성원이란?</strong><p>본인뿐 아니라 법에서 확인하도록 정한 세대원 모두가 주택을 소유하지 않은 경우입니다. 배우자는 주소가 달라도 확인하며, 등본에 함께 있는 직계존속·직계비속과 그 배우자 등은 관계에 따라 포함됩니다. 형제자매·동거인은 같은 등본이라는 이유만으로 포함되지 않습니다.</p><p>분양권·입주권·공유지분도 영향을 줄 수 있습니다. 60세 이상 직계존속 소유, 상속 지분 등에는 예외가 있지만 공급유형마다 적용이 달라 원문 확인이 필요합니다.</p><a href={`${LAW}제2조`} target="_blank" rel="noopener noreferrer">세대 범위 · 제2조</a> · <a href={`${LAW}제53조`} target="_blank" rel="noopener noreferrer">소유 판정·예외 · 제53조</a></div>
      {fact('isHouseholdHead', '주민등록등본에서 본인이 세대주인가요?')}<FactChangeFields profile={profile} onChange={onChange} today={today} group="household_head" label="세대주 여부" needed={needsPastGroup('household_head')} />
      <HouseholdFields profile={profile} onChange={onChange} today={today} notices={notices} />
      {fact('applicantOwnsHome', '본인이 현재 주택·분양권·입주권·공유지분을 보유하나요?')}
      {profile.hasSpouse === true && fact('spouseOwnsHome', '배우자가 현재 주택·관련 권리를 보유하나요?')}
      <FactChangeFields profile={profile} onChange={onChange} today={today} group="ownership" label="주택·권리 보유 상태" needed={needsPast(['homeless', 'ownership_count_max', 'never_owned_home']) && !profile.ownershipFacts.length} /><OwnershipFields profile={profile} onChange={onChange} today={today} notices={notices} />
      {fact('applicantPreviouslyOwnedHome', '본인이 과거 주택·관련 권리를 소유한 적이 있나요?')}
      {profile.hasSpouse === true && fact('spousePreviouslyOwnedHome', '배우자가 과거 주택·관련 권리를 소유한 적이 있나요?', '혼인 전 소유 이력의 예외는 공고별로 확인합니다.')}
      {profile.hasSpouse === true && profile.spousePreviouslyOwnedHome === true && fact('spousePremarriageOwnershipDisposed', '배우자의 과거 소유는 모두 혼인 전에 취득·처분한 주택인가요?', '이 예외를 허용하는 공고에만 적용하며, 본인의 과거 소유 이력을 대신하지 않습니다.')}
      {household.members.some((member) => member.included && !['applicant', 'spouse'].includes(member.id)) && <p className="field-help">다른 가족의 현재·과거 보유 사실은 위 가족 항목에서 각각 입력합니다.</p>}
    </StepFacts>,
<StepFacts profile={profile} notices={notices} today={today} field={initialField}><div className="step-icon"><CalendarDays size={22} /></div><h3>민영·국민주택을 각각 비교합니다</h3><p>통장의 가입일과 순위기산일은 전환·미성년 납입 인정 등에 따라 다를 수 있습니다. 은행의 청약통장 내역이나 청약홈 ‘청약통장 순위확인서’에서 각 날짜와 인정 내역을 확인해 주세요.</p>
      <label data-profile-field="accountType">청약통장 종류<select value={profile.accountType} onChange={(event) => update({ accountType: event.target.value as LocalProfile['accountType'] })}><option value="unknown">미확인</option><option value="comprehensive">주택청약종합저축 (청년형 포함)</option><option value="savings">청약저축</option><option value="deposit">청약예금</option><option value="installment">청약부금</option><option value="none">통장 없음</option></select></label>
      {profile.accountType !== 'none' && <><section className="question-group"><h4>민영주택</h4>{date('privateRankBaseDate', '민영주택 순위기산일')}{money('privateDepositKrw', '민영주택 예치금 (원)')}<FactChangeFields profile={profile} onChange={onChange} today={today} group="bank_private" label="민영 예치금" needed={!!profile.privateDepositKrw && needsPastGroup('bank_private')} /><p className="field-help">은행에서 확인한 예치금을 입력하세요. 지역·전용면적별 공고 기준과 비교하며, 과거 금액이 필요한 경우 마지막 변경일을 사용합니다.</p></section><section className="question-group"><h4>국민주택</h4>{date('nationalRankBaseDate', '국민주택 순위기산일')}{number('nationalRecognizedPayments', '국민주택 납입인정횟수 (회)')}{money('nationalRecognizedAmountKrw', '국민주택 납입인정금액 (원)')}<FactChangeFields profile={profile} onChange={onChange} today={today} group="bank_national" label="납입인정 내역" needed={!!profile.nationalRecognizedPayments && needsPastGroup('bank_national')} /><p className="field-help">입력한 납입인정횟수·금액은 은행에서 확인된 내역으로 비교합니다.</p></section></>}
      {fact('restrictedFromApplying', '청약홈에서 재당첨 제한 등 현재 신청 제한이 확인되나요?', '확인하지 않았다면 모름으로 두세요. 당첨 이력이 있다고 항상 신청 제한이 생기는 것은 아닙니다.')}
      {notices.some((notice) => (notice.selection_methods || notice.rules).some((rule) => rule.kind === 'selection_method' && rule.verification === 'official' && typeof rule.points_percent === 'number' && rule.points_percent > 0)) && <PointsFields profile={profile} onChange={onChange} today={today} />}
      <ApplicationFactsFields profile={profile} onChange={onChange} today={today} notices={notices} section="restrictions" />
      {needsProvider && <section className="question-group"><h4>공급기관의 임직원 매입 제한</h4><FactChangeFields profile={profile} onChange={onChange} today={today} group="provider_employee" label="공급기관 임직원·관련 가족 상태" needed={needsPastGroup('provider_employee') && profile.providerEmployeeOrRelatedFamily !== null} />{fact('providerEmployeeOrRelatedFamily', '공고가 정한 공급기관 임직원 또는 관련 가족에 해당하나요?', model.providerHelp)}{profile.providerEmployeeOrRelatedFamily === true && model.providerApproval && fact('providerPurchaseApproval', '공고가 허용하는 공식 매입 승인을 받았나요?')}</section>}
      <div className="step-tip"><Info size={16} /> 날짜만으로 1순위를 확정하지 않습니다. 1순위 조건을 충족하지 않아도 자동으로 2순위로 바꾸지 않습니다.</div><p className="help-link"><a href={`${LAW}제27조`} target="_blank" rel="noopener noreferrer">국민주택 · 제27조</a> · <a href={`${LAW}제28조`} target="_blank" rel="noopener noreferrer">민영주택 · 제28조</a></p>
    </StepFacts>,
<StepFacts profile={profile} notices={notices} today={today} field={initialField}><div className="step-icon"><Wallet size={22} /></div><h3>소득·자산의 산정 항목</h3><p>원 단위로 입력하세요. 공고에서 요구하는 가구 범위·산정 기간이 같을 때만 비교합니다.</p>{number('incomeHouseholdSize', '공고 기준 소득 산정 가구원 수 (명)')}<p className="field-help">위에서 계산한 주택 보유 확인 가족 수와 다를 수 있습니다. 소득 공고의 산정 범위를 확인한 인원만 입력하세요.</p>{money('annualIncomeKrw', '가구 연 소득 합계 (원)')}{money('assetsKrw', '가구 자산 합계 (원)')}{profile.hasSpouse === true && fact('dualIncome', '소득이 있는 신청자와 배우자가 모두 있나요?')}<FactChangeFields profile={profile} onChange={onChange} today={today} group="income" label="소득 산정값" needed={needsPastGroup('income') && !!(profile.monthlyIncomeKrw || profile.annualIncomeKrw)} /><FactChangeFields profile={profile} onChange={onChange} today={today} group="assets" label="자산 산정값" needed={needsPastGroup('assets') && !!(profile.assetsKrw || profile.officialNetAssetsKrw || profile.realEstateKrw || profile.vehicleKrw)} />
      <details className="additional-questions" open={needsMonthly || needsProperty || needsNetAssets || undefined}><summary>공고가 요구하는 추가 소득·자산 항목</summary>{money('monthlyIncomeKrw', '공고 기준 가구 월평균소득 (원)')}{needsNetAssets && <>{money('officialNetAssetsKrw', '공고 기준 순자산 · 인정 부채 차감 (원)')}<p className="field-help">부동산·자동차·금융·기타자산을 공고의 평가 방식으로 계산하고 인정 부채를 뺀 금액입니다. 조사 대상 가족과 자산별 산정 시점은 공고문에서 확인하세요.</p></>}{money('realEstateKrw', '공고 기준 부동산 가액 (원)')}{money('vehicleKrw', '공고 기준 자동차 가액 (원)')}<p className="field-help">연 소득 ÷ 12를 법정 월평균소득으로 인정하지 않습니다. 조사 대상·평가 방식이 맞는 공식 산정값을 입력하세요.</p></details>
    </StepFacts>,
<StepFacts profile={profile} notices={notices} today={today} field={initialField}><div className="step-icon"><Sparkles size={22} /></div><h3>가족·이력 사실로 특별공급 비교</h3><p>신혼부부·신생아·생애최초·다자녀·노부모부양·기관추천·청년·이전기관 종사자 등을 함께 비교합니다. 실제 모집 유형만 공고의 신청 후보에 포함됩니다.</p>
      {date('dateOfBirth', '본인 생년월일')}
      <label data-profile-field="maritalStatus">현재 혼인 상태<select value={profile.maritalStatus} onChange={(event) => update({ maritalStatus: event.target.value as LocalProfile['maritalStatus'], hasSpouse: event.target.value === 'unknown' ? null : event.target.value === 'married' })}><option value="unknown">미확인</option><option value="single">미혼</option><option value="married">혼인 중</option><option value="engaged">예비신혼 (혼인 예정)</option><option value="divorced">이혼</option><option value="widowed">사별</option></select></label>
      <FactChangeFields profile={profile} onChange={onChange} today={today} group="marital" label="혼인 상태" needed={profile.maritalStatus !== 'unknown' && !profile.marriageDate && needsPast(['marital_status', 'married', 'marriage_months_max', 'single_parent_family', 'planned_marriage'])} />{profile.maritalStatus === 'married' && date('marriageDate', '혼인신고일')}{needsPlannedMarriage && fact('plannedMarriage', '입주 전에 혼인신고할 예정인 상대방이 있나요?', '예비신혼부부 공고는 예정 배우자와 구성할 세대의 소유·소득·자산 및 입주 전 혼인 증빙도 요구합니다.')}{needsSingleParent && <>{fact('raisesChildWithoutSpouse', '배우자 없이 본인이 자녀를 양육하나요?')}{fact('hasDeFactoPartner', '혼인신고 없이 부부로 생활하는 상대방이 있나요?', '사실혼 관계는 공고의 한부모 경로에 영향을 줍니다.')}</>}
      <ChildFactsFields profile={profile} onChange={onChange} today={today} needsPast={needsPastGroup('children') || needsPastGroup('pregnancy')} />
      <details className="additional-questions" open={firstHome || undefined}><summary>생애최초 관련 추가 사실</summary>{number('taxYears', '소득세 납부한 연수 (년)')}{fact('employed', '현재 근로자·자영업자인가요?')}{profile.employed !== true && fact('incomeTaxPaidWithinPastYear', '최근 12개월 안에 소득세를 납부한 사실이 있나요?')}<FactChangeFields profile={profile} onChange={onChange} today={today} group="income_tax" label="소득 활동·납세 상태" needed={needsPastGroup('income_tax')} /><p className="field-help">공고가 납부의무 면제 기간을 인정하면 해당 기간을 포함한 연수를 입력하세요.</p></details>
      <details className="additional-questions" open={elderParent || undefined}><summary>부모 부양 관련 추가 사실</summary>{date('parentDateOfBirth', '부양 중인 부모·조부모 생년월일')}{parentQuestions.stopped ? <p className="field-help" role="status">{parentQuestions.detail}</p> : <>{fact('parentSameRegister', '부양 중인 부모·조부모가 같은 주민등록등본에 있나요?')}{date('parentSupportSince', '부양 시작일 · 동일 등본에서 연속 부양을 시작한 날짜')}{fact('parentOwnsHome', '부양 대상 부모·조부모가 주택·관련 권리를 보유하나요?', '노부모부양에는 일반 무주택 판단의 60세 이상 부모 소유 예외가 동일하게 적용되지 않을 수 있습니다.')}{fact('parentSpouseOwnsHome', '부양 대상 부모·조부모의 배우자가 주택·관련 권리를 보유하나요?', '배우자가 다른 등본에 있어도 공고가 정한 확인 대상이면 입력하세요. 배우자가 없거나 보유 주택이 없으면 아니요를 선택하세요.')}<FactChangeFields profile={profile} onChange={onChange} today={today} group="parent_support" label="부모 부양·소유 상태" needed={needsPastGroup('parent_support')} /></>}</details>
      <details className="additional-questions" open={institution || undefined}><summary>기관추천 관련 추가 사실</summary><label data-profile-field="recommendationReason">추천 대상 사유<select value={profile.recommendationReason} onChange={(event) => update({ recommendationReason: event.target.value })}><option value="">미확인</option>{['장애인', '국가유공자·보훈', '중소기업 장기근속', '장기복무 군인', '북한이탈주민', '기타 공고상 사유'].map((name) => <option key={name}>{name}</option>)}</select></label><label data-profile-field="recommendationStatus">추천 진행 상태<select value={profile.recommendationStatus} onChange={(event) => update({ recommendationStatus: event.target.value as LocalProfile['recommendationStatus'] })}><option value="unknown">미확인</option><option value="none">추천 없음</option><option value="pending">신청·심사 중</option><option value="confirmed">추천 기관에서 확정 통보 받음</option></select></label></details>
      <details className="additional-questions" open={relocation || undefined}><summary>이전기관 종사자 관련 추가 사실</summary>{fact('relocatedWorker', '공고에서 지정한 이전기관에 소속되어 근무하나요?')}</details>
      <div className="step-tip"><Info size={16} /> 현재·과거 소유와 세대 관계는 ‘세대·주택’, 소득·자산은 앞 단계의 사실을 함께 사용합니다. 공고 유형별 추가 증빙이 없으면 확인 필요로 남습니다.</div>
    </StepFacts>
  ], [profile, notices, today, initialField, onChange])
  return <div className="dialog-backdrop" aria-hidden={!open} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><div className="profile-dialog" role="dialog" aria-modal="true" aria-labelledby="profile-title"><div className="dialog-header"><div><span className="dialog-eyebrow"><LockKeyhole size={14} /> 브라우저에만 저장</span><h2 id="profile-title">내 조건 설정</h2><p>현재 사실을 입력하면 공고별 요구 조건과 비교합니다. 오늘 기준으로 자동 저장합니다.</p></div><button type="button" className="dialog-close" aria-label="닫기" onClick={onClose}><X size={21} /></button></div><div className="step-progress" aria-label="입력 단계">{steps.map((name, index) => <button key={name} type="button" className={step === index ? 'active' : step > index ? 'done' : ''} onClick={() => setStep(index)} aria-current={step === index ? 'step' : undefined}><span>{step > index ? <Check size={12} /> : index + 1}</span><small>{name}</small></button>)}</div><div className="dialog-body">
    {stepContent.map((content, index) => <div className="step-fields" hidden={step !== index} aria-hidden={step !== index} inert={step !== index} key={index}>{content}</div>)}
  </div><div className="dialog-footer"><button type="button" className="footer-back" onClick={() => step ? setStep(step - 1) : onClose()}>{step ? '이전' : '닫기'}</button><span>{step + 1} / {steps.length}</span><button type="button" className="footer-next" onClick={() => step < 4 ? setStep(step + 1) : onClose()}>{step < 4 ? '다음 단계' : '저장하고 보기'} <ArrowRight size={16} /></button></div></div></div>
})
