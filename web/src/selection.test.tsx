import { demoNotices } from './demo'
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { EMPTY_PROFILE, emptyPointsFamilyFact, type LocalProfile, type Notice } from './types'
import { nextDeadline } from './deadlines'
import { migrateProfile, updateProfileFacts } from './profile'
import { setEvaluationToday, factsAtDate } from './factTimeline'
import { calculatePoints, bankPoints, recognizedAccountMonths } from './points'
import { evaluateRule } from './qualification'
import { selectionOpportunity } from './opportunity'
import { ChildFactsFields } from './ChildFactsFields'

setEvaluationToday('2026-10-05')
const stable = Object.fromEntries(['ownership', 'marital', 'household', 'household_head', 'points', 'children', 'pregnancy'].map((g) => [g, { mode: 'never_changed', date: '' }])) as LocalProfile['factChanges']
const person = (extra: Partial<LocalProfile> = {}): LocalProfile => ({ ...EMPTY_PROFILE, dateOfBirth: '1993-09-15', maritalStatus: 'single', hasSpouse: false, applicantOnRegister: true, applicantOwnsHome: false, applicantPreviouslyOwnedHome: false, householdMembersComplete: true, accountType: 'comprehensive', privateRankBaseDate: '2009-06-01', factChanges: stable, ...extra })
const official = 'https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetailView.do?houseManageNo=2026000468&pblancNo=2026000468'
const housing = (extra: Partial<Notice> = {}): Notice => ({ ...demoNotices(new Date('2026-10-05T12:00:00+09:00'))[0], id: 'test', title: '공식 공고', source: 'cheongyak_home', provider: '', category: 'apt', housing_kind: 'private', application_method: 'apt_ranked', official_url: official, announcement_date: '2026-10-02', price_cap_status: 'no', events: [{kind:'special', label:'특별공급', start_date:'2026-10-06', end_date:'2026-10-07'}, {kind:'first_priority', label:'1순위', start_date:'2026-10-08', end_date:'2026-10-08'}], prices: [], rules: [], selection_methods: [], qualification_context: undefined, rules_complete: false, offered_supplies: [{supply_type:'일반공급',unit_type:'84A',verification:'official',supply_count:4}], ...extra })
const rule = {kind:'children_min',value:2,child_age_max:19,include_pregnancy:true,verification:'official',criterion_date:'2026-10-02',evidence_url:official}

