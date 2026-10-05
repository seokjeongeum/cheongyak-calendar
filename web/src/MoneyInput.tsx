import { useId, useLayoutEffect, useRef, useState } from 'react'
import { formatMoney, normalizeMoney } from './profile'

export function moneyEdit(text: string, caret: number): { raw: string; display: string; caret: number; error: string } {
  if (!text) return { raw: '', display: '', caret: 0, error: '' }
  if (!/^[\d,]+$/.test(text) || !/\d/.test(text)) return { raw: '', display: text, caret, error: '음수·소수·문자 없이 원 단위 정수를 입력해 주세요.' }
  const digitsBefore = text.slice(0, caret).replaceAll(',', '').length
  const originalDigits = text.replaceAll(',', '')
  const raw = originalDigits.replace(/^0+(?=\d)/, '')
  if (!Number.isSafeInteger(Number(raw))) return { raw: '', display: text, caret, error: '입력 가능한 금액 범위를 넘었습니다.' }
  const display = formatMoney(raw)
  const targetDigits = Math.max(0, digitsBefore - (originalDigits.length - raw.length))
  let position = 0
  let count = 0
  while (position < display.length && count < targetDigits) { if (/\d/.test(display[position])) count++; position++ }
  return { raw, display, caret: position, error: '' }
}

export function MoneyInput({ label, value, onChange, placeholder = '예: 60,000,000' }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  const id = useId()
  const ref = useRef<HTMLInputElement>(null)
  const [invalid, setInvalid] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [, setEditRevision] = useState(0)
  const caret = useRef<number | null>(null)
  const display = invalid ?? formatMoney(value)
  useLayoutEffect(() => { if (caret.current !== null && document.activeElement === ref.current) { ref.current?.setSelectionRange(caret.current, caret.current); caret.current = null } })
  return <label>{label}<input ref={ref} type="text" inputMode="numeric" autoComplete="off" value={display} placeholder={placeholder} aria-label={label} onPaste={(event) => {
    const pasted = event.clipboardData.getData('text').trim()
    if (normalizeMoney(pasted) === null) {
      event.preventDefault()
      setInvalid(pasted)
      setError('원 단위 정수 또는 60,000,000 형식으로 붙여넣어 주세요.')
      onChange('')
    }
  }} aria-invalid={!!error} aria-describedby={error ? `${id}-error` : undefined} onChange={(event) => {
    const result = moneyEdit(event.target.value, event.target.selectionStart ?? event.target.value.length)
    setEditRevision((revision) => revision + 1)
    caret.current = result.caret
    setError(result.error)
    setInvalid(result.error ? result.display : null)
    onChange(result.raw)
  }} />{error && <span id={`${id}-error`} className="input-error" role="alert">{error}</span>}</label>
}
