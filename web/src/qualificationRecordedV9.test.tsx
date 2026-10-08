import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import recorded from './fixtures/gajeong-admission-v9.json'
import { EligibilityDetails } from './EligibilityDetails'
import { applicationEventAvailability, beginEvaluationRevision, eligibilityCombinations } from './eligibility'
import { evaluateNotice } from './evaluation'
import { setEvaluationToday } from './factTimeline'
import { applicantRegionEligibility, evaluateQualification, regionDecision } from './qualification'
import { EMPTY_PROFILE, type LocalProfile, type Notice } from './types'

const notice = recorded.notice as unknown as Notice
const today = '2026-10-07'
const groups = ['household', 'household_head', 'domestic_residence', 'restrictions', 'overseas', 'citizenship', 'ownership'] as const
function profile(extra: Partial<LocalProfile> = {}): LocalProfile {
  return { ...EMPTY_PROFILE, region: '경기도', regionCode: '41', district: '화성시', districtCode: '41590',
    movedInDate: '2010-01-01', districtMovedInDate: '2010-01-01', dateOfBirth: '1990-01-01',
    applicantOnRegister: true, hasSpouse: false, maritalStatus: 'single', isHouseholdHead: true,
    householdMembersComplete: true, applicantOwnsHome: false, ownershipFactsKnown: true,
    currentlyDomesticResident: true, citizenship: 'korean', overseasContinuousDays: '0',
    applicationHistoryPresence: false, applicationHistoryComplete: true, applicationHistoryPeople: ['applicant'],
    applicationRestrictionFacts: { applicant: { resaleRestrictionActive: false, ineligibleRestrictionActive: false,
      rewinningRestrictionActive: false, asOfDate: '2026-09-01', historyConfirmations: [] } },
    factChanges: Object.fromEntries(groups.map((group) => [group, { mode: 'never_changed', date: '' }])), ...extra }
}
beforeEach(() => { setEvaluationToday(today); beginEvaluationRevision() })
afterEach(() => setEvaluationToday(null))

describe('recorded Gajeong full-source admission integration', () => {
  it('compares the sole offered general-supply path without inventing a common source gap', () => {
    expect(recorded.personalDataIncluded).toBe(false)
    expect(notice.offered_supplies).toHaveLength(4)
    expect(notice.rules.filter((rule) => rule.supply_type === '일반공급' && rule.effect !== 'metadata')).toHaveLength(7)
    const evaluated = evaluateNotice(notice, profile(), today, Date.parse(today + 'T03:00:00Z'))
    expect(evaluated.common.status).toBe('possible')
    expect(evaluated.summary.status).toBe('possible')
    expect(evaluated.common.reasons.some((reason) => reason.category === 'source_gap')).toBe(false)
    const html = renderToStaticMarkup(<EligibilityDetails notice={notice} profile={profile()} onProfile={() => {}} />)
    expect(html).not.toContain('서비스 원문 검토 부족')
    expect(html).not.toContain('class="qualification-source-gap"')
  })
  it('uses the actual 90-day overseas equivalence for regions, common admission and all four offer rows', () => {
    const p = profile({ currentlyDomesticResident: false, overseasContinuousDays: '90' })
    expect(regionDecision(notice, p).status).toBe('not_divided')
    expect(evaluateQualification(notice, p).status).toBe('possible')
    const combinations = eligibilityCombinations(notice, p)
    expect(combinations).toHaveLength(4)
    expect(combinations.every((entry) => entry.result.status === 'possible')).toBe(true)
    expect(applicationEventAvailability({ kind: 'general', label: '일반공급 접수', start_date: today, end_date: today }, notice, p).unavailable).toBe(false)
    const evaluated = evaluateNotice(notice, p, today, Date.parse(today + 'T03:00:00Z'))
    expect(evaluated.common.reasons.some((reason) => reason.status === 'fail')).toBe(false)
    expect(evaluated.summary.status).toBe('possible')
  })
  it('keeps the domestic-residence prerequisite and its excluded one-person 91-day exception', () => {
    const p = profile({ currentlyDomesticResident: false, overseasContinuousDays: '91', overseasOnlyApplicantForLivelihood: true })
    expect(regionDecision(notice, p).status).toBe('outside')
    expect(evaluateQualification(notice, p).status).toBe('mismatch')
    const strict = { ...notice, rules: notice.rules.map((rule) => rule.kind === 'domestic_residence' ? { ...rule, overseas_residence_equivalence: undefined } : rule) }
    expect(regionDecision(strict, profile({ currentlyDomesticResident: false, overseasContinuousDays: '90' })).status).toBe('outside')
  })
  it('applies the documented domestic equivalence only to its allowed supply scope', () => {
    const institution = '기관추천 특별공급'
    const scoped = { ...notice, offered_supplies: [...notice.offered_supplies!, { supply_type: institution, unit_type: '84.0000A', supply_count: 1, verification: 'official' as const }] }
    const p = profile({ currentlyDomesticResident: false, overseasContinuousDays: '90' })
    expect(applicantRegionEligibility(scoped, p, { supplyType: '일반공급' })?.status).toBe('pass')
    expect(applicantRegionEligibility(scoped, p, { supplyType: institution })?.status).toBe('fail')
    expect(applicantRegionEligibility(scoped, p)?.category).toBe('selection')
    const common = evaluateQualification(scoped, p)
    expect(common.reasons.some((reason) => reason.status === 'fail')).toBe(false)
    expect(common.reasons.some((reason) => reason.category === 'source_gap')).toBe(false)
  })
})
