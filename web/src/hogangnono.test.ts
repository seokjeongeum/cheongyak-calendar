import { describe, expect, it } from 'vitest'
import { hogangnonoDetailUrl } from './hogangnono'

describe('collected Hogangnono detail links', () => {
  it('renders a resolved detail link for a newly collected complex without a project catalog', () => {
    expect(hogangnonoDetailUrl({ hogangnono_url: 'https://hogangnono.com/apt/newComplex23' }))
      .toBe('https://hogangnono.com/apt/newComplex23')
  })

  it.each([undefined, null, '', 'https://hogangnono.com/search?q=새공고',
    'https://hogangnono.com/apt/newComplex?profile=private',
    'https://hogangnono.com/apt/newComplex#private',
    'http://hogangnono.com/apt/newComplex', 'https://hogangnono.com.evil.example/apt/newComplex',
    'https://user:pass@hogangnono.com/apt/newComplex', 'https://hogangnono.com:8080/apt/newComplex',
    'javascript:alert(1)', '/apt/newComplex', 'https://hogangnono.com/apt/a/b'])
  ('does not render an unresolved, search, or malformed link: %s', (hogangnono_url) => {
    expect(hogangnonoDetailUrl({ hogangnono_url })).toBeUndefined()
  })
})
