import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ReasonList } from './EligibilityDetails'
import { conditionSourceStatus } from './eligibility'
import { setEvaluationToday } from './factTimeline'
import { evaluateRule, FIRST_HOME_ANCESTOR_GUIDANCE_URL } from './qualification'
import { createHouseholdMember, EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'

const cutoff = '2026-10-02', today = '2026-10-09', supply = '생애최초 특별공급'
const digest = '90a4d4e7e50b205ae45ee27cd7b3b50b5b8e1b3a65f19580f156336308cc1c34'
const source = 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000468&pblancNo=2026000468&atchmnflSeqNo=1990183&atchmnflSn=2'
const clause: NoticeRule = { kind: 'unparsed', verification: 'official', supply_type: supply, document_hash: digest, evidence_url: source, evidence_page: 38, label: '생애최초의 제53조 과거 주택 소유 예외', text: '법령상 소유 예외와 과거 소유 사실의 적용 범위', evidence_text: '만60세 이상의 직계존속(배우자의 직계존속을 포함한다)이 주택 또는 분양권등을 소유하고 있는 경우(단, 노부모부양 특별공급 신청자 제외)' }
const rule: NoticeRule = { kind: 'never_owned_home', value: true, verification: 'official', supply_type: supply, scope: 'household', criterion_date: cutoff, document_hash: digest, evidence_url: source, evidence_page: 17, exclude_spouse_pre_marriage_disposed: true, exceptions: [clause] }
const notice: Notice = { id: 'first-home', title: '현재 민영주택 공고', category: 'apt', housing_kind: 'private', source: 'cheongyak_home', provider: '공식 기관', address: null, region_code: null, region_name: null, announcement_date: cutoff, official_url: source, price_cap_status: 'unknown', events: [], prices: [], rules: [rule], updated_at: null, version: 1 }
const parent = { ...createHouseholdMember('parent'), relation: 'applicant_parent' as const, register: 'applicant' as const, dateOfBirth: '1966-10-02', ownsHome: true, previouslyOwnedHome: true }
const profile = (part: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, dateOfBirth: '1990-01-01', hasSpouse: false, maritalStatus: 'single', householdSnapshotDate: cutoff, householdMembers: [parent], applicantPreviouslyOwnedHome: false, factChanges: { household: { mode: 'never_changed', date: '' } }, ...part })
beforeEach(() => setEvaluationToday(today))
afterEach(() => setEvaluationToday(null))

describe('source-bound first-home ancestor historical ownership', () => {
  it('uses age at the original announcement, including current and past ownership, with the official guidance link', () => {
    const result = evaluateRule(rule, profile(), notice)
    expect(result).toMatchObject({ status: 'pass', criterionDate: cutoff, legalEvidenceUrl: FIRST_HOME_ANCESTOR_GUIDANCE_URL })
    expect(result.detail).toContain('공고일 만 60세')
    expect(result.detail).toContain('현재·과거 주택 소유')
    expect(renderToStaticMarkup(<ReasonList reasons={[result]} />)).toContain(FIRST_HOME_ANCESTOR_GUIDANCE_URL.replaceAll('&', '&amp;'))
    expect(evaluateRule(rule, profile({ householdMembers: [{ ...parent, previouslyOwnedHome: null }] }), notice).status).toBe('pass')
  })
  it('does not use today’s age for a younger parent at the announcement and asks a missing birth date directly', () => {
    expect(evaluateRule(rule, profile({ householdMembers: [{ ...parent, dateOfBirth: '1966-10-06' }] }), notice)).toMatchObject({ status: 'review', category: 'source_gap' })
    expect(evaluateRule(rule, profile({ householdMembers: [{ ...parent, dateOfBirth: '' }] }), notice)).toMatchObject({ status: 'review', category: 'missing_input', label: '과거 소유 직계존속의 생년월일', profileField: 'householdMembers', profileMemberId: parent.id })
  })
  it('retains other owners’ histories and combines only the documented spouse exception', () => {
    expect(evaluateRule(rule, profile({ applicantPreviouslyOwnedHome: true }), notice)).toMatchObject({ status: 'review', category: 'source_gap' })
    expect(evaluateRule(rule, profile({ householdMembers: [{ ...parent, relation: 'applicant_child' }] }), notice)).toMatchObject({ status: 'review', category: 'source_gap' })
    const spouse = profile({ hasSpouse: true, maritalStatus: 'married', spousePreviouslyOwnedHome: true, spousePremarriageOwnershipDisposed: true })
    expect(evaluateRule(rule, spouse, notice).status).toBe('pass')
    expect(evaluateRule(rule, { ...spouse, spousePremarriageOwnershipDisposed: null }, notice).status).toBe('review')
  })
  it('requires the verified matching document clause and private first-home scope', () => {
    for (const exception of [{ ...clause, verification: 'ai_unverified' }, { ...clause, document_hash: 'f'.repeat(64) }, { ...clause, supply_type: '노부모부양 특별공급' }, { ...clause, evidence_text: '주택 소유의 일부 예외를 검토합니다.' }]) {
      expect(evaluateRule({ ...rule, exceptions: [exception] }, profile(), notice).status).not.toBe('pass')
    }
    const otherNotices: Notice[] = [{ ...notice, housing_kind: 'national' }, { ...notice, category: 'public_rental' }]
    for (const other of otherNotices) expect(evaluateRule(rule, profile(), other).status).not.toBe('pass')
    const youngerNotice = { ...notice, rules: [{ ...rule, supply_type: '노부모부양 특별공급' }] }
    expect(evaluateRule(youngerNotice.rules[0], profile(), youngerNotice).status).not.toBe('pass')
  })
  it('keeps the historical roster and removes only the fully compared conditional source gap', () => {
    const coverage: NoticeRule = { kind: 'condition_coverage', effect: 'metadata', verification: 'official', scopes: [{ supply_type: supply, complete: true, topics: [{ topic: clause.label, status: 'partial', required: true, reason: clause.text }] }] }
    const n = { ...notice, rules: [rule, coverage] }
    expect(conditionSourceStatus(n, profile()).topics.map((item) => item.label)).not.toContain(clause.label)
    expect(conditionSourceStatus(n, profile({ applicantPreviouslyOwnedHome: true })).topics.map((item) => item.label)).toContain(clause.label)
    const old = profile({ householdMembers: [{ ...parent, dateOfBirth: '1950-01-01' }], factChanges: {}, factSnapshots: [{ group: 'household', date: cutoff, values: { hasSpouse: false, maritalStatus: 'single', householdMembers: [{ ...parent, dateOfBirth: '1966-10-06' }] } }] })
    expect(evaluateRule(rule, old, n).status).toBe('review')
  })
})
