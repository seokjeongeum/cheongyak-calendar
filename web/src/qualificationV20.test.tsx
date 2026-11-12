import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { conditionCoverage, deriveRank, evaluateQualification, evaluateRule, specialType } from './qualification'
import { setEvaluationToday } from './factTimeline'
import { migrateProfile } from './profile'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'
import { EligibilityDetails, ReasonList } from './EligibilityDetails'
import { getProfileQuestionModel, needsSameSpouseMarriageFacts } from './profileQuestionModel'

const today = '2026-11-09', cutoff = '2026-10-30', hash = 'a'.repeat(64)
const url = 'https://apply.lh.or.kr/lhapply/lhFile.do?fileid=69224266'
const married = '신혼부부(신혼희망타운)', engaged = '예비신혼부부(신혼희망타운)', parent = '한부모가족(신혼희망타운)'
const rule = (kind: string, extra: Partial<NoticeRule> = {}): NoticeRule => ({ id: kind, kind, verification: 'official', criterion_date: cutoff, evidence_page: 7, evidence_url: url, document_hash: hash, evidence_text: '공식 신청자격 원문', ...extra })
const profile = (extra: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, maritalStatus: 'single', plannedMarriage: false, hasChildren: false, pregnant: false, children: [], dateOfBirth: '1993-01-01', currentlyDomesticResident: true, citizenship: 'korean',
  factChanges: Object.fromEntries(['marital','children','pregnancy','domestic_residence','citizenship','bank_private','bank_national'].map(group => [group, { mode: 'never_changed', date: '' }])) as LocalProfile['factChanges'], ...extra })
function notice(admission: NoticeRule[], supply = '일반공급', scopeExtra: Record<string, unknown> = {}, extra: Partial<Notice> = {}): Notice {
  const conditions = admission.map(r => ({ ...r, supply_type: supply }))
  const review = { supply_type: supply, complete: true, review_version: 'generic-admission-2026-10-12-public-v1', reviewed_document_hash: hash, reviewed_pages: [1,7], completion_basis: 'current_document_clause_coverage', verified_rule_count: conditions.length,
    topics: conditions.map(r => ({ topic: r.kind, required: true, status: 'verified', rule_ids: [r.id] })), missing_topics: [], source_gaps: [], branches: [{ branch_id: 'current', required: true, status: 'verified', rule_ids: conditions.map(r => r.id) }], ...scopeExtra }
  return { id:'A2', title:'인천가정2 A-2', category:'public_sale', source:'lh', provider:'LH', address:null, region_code:null, region_name:null, announcement_date:cutoff, official_url:url, document_hash:hash, price_cap_status:'yes', events:[], prices:[], updated_at:null, version:1,
    rank_applicability:{status:'not_applicable', account_required:false, verification:'official'},
    rules:[...conditions, rule('condition_coverage',{effect:'metadata',status:'complete',scopes:[review]})], ...extra }
}
beforeEach(() => setEvaluationToday(today))
afterEach(() => setEvaluationToday(null))

