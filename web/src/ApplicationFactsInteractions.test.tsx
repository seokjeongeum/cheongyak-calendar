import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApplicationFactsFields } from './ApplicationFactsFields'
import { applicationHistoryCoveredPeople, applicationHistoryPersonPresence } from './applicationHistoryFacts'
import { setEvaluationToday } from './factTimeline'
import { HouseholdFields } from './HouseholdFields'
import { updateProfileFacts } from './profile'
import { createHouseholdMember, EMPTY_PROFILE, type LocalProfile, type Notice } from './types'

// Exercise the actual JSX callbacks without a browser or a DOM replacement.
// These two fields have no stateful hooks: their parent owns the local draft.
vi.mock('react', async (original) => ({
  ...await original<typeof import('react')>(),
  useMemo: <T,>(factory: () => T) => factory(),
}))

type Element = ReactElement<Record<string, unknown>>
const today = '2026-10-09'
const notice: Notice = {
  id: 'history-interaction-fixture', title: '공통 이력 검증 공고', category: 'apt',
  source: 'cheongyak_home', provider: '청약홈', address: null, region_code: null,
  region_name: null, announcement_date: '2026-10-02', official_url: 'https://example.com/official.pdf',
  price_cap_status: 'unknown', events: [], prices: [], updated_at: null, version: 1,
  rules: [{ kind: 'previous_winning', value: false, scope: 'household', verification: 'official', criterion_date: '2026-10-02', evidence_url: 'https://example.com/official.pdf' }],
}
const initial = (part: Partial<LocalProfile> = {}): LocalProfile => ({
  ...EMPTY_PROFILE, maritalStatus: 'married', hasSpouse: true, spouseSameRegister: true,
  applicantOnRegister: null, additionalFamilyPresence: false,
  applicationHistoryPresence: false, applicationHistoryComplete: true,
  applicationHistoryPeople: ['applicant', 'spouse'], applicationHistoryAbsencePeople: [],
  applicationHistoryEvents: [], householdMembers: [], factChanges: {}, factSnapshots: [], ...part,
})

function elements(node: ReactNode): Element[] {
  if (Array.isArray(node)) return node.flatMap(elements)
  if (!isValidElement<Record<string, unknown>>(node)) return []
  if (typeof node.type === 'function') {
    return elements((node.type as (props: Record<string, unknown>) => ReactNode)(node.props))
  }
  return [node, ...elements(node.props.children as ReactNode)]
}
function content(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(content).join('')
  if (!isValidElement<Record<string, unknown>>(node)) return ''
  if (typeof node.type === 'function') return content((node.type as (props: Record<string, unknown>) => ReactNode)(node.props))
  return content(node.props.children as ReactNode)
}
function labelContent(node: ReactNode): string {
  if (Array.isArray(node)) return node.map(labelContent).join('')
  if (isValidElement<Record<string, unknown>>(node)) {
    if (['input', 'select', 'textarea'].includes(String(node.type))) return ''
    return labelContent(node.props.children as ReactNode)
  }
  return content(node)
}
function find(root: ReactNode, type: string, label: string): Element {
  const matches = elements(root).filter((node) => node.type === type && (type === 'label' ? labelContent(node) : content(node)) === label)
  expect(matches, `${type}: ${label}`).toHaveLength(1)
  return matches[0]
}
function invoke(node: Element, event = 'onClick', input?: unknown): void {
  expect(node.props[event]).toBeTypeOf('function')
  ;(node.props[event] as (value?: unknown) => void)(input)
}
function harness(start: LocalProfile) {
  let value = start
  const change = (next: LocalProfile) => { value = updateProfileFacts(value, next, today) }
  const history = () => ApplicationFactsFields({ profile: value, onChange: change, today, notices: [notice], section: 'restrictions' })
  const household = () => HouseholdFields({ profile: value, onChange: change, today, notices: [] })
  return {
    get value() { return value },
    history, household,
    click(label: string) { invoke(find(history(), 'button', label)) },
    edit(label: string, text: string) {
      const field = elements(find(history(), 'label', label)).find((node) => ['input', 'select'].includes(String(node.type)))
      expect(field).toBeDefined()
      invoke(field!, 'onChange', { target: { value: text } })
    },
    answer(label: string, answer: string) {
      const fieldset = elements(history()).find((node) => node.type === 'fieldset' && elements(node.props.children as ReactNode).some((child) => child.type === 'legend' && content(child) === label))
      expect(fieldset, label).toBeDefined()
      invoke(find(fieldset, 'button', answer))
    },
    questions() { return elements(history()).filter((node) => node.type === 'legend').map(content) },
  }
}

beforeEach(() => {
  setEvaluationToday(today)
  let counter = 0
  vi.stubGlobal('crypto', { randomUUID: () => `local-event-${++counter}` })
})
afterEach(() => { setEvaluationToday(null); vi.unstubAllGlobals() })

