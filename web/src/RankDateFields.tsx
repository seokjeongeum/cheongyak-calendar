import { DateInput } from './DateInput'
import type { LocalProfile } from './types'

export function RankDateFields({ profile, onChange, today }: { profile: LocalProfile; onChange: (profile: LocalProfile) => void; today: string }) {
  const separate = !!profile.rankBaseDatesSeparate || profile.privateRankBaseDate !== profile.nationalRankBaseDate
  const commonDate = profile.privateRankBaseDate || profile.nationalRankBaseDate
  return <section className="question-group">
    <h4>청약통장 순위기산일</h4>
    <p className="field-help">은행에서 확인한 인정 시작일이 같으면 한 번만 입력합니다. 통장 전환 등으로 민영·국민주택 인정일이 다르면 따로 입력하세요.</p>
    <label className="rank-date-separate"><input type="checkbox" checked={separate} onChange={(event) => onChange(event.target.checked ? { ...profile, rankBaseDatesSeparate: true } : { ...profile, rankBaseDatesSeparate: false, privateRankBaseDate: commonDate, nationalRankBaseDate: commonDate })} />민영·국민주택 기산일 따로 입력</label>
    {separate ? <><DateInput field="privateRankBaseDate" label="민영주택 순위기산일" value={profile.privateRankBaseDate} max={today} onChange={(value) => onChange({ ...profile, rankBaseDatesSeparate: true, privateRankBaseDate: value })} /><DateInput field="nationalRankBaseDate" label="국민주택 순위기산일" value={profile.nationalRankBaseDate} max={today} onChange={(value) => onChange({ ...profile, rankBaseDatesSeparate: true, nationalRankBaseDate: value })} /></> : <div data-profile-field="nationalRankBaseDate"><DateInput field="privateRankBaseDate" label="순위기산일 (민영·국민주택 공통)" value={commonDate} max={today} onChange={(value) => onChange({ ...profile, privateRankBaseDate: value, nationalRankBaseDate: value })} /></div>}
  </section>
}
