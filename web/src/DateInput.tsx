import { useId } from 'react'

/** Date segments have inconsistent keyboard clearing across browsers. */
export function DateInput({ label, value, onChange, max, field }: { label: string; value: string; onChange: (value: string) => void; max?: string; field?: string }) {
  const id = useId()
  return <div className="date-field" data-profile-field={field}>
    <label htmlFor={id}>{label}</label>
    <div className="date-input-row"><input id={id} type="date" max={max} value={value} onChange={(event) => onChange(event.target.value)} /><button type="button" className="text-button" aria-label={`${label} 지우기`} disabled={!value} onClick={() => onChange('')}>지우기</button></div>
  </div>
}
