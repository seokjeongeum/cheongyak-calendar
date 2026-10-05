"""Read-only official unranked and retained competition integration QA.

Fictional inputs are evaluated in a temporary local Node process. Only public
GET requests are used, and the report contains no profile values.
"""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("live_harness", ROOT / "web/tests/v3_live_engine_qa.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)
qa.NOTICE_IDS = {
    "sejong": "0f434f69-2838-4e6f-a186-445940910a13",
    "sillim": "ede290da-b467-42b9-a944-eae51d0fa705",
    "gang": "1706ac8d-4c6a-4472-88fa-9a43dbdbf8da",
    "gwangmyeong": "342f3968-02fd-4d2a-aa79-71baecedf9c4",
    "dongin": "46bcf351-feda-4a60-ab2d-2c29cbd2bc16",
    "jamsil": "0458dfae-6269-4b94-b1fa-9e7034e805ee",
    "a6": "dabc205e-71fb-4ce9-b0c9-ac75e58f9872",
}
qa.ENGINE_FILES += ("household.ts", "profile.ts")
qa.ENGINE_QA = r"""
import { readFileSync } from 'node:fs'
import { EMPTY_PROFILE, createHouseholdMember, createOwnershipFact } from '__SOURCE__/types.ts'
import { deriveRank, unitRankResults, evaluateRule, criterionDate } from '__SOURCE__/qualification.ts'
import { evaluateEligibility, noticeEligibilitySummary, eligibilityCombinations, competitionRowAvailability } from '__SOURCE__/eligibility.ts'
import { resultCompetitionDecision, resultCompetitionRows, competitionDecision } from '__SOURCE__/competition.ts'
import { deriveHousehold } from '__SOURCE__/household.ts'
const { notices, asOf } = JSON.parse(readFileSync(0, 'utf8'))
const checks = [], snapshots = {}, now = Date.parse(asOf)
function check(label, passed) { checks.push({ label, passed: !!passed }) }
function profile(notice, overrides = {}) {
  const cutoff = notice.application_method_evidence?.criterion_date || notice.announcement_date
  const history = [{criterionDate: cutoff, unchanged: true}]
  const restrictions = { ineligibleRestrictionActive: false, resaleRestrictionActive: false,
    rewinningRestrictionActive: false, asOfDate: cutoff, historyConfirmations: [] }
  const projects = {}
  for (const rule of notice.rules) if (rule.project_id) projects[rule.project_id] = {
    winning: false, contract: false, additionalResident: false, winningScope: rule.scope,
    contractScope: rule.scope, asOfDate: cutoff, historyConfirmations: [] }
  const sejong = notice.id === notices.sejong.id
  return { ...EMPTY_PROFILE, region: sejong ? '세종특별자치시' : '서울특별시',
    regionCode: sejong ? '36' : '11', districtCode: sejong ? '36110' : '11110',
    movedInDate: '2010-01-01', districtMovedInDate: '2010-01-01', cityMovedInDate: '2010-01-01',
    dateOfBirth: '1990-01-01', applicantOnRegister: true, hasSpouse: false, maritalStatus: 'single',
    householdMembers: [], householdMembersComplete: true, householdSnapshotDate: cutoff,
    householdHistoryConfirmations: [], householdCompositionUnchanged: null,
    applicantOwnsHome: false, applicantPreviouslyOwnedHome: false, ownershipFactsKnown: true,
    ownershipFacts: [], isHouseholdHead: true, citizenship: 'korean', overseasContinuousDays: '0',
    overseasFactsAsOfDate: cutoff, overseasFactsHistoryConfirmations: [],
    overseasOnlyApplicantForLivelihood: false, projectApplicationHistory: projects,
    applicationRestrictionFacts: {applicant: {...restrictions}, applicant_spouse: {...restrictions}, household: {...restrictions}},
    accountType: 'none', privateRankBaseDate: '', nationalRankBaseDate: '',
    ...overrides }
}
function assess(notice, person) { return evaluateEligibility(notice, person, undefined, '일반공급') }
for (const key of ['sejong', 'sillim', 'gang']) {
  const notice = notices[key], person = profile(notice), outcome = assess(notice, person)
  const expected = key === 'gang' ? 'cancelled_resupply' : 'unranked_after'
  const cutoff = key === 'gang' ? '2026-09-23' : '2026-10-01'
  const verified = notice.rules.filter(rule => rule.effect !== 'metadata' && rule.verification === 'official')
  check(`${key}: official method is independent from category`, notice.application_method === expected)
  check(`${key}: every applicable criterion uses the new reception cutoff`, verified.length > 0 && verified.every(rule => rule.criterion_date === cutoff))
  check(`${key}: application method has page, document hash and original evidence`,
    notice.application_method_evidence?.verification === 'official' && notice.application_method_evidence?.document_hash === notice.document_hash && !!notice.application_method_evidence?.evidence_text)
  check(`${key}: complete official facts actually produce application possibility`, outcome.status === 'possible')
  check(`${key}: no apartment rank requirement is asked`, deriveRank(notice, person).rank === 'not_applicable' && !outcome.reasons.some(reason => /RankBaseDate/.test(reason.profileField || '')))
  check(`${key}: an outside-region applicant is definitively ineligible`, assess(notice, profile(notice, {regionCode:'41', region:'경기도',districtCode:'41590'})).status === 'mismatch')
  check(`${key}: missing roster completeness remains review`, assess(notice, profile(notice, {householdMembersComplete:null})).status === 'review')
  check(`${key}: unconfirmed historical composition cannot certify eligibility`, assess(notice, profile(notice, {householdSnapshotDate:'2026-10-04',householdCompositionUnchanged:true})).status === 'review')
  check(`${key}: exact historical composition confirmation restores the comparison`, assess(notice, profile(notice, {householdSnapshotDate:'2026-10-04',householdHistoryConfirmations:[{criterionDate:cutoff,unchanged:true}]})).status === 'possible')
  check(`${key}: foreign nationality fails its actual official condition`, assess(notice, profile(notice, {citizenship:'foreign'})).status === 'mismatch')
  check(`${key}: 91-day continuous overseas residence fails without exception`, assess(notice, profile(notice, {overseasContinuousDays:'91'})).status === 'mismatch')
  check(`${key}: official livelihood exception uses concrete family residence facts`, assess(notice, profile(notice, {overseasContinuousDays:'91',overseasOnlyApplicantForLivelihood:true})).status === 'possible')
  for (const rule of notice.rules.filter(rule=>rule.kind==='application_restriction')) {
    if (rule.project_id) {
      const old = person.projectApplicationHistory[rule.project_id], field = rule.restriction==='prior_project_contract' ? 'contract' : 'winning'
      const fail = profile(notice,{projectApplicationHistory:{...person.projectApplicationHistory,[rule.project_id]:{...old,[field]:true}}})
      check(`${key}: ${rule.restriction} is compared only within the original project`, evaluateRule(rule, fail, notice).status === 'fail')
      check(`${key}: a different project's answer cannot establish history`, evaluateRule(rule, profile(notice,{projectApplicationHistory:{}}), notice).status === 'review')
    } else {
      const field = {ineligible_restriction_active:'ineligibleRestrictionActive',resale_restriction_active:'resaleRestrictionActive',rewinning_restriction_active:'rewinningRestrictionActive'}[rule.restriction]
      const fail = profile(notice,{applicationRestrictionFacts:{...person.applicationRestrictionFacts,[rule.scope]:{...person.applicationRestrictionFacts[rule.scope],[field]:true}}})
      check(`${key}: ${rule.restriction} applies to the exact official family scope`, evaluateRule(rule, fail, notice).status === 'fail')
      check(`${key}: current restriction lookup is not automatically backdated`, evaluateRule(rule, profile(notice,{applicationRestrictionFacts:{[rule.scope]:{...person.applicationRestrictionFacts[rule.scope],asOfDate:'2026-10-04'}}}), notice).status === 'review')
    }
  }
  const head = assess(notice,profile(notice,{isHouseholdHead:false}))
  check(`${key}: head requirement follows this document, not all unranked notices`, head.status === (key==='gang'?'mismatch':'possible'))
  snapshots[key] = { applicationMethod: notice.application_method, criterionDate: cutoff,
    qualification: outcome.status, rank: deriveRank(notice,person).rank,
    nonHeadOutcome: head.status, prices: notice.prices.length,
    verifiedCriteria: verified.length, originalDate: notice.qualification_context?.original_announcement_date }
}
const gw = notices.gwangmyeong, person = profile(gw,{regionCode:'41',districtCode:'41590',region:'경기도'})
const result = resultCompetitionDecision(gw,person,undefined,now)
const allRows = resultCompetitionRows(gw,result,true)
const closed = allRows.filter(row=>row.unit_type==='059.9742A')
const open = allRows.find(row=>row.unit_type==='059.7421B' && row.competition_rate==='1.10')
check('Gwangmyeong: all 28 official rows and all seven prices remain',allRows.length===28 && gw.prices.length===7)
check('Gwangmyeong: the four 59A rows are unavailable instead of hidden',closed.length===4 && closed.every(row=>competitionRowAvailability(row,gw,person,result).unavailable))
check('Gwangmyeong: 59B stays available even at a rate of 1.10',open && !competitionRowAvailability(open,gw,person,result).unavailable)
check('Gwangmyeong: legacy hide preference has no filtering effect',JSON.stringify(resultCompetitionRows(gw,result,false))===JSON.stringify(allRows) && result.hidden===false)
const corrected = {...gw,competition:{...gw.competition,proof_invalidated:true}}
check('Gwangmyeong: a relevant correction releases old closure decisions',resultCompetitionDecision(corrected,person,undefined,now).closedUnits.length===0)
check('Gwangmyeong: collection failure releases live application exclusion',competitionDecision({...gw,competition:{...gw.competition,status:'error'}},person,'2026-10-04',undefined,now).closedUnits.length===0)
snapshots.gwangmyeong={prices:gw.prices.length,officialRows:allRows.length,closed59ARows:closed.length,open59BRate:open?.competition_rate}
const office=notices.jamsil, officePerson=profile(office)
check('Jamsil: four corrected sale prices are retained',office.prices.map(row=>row.amount_krw).sort((a,b)=>a-b).join(',')==='588000000,819800000,913810000,937560000')
check('Jamsil: official office eligibility remains distinct from apartment ranking',office.application_method==='officetel' && deriveRank(office,officePerson).rank==='not_applicable')
function bookProfile(notice) {
  const cutoff=criterionDate({kind:'baseline'},notice)
  return profile(notice,{accountType:'comprehensive',privateRankBaseDate:'2010-01-01',nationalRankBaseDate:'2010-01-01',
    privateDepositKrw:'6000000',privateDepositAsOfDate:cutoff,privateDepositMaintained:true,
    nationalRecognizedPayments:'12',nationalPaymentsAsOfDate:cutoff,
    accountConversionUnclear:false,previousWinning:false,restrictedFromApplying:false,
    householdSnapshotDate:cutoff})
}
for(const key of ['dongin','gwangmyeong']) {
  const notice=notices[key], person=bookProfile(notice), units=unitRankResults(notice,person)
  check(`${key}: all actual private unit ranks still satisfy their official bank requirements`,units.length===notice.prices.length&&units.every(row=>row.result.rank==='first'))
}
const national=notices.a6, bank=bookProfile(national)
check('A6: national rank still uses twelve recognized payments',national.housing_kind==='national'&&deriveRank(national,bank).rank==='first')
check('A6: nine payments do not satisfy national rank',deriveRank(national,{...bank,nationalRecognizedPayments:'9'}).status==='mismatch')
check('Dongin: the same nine payments do not affect private first rank',deriveRank(notices.dongin,{...bookProfile(notices.dongin),nationalRecognizedPayments:'9'}).rank==='first')
console.log(JSON.stringify({checks,snapshots}))
"""

if __name__ == "__main__":
    if "--output" not in sys.argv:
        sys.argv += ["--output", str(ROOT / "docs/qa/v4-live-engine-2026-10-04.json")]
    sys.exit(qa.main())