describe('current residual-family routes', () => {
  it('classifies the actual family name before the Shinhee suffix', () => {
    expect(specialType(married)).toBe('newlywed')
    expect(specialType(engaged)).toBe('engaged')
    expect(specialType(parent)).toBe('single_parent')
  })
  it('compares no marriage plan as mismatch without asking future-household facts', () => {
    const item=notice([rule('planned_marriage',{value:true}),rule('planned_household_homeless',{value:true}),rule('planned_marriage_not_former_spouse',{value:true})],engaged)
    const result=evaluateQualification(item,profile(),undefined,engaged)
    expect(result.status).toBe('mismatch')
    expect(result.reasons.some(r => ['missing_input','past_fact'].includes(r.category || ''))).toBe(false)
    expect(result.reasons.some(r => r.detail.includes('혼인 기간') || r.label==='미확보 유형별 요건')).toBe(false)
  })
  it('does not use current registered family facts for an unknown future household', () => {
    const item=notice([rule('planned_marriage',{value:true}),rule('planned_household_homeless',{value:true})],engaged)
    const facts=profile({plannedMarriage:true,applicantOwnsHome:false,spouseOwnsHome:false,householdMembersComplete:true})
    const result=evaluateQualification(item,facts,undefined,engaged)
    expect(result.status).toBe('review')
    expect(result.reasons.find(r=>r.ruleId==='planned_household_homeless')).toMatchObject({category:'missing_input',profileField:'plannedHouseholdHomelessConfirmed'})
  })
  it('compares the confirmed planned household and former spouse prohibition separately', () => {
    const item=notice([rule('planned_marriage',{value:true}),rule('planned_household_homeless',{value:true}),rule('planned_marriage_not_former_spouse',{value:true})],engaged)
    const facts=profile({plannedMarriage:true,plannedHouseholdHomelessConfirmed:true,plannedPartnerIsFormerSpouse:false})
    expect(evaluateQualification(item,facts,undefined,engaged).status).toBe('possible')
    expect(evaluateQualification(item,{...facts,plannedPartnerIsFormerSpouse:true},undefined,engaged).status).toBe('mismatch')
    expect(evaluateQualification(item,{...facts,plannedHouseholdHomelessConfirmed:false},undefined,engaged).status).toBe('mismatch')
  })
  it('compares zero recognised children for a single parent without a marriage-period requirement', () => {
    const item=notice([rule('single_parent_family',{value:true}),rule('children_min',{value:1,child_age_max:7,child_age_inclusive:false,include_pregnancy:true})],parent)
    const result=evaluateQualification(item,profile(),undefined,parent)
    expect(result.status).toBe('mismatch')
    expect(result.reasons.some(r=>r.category==='missing_input'||r.category==='past_fact')).toBe(false)
    expect(result.reasons.some(r=>r.label==='미확보 유형별 요건'||r.detail.includes('혼인 기간 원문'))).toBe(false)
  })
  it('keeps a never-married applicant out of the married route without asking a marriage date', () => {
    const item=notice([rule('marital_status',{allowed_values:['married']}),rule('marriage_months_max',{value:84})],married)
    const result=evaluateQualification(item,profile(),undefined,married)
    expect(result.status).toBe('mismatch')
    expect(result.reasons.some(r=>r.profileField==='marriageDate')).toBe(false)
  })
  it('sums previous marriage months only for an explicit same-spouse rule', () => {
    const item=notice([]), condition=rule('marriage_months_max',{value:84,anniversary_limit:true,sum_same_spouse_remarriage:true})
    const facts=profile({maritalStatus:'married',marriageDate:'2025-10-30',sameSpouseRemarriage:true,priorSameSpouseMarriageMonths:'80'})
    expect(evaluateRule(condition,facts,item).status).toBe('fail')
    expect(evaluateRule(condition,{...facts,sameSpouseRemarriage:false},item).status).toBe('pass')
    expect(evaluateRule(condition,{...facts,sameSpouseRemarriage:null},item)).toMatchObject({category:'missing_input',profileField:'sameSpouseRemarriage'})
  })
  it('does not ask marriage-duration history when the child alternative already passes', () => {
    const family=rule('all',{conditions:[rule('marital_status',{allowed_values:['married']}),rule('any',{conditions:[rule('marriage_months_max',{value:84,sum_same_spouse_remarriage:true}),rule('children_min',{value:1,child_age_max:7,child_age_inclusive:false,include_pregnancy:true})]})]})
    const item=notice([family],married)
    const facts=profile({maritalStatus:'married',marriageDate:'2010-01-01',hasChildren:true,children:[{dateOfBirth:'2024-01-01',adopted:false,adoptionDate:''}],sameSpouseRemarriage:null})
    expect(evaluateQualification(item,facts,undefined,married).status).toBe('possible')
    expect(needsSameSpouseMarriageFacts(facts,getProfileQuestionModel([item],today))).toBe(false)
  })
})

