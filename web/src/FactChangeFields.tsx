import type { FactChangeGroup, LocalProfile } from './types'

const GROUP_FIELD: Record<FactChangeGroup, keyof LocalProfile> = {
  household: 'householdSnapshotDate', household_head: 'isHouseholdHead', domestic_residence: 'domesticResidenceFactsAsOfDate', restrictions: 'applicationRestrictionsAsOfDate', overseas: 'overseasFactsAsOfDate', military: 'militaryFactsAsOfDate', income_tax: 'incomeTaxFactsAsOfDate', income: 'monthlyIncomeKrw', assets: 'assetsKrw', bank_private: 'privateDepositAsOfDate', bank_national: 'nationalPaymentsAsOfDate', citizenship: 'citizenship', employment: 'employed', parent_support: 'parentSupportSince', marital: 'maritalStatus', children: 'children', pregnancy: 'pregnant', points: 'pointsFamily', provider_employee: 'providerEmployeeOrRelatedFamily', ownership: 'ownershipFactsKnown',
}

/** A current state has one effective date, reused across every notice. */
export function FactChangeFields({ profile, onChange, today, group, label, needed = true }: { profile: LocalProfile; onChange: (profile: LocalProfile) => void; today: string; group: FactChangeGroup; label: string; needed?: boolean }) {
  if (!needed) return null
  const value = profile.factChanges?.[group] || { mode: 'unknown' as const, date: '' }
  const patch = (part: Partial<typeof value>) => onChange({ ...profile, factChanges: { ...profile.factChanges, [group]: { ...value, ...part } } })
  return <div className="fact-change-fields" data-profile-field={GROUP_FIELD[group]} data-fact-group={group}><div data-profile-field="factChanges">
    <label>{label} 마지막 변경일<select value={value.mode} onChange={(event) => patch({ mode: event.target.value as typeof value.mode, date: '' })}><option value="unknown">날짜 모름</option><option value="never_changed">변경된 적 없음</option><option value="known">변경일 입력</option></select></label>
    {value.mode === 'known' && <label>{label} 현재 상태가 된 날짜<input type="date" max={today} value={value.date} onChange={(event) => patch({ date: event.target.value })} /></label>}
    <p className="field-help">오늘의 상태를 과거 공고와 비교할 때 필요한 날짜입니다. 이미 입력한 혼인·전입·취득·처분일은 다시 묻지 않습니다.</p>
  </div></div>
}
