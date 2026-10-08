import { describe, it, expect } from 'vitest'
import { EMPTY_PROFILE, type Notice, type NoticeRule, createOwnershipFact } from './types'
const unchangedFacts = { bank_private: { mode: 'never_changed' as const, date: '' }, bank_national: { mode: 'never_changed' as const, date: '' }, children: { mode: 'never_changed' as const, date: '' }, military: { mode: 'never_changed' as const, date: '' } }
import { applicantRegionEligibility, deriveRank, evaluateQualification, unitRankResults, exclusiveArea, evaluateRule } from './qualification'
const source = 'https://www.applyhome.co.kr/official'
const rule = (kind: string, value: NoticeRule['value'], extra: Partial<NoticeRule> = {}): NoticeRule => ({ kind, value, verification: 'official', evidence_url: source, ...extra })
const notice = (extra: Partial<Notice> = {}): Notice => ({ id:'v3', title:'공식 사례', category:'apt', housing_kind:'private', housing_kind_evidence:{verification:'official'}, source:'cheongyak_home',provider:'사업자',address:null,region_code:'27',region_name:'대구광역시',announcement_date:'2026-10-02',official_url:source,price_cap_status:'no',events:[],prices:[],rules:[],updated_at:null,version:1,...extra })
const rankRules = [rule('private_rank_months',6,{purpose:'first_rank'}),rule('deposit_min_krw',2000000,{purpose:'first_rank'}),rule('account_type','comprehensive',{purpose:'first_rank'}),rule('rank_requirements',null,{effect:'metadata',complete:true,required_kinds:['private_rank_months','deposit_min_krw','account_type'],criterion_date:'2026-10-02'})]
const facts = {...EMPTY_PROFILE, factChanges: unchangedFacts,accountType:'comprehensive' as const,privateRankBaseDate:'2025-01-01',privateDepositKrw:'3000000',accountConversionUnclear:false}
describe('v3 official rank coverage',()=>{
  it('confirmsfirst despitewholeeligibilitypartial and unknownglobal restriction',()=>{
    expect(deriveRank(notice({rules:rankRules,rules_complete:false}),facts)).toMatchObject({rank:'first',label:'민영주택 1순위 조건 충족'})
  })
  it('unknownkind producesonecollectionnotice withoutanimaginedrankdatequestion',()=>{
    const result=deriveRank(notice({housing_kind:'unknown'}),facts)
    expect(result.reasons).toHaveLength(1)
    expect(result.reasons.some(r=>r.category==='missing_input'||r.profileField)).toBe(false)
  })
  it('official notapplicable skipsallaccountfacts evenwitholdprivateclassification',()=>{
    const result=deriveRank(notice({rank_applicability:{status:'not_applicable',account_required:false,verification:'official',reason:'오피스텔 청약통장 불필요'}}),EMPTY_PROFILE)
    expect(result.rank).toBe('not_applicable')
    expect(result.reasons).toHaveLength(1)
    expect(result.reasons[0].requirement).toBe('청약통장 불필요')
  })
  it('doesnottrustAIapplicabilityorpartial requiredkinds',()=>{
    expect(deriveRank(notice({rank_applicability:{status:'not_applicable',account_required:false,verification:'ai_unverified'}}),EMPTY_PROFILE).rank).toBe('unknown')
    expect(deriveRank(notice({rules:rankRules.filter(r=>r.kind!=='account_type')}),facts).rank).toBe('unknown')
  })
  it('comparesamountasof officialcutoff without treatingnewbalanceashistoricalbalance',()=>{
    const rules=rankRules.map(r=>r.kind==='deposit_min_krw'?{...r,require_as_of_date:true}:r)
    expect(deriveRank(notice({rules}),{...facts,factChanges:{}}).reasons.find(r=>r.profileField==='privateDepositAsOfDate')).toBeTruthy()
    expect(deriveRank(notice({rules}),{...facts,factChanges:{},privateDepositAsOfDate:'2026-10-03'}).rank).toBe('unknown')
    expect(deriveRank(notice({rules}),{...facts,factChanges:{},privateDepositAsOfDate:'2026-10-02'}).rank).toBe('first')
    expect(deriveRank(notice({rules}),{...facts,factChanges:{},privateDepositAsOfDate:'2026-10-01'}).reasons.find(r=>r.profileField==='privateDepositAsOfDate')).toBeTruthy()
    expect(deriveRank(notice({rules}),{...facts,factChanges:{},privateDepositAsOfDate:'2026-10-01',privateDepositMaintained:false}).rank).toBe('unknown')
    expect(deriveRank(notice({rules}),{...facts,factChanges:{},privateDepositAsOfDate:'2026-10-01',privateDepositMaintained:true}).rank).toBe('first')
  })
  it('comparesunitdeposit requirements independently',()=>{
    const rules=[...rankRules.filter(r=>r.kind!=='deposit_min_krw'),rule('deposit_min_krw',2000000,{purpose:'first_rank',unit_type:'59A'}),rule('deposit_min_krw',5000000,{purpose:'first_rank',unit_type:'135A'})]
    const item=notice({rules,prices:[{unit_type:'59A',area_sqm:59,price_kind:'sale'},{unit_type:'135A',area_sqm:135,price_kind:'sale'}]})
    expect(deriveRank(item,facts).rank).toBe('unknown')
    expect(unitRankResults(item,facts).map(r=>[r.unitType,r.result.rank,r.result.status])).toEqual([['59A','first','possible'],['135A','unknown','mismatch']])
  })
  it('uses verified exclusive area rather than supply area to selectdepositandinstallment thresholds',()=>{
    const item = notice({prices:[{unit_type:'084.2551A',price_kind:'sale',area_sqm:115.374,exclusive_area_sqm:84.2551,area_basis:'supply'}]})
    expect(exclusiveArea(item.prices[0])).toBe(84.2551)
    const deposit=rule('deposit_min_krw',null,{deposit_table:[{max_area_sqm:85,amounts_krw:{seoul_busan:3000000,other_metropolitan:2500000,other:2000000}},{max_area_sqm:null,amounts_krw:{seoul_busan:15000000,other_metropolitan:10000000,other:5000000}}]})
    const person={...facts,region:'경기도',regionCode:'41',movedInDate:'2020-01-01',privateDepositKrw:'2000000'}
    expect(evaluateRule(deposit,person,item,'084.2551A')).toMatchObject({status:'pass'})
    const account=rule('account_type',null,{allowed_values:['installment'],area_limit_for_installment:85})
    expect(evaluateRule(account,{...person,accountType:'installment'},item,'084.2551A').status).toBe('pass')
    const unverifiedArea=notice({prices:[{unit_type:'084.2551A',price_kind:'sale',area_sqm:115.374,area_basis:'supply'}]})
    expect(evaluateRule(deposit,person,unverifiedArea,'084.2551A').status).toBe('review')
    expect(evaluateRule(account,{...person,accountType:'installment'},unverifiedArea,'084.2551A').status).toBe('review')
  })
  it('does not reuse a post-cutoff current province for a cheaper deposit-table threshold',()=>{
    const deposit = rule('deposit_min_krw',null,{purpose:'first_rank',deposit_table:[{max_area_sqm:85,amounts_krw:{seoul_busan:3000000,other_metropolitan:2500000,other:2000000}},{max_area_sqm:null,amounts_krw:{seoul_busan:15000000,other_metropolitan:10000000,other:5000000}}]})
    const item = notice({rules:[...rankRules.filter(r=>r.kind!=='deposit_min_krw'),deposit],prices:[{unit_type:'59A',price_kind:'sale',exclusive_area_sqm:59}]})
    const person = {...facts,region:'경기도',regionCode:'41',privateDepositKrw:'2000000',movedInDate:'2026-10-03'}
    const historical = evaluateRule(deposit,person,item,'59A')
    expect(historical).toMatchObject({status:'review',label:'민영주택 예치금 거주지역',criterionDate:'2026-10-02'})
    expect(historical.detail).toContain('저장된 당시 주소가 없어')
    expect(historical.profileField).toBeUndefined()
    expect(deriveRank(item,person,'59A').rank).toBe('unknown')
    expect(deriveRank(item,{...person,movedInDate:'2026-10-02'},'59A').rank).toBe('first')
    expect(evaluateRule(deposit,{...person,region:'서울특별시',regionCode:'11',movedInDate:'2020-01-01'},item,'59A').status).toBe('fail')
    // A fixed official amount has no regional table to infer from an address.
    expect(deriveRank(notice({rules:rankRules}),person).rank).toBe('first')
  })
  it('requests only the province date needed by a deposit table and rejects unresolved geography',()=>{
    const deposit = rule('deposit_min_krw',null,{deposit_table:[{max_area_sqm:null,amounts_krw:{seoul_busan:3000000,other_metropolitan:2500000,other:2000000}}]})
    const item = notice({prices:[{unit_type:'59A',price_kind:'sale',exclusive_area_sqm:59}]})
    const person = {...facts,region:'경기도',regionCode:'41'}
    for (const movedInDate of ['','2026-02-30']) {
      expect(evaluateRule(deposit,{...person,movedInDate},item,'59A')).toMatchObject({status:'review',category:'missing_input',profileField:'movedInDate'})
    }
    expect(evaluateRule(deposit,{...person,movedInDate:'2020-01-01',districtMovedInDate:''},item,'59A').status).toBe('pass')
    expect(evaluateRule(deposit,{...person,region:'해외',movedInDate:'2020-01-01'},item,'59A').status).toBe('review')
  })
})
describe('official regional eligibility includingmilitaryfacts',()=>{
  const regionRule=rule('applicant_regions',null,{effect:'metadata',regions:[{region_code:'27',region_name:'대구광역시'},{region_code:'47',region_name:'경상북도'}],exceptions:[{kind:'military_service_years',min_years:10}]})
  const item=notice({rules:[regionRule]})
  const home={...EMPTY_PROFILE, factChanges: unchangedFacts,region:'경기도',regionCode:'41',district:'화성시',districtCode:'41590',movedInDate:'2020-01-01'}
  it('doesnotcall Hwaseonganordinaryotherregioncandidate',()=>{
    expect(applicantRegionEligibility(item,{...home,militaryFactsAsOfDate:'2026-10-02',militaryCurrentlyServing:false})).toMatchObject({status:'fail',requirement:'대구광역시 · 경상북도'})
    expect(applicantRegionEligibility(item,home)).toMatchObject({status:'review',profileField:'militaryCurrentlyServing'})
  })
  it('admits verifiedserviceexceptiononlywhenfactsmeetactualminimum',()=>{
    expect(applicantRegionEligibility(item,{...home,militaryFactsAsOfDate:'2026-10-02',militaryCurrentlyServing:true,militaryServiceYears:'10'})?.status).toBe('pass')
    expect(applicantRegionEligibility(item,{...home,militaryFactsAsOfDate:'2026-10-02',militaryCurrentlyServing:true,militaryServiceYears:'9'})?.status).toBe('fail')
    expect(applicantRegionEligibility(item,{...home,militaryFactsAsOfDate:'2026-10-02',militaryCurrentlyServing:true})?.profileField).toBe('militaryServiceYears')
  })
  it('admitsactualscope withoutaskingformilitaryfacts',()=>{
    expect(applicantRegionEligibility(item,{...home,region:'대구광역시',regionCode:'27',district:'중구',districtCode:'27110'})?.status).toBe('pass')
  })
})
describe('official residence scope at the announcement cutoff',()=>{
  const daegu = { ...EMPTY_PROFILE, factChanges: unchangedFacts, region:'대구광역시', regionCode:'27', district:'중구', districtCode:'27110', movedInDate:'2026-10-03' }
  const suwon = { ...EMPTY_PROFILE, factChanges: unchangedFacts, region:'경기도', regionCode:'41', district:'수원시 영통구', districtCode:'41117', movedInDate:'2020-01-01', cityMovedInDate:'2020-01-01', districtMovedInDate:'2026-10-03' }
  const applicant = (regions: {region_code:string;region_name:string}[], extra: Partial<NoticeRule> = {}) => rule('applicant_regions',null,{effect:'metadata',regions,...extra})
  const daeguScope = {region_code:'27',region_name:'대구광역시'}
  const provinceScope = {region_code:'41',region_name:'경기도'}
  const cityScope = {region_code:'41110',region_name:'경기도 수원시'}
  const districtScope = {region_code:'41117',region_name:'경기도 수원시 영통구'}
  it('reviews both moves into and out of the applicant region after the cutoff',()=>{
    const item = notice({rules:[applicant([daeguScope])]})
    for (const person of [daegu,{...suwon,movedInDate:'2026-10-03'}]) {
      const result = applicantRegionEligibility(item,person)
      expect(result).toMatchObject({status:'review',label:'공고 기준일 거주지역',criterionDate:'2026-10-02',requirement:'대구광역시'})
      expect(result?.detail).toContain('저장된 당시 주소가 없어')
      expect(result?.detail).toContain('2026-10-03')
      expect(result?.profileField).toBeUndefined()
      expect(result?.category).toBe('past_fact')
    }
    expect(applicantRegionEligibility(item,{...daegu,movedInDate:'2026-10-02'})?.status).toBe('pass')
  })
  it.each(['residence_region','residence_area','region','residence_months'])('reviews %s before using a post-cutoff current address for pass or fail',(kind)=>{
    const requirement = rule(kind,kind==='residence_months'?1:null,{...daeguScope})
    for (const person of [daegu,{...suwon,movedInDate:'2026-10-03'}]) {
      expect(evaluateRule(requirement,person,notice())).toMatchObject({status:'review',label:'공고 기준일 거주지역',criterionDate:'2026-10-02'})
    }
  })
  it('uses only the required province or parent city clock despite a later child-district move',()=>{
    for (const scope of [provinceScope,cityScope]) {
      expect(applicantRegionEligibility(notice({rules:[applicant([scope])]}),suwon)?.status).toBe('pass')
      expect(evaluateRule(rule('residence_region',null,scope),suwon,notice()).status).toBe('pass')
    }
    expect(applicantRegionEligibility(notice({rules:[applicant([districtScope])]}),suwon)?.status).toBe('review')
    expect(evaluateRule(rule('residence_region',null,districtScope),suwon,notice()).status).toBe('review')
    expect(applicantRegionEligibility(notice({rules:[applicant([districtScope,provinceScope])]}),suwon)?.status).toBe('pass')
    const alternatives = rule('any',null,{conditions:[rule('residence_region',null,districtScope),rule('residence_region',null,provinceScope)]})
    expect(evaluateRule(alternatives,suwon,notice()).status).toBe('pass')
  })
  it('preserves an exclusion established by a stable broader province or parent city',()=>{
    for (const scope of [{region_code:'27110',region_name:'대구광역시 중구'},{region_code:'41130',region_name:'경기도 성남시'}]) {
      expect(applicantRegionEligibility(notice({rules:[applicant([scope])]}),suwon)?.status).toBe('fail')
      expect(evaluateRule(rule('residence_region',null,scope),suwon,notice()).status).toBe('fail')
    }
  })
  it.each([
    {scope:provinceScope,field:'movedInDate' as const},
    {scope:cityScope,field:'cityMovedInDate' as const},
    {scope:districtScope,field:'districtMovedInDate' as const},
  ])('asks only for the absent or invalid date of the required scope: $field',({scope,field})=>{
    for (const value of ['','2026-02-30']) {
      const person = {...suwon,districtMovedInDate:'2020-01-01',[field]:value}
      expect(applicantRegionEligibility(notice({rules:[applicant([scope])]}),person)).toMatchObject({status:'review',category:'missing_input',profileField:field})
      expect(evaluateRule(rule('residence_region',null,scope),person,notice())).toMatchObject({status:'review',category:'missing_input',profileField:field})
    }
  })
  it('skips missing child dates for established broader matches and exclusions',()=>{
    const person = {...suwon,districtMovedInDate:''}
    for (const scope of [provinceScope,cityScope]) {
      expect(applicantRegionEligibility(notice({rules:[applicant([scope])]}),person)?.status).toBe('pass')
    }
    for (const scope of [{region_code:'27110',region_name:'대구광역시 중구'},{region_code:'41130',region_name:'경기도 성남시'}]) {
      expect(applicantRegionEligibility(notice({rules:[applicant([scope])]}),person)?.status).toBe('fail')
    }
    const militaryItem = notice({rules:[applicant([daeguScope],{exceptions:[{kind:'military_service_years',min_years:10}]})]})
    expect(applicantRegionEligibility(militaryItem,{...person,movedInDate:'',militaryFactsAsOfDate:'2026-10-02',militaryCurrentlyServing:true,militaryServiceYears:'10'})?.status).toBe('pass')
  })
  it('uses the narrower municipality name when the code identifies only the province',()=>{
    const coarseScope = {...provinceScope,region_name:'경기도 수원시'}
    const person = {...suwon,cityMovedInDate:'2026-10-03',districtMovedInDate:'2020-01-01'}
    expect(applicantRegionEligibility(notice({rules:[applicant([coarseScope])]}),person)?.status).toBe('review')
    expect(evaluateRule(rule('residence_region',null,coarseScope),person,notice()).status).toBe('review')
    expect(evaluateRule(rule('residence_region',null,districtScope),{...suwon,movedInDate:'2026-10-03',districtMovedInDate:'2020-01-01'},notice()).status).toBe('review')
  })
  it.each([{...cityScope,region_name:districtScope.region_name},{...districtScope,region_name:cityScope.region_name}])('uses the child district clock when either official identifier narrows a parent city: %j',(scope)=>{
    expect(applicantRegionEligibility(notice({rules:[applicant([scope])]}),suwon)?.status).toBe('review')
    expect(evaluateRule(rule('residence_region',null,scope),suwon,notice()).status).toBe('review')
    expect(evaluateRule(rule('residence_months',12,scope),{...suwon,districtMovedInDate:'2026-05-01'},notice()).status).toBe('fail')
    expect(evaluateRule(rule('residence_months',12,scope),{...suwon,districtMovedInDate:''},notice())).toMatchObject({status:'review',category:'missing_input',profileField:'districtMovedInDate'})
  })
  it('uses the original or explicit criterion date and admits a move on that date',()=>{
    const item = notice({announcement_date:'2026-10-04',qualification_context:{public_housing:false,speculation_zone:false,subscription_overheated:false,weakened_area:false,capital_region:false,original_announcement_date:'2026-10-02'},rules:[applicant([daeguScope])]})
    expect(applicantRegionEligibility(item,daegu)).toMatchObject({status:'review',criterionDate:'2026-10-02'})
    expect(evaluateRule(rule('residence_region',null,daeguScope),daegu,item).status).toBe('review')
    const explicit = {criterion_date:'2026-10-03'}
    expect(applicantRegionEligibility({...item,rules:[applicant([daeguScope],explicit)]},daegu)?.status).toBe('pass')
    expect(evaluateRule(rule('residence_region',null,{...daeguScope,...explicit}),daegu,item).status).toBe('pass')
  })
  it('retains the independent military exception without inventing an outside-region history',()=>{
    const item = notice({rules:[applicant([daeguScope],{exceptions:[{kind:'military_service_years',min_years:10}]})]})
    expect(applicantRegionEligibility(item,{...suwon,movedInDate:'2026-10-03',militaryFactsAsOfDate:'2026-10-02',militaryCurrentlyServing:true,militaryServiceYears:'10'})).toMatchObject({status:'pass',label:'장기복무군인 신청 지역 예외'})
    expect(applicantRegionEligibility(item,{...suwon,movedInDate:'2026-10-03',militaryFactsAsOfDate:'2026-10-02',militaryCurrentlyServing:false})?.status).toBe('review')
  })
  it('keeps private rank independent from the historical regional review',()=>{
    const item = notice({rules:[...rankRules,applicant([daeguScope]),rule('household_min',1)],rules_complete:true})
    const person = {...facts,...daegu,accountType:facts.accountType,privateRankBaseDate:facts.privateRankBaseDate,privateDepositKrw:facts.privateDepositKrw,accountConversionUnclear:false,householdSize:'1'}
    expect(evaluateQualification(item,person).status).toBe('review')
    expect(deriveRank(item,person)).toMatchObject({rank:'first',status:'possible'})
  })
  it('shows official applicant-region mismatch for general supply when the remaining conditions are missing',()=>{
    const item = notice({rules:[...rankRules,applicant([daeguScope]),rule('household_min',1,{supply_type:'신혼부부 특별공급'})]})
    const person = {...facts,region:suwon.region,regionCode:suwon.regionCode,district:suwon.district,districtCode:suwon.districtCode,movedInDate:suwon.movedInDate,militaryFactsAsOfDate:'2026-10-02',militaryCurrentlyServing:false}
    const general = evaluateQualification(item,person,undefined,'일반공급')
    expect(general.status).toBe('mismatch')
    expect(general.reasons).toEqual(expect.arrayContaining([expect.objectContaining({status:'fail',label:'신청 가능한 지역'}),expect.objectContaining({status:'review',category:'source_gap',label:'공고 조건 정리 중'})]))
    expect(deriveRank(item,person).rank).toBe('first')
    const admitted = evaluateQualification(item,{...person,region:daegu.region,regionCode:daegu.regionCode,district:daegu.district,districtCode:daegu.districtCode},undefined,'일반공급')
    expect(admitted.status).toBe('review')
    expect(admitted.reasons).toEqual(expect.arrayContaining([expect.objectContaining({status:'pass',label:'신청 가능한 지역'}),expect.objectContaining({status:'review',category:'source_gap'})]))
  })
  it('does not admit unknown, foreign or unresolved current regions',()=>{
    const item = notice({rules:[applicant([provinceScope])]})
    for (const person of [EMPTY_PROFILE,{...suwon,region:'해외',regionCode:'99'},{...suwon,regionNeedsReview:true}]) {
      expect(applicantRegionEligibility(item,person)?.status).toBe('review')
      expect(evaluateRule(rule('residence_region',null,provinceScope),person,item).status).toBe('review')
    }
  })
  it('does not certify region eligibility when the official comparison date is unavailable',()=>{
    const item = notice({announcement_date:null,rules:[applicant([provinceScope])]})
    expect(applicantRegionEligibility(item,suwon)).toMatchObject({status:'review',category:'source_gap'})
    expect(evaluateRule(rule('residence_region',null,provinceScope),suwon,item)).toMatchObject({status:'review',category:'source_gap'})
  })
})
describe('sharedhomelesscondition honorstheselectedsupply',()=>{
  it('appliesancestor exceptiontogeneralbutnotelderparentsupply',()=>{
    const item=notice({rules:[rule('homeless',true)],rules_complete:true})
    const home={...EMPTY_PROFILE, factChanges: unchangedFacts,applicantOnRegister:true,hasSpouse:false,householdMembersComplete:true,householdSnapshotDate:'2026-10-02',householdMembers:[{id:'parent',relation:'applicant_parent' as const,register:'applicant' as const,dateOfBirth:'1960-01-01',ownsHome:true,previouslyOwnedHome:null}],applicantOwnsHome:false,familyOwnsHome:true,ownershipFactsKnown:true,ownershipFacts:[{...createOwnershipFact('parent'),ownerMemberId:'parent',ownerRelation:'ascendant' as const,ownerDateOfBirth:'1960-01-01',propertyKind:'apartment' as const,areaSqm:'84',propertyRegionCode:'41',acquiredDate:'2020-01-01',acquisitionMethod:'purchase' as const,abandonedOrDestroyedOrNonResidential:false,oldLawUnauthorized:false}]}
    expect(evaluateQualification(item,home,undefined,'일반공급').reasons.find(r=>r.label==='무주택 세대구성원')?.status).toBe('pass')
    expect(evaluateQualification(item,home,undefined,'노부모부양 특별공급').reasons.find(r=>r.label==='무주택 세대구성원')?.status).toBe('fail')
  })
})
