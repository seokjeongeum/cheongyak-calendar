import { useMemo } from 'react'
import { FactChangeFields } from './FactChangeFields'
import { deriveHousehold, HOUSEHOLD_LAW_URL, HOUSEHOLD_RELATIONS } from './household'
import { updateProfileFacts } from './profile'
import { getProfileQuestionModel } from './profileQuestionModel'
import { createHouseholdMember, type HouseholdMember, type LocalProfile, type Notice } from './types'

function Fact({ label, value, onChange, field }: { label: string; value: boolean | null; onChange: (value: boolean | null) => void; field?: keyof LocalProfile }) {
  return <fieldset className="radio-field" data-profile-field={field}><legend>{label}</legend><div>{([[true, '예'], [false, '아니요'], [null, '모름']] as const).map(([answer, text]) => <button type="button" key={text} aria-pressed={value === answer} className={value === answer ? 'chosen' : ''} onClick={() => onChange(answer)}>{text}</button>)}</div></fieldset>
}
export function HouseholdFields({ profile, onChange, today, notices }: { profile: LocalProfile; onChange: (profile: LocalProfile) => void; today: string; notices: Notice[] }) {
  const needsPast = useMemo(() => ['homeless', 'ownership_count_max', 'household_min', 'never_owned_home'].some((kind) => getProfileQuestionModel(notices, today).pastKinds.has(kind)), [notices, today])
  const scope = deriveHousehold(profile)
  const resetComposition = (part: Partial<LocalProfile>) => onChange(updateProfileFacts(profile, part, today))
  const patch = (id: string, part: Partial<HouseholdMember>) => resetComposition({ householdMembers: profile.householdMembers.map((member) => member.id === id ? { ...member, ...part } : member) })
  const fact = (key: 'applicantOnRegister' | 'hasSpouse' | 'spouseSameRegister', label: string) => <Fact field={key} label={label} value={profile[key]} onChange={(answer) => resetComposition({ [key]: answer })} />
  const memberFacts = (member: HouseholdMember) => <>
    <Fact label="이 가족이 주택·분양권·입주권·공유지분을 보유하나요?" value={member.ownsHome} onChange={(answer) => onChange({ ...profile, ownershipFactsKnown: null, householdMembers: profile.householdMembers.map((other) => other.id === member.id ? { ...other, ownsHome: answer } : other) })} />
    <details className="additional-questions"><summary>과거 주택 보유 이력</summary><Fact label="이 가족이 과거 주택·관련 권리를 소유한 적이 있나요?" value={member.previouslyOwnedHome} onChange={(answer) => onChange({ ...profile, householdMembers: profile.householdMembers.map((other) => other.id === member.id ? { ...other, previouslyOwnedHome: answer } : other) })} /></details>
  </>
  return <section className="question-group household-fields" data-profile-field="householdMembers">
    <h4>등본에 적힌 가족을 알려 주세요</h4><p className="field-help">이름은 입력하지 않습니다. 가족 관계와 어느 등본에 함께 있는지만 입력하면 주택 보유를 함께 확인할 사람을 앱이 계산합니다. 별도 주소의 배우자도 포함합니다.</p>
    {fact('applicantOnRegister', '본인이 주민등록등본에 등재되어 있나요?')}
    {profile.maritalStatus === 'unknown' ? fact('hasSpouse', '현재 법률상 배우자가 있나요?') : <p className="field-help">입력한 혼인 상태: {profile.maritalStatus === 'married' ? '혼인 중 · 배우자 함께 확인' : '법률상 배우자 없음'}</p>}
    {profile.hasSpouse === true && fact('spouseSameRegister', '배우자가 본인과 같은 주민등록등본에 있나요?')}
    {profile.householdMembers.map((member, index) => {
      const decision = scope.members.find((person) => person.id === member.id)
      return <section className="ownership-item household-member" key={member.id} aria-label={`가족 ${index + 1}`}>
        <div className="ownership-item-heading"><h5>가족 {index + 1}</h5><button type="button" className="text-button" onClick={() => resetComposition({ householdMembers: profile.householdMembers.filter((other) => other.id !== member.id) })}>가족 {index + 1} 삭제</button></div>
        <label>본인과의 가족 관계<select aria-label="본인과의 가족 관계" value={member.relation} onChange={(event) => patch(member.id, { relation: event.target.value as HouseholdMember['relation'], ownsHome: null, previouslyOwnedHome: null, dateOfBirth: '' })}>{HOUSEHOLD_RELATIONS.filter(([value]) => profile.hasSpouse !== false || !value.startsWith('spouse_')).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>어느 주민등록등본에 함께 있나요?<select aria-label="어느 주민등록등본에 함께 있나요?" value={member.register} onChange={(event) => patch(member.id, { register: event.target.value as HouseholdMember['register'] })}><option value="unknown">등본 위치 선택</option><option value="applicant">본인 등본</option>{profile.hasSpouse === true && <><option value="spouse">배우자 등본</option><option value="both">본인·배우자가 함께 있는 등본</option></>}<option value="separate">본인·배우자와 별도 등본</option></select></label>
        <p className="field-help household-member-reason"><strong>{decision?.included === true ? '주택 보유 함께 확인' : decision?.included === false ? '이 세대의 확인 대상에서 제외' : '관계·등본 정보 입력 필요'}</strong><br />{decision?.reason}</p>
        {decision?.included !== false && memberFacts(member)}
      </section>
    })}
    <button type="button" className="add-fact" onClick={() => resetComposition({ householdMembers: [...profile.householdMembers, createHouseholdMember(crypto.randomUUID())] })}>가족 추가</button>
    <Fact field="householdMembersComplete" label="본인·배우자 등본에 적힌 가족을 빠짐없이 추가했나요?" value={profile.householdMembersComplete} onChange={(answer) => onChange({ ...profile, householdMembersComplete: answer, householdSnapshotDate: today })} />
    <p className="field-help">본인·배우자만 있다면 가족을 추가하지 않고 ‘예’를 선택하세요. 포함 여부는 위 가족 관계를 기준으로 앱이 정합니다.</p>
    <FactChangeFields profile={profile} onChange={onChange} today={today} group="household" label="가족 구성·등본 관계" needed={needsPast} />
    <section className="term-explanation household-scope-summary" aria-live="polite"><strong>주택 보유를 함께 확인할 사람{scope.complete ? ` · ${scope.legalCount}명` : ''}</strong><ul>{scope.members.filter((member) => member.included === true).map((member) => <li key={member.id}><strong>{member.label}</strong> — {member.reason}</li>)}</ul>{!scope.complete && <p>{scope.reviewDetail}</p>}<p>소득을 계산할 가구원 수와는 별개입니다.</p><a href={HOUSEHOLD_LAW_URL} target="_blank" rel="noopener noreferrer">포함 기준 · 주택공급 규칙 제2조</a></section>
  </section>
}