describe('common history field interactions', () => {
  it('adds and completes an applicant event while preserving the exact saved spouse absence', () => {
    const ui = harness(initial()) // Deliberately use legacy in-memory data, before migration.
    expect(ui.questions()).toEqual([])
    ui.click('이력 추가')
    expect(ui.value.applicationHistoryAbsencePeople).toEqual(['spouse'])
    expect(applicationHistoryPersonPresence(ui.value, 'applicant')).toBe(true)
    expect(applicationHistoryPersonPresence(ui.value, 'spouse')).toBe(false)
    expect(applicationHistoryCoveredPeople(ui.value).has('applicant')).toBe(false)
    ui.edit('사업번호 · 같은 사업 판정에만 필요', '2026000468')
    ui.edit('실제 사건 날짜', '2026-10-01')
    expect([...applicationHistoryCoveredPeople(ui.value)].sort()).toEqual(['applicant', 'spouse'])
    expect(ui.value.applicationHistoryComplete).toBeNull()
    expect(ui.questions()).toEqual([])
    expect(content(ui.history())).not.toContain('위 확인 대상의 당첨·계약 이력을 모두 입력했나요?')
    expect(content(ui.history())).not.toContain('위 사람 중 당첨·예비당첨')
  })

  it('edits a legacy mixed event without losing an unaffected person’s recorded absence', () => {
    const ui = harness(initial({
      applicationHistoryPresence: true,
      applicationHistoryEvents: [{ id: 'saved', personId: 'applicant', projectId: '2026000468', eventKind: 'winning', eventDate: '2026-10-01' }],
    }))
    expect(applicationHistoryPersonPresence(ui.value, 'spouse')).toBe(false)
    ui.edit('사건 종류', 'contract')
    ui.edit('사업번호 · 같은 사업 판정에만 필요', 'LH-0000061183')
    ui.edit('실제 사건 날짜', '2026-09-30')
    expect(ui.value.applicationHistoryAbsencePeople).toEqual(['spouse'])
    expect(applicationHistoryPersonPresence(ui.value, 'spouse')).toBe(false)
    expect([...applicationHistoryCoveredPeople(ui.value)].sort()).toEqual(['applicant', 'spouse'])
    expect(ui.value.applicationHistoryEvents[0]).toMatchObject({ projectId: 'LH-0000061183', eventKind: 'contract', eventDate: '2026-09-30' })
    expect(ui.questions()).toEqual([])
  })

  it('deleting the last applicant event restores only the applicant’s unresolved substantive history', () => {
    const ui = harness(initial())
    ui.click('이력 추가')
    ui.edit('사업번호 · 같은 사업 판정에만 필요', '2026000468')
    ui.edit('실제 사건 날짜', '2026-10-01')
    ui.click('이력 삭제')
    expect(ui.value.applicationHistoryEvents).toEqual([])
    expect(applicationHistoryPersonPresence(ui.value, 'applicant')).toBeNull()
    expect(applicationHistoryPersonPresence(ui.value, 'spouse')).toBe(false)
    expect(ui.questions()).toEqual(['본인에게 당첨·예비당첨 또는 주택 공급계약 이력이 있나요?'])
    ui.answer(ui.questions()[0], '아니요')
    expect([...applicationHistoryCoveredPeople(ui.value)].sort()).toEqual(['applicant', 'spouse'])
    expect(ui.questions()).toEqual([])
  })

  it('asks only a newly added parent’s history and creates an event for that exact parent', () => {
    const ui = harness(initial())
    invoke(find(ui.household(), 'button', '가족 추가'))
    const parentId = ui.value.householdMembers[0].id
    const editHousehold = (label: string, value: string) => {
      const field = elements(ui.household()).find((node) => node.type === 'select' && node.props['aria-label'] === label)!
      expect(field).toBeDefined()
      invoke(field, 'onChange', { target: { value } })
    }
    editHousehold('본인과의 가족 관계', 'applicant_parent')
    editHousehold('어느 주민등록등본에 함께 있나요?', 'applicant')
    expect(ui.questions()).toEqual(['본인의 부모 · 가족 1에게 당첨·예비당첨 또는 주택 공급계약 이력이 있나요?'])
    expect(applicationHistoryPersonPresence(ui.value, 'applicant')).toBe(false)
    expect(applicationHistoryPersonPresence(ui.value, 'spouse')).toBe(false)
    expect(applicationHistoryPersonPresence(ui.value, parentId)).toBeNull()
    ui.answer(ui.questions()[0], '예')
    expect(ui.value.applicationHistoryEvents).toHaveLength(1)
    expect(ui.value.applicationHistoryEvents[0].personId).toBe(parentId)
    expect(ui.value.applicationHistoryAbsencePeople.sort()).toEqual(['applicant', 'spouse'])
    expect(ui.questions()).toEqual([])
    expect(content(ui.history())).not.toContain('모두 입력했나요?')
  })

  it('keeps an exceptional registration answer editable without mounting a baseline confirmation', () => {
    const ui = harness(initial({ applicantOnRegister: false }))
    expect(content(ui.household())).not.toContain('본인이 주민등록등본에 등재되어 있나요?')
    const checkbox = elements(ui.household()).find((node) => node.type === 'input' && node.props.type === 'checkbox')!
    expect(checkbox.props.checked).toBe(true)
    invoke(checkbox, 'onChange', { target: { checked: false } })
    expect(ui.value.applicantOnRegister).toBe(true)
    expect(elements(ui.household()).find((node) => node.type === 'input' && node.props.type === 'checkbox')!.props.checked).toBe(false)
    expect(content(ui.household())).not.toContain('본인이 주민등록등본에 등재되어 있나요?')
    const ordinary = harness(initial({ applicantOnRegister: null }))
    expect(content(ordinary.household())).toContain('주택 보유를 함께 확인할 사람 · 2명')
  })

  it('does not extend a new no-history answer to an unrelated identity', () => {
    const parent = { ...createHouseholdMember('exact-parent'), relation: 'applicant_parent' as const, register: 'applicant' as const }
    const ui = harness(initial({ householdMembers: [parent], additionalFamilyPresence: true }))
    ui.answer('본인의 부모 · 가족 1에게 당첨·예비당첨 또는 주택 공급계약 이력이 있나요?', '아니요')
    expect([...applicationHistoryCoveredPeople(ui.value)].sort()).toEqual(['applicant', 'exact-parent', 'spouse'])
    expect(applicationHistoryPersonPresence(ui.value, 'another-parent')).toBeNull()
    expect(ui.questions()).toEqual([])
  })
})
