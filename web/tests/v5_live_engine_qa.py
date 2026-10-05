"""Compare the current browser engine with retained, real official documents.

Public GETs only. Invented profiles remain in a temporary local Node process;
the report records outcomes and source identities, never profile values.
"""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("live_harness", ROOT / "web/tests/v3_live_engine_qa.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)
qa.NOTICE_IDS = {
    "chungjeong": "11392454-ce19-4183-8140-f26e281492cd",
    "goyang": "d807d08e-3271-4fdf-be1c-aa1a086e469b",
    "tangjeong": "783152f1-7537-4c48-872c-75466601b153",
    "jeju": "60401c1e-b718-44a9-acf4-09f548ee51e5",
    "cheonan": "71d1726a-1e92-4338-9d1d-932e5b6e3ee8",
    "a17": "5faf1ba8-7b13-47a3-9d08-7ae8fd2689a3",
    "a17_lh": "d2136733-94c5-461c-a504-f1c98fe44bdf",
    "yeongcheon": "3aa440bd-520d-4e1b-b767-1e4ea3321796",
    "gyeongsan": "357d40f0-2bff-41f3-ab5e-14581230a812",
    "wonju": "78d6acfa-fad7-45f2-b39e-4b2c4549bf99",
    "suwon": "592b796e-e0b3-47ad-8268-4840107cc45c",
}
qa.ENGINE_FILES += ("household.ts", "profile.ts")
qa.ENGINE_QA = r"""
import { readFileSync } from 'node:fs'
import { EMPTY_PROFILE } from '__SOURCE__/types.ts'
import { deriveRank, evaluateRule, regionDecision, criterionDate } from '__SOURCE__/qualification.ts'
import { evaluateEligibility, eligibilityCombinations, officialOfferedSupplies } from '__SOURCE__/eligibility.ts'
const { notices } = JSON.parse(readFileSync(0,'utf8'))
const checks=[],snapshots={}
const check=(label,passed)=>checks.push({label,passed:!!passed})
const meta=(n,kind)=>n.rules.find(r=>r.kind===kind&&r.effect==='metadata')
function person(n,overrides={}) {
  const cutoff=n.qualification_context?.application_criterion_date||n.announcement_date
  return {...EMPTY_PROFILE,region:'경기도',regionCode:'41',district:'화성시',districtCode:'41590',
    movedInDate:'2010-01-01',districtMovedInDate:'2010-01-01',cityMovedInDate:'2010-01-01',
    dateOfBirth:'1990-01-01',applicantOnRegister:true,hasSpouse:false,maritalStatus:'single',
    householdMembers:[],householdMembersComplete:true,householdSnapshotDate:cutoff,
    ownershipFacts:[],ownershipFactsKnown:true,applicantOwnsHome:false,applicantPreviouslyOwnedHome:false,
    isHouseholdHead:true,citizenship:'korean',militaryCurrentlyServing:false,militaryFactsAsOfDate:cutoff,
    currentlyDomesticResident:true,domesticResidenceFactsAsOfDate:cutoff,providerEmployeeOrRelatedFamily:false,
    accountType:'comprehensive',privateRankBaseDate:'2010-01-01',nationalRankBaseDate:'2010-01-01',
    accountConversionUnclear:false,privateDepositKrw:'6000000',privateDepositAsOfDate:cutoff,
    privateDepositMaintained:true,nationalRecognizedPayments:'12',nationalPaymentsAsOfDate:cutoff,
    previousWinning:false,restrictedFromApplying:false,specialWinning:false,hasChildren:false,children:[],
    pregnant:false,taxYears:'5',employed:true,incomeTaxFactsAsOfDate:cutoff,incomeHouseholdSize:'1',
    monthlyIncomeKrw:'5000000',realEstateKrw:'0',...overrides}
}
function at(n,code,province,districtCode,district,start='2010-01-01') {
  return person(n,{regionCode:code,region:province,districtCode,district,movedInDate:start,districtMovedInDate:start,cityMovedInDate:start})
}
for(const key of ['chungjeong','goyang','tangjeong','jeju','cheonan']) {
 const n=notices[key], inv=officialOfferedSupplies(n)
 check(`${key}: official applicant scope includes a cutoff, source page and document hash`,!!meta(n,'applicant_regions')?.criterion_date&&!!meta(n,'applicant_regions')?.evidence_page&&meta(n,'applicant_regions')?.document_hash===n.document_hash)
 check(`${key}: only real positive supply-table combinations are returned`,inv.length>0&&inv.every(r=>r.supply_count>0&&r.document_hash===n.document_hash))
 check(`${key}: every personal assessment has source evidence for its comparison`,eligibilityCombinations(n,person(n)).every(c=>c.result.reasons.filter(r=>r.category==='condition').every(r=>!!r.evidenceUrl&&!!r.evidenceText)))
 snapshots[key]={applicationMethod:n.application_method,criterionDate:n.qualification_context?.application_criterion_date,
   supplyTypes:[...new Set(inv.map(r=>r.supply_type))],supplyCombinations:inv.length,priceCount:n.prices.length,
   outsideOutcome:regionDecision(n,person(n)).status}
}
const cj=notices.chungjeong
check('Chungjeong: Seoul admission has no invented local/other split',regionDecision(cj,at(cj,'11','서울특별시','11140','중구')).status==='not_divided')
check('Chungjeong: Hwaseong is outside Seoul',regionDecision(cj,person(cj)).status==='outside')
check('Chungjeong: this reception cutoff differs from the original project date',cj.qualification_context?.application_criterion_date==='2026-09-28'&&cj.qualification_context?.original_announcement_date==='2026-08-07')
check('Chungjeong: no apartment bank rank is requested',deriveRank(cj,EMPTY_PROFILE).rank==='not_applicable')
const gy=notices.goyang
check('Goyang: Il san district satisfies the parent city boundary',regionDecision(gy,at(gy,'41','경기도','41285','고양시 일산동구')).status==='not_divided')
check('Goyang: another Gyeonggi city does not satisfy city residence',regionDecision(gy,person(gy)).status==='outside')
check('Goyang: only general and elderly-parent types are assessed',snapshots.goyang.supplyTypes.join('|')==='노부모부양 특별공급|일반공급')
check('Goyang: an unknown military fact is not substituted into a nonmilitary exception',regionDecision(gy,person(gy,{militaryCurrentlyServing:null})).status==='outside')
const tg=notices.tangjeong, tp=at(tg,'44','충청남도','44200','아산시')
check('Tangjeong: no nonexistent general supply is diagnosed',snapshots.tangjeong.supplyTypes.length===1&&snapshots.tangjeong.supplyTypes[0]==='생애최초 특별공급'&&eligibilityCombinations(tg,tp).length===2)
check('Tangjeong: Asan satisfies its city-only applicant scope',regionDecision(tg,tp).status==='not_divided')
check('Tangjeong: Cheonan is not treated as all of Chungnam',regionDecision(tg,at(tg,'44','충청남도','44131','천안시 동남구')).status==='outside')
check('Tangjeong: current ten-year military exception grants admission',regionDecision(tg,person(tg,{militaryCurrentlyServing:true,militaryServiceYears:'10'})).status==='not_divided')
check('Tangjeong: nine years of military service does not grant admission',regionDecision(tg,person(tg,{militaryCurrentlyServing:true,militaryServiceYears:'9'})).status==='outside')
check('Tangjeong: missing military facts link to an actual question',regionDecision(tg,person(tg,{militaryCurrentlyServing:null})).reasons.some(r=>r.profileField==='militaryCurrentlyServing'))
const family=tg.rules.find(r=>r.kind==='first_home_family')
check('Tangjeong: single-person 59sqm route meets the exclusive area limit',evaluateRule(family,tp,tg,'059.9901A').status==='pass')
check('Tangjeong: single-person 74sqm route fails its own area limit',evaluateRule(family,tp,tg,'074.8177A').status==='fail')
const income=tg.rules.find(r=>r.label==='월평균소득 또는 부동산 기준')
check('Tangjeong: official income threshold and real-estate alternative are distinct',evaluateRule(income,{...tp,monthlyIncomeKrw:'99999999',realEstateKrw:'331000000'},tg).status==='pass')
check('Tangjeong: both income and real-estate above their limits fail',evaluateRule(income,{...tp,monthlyIncomeKrw:'99999999',realEstateKrw:'331000001'},tg).status==='fail')
const j=notices.jeju
check('Jeju: exact one-year residence anniversary has local priority',regionDecision(j,at(j,'50','제주특별자치도','50110','제주시','2025-10-02')).status==='local')
check('Jeju: one day short receives other-region allocation',regionDecision(j,at(j,'50','제주특별자치도','50110','제주시','2025-10-03')).status==='other')
check('Jeju: Seoul is outside the ordinary applicant scope',regionDecision(j,at(j,'11','서울특별시','11140','중구')).status==='outside')
check('Jeju: missing province move-in date asks that date',regionDecision(j,{...at(j,'50','제주특별자치도','50110','제주시'),movedInDate:''}).reasons.some(r=>r.profileField==='movedInDate'))
check('Jeju: a move after the cutoff asks historical address',regionDecision(j,at(j,'50','제주특별자치도','50110','제주시','2026-10-03')).reasons.some(r=>r.profileField==='residenceHistory'))
check('Jeju: verified six-month private bank requirements establish first rank',deriveRank(j,at(j,'50','제주특별자치도','50110','제주시')).rank==='first')
const c=notices.cheonan
check('Cheonan: a subordinate city district establishes city priority',regionDecision(c,at(c,'44','충청남도','44131','천안시 동남구')).status==='local')
for(const args of [['44','충청남도','44200','아산시'],['30','대전광역시','30110','동구'],['36','세종특별자치시','36110','세종시']]) check(`Cheonan: ${args[1]} resident outside Cheonan has other-region admission`,regionDecision(c,at(c,...args)).status==='other')
check('Cheonan: Hwaseong is outside the specified three provinces',regionDecision(c,person(c)).status==='outside')
check('Cheonan: current second-round cutoff is used',c.qualification_context?.application_criterion_date==='2026-10-02')
check('Cheonan: verified private bank rank is separate from outside-region rejection',deriveRank(c,person(c)).rank==='first'&&evaluateEligibility(c,person(c),undefined,'일반공급').status==='mismatch')
for(const key of ['yeongcheon','gyeongsan','wonju']) {
 const n=notices[key],cutoff=key==='gyeongsan'?'2026-10-27':n.announcement_date
 const p=person(n,{applicantOwnsHome:true,intendedContractDate:cutoff,domesticResidenceFactsAsOfDate:cutoff})
 const outcome=evaluateEligibility(n,p,undefined,'일반공급')
 check(`${key}: official homeowner permission produces actual application possibility`,outcome.status==='possible')
 check(`${key}: no national bank rank is invented for the provider`,deriveRank(n,p).rank==='not_applicable')
 check(`${key}: full admission completion is backed by reviewed mandatory topics`,meta(n,'condition_coverage').scopes.every(s=>s.complete))
 snapshots[key]={rank:deriveRank(n,p).rank,eligibility:outcome.status,criterionBasis:n.qualification_context?.application_criterion_basis}
}
const gs=notices.gyeongsan
check('Gyeongsan: contract-date criteria ask for the actual date instead of using the announcement',evaluateEligibility(gs,person(gs)).reasons.some(r=>r.profileField==='intendedContractDate'))
const w=notices.wonju
check('Wonju: potential employee restriction remains a specific source review',evaluateEligibility(w,person(w,{providerEmployeeOrRelatedFamily:true}),undefined,'일반공급').reasons.some(r=>r.category==='source_gap'&&r.label==='공급기관 임직원 매입 심사'))
const a=notices.a17,al=notices.a17_lh
check('A17: LH and Applyhome use the same current official document',a.document_hash===al.document_hash)
check('A17: both feeds expose the same three genuine family routes',JSON.stringify(meta(a,'offered_supplies').supplies)===JSON.stringify(meta(al,'offered_supplies').supplies)&&!officialOfferedSupplies(a).some(r=>r.supply_type==='일반공급'))
check('A17: no ordinary first-rank requirement is substituted for special account requirements',deriveRank(a,person(a)).rank==='not_applicable')
const period=a.rules.find(r=>r.kind==='subscription_months'),payments=a.rules.find(r=>r.kind==='recognized_payments_min')
check('A17: six months and six recognized payments are independently compared',period.value===6&&payments.value===6&&evaluateRule(period,person(a),a).status==='pass'&&evaluateRule(payments,person(a,{nationalRecognizedPayments:'6'}),a).status==='pass')
check('A17: five payments fail the actual special account condition',evaluateRule(payments,person(a,{nationalRecognizedPayments:'5'}),a).status==='fail')
const ai=a.rules.find(r=>r.kind==='shinhee_income'),aa=a.rules.find(r=>r.kind==='shinhee_assets')
check('A17: base income does not require irrelevant childbirth information',evaluateRule(ai,person(a,{monthlyIncomeKrw:'9000000',hasChildren:null,pregnant:null}),a).status==='pass')
check('A17: 200 percent dual-income admission is not confused with selection priority',ai.dual_income_percent===200&&evaluateRule(ai,person(a,{dualIncome:true,monthlyIncomeKrw:'14000000'}),a).status==='pass')
check('A17: an annual amount cannot replace legal monthly income',evaluateRule(ai,person(a,{monthlyIncomeKrw:'',annualIncomeKrw:'100000'}),a).profileField==='monthlyIncomeKrw')
check('A17: total assets cannot replace net assets after recognized debt',evaluateRule(aa,person(a,{assetsKrw:'100000',officialNetAssetsKrw:''}),a).profileField==='officialNetAssetsKrw')
const kid=(birth)=>({id:birth,dateOfBirth:birth,adopted:false})
check('A17: one recent child relaxes net assets to 397 million',evaluateRule(aa,person(a,{officialNetAssetsKrw:'397000000',hasChildren:true,children:[kid('2025-01-01')]}),a).status==='pass')
check('A17: a recent child and older child relax net assets to 431 million',evaluateRule(aa,person(a,{officialNetAssetsKrw:'431000000',hasChildren:true,children:[kid('2025-01-01'),kid('2020-01-01')]}),a).status==='pass')
check('A17: without recent childbirth the higher net assets fail',evaluateRule(aa,person(a,{officialNetAssetsKrw:'397000000'}),a).status==='fail')
const sp=notices.suwon
check('Suwon A3: waived account rules are not replaced with A17 six-month requirements',!sp.rules.some(r=>r.kind==='subscription_months'||r.kind==='recognized_payments_min')&&deriveRank(sp,person(sp)).rank==='not_applicable')
check('Suwon A3: the public project restriction asks its own household lookup',evaluateEligibility(sp,person(sp),undefined,'신혼부부(신혼희망타운)').reasons.some(r=>r.profileField==='projectApplicationHistory'))
const untouched=JSON.stringify(EMPTY_PROFILE)
for(const n of Object.values(notices)) {regionDecision(n,EMPTY_PROFILE);evaluateEligibility(n,EMPTY_PROFILE)}
check('Public comparisons do not mutate local profile input',JSON.stringify(EMPTY_PROFILE)===untouched)
console.log(JSON.stringify({checks,snapshots}))
"""

if __name__ == "__main__":
    if "--output" not in sys.argv:
        sys.argv += ["--output", str(ROOT / "docs/qa/v5-live-engine-2026-10-05.json")]
    sys.exit(qa.main())
