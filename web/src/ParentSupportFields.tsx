import { useState } from 'react'
import { householdMemberLabel } from './household'
import { resolveParentSupport } from './parentSupport'
import { updateProfileFacts } from './profile'
import { getElderParentQuestionState, getParentSupportHistoryGroups, type ProfileQuestionModel } from './profileQuestionModel'
import { createHouseholdMember, emptyPointsFamilyFact, type FactChangeGroup, type HouseholdMember, type HouseholdRelation, type LocalProfile } from './types'

function Choice({ label, value, onChange, field }: { label: string; value: boolean | null; onChange: (value: boolean | null) => void; field: keyof LocalProfile }) {
  return <fieldset className="radio-field" data-profile-field={field}><legend>{label}</legend><div>{([[true, '예'], [false, '아니요'], [null, '모름']] as const).map(([answer, text]) => <button type="button" key={text} aria-pressed={value === answer} className={value === answer ? 'chosen' : ''} onClick={() => onChange(answer)}>{text}</button>)}</div></fieldset>
}
const answer = (value: string | boolean | null): string => value === true ? '예' : value === false ? '아니요' : value || '미입력'
export function ParentSupportFields({ profile, onChange, today, model, onHistory }: { profile: LocalProfile; onChange: (profile: LocalProfile) => void; today: string; model: ProfileQuestionModel; onHistory?: (group: FactChangeGroup) => void }) {
  const resolved = resolveParentSupport(profile, today), stopped = getElderParentQuestionState(profile, model)
  const [newRelation, setNewRelation] = useState<HouseholdRelation>('unknown')
  const change = (part: Partial<LocalProfile>) => onChange(updateProfileFacts(profile, part, today))
  const member = resolved.member
  const patchMember = (part: Partial<HouseholdMember>) => member && change({ householdMembers: profile.householdMembers.map((row) => row.id === member.id ? { ...row, ...part } : row), ...(part.dateOfBirth !== undefined ? { ownershipFacts: profile.ownershipFacts.map((item) => item.ownerMemberId === member.id ? { ...item, ownerDateOfBirth: part.dateOfBirth! } : item) } : {}) })
  const points = member ? profile.pointsFamily[member.id] || emptyPointsFamilyFact() : emptyPointsFamilyFact()
  const patchPoints = (part: Partial<typeof points>) => member && change({ pointsFamily: { ...profile.pointsFamily, [member.id]: { ...points, ...part } } })
  const history = stopped.stopped ? [] : getParentSupportHistoryGroups(profile, model)
  const addParent = () => {
    if (newRelation === 'unknown') return
    const reuseLegacy = resolved.mode === 'legacy'
    const added = { ...createHouseholdMember(crypto.randomUUID()), relation: newRelation, dateOfBirth: reuseLegacy ? profile.parentDateOfBirth : '', register: reuseLegacy && profile.parentSameRegister === true ? 'applicant' as const : reuseLegacy && profile.parentSameRegister === false ? 'separate' as const : 'unknown' as const, ownsHome: reuseLegacy ? profile.parentOwnsHome : null }
    change({ householdMembers: [...profile.householdMembers, added], additionalFamilyPresence: true, parentSupportMemberId: added.id, pointsFamily: { ...profile.pointsFamily, [added.id]: { ...emptyPointsFamilyFact(), registeredSince: reuseLegacy && profile.parentSameRegister === true ? profile.parentSupportSince : '', spouseOwnsHome: reuseLegacy ? profile.parentSpouseOwnsHome ?? null : null } } })
  }
  const addFields = <><label>추가할 부양 대상의 가족 관계<select value={newRelation} onChange={(event) => setNewRelation(event.target.value as HouseholdRelation)}><option value="unknown">관계 선택</option><option value="applicant_parent">본인의 부모</option><option value="applicant_grandparent">본인의 조부모</option><option value="spouse_parent">배우자의 부모</option><option value="spouse_grandparent">배우자의 조부모</option></select></label><button type="button" className="add-fact" disabled={newRelation === 'unknown'} onClick={addParent}>이 부양 대상을 가족으로 연결</button></>
  return <details className="additional-questions" open={model.elderParent || undefined} data-profile-field="parentSupportMemberId"><summary>부모 부양 조건</summary>
    {(resolved.candidates.length > 1 || resolved.mode === 'selection') && <label>부양 대상 부모·조부모<select value={member?.id || ''} onChange={(event) => change({ parentSupportMemberId: event.target.value })}><option value="">가족 목록에서 선택</option>{resolved.candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{householdMemberLabel(candidate, profile.householdMembers.indexOf(candidate))}{candidate.dateOfBirth ? ` · ${candidate.dateOfBirth}` : ''}</option>)}</select></label>}
    {resolved.mode === 'selection' ? <><p className="field-help">부양 대상을 선택하면 그 가족의 생년월일·등본 위치·주택 이력과 가점 입력을 함께 사용합니다. 삭제된 가족 대신 다른 부모를 자동 선택하지 않습니다.</p>{resolved.candidates.length === 0 && addFields}</> : resolved.mode === 'legacy' ? <>
      {!!profile.parentDateOfBirth && <section className="term-explanation" data-profile-field="parentDateOfBirth"><strong>저장된 부양 대상</strong><p>생년월일: {profile.parentDateOfBirth} · 같은 등본: {answer(profile.parentSameRegister)}</p><p>부양 시작일: {profile.parentSupportSince || '미입력'} · 주택 보유: {answer(profile.parentOwnsHome)}</p></section>}
      {stopped.stopped && <p className="field-help" role="status">{stopped.detail}</p>}
      <p className="field-help">부양 대상의 가족 관계를 선택해 가족 목록에 연결하면 기존 입력을 재사용합니다.</p>
      {addFields}
    </> : member && <>
      <section className="term-explanation" aria-live="polite"><strong>{resolved.label} · 기존 입력 재사용</strong><p data-profile-field="parentDateOfBirth">생년월일: {answer(resolved.facts.parent_age_min.value)}</p>
        {!stopped.stopped && <><p>본인과 같은 등본: {answer(resolved.facts.parent_same_register.value)}</p><p>부양 시작일: {answer(resolved.facts.parent_support_months_min.value)}</p><p>주택·권리 보유: {answer(resolved.facts.parent_owns_home.value)}</p><p>이 부모의 배우자 주택 보유: {answer(resolved.facts.parent_spouse_owns_home.value)}</p><p className="field-help">생년월일·등본·보유 사실은 세대·주택 입력에서, 연속 등재일·배우자 소유는 일반공급 가점 입력에서 재사용합니다.</p></>}
      </section>
      {!resolved.facts.parent_age_min.value && <label data-profile-field="parentDateOfBirth">이 가족의 생년월일<input type="date" max={today} value={member.dateOfBirth} onChange={(event) => patchMember({ dateOfBirth: event.target.value })} />{resolved.facts.parent_age_min.detail && <span className="field-help">{resolved.facts.parent_age_min.detail}</span>}</label>}
      {stopped.stopped ? <p className="field-help" role="status">{stopped.detail}</p> : <>
        {resolved.facts.parent_same_register.value === null && <label data-profile-field="parentSameRegister">이 가족의 등본 위치<select value={member.register} onChange={(event) => patchMember({ register: event.target.value as HouseholdMember['register'] })}><option value="unknown">등본 위치 선택</option><option value="applicant">본인 등본</option>{profile.hasSpouse === true && <><option value="spouse">배우자 등본</option><option value="both">본인·배우자 같은 등본</option></>}<option value="separate">본인·배우자와 별도 등본</option></select></label>}
        {resolved.facts.parent_same_register.value === true && !resolved.facts.parent_support_months_min.value && <label data-profile-field="parentSupportSince">부양 시작일 · 본인과 같은 등본에 연속 등재된 날<input type="date" max={today} value={points.registeredSince} onChange={(event) => patchPoints({ registeredSince: event.target.value })} /></label>}
        {resolved.facts.parent_owns_home.value === null && <Choice field="parentOwnsHome" label="이 가족이 주택·분양권·입주권·공유지분을 보유하나요?" value={member.ownsHome} onChange={(value) => patchMember({ ownsHome: value })} />}
        {resolved.facts.parent_spouse_owns_home.value === null && <><Choice field="parentSpouseOwnsHome" label="이 직계존속의 배우자가 주택을 보유하나요?" value={points.spouseOwnsHome} onChange={(value) => patchPoints({ spouseOwnsHome: value })} /><p className="field-help">배우자가 없거나 보유 주택이 없으면 아니요입니다. 이 가족의 가점 입력에도 같은 답을 사용합니다.</p></>}
        {history.map((group) => <p className="field-help" key={group}>과거 공고와 비교할 {group === 'household' ? '가족 구성·등본 관계 변경일' : group === 'points' ? '가점 가족 소유 사실 변경일' : '주택·권리 보유 이력'}이 아직 없습니다. {onHistory && <button type="button" className="text-button" onClick={() => onHistory(group)}>기존 입력에서 보완</button>}</p>)}
        <p className="field-help">노부모부양에서 60세 이상 부모의 주택을 일반 무주택 판단처럼 자동 제외하지 않습니다.</p>
      </>}
    </>}
  </details>
}