describe('next reception deadline', () => {
  it('takes the first unexpired end, including reception already running', () => {
    expect(nextDeadline(housing(), '2026-10-05')).toBe('2026-10-07')
    expect(nextDeadline(housing(), '2026-10-07')).toBe('2026-10-07')
    expect(nextDeadline(housing(), '2026-10-08')).toBe('2026-10-08')
    expect(nextDeadline(housing(), '2026-10-09')).toBeNull()
  })
  it('does not use winner or contract dates as reception deadlines', () => {
    expect(nextDeadline(housing({events:[{kind:'contract',label:'계약',start_date:'2026-10-06',end_date:'2026-10-09'},{kind:'application',label:'상시 접수 종료일 미공개',start_date:'2026-09-01',end_date:null}]}), '2026-10-05')).toBeNull()
  })
})
describe('explicit child history', () => {
  it('never promotes today’s no into a past fact, but an explicit never answer resolves every notice', () => {
    const current = person({hasChildren:false,pregnant:false,factChanges:{}})
    expect(evaluateRule(rule,current,housing()).status).toBe('review')
    const never = updateProfileFacts(current, {hasChildren:false,pregnant:false,factChanges:{children:{mode:'never_changed',date:''},pregnancy:{mode:'never_changed',date:''}}},'2026-10-05')
    expect(evaluateRule(rule,never,housing())).toMatchObject({status:'fail',input:'0명'})
  })
  it('a new pregnancy does not erase child timeline facts', () => {
    const updated = updateProfileFacts(person({hasChildren:false,pregnant:false}),{pregnant:true,expectedChildren:'2'},'2026-10-05')
    expect(updated.factChanges.children?.mode).toBe('never_changed')
    expect(updated.factChanges.pregnancy?.mode).toBe('unknown')
    expect(factsAtDate(updated,'pregnancy','2026-10-02').known).toBe(false)
  })
  it('preserves combined v5 history and real adoption dates during migration', () => {
    const p=migrateProfile({...person(),factChanges:{children:{mode:'known',date:'2026-09-01'}},children:[{dateOfBirth:'2020-01-01',adopted:true,adoptionDate:'2026-09-20'}]})
    expect(p.factChanges.pregnancy?.date).toBe('2026-09-01')
    expect(p.children[0].adoptionDate).toBe('2026-09-20')
  })
  it('does not ask pregnancy if the official condition excludes it', () => {
    expect(evaluateRule({...rule,include_pregnancy:false},person({hasChildren:false,pregnant:null}),housing())).toMatchObject({status:'fail',input:'0명'})
  })
  it('hides birth/adoption/add controls when there are no children', () => {
    const html=renderToStaticMarkup(<ChildFactsFields profile={person({hasChildren:false,pregnant:false})} onChange={()=>{}} today="2026-10-05" needsPast />)
    expect(html).toContain('계속 자녀·임신 없음')
    expect(html).not.toContain('자녀 정보 추가')
    expect(html).not.toContain('임신 중 태아 수')
  })
})
describe('official general-supply points', () => {
  it('calculates known parts at the notice date; unknowns never produce a total', () => {
    const result=calculatePoints(housing(),person())
    expect(result.parts.map((part)=>part.score)).toEqual([8,5,17])
    expect(result.total).toBe(30)
    expect(calculatePoints(housing(),person({applicantPreviouslyOwnedHome:null})).total).toBeNull()
  })
  it('handles birthday/month boundaries and the bank minor period transition', () => {
    expect(bankPoints(5)).toBe(1);expect(bankPoints(6)).toBe(2);expect(bankPoints(12)).toBe(3);expect(bankPoints(180)).toBe(17)
    expect(recognizedAccountMonths('2010-01-01','2000-01-01','2026-10-02')).toBe(24+93)
    expect(calculatePoints(housing({announcement_date:'2023-09-14'}),person({privateRankBaseDate:'2023-01-01'})).parts[0].score).toBe(0)
  })
  it('excludes a homeowner parent age 60 despite the eligibility ownership exception', () => {
    const p=person({isHouseholdHead:true,householdMembers:[{id:'parent',relation:'applicant_parent',register:'applicant',dateOfBirth:'1966-01-01',ownsHome:true,previouslyOwnedHome:true}]})
    expect(calculatePoints(housing(),p).parts[1]).toMatchObject({score:5})
    expect(calculatePoints(housing(),p).parts[1].detail).toContain('60세 예외')
  })
  it('compares 3-year ancestor continuity, unmarried child and overseas exclusions', () => {
    const p=person({isHouseholdHead:true,pointsFamilyComplete:true,householdMembers:[{id:'parent',relation:'applicant_parent',register:'applicant',dateOfBirth:'1966-01-01',ownsHome:false,previouslyOwnedHome:false}],pointsFamily:{parent:{...emptyPointsFamilyFact(),registeredSince:'2023-10-02',spouseOwnsHome:false,overseasExcluded:false}}})
    expect(calculatePoints(housing(),p).parts[1].score).toBe(10)
    expect(calculatePoints(housing(),{...p,pointsFamily:{parent:{...p.pointsFamily.parent,registeredSince:'2023-10-03'}}}).parts[1].score).toBe(5)
  })
  it('adds half the spouse bank period up to 3 points without applying current status to the past', () => {
    const p=person({maritalStatus:'married',hasSpouse:true,marriageDate:'2020-01-01',spouseSameRegister:true,privateRankBaseDate:'2025-10-02',spouseAccountPresent:true,spouseAccountBaseDate:'2025-10-02'})
    expect(calculatePoints(housing(),p).parts[2]).toMatchObject({score:5})  // 3 + (12/2 months => 2).
    expect(calculatePoints(housing(),{...p,spouseAccountBaseDate:'2024-10-02'}).parts[2].score).toBe(6)
    expect(calculatePoints(housing(),{...p,spouseAccountPresent:false,factChanges:{...stable,points:{mode:'known',date:'2026-10-04'}}}).parts[2].score).toBeNull()
  })
  it('does not award points to married or overseas-excluded children', () => {
    const p=person({pointsFamilyComplete:true,householdMembers:[{id:'child',relation:'applicant_child',register:'applicant',dateOfBirth:'2000-01-01',ownsHome:false,previouslyOwnedHome:false}],pointsFamily:{child:{...emptyPointsFamilyFact(),registeredSince:'2020-01-01',unmarried:false,overseasExcluded:false}}})
    expect(calculatePoints(housing(),p).parts[1].score).toBe(5)
    expect(calculatePoints(housing(),{...p,pointsFamily:{child:{...p.pointsFamily.child,unmarried:true,overseasExcluded:true}}}).parts[1].score).toBe(5)
    expect(calculatePoints(housing(),{...p,pointsFamily:{child:{...p.pointsFamily.child,unmarried:true}}}).parts[1].score).toBe(10)
  })
})
describe('opportunity is separate from admission', () => {
  const selection = {kind:'selection_method',effect:'metadata',supply_type:'일반공급',rank:1,points_percent:100,lottery_percent:0,unit_types:['84A'],verification:'official',evidence_url:official,tie_break:'account_duration_then_lottery'}
  it('emphasizes 100% points but never assigns a probability from the percentage', () => {
    const value=selectionOpportunity(housing({selection_methods:[selection]}),person())
    expect(value.rows[0].label).toContain('가점제 100%')
    expect(value.rows[0].detail).toContain('동점')
    expect(value.points?.total).toBe(30)
  })
  it('ignores AI ratios, other units, and score results from another region/project', () => {
    expect(selectionOpportunity(housing({selection_methods:[{...selection,verification:'ai_unverified'}]}),person()).rows).toEqual([])
    expect(selectionOpportunity(housing({selection_methods:[{...selection,unit_types:['59A']}]}),person()).rows).toEqual([])
  })
  const regions={kind:'applicant_regions',effect:'metadata',verification:'official',criterion_date:'2026-10-02',evidence_url:official,regions:[{region_code:'41',region_name:'경기도'},{region_code:'11',region_name:'서울특별시'}],priority_division:'regional',local_priority:{region_code:'41830',region_name:'경기도 양평군',min_months:0},other_priority:{region_code:'41',region_name:'경기도'}}
  const other=person({region:'경기도',regionCode:'41',district:'화성시',districtCode:'41590',movedInDate:'2010-01-01',cityMovedInDate:'2010-01-01',districtMovedInDate:'2010-01-01'})
  const allocation={kind:'regional_allocation',effect:'metadata',verification:'official',evidence_url:official,allocation_method:'region_priority'}
  it('shows verified other-region priority but gives quota information instead of a blanket disadvantage', () => {
    const n=housing({rules:[regions],selection_methods:[allocation,selection]})
    expect(selectionOpportunity(n,other).rows.some(r=>r.label==='해당지역 우선 · 기타지역 기회 제한')).toBe(true)
    const quota={...allocation,allocation_method:'regional_quota',regional_shares:[{residence_area:'local',percent:50},{residence_area:'other',percent:50}]}
    expect(selectionOpportunity({...n,selection_methods:[quota,selection]},other).rows[0]).toMatchObject({label:'기타지역 별도 배정',limited:false})
    expect(selectionOpportunity(n,person()).rows.some(r=>r.label.includes('기회 제한'))).toBe(false)
  })
  it('compares only the same official unit, region, project, path and cutoff', () => {
    const score={unit_type:'84A',residence_area:'other' as const,house_manage_no:'2026000468',notice_no:'2026000468',supply_type:'일반공급',rank:1,selection_path:'points' as const,min_score:37,max_score:60,average_score:42.79,verification:'official' as const,criterion_date:'2026-10-02',evidence_url:official,collection_status:'success'}
    const n=housing({rules:[regions],selection_methods:[selection],winning_scores:[score]})
    expect(selectionOpportunity(n,other).rows.find(r=>r.pointsPercent!=null)?.benchmark).toMatchObject({minimum:37,label:'과거 최저가점 미만',difference:-7})
    for (const change of [{residence_area:'local' as const},{house_manage_no:'unrelated'},{unit_type:'59A'},{criterion_date:'2026-09-01'},{selection_path:'lottery'},{collection_status:'error'}]) {
      expect(selectionOpportunity({...n,winning_scores:[{...score,...change}]},other).rows.find(r=>r.pointsPercent!=null)?.benchmark).toBeUndefined()
    }
  })
  it('uses explicit general-supply region selection only when automatic data is incomplete', () => {
    const score={unit_type:'84A',residence_area:'local' as const,house_manage_no:'2026000468',notice_no:'2026000468',supply_type:'일반공급',rank:1,selection_path:'points' as const,min_score:37,max_score:60,average_score:42.79,verification:'official' as const,criterion_date:'2026-10-02',evidence_url:official,collection_status:'success'}
    const n=housing({selection_methods:[selection],winning_scores:[score]})
    expect(selectionOpportunity(n,person()).rows[0].benchmark).toBeUndefined()
    const selected=selectionOpportunity(n,person(),'local').rows[0]
    expect(selected.benchmark?.minimum).toBe(37)
    expect(selected.detail).toContain('직접 선택한 청약 지역')
    expect(selectionOpportunity(n,person(),'unknown').rows[0].benchmark).toBeUndefined()
    expect(selectionOpportunity({...n,rules:[regions]},other,'local').rows.find(r=>r.pointsPercent!=null)?.benchmark).toBeUndefined()
  })
})
