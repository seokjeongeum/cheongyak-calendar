import { describe, expect, it } from 'vitest'
import { moneyEdit } from './MoneyInput'
import { formatMoney, normalizeMoney } from './profile'

describe('won input values and display', () => {
  it('stores integer won while displaying grouping separators for all monetary fields', () => {
    expect(normalizeMoney('60,000,000')).toBe('60000000')
    expect(normalizeMoney('00060000000')).toBe('60000000')
    expect(formatMoney('60000000')).toBe('60,000,000')
    expect(formatMoney('3000000')).toBe('3,000,000')
    expect(formatMoney('0')).toBe('0')
    expect(formatMoney('')).toBe('')
  })

  it('rejects invalid persisted values rather than changing their financial meaning', () => {
    for (const value of ['-1', '1.5', '1e6', '1원', '1,20', '1,,000', 'NaN', Infinity, null, false]) {
      expect(normalizeMoney(value)).toBeNull()
    }
    expect(normalizeMoney('9007199254740991')).toBe('9007199254740991')
    expect(normalizeMoney('9007199254740992')).toBeNull()
  })

  it('formats a pasted amount and places the caret after its last digit', () => {
    expect(moneyEdit('60000000', 8)).toEqual({ raw: '60000000', display: '60,000,000', caret: 10, error: '' })
    expect(moneyEdit('60,000,000', 10)).toEqual({ raw: '60000000', display: '60,000,000', caret: 10, error: '' })
  })

  it('keeps the caret by the inserted digits when editing in the middle of the amount', () => {
    // Insert 5 after the initial 60 in the already formatted 60,000,000.
    expect(moneyEdit('605,000,000', 3)).toEqual({ raw: '605000000', display: '605,000,000', caret: 3, error: '' })
    // Remove a middle digit: the remaining separator positions are reformatted.
    expect(moneyEdit('60,00,000', 4)).toEqual({ raw: '6000000', display: '6,000,000', caret: 4, error: '' })
  })

  it('keeps a caret before the first digit and accounts for removed leading zeros', () => {
    expect(moneyEdit('60,000,000', 0)).toMatchObject({ raw: '60000000', caret: 0, error: '' })
    expect(moneyEdit('0006000', 4)).toEqual({ raw: '6000', display: '6,000', caret: 1, error: '' })
    expect(moneyEdit('0006000', 2)).toMatchObject({ raw: '6000', caret: 0, error: '' })
  })

  it('reports negative, decimal, or text input and clears the amount used for diagnosis', () => {
    for (const text of ['-3,000,000', '3000000.50', '300만', '1e6', ',,,']) {
      const result = moneyEdit(text, text.length)
      expect(result.raw).toBe('')
      expect(result.display).toBe(text)
      expect(result.error).toContain('원 단위 정수')
    }
  })

  it('rejects an unsafe integer without rounding and accepts the maximum exact integer', () => {
    expect(moneyEdit('9,007,199,254,740,991', 21)).toMatchObject({ raw: '9007199254740991', display: '9,007,199,254,740,991', error: '' })
    expect(moneyEdit('9,007,199,254,740,992', 21)).toMatchObject({ raw: '', display: '9,007,199,254,740,992', error: '입력 가능한 금액 범위를 넘었습니다.' })
  })

  it('supports clearing a value and normalizes zero without introducing a missing amount', () => {
    expect(moneyEdit('', 0)).toEqual({ raw: '', display: '', caret: 0, error: '' })
    expect(moneyEdit('000', 3)).toEqual({ raw: '0', display: '0', caret: 1, error: '' })
  })
})