describe('partial source review and rank items', () => {
  const domestic=rule('domestic_residence',{value:true})
  it('accepts an intact partial record while retaining its actual unresolved clause', () => {
    const item=notice([domestic],'일반공급',{complete:false,completion_basis:null,missing_topics:['해외 체류 예외'],source_gaps:[{item:'해외 체류 예외',stage:'clause_extraction'}],topics:[{topic:'domestic',status:'verified',required:true,rule_ids:[domestic.id]},{topic:'해외 체류 예외',status:'missing',required:true,rule_ids:[]}]})
    const coverage=conditionCoverage(item,undefined,'일반공급')
    expect(coverage.complete).toBe(false)
    expect(coverage.missingTopics).toContain('해외 체류 예외')
    expect(coverage.missingTopics.some(t=>t.includes('해시 기록 미확보'))).toBe(false)
    expect(evaluateQualification(item,profile(),undefined,'일반공급').status).toBe('review')
  })
  it('does not grant possible for a forged complete flag or a changed review hash', () => {
    const forged=notice([domestic],'일반공급',{complete:true,source_gaps:[{item:'미해석 실제 조항'}],missing_topics:['미해석 실제 조항']})
    expect(conditionCoverage(forged,undefined,'일반공급').complete).toBe(false)
    expect(evaluateQualification(forged,profile(),undefined,'일반공급').status).toBe('review')
    const changed=notice([domestic],'일반공급',{reviewed_document_hash:'b'.repeat(64)})
    expect(conditionCoverage(changed,undefined,'일반공급').missingTopics).toContain('현재 문서의 신청 분기·검토 페이지·해시 기록 미확보')
  })
  it('excludes post-selection paperwork from eligibility and review references', () => {
    const item=notice([domestic]);item.rules.push(rule('unparsed',{phase:'post_selection',text:'입주 시 등본을 제출해야 합니다.'}))
    expect(evaluateQualification(item,profile(),undefined,'일반공급').status).toBe('possible')
  })
  it('does not invalidate admission because an optional price table failed', () => {
    const item=notice([domestic]);item.rules.push(rule('document_diagnostics',{effect:'metadata',diagnostics:[{stage:'identity',code:'current_document_mismatch',status:'error',document_role:'price_table',evidence_url:'https://apply.lh.or.kr/price.pdf'}]}))
    expect(conditionCoverage(item,undefined,'일반공급').complete).toBe(true)
  })
  it('keeps a known official bank period met while only the missing deposit criterion is unresolved', () => {
    const item=notice([],'일반공급',{}, {housing_kind:'private',housing_kind_evidence:{verification:'official'},rank_applicability:{status:'applicable',account_required:true,verification:'official'},rules:[rule('account_type',{purpose:'first_rank',allowed_values:['comprehensive']}),rule('private_rank_months',{purpose:'first_rank',value:24})]})
    const facts=profile({accountType:'comprehensive',privateRankBaseDate:'2009-06-24',privateDepositKrw:'19550000'})
    const rank=deriveRank(item,facts)
    expect(rank.rank).toBe('unknown')
    expect(rank.reasons.filter(r=>r.label==='민영 순위 인정기간')).toHaveLength(1)
    expect(rank.reasons.find(r=>r.label==='민영 순위 인정기간')?.status).toBe('pass')
    expect(rank.reasons.find(r=>r.label==='민영주택 예치금')).toMatchObject({status:'review',category:'source_gap'})
  })
  it('keeps empty source-only supply groups out of evidence while preserving the official inventory', () => {
    const item=notice([],'일반공급',{complete:false,verified_rule_count:0,topics:[],source_gaps:[{item:'실제 공급별 신청조건'}],missing_topics:['실제 공급별 신청조건'],branches:[]})
    item.rules.push(rule('offered_supplies',{effect:'metadata',supplies:[{supply_type:'일반공급',unit_type:'59A',supply_count:2,verification:'official'}]}))
    const html=renderToStaticMarkup(<EligibilityDetails notice={item} profile={profile()} onProfile={()=>{}} />)
    expect(html).toContain('공식 모집 주택형·공급유형')
    expect(html).toContain('59A')
    expect(html).not.toContain('<h5>일반공급<small>')
    expect(renderToStaticMarkup(<ReasonList reasons={[]} />)).toBe('')
  })
  it('preserves v5 inputs and does not invent future household answers during migration', () => {
    const old=migrateProfile({...profile(),version:5,privateDepositKrw:'19550000'})
    expect(old.privateDepositKrw).toBe('19550000')
    expect(old.plannedHouseholdHomelessConfirmed).toBeNull()
    expect(old.plannedPartnerIsFormerSpouse).toBeNull()
    const answered=migrateProfile({...old,plannedHouseholdHomelessConfirmed:true,plannedPartnerIsFormerSpouse:false,sameSpouseRemarriage:true,priorSameSpouseMarriageMonths:'12'})
    expect(answered).toMatchObject({plannedHouseholdHomelessConfirmed:true,plannedPartnerIsFormerSpouse:false,sameSpouseRemarriage:true,priorSameSpouseMarriageMonths:'12'})
  })
})
