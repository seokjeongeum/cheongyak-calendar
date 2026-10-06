import { emptyPointsFamilyFact, type LocalProfile, type PointsFamilyFact } from './types'
import { FactChangeFields } from './FactChangeFields'
import { POINTS_SOURCE } from './points'

export function PointsFields({ profile, onChange, today }: { profile: LocalProfile; onChange: (value: LocalProfile) => void; today: string }) {
  const patch = (part: Partial<LocalProfile>) => onChange({ ...profile, ...part })
  const choice = (label: string, value: boolean | null, apply: (value: boolean | null) => void) => <label>{label}<select value={value === null ? 'unknown' : String(value)} onChange={(event) => apply(event.target.value === 'unknown' ? null : event.target.value === 'true')}><option value="unknown">미확인</option><option value="true">예</option><option value="false">아니요</option></select></label>
  const members = profile.householdMembers.filter((m) => !['separate', 'unknown'].includes(m.register) && !['sibling', 'unrelated', 'descendant_spouse', 'unknown'].includes(m.relation))
  return <details className="additional-questions" data-profile-field="pointsFamily"><summary>일반공급 내 가점 비교</summary><p className="field-help">무주택기간 32점 · 부양가족 35점 · 통장 17점. 세대·주택과 은행 인정 가입일을 재사용합니다. 공고 기준일에 따라 계산하며 미입력 항목은 총점으로 확정하지 않습니다.</p>
    <label data-profile-field="pointsHomelessSince">본인·배우자가 마지막으로 무주택이 된 날 (기존 처분 이력으로 확인되지 않을 때)<input type="date" max={today} value={profile.pointsHomelessSince} onChange={(event) => patch({ pointsHomelessSince: event.target.value })} /></label><p className="field-help">주택을 소유한 적이 없으면 입력하지 않아도 됩니다. 배우자의 혼인 전 처분 이력은 제외합니다.</p>
    {members.map((member, i) => {
      const ancestor = /parent$/.test(member.relation), value = profile.pointsFamily[member.id] || emptyPointsFamilyFact()
      const update = (part: Partial<PointsFamilyFact>) => patch({ pointsFamily: { ...profile.pointsFamily, [member.id]: { ...value, ...part } }, pointsFamilyComplete: null })
      return <div className="child-fact" key={member.id}><strong>가족 {i + 1} · {member.relation.includes('grandparent') ? '조부모' : ancestor ? '부모' : member.relation.includes('grandchild') ? '손자녀' : '자녀'} · {member.dateOfBirth || '생년월일 미입력'}</strong>
        {ancestor && member.ownsHome === true && <p className="field-help">주택 소유 직계존속은 가점 부양가족에서 원칙적으로 제외됩니다. 60세 이상 소유 예외만으로 인정하지 않습니다.</p>}
        <label>본인 또는 배우자와 같은 등본에 연속 등재된 날<input type="date" max={today} value={value.registeredSince} onChange={(event) => update({ registeredSince: event.target.value })} /></label>
        {ancestor ? choice('이 직계존속의 배우자가 주택을 보유하나요? (배우자가 없으면 아니요)', value.spouseOwnsHome, (v) => update({ spouseOwnsHome: v })) : choice('이 자녀·손자녀가 미혼인가요?', value.unmarried, (v) => update({ unmarried: v }))}
        {choice(ancestor ? '최근 3년 내 연속 90일 초과 국외 체류로 부양가족에서 제외되나요?' : '공고의 자녀 국외 체류 제외 기준에 해당하나요?', value.overseasExcluded, (v) => update({ overseasExcluded: v }))}
        {!ancestor && <p className="field-help">30세 미만은 공고일 현재 계속 90일 초과 해외 체류, 30세 이상은 최근 1년 내 계속 90일 초과 체류를 확인합니다.</p>}
        {member.relation.includes('grandchild') && choice('부모 모두 사망 등 공고의 손자녀 인정 사유가 있나요?', value.grandchildrenParentsAbsent, (v) => update({ grandchildrenParentsAbsent: v }))}
      </div>
    })}
    {members.length > 0 && <div data-profile-field="pointsFamilyComplete">{choice('위 가점용 가족 사실에 빠진 내용이 없나요?', profile.pointsFamilyComplete, (v) => patch({ pointsFamilyComplete: v }))}</div>}
    {profile.hasSpouse === true && <div data-profile-field="spouseAccountBaseDate">{choice('배우자가 청약통장에 가입했나요?', profile.spouseAccountPresent, (v) => patch({ spouseAccountPresent: v }))}{profile.spouseAccountPresent === true && <label>배우자 통장 은행 인정 가입일<input type="date" max={today} value={profile.spouseAccountBaseDate} onChange={(event) => patch({ spouseAccountBaseDate: event.target.value })} /></label>}<p className="field-help">배우자의 인정 가입기간 50%, 최대 3점을 더하며 통장 점수 합계는 17점까지입니다.</p></div>}
    {(members.length > 0 || profile.hasSpouse === true || !!profile.pointsHomelessSince) && <FactChangeFields profile={profile} onChange={onChange} today={today} group="points" label="가점 산정 사실" />}
    <a href={POINTS_SOURCE} target="_blank" rel="noopener noreferrer">청약홈 공식 가점 산정 기준</a>
  </details>
}
