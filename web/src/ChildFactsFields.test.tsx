import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ChildFactsFields } from './ChildFactsFields'
import { migrateProfile, updateProfileFacts } from './profile'
import { EMPTY_PROFILE, type LocalProfile } from './types'

const profile = (extra: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, hasChildren: false, pregnant: false, factChanges: {}, ...extra })
const render = (value: LocalProfile) => renderToStaticMarkup(<ChildFactsFields profile={value} onChange={() => {}} today="2026-10-05" needsPast />)
const commonChoice = (html: string) => html.match(/<button[^>]*>계속 자녀·임신 없음<\/button>/)?.[0]

describe('child and pregnancy history controls', () => {
  it('keeps a current-only absence separate from an explicit lifelong absence', () => {
    const current = profile()
    const html = render(current)
    expect(commonChoice(html)).toContain('aria-pressed="false"')
    expect(html).toContain('자녀 상태 마지막 변경일')
    expect(html).toContain('임신 상태 마지막 변경일')
    expect(html).not.toContain('자녀 정보 추가')
    expect(html).not.toContain('임신 중 태아 수')
    expect(migrateProfile(current).factChanges).toEqual({})
  })
  it('protects current pregnancy and retained pregnancy data from the lifelong-absence shortcut', () => {
    for (const extra of [{ pregnant: true }, { expectedChildren: '2' }, { factSnapshots: [{ group: 'pregnancy' as const, date: '2026-09-01', values: { expectedChildren: '1' } }] }]) {
      const html = render(profile(extra))
      expect(commonChoice(html)).toContain('disabled=""')
      expect(commonChoice(html)).toContain('aria-pressed="false"')
      expect(html).toContain('저장된 자녀·임신 이력이 있습니다')
    }
  })
  it('keeps genuine child and adoption details when the current answer becomes no', () => {
    const previous = profile({ hasChildren: true, children: [{ dateOfBirth: '2020-01-01', adopted: true, adoptionDate: '2026-09-01' }] })
    const current = updateProfileFacts(previous, { hasChildren: false }, '2026-10-05')
    expect(current.children).toEqual(previous.children)
    expect(migrateProfile(current).children).toEqual(previous.children)
    const html = render(current)
    expect(commonChoice(html)).toContain('disabled=""')
    expect(html).not.toContain('자녀 정보 추가')
    expect(html).not.toContain('자녀 1 생년월일')
  })
  it('does not present contradictory saved history as a selected lifelong absence', () => {
    const html = render(profile({ expectedChildren: '2', factChanges: { children: { mode: 'never_changed', date: '' }, pregnancy: { mode: 'never_changed', date: '' } } }))
    expect(commonChoice(html)).toContain('aria-pressed="false"')
    expect(html).toContain('임신 상태 마지막 변경일')
  })
})
