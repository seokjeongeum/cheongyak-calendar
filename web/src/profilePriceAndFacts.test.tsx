import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { OwnershipFields } from './OwnershipFields'
import { PointsFields } from './PointsFields'
import { calculatePoints } from './points'
import { setEvaluationToday } from './factTimeline'
import { EMPTY_PROFILE, createHouseholdMember, createOwnershipFact, emptyPointsFamilyFact, type LocalProfile, type Notice } from './types'

const today = '2026-10-09'
const notice: Notice = { id: 'points-facts', title: '가점 비교 공고', category: 'apt', source: 'cheongyak_home', provider: '', address: null, region_code: null, region_name: null, announcement_date: '2026-10-02', official_url: null, price_cap_status: 'unknown', events: [], prices: [], rules: [], updated_at: null, version: 1 }
const profile: LocalProfile = { ...EMPTY_PROFILE, applicantOnRegister: true, applicantOwnsHome: false, applicantPreviouslyOwnedHome: false, householdMembersComplete: true, maritalStatus: 'single', hasSpouse: false, dateOfBirth: '1993-01-01', factChanges: { household: { mode: 'never_changed', date: '' }, household_head: { mode: 'never_changed', date: '' }, points: { mode: 'never_changed', date: '' }, ownership: { mode: 'never_changed', date: '' }, marital: { mode: 'never_changed', date: '' } } }
const child = { ...createHouseholdMember('child'), relation: 'applicant_child' as const, register: 'applicant' as const, dateOfBirth: '2015-01-01', ownsHome: false, previouslyOwnedHome: false }
const withChild: LocalProfile = { ...profile, householdMembers: [child], pointsFamily: { child: { ...emptyPointsFamilyFact(), registeredSince: '2015-01-01', unmarried: true, overseasExcluded: false } } }
const dependantPart = (value: LocalProfile) => { setEvaluationToday(today); return calculatePoints(notice, value).parts.find((part) => part.label === '부양가족')! }

describe('factual profile entries without repeated completion questions', () => {
  it('computes a documented dependent without a separate completion answer', () => {
    expect(dependantPart({ ...withChild, pointsFamilyComplete: null })).toMatchObject({ score: 10 })
    expect(dependantPart({ ...withChild, pointsFamilyComplete: false })).toMatchObject({ score: 10 })
    const html = renderToStaticMarkup(<PointsFields profile={withChild} today={today} onChange={() => {}} />)
    expect(html).not.toContain('위 가점용 가족 사실에 빠진 내용이 없나요?')
    expect(html).toContain('이 자녀·손자녀가 미혼인가요?')
    expect(html).toContain('공고의 자녀 국외 체류 제외 기준에 해당하나요?')
  })

  it('retains missing concrete facts and unverified past state', () => {
    const missing: LocalProfile = { ...withChild, pointsFamilyComplete: true, pointsFamily: { child: { ...withChild.pointsFamily.child, overseasExcluded: null } } }
    expect(dependantPart(missing)).toMatchObject({ score: null })
    expect(dependantPart(missing).detail).toContain('국외 체류')
    const undated: LocalProfile = { ...withChild, factChanges: { ...withChild.factChanges, points: { mode: 'unknown', date: '' } } }
    expect(dependantPart(undated)).toMatchObject({ score: null })
    expect(dependantPart(undated).detail).toContain('변경 이력')
  })

  it('uses the historical inventory day for a recorded ownership snapshot in points', () => {
    setEvaluationToday(today)
    const fact = { ...createOwnershipFact('disposed'), ownerMemberId: 'applicant', ownerRelation: 'applicant' as const, propertyKind: 'apartment' as const, acquiredDate: '2020-01-01', disposedDate: '2026-10-05', areaSqm: '84', acquisitionMethod: 'purchase' as const, standardResidentialBuilding: true }
    const recorded: LocalProfile = { ...profile, ownershipPropertyCounts: { applicant: '0' }, ownershipFacts: [fact], factSnapshots: [{ group: 'ownership', date: '2026-10-02', values: { applicantOwnsHome: true, ownershipPropertyCounts: { applicant: '1' }, ownershipFacts: [fact] } }] }
    expect(calculatePoints(notice, recorded).parts.find((part) => part.label === '무주택기간')).toMatchObject({ score: 0 })
  })

  it('explains an existing home’s official price and preserves unknown basis', () => {
    const fact = { ...createOwnershipFact('home'), ownerMemberId: 'applicant', ownerRelation: 'applicant' as const, propertyKind: 'apartment' as const }
    const html = renderToStaticMarkup(<OwnershipFields profile={{ ...profile, applicantOwnsHome: true, ownershipFacts: [fact] }} onChange={() => {}} today={today} />)
    expect(html).not.toContain('보유한 주택·권리를 빠짐없이 추가했나요?')
    expect(html).toContain('공동주택가격')
    expect(html).toContain('처분일 전에 공시된 가격')
    expect(html).toContain('가격 적용일 · 선택한 주택가격 공시일')
    expect(html).toContain('공시가격 산정기준일인 1월 1일과 구분')
    expect(html).toContain('공공주택의 자산 심사는 해당 공고의 별도 평가 기준')
    expect(html).toContain('value="unknown" selected')
    expect(html).toContain('https://www.realtyprice.kr/notice/main/mainBody.htm')
  })

  it('uses supply price for rights and keeps transaction price distinct', () => {
    const fact = { ...createOwnershipFact('right'), ownerMemberId: 'applicant', ownerRelation: 'applicant' as const, propertyKind: 'presale_right' as const }
    const html = renderToStaticMarkup(<OwnershipFields profile={{ ...profile, applicantOwnsHome: true, ownershipFacts: [fact] }} onChange={() => {}} today={today} />)
    expect(html).toContain('원래 공급계약서의 공급가격')
    expect(html).toContain('선택품목 가격과 전매 프리미엄은 포함하지 않습니다')
    expect(html).toContain('가격 적용일 · 원래 공급계약일')
    expect(html).toContain('취득 신고가격 (원)')
    expect(html).not.toContain('공동주택가격')
  })
})
