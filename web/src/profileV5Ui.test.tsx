import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ProfileDialog } from './ProfileDialog'
import { ApplicationFactsFields } from './ApplicationFactsFields'
import { FactChangeFields } from './FactChangeFields'
import { EMPTY_PROFILE, type LocalProfile, type Notice, type NoticeRule } from './types'

const rule = (kind: string, extra: Partial<NoticeRule> = {}): NoticeRule => ({ kind, value: true, verification: 'official', criterion_date: '2026-09-30', ...extra })
const notice = (id: string, rules: NoticeRule[]): Notice => ({ id, title: `공고 ${id}`, category: 'apt', source: 'cheongyak_home', provider: 'LH', address: null, region_code: null, region_name: null, announcement_date: '2026-09-30', official_url: null, price_cap_status: 'unknown', events: [], prices: [], rules, updated_at: null, version: 1 })
const profile = { ...EMPTY_PROFILE, maritalStatus: 'single' as const, hasSpouse: false, applicantOnRegister: true, householdMembersComplete: true }
const renderDialog = (initialField: keyof LocalProfile, notices: Notice[] = []) => renderToStaticMarkup(<ProfileDialog profile={profile} onChange={() => {}} onClose={() => {}} today="2026-10-05" notices={notices} initialField={initialField} />)

describe('v5 profile questions', () => {
  it('asks effective changes instead of confirmation dates and removes personal contract/former address prompts', () => {
    const html = renderDialog('regionCode', [notice('contract', [rule('domestic_residence', { criterion_basis: 'contract_date' }), rule('military_currently_serving')])])
    for (const old of ['확인한 기준일', '예정 계약일', '공고 기준일에 다른 지역에 살았다면', '공고 기준일의 조회 사실 확인']) expect(html).not.toContain(old)
    expect(html).not.toContain('<option value="41597">')
    expect(html).toContain('국내 거주 상태')
    expect(html).toContain('마지막 변경일')
  })
  it('removes household snapshot confirmations and single-profile spouse questions', () => {
    const html = renderDialog('householdMembers', [notice('home', [rule('homeless')])])
    expect(html).not.toContain('위 가족 목록이 맞는 기준일')
    expect(html).not.toContain('과거 공고 기준일의 가족 구성')
    expect(html).not.toContain('배우자가 과거 주택')
    expect(html).not.toContain('현재 법률상 배우자가 있나요?')
    expect(html).toContain('가족 구성·등본 관계')
  })
  it('removes uncertain recognition and old bank observation-date prompts', () => {
    const html = renderDialog('accountType')
    expect(html).toContain('민영주택 순위기산일')
    expect(html).toContain('국민주택 순위기산일')
    for (const old of ['확인하지 못한 부분이 있나요?', '위 예치금이 충족되어 있던 기준일', '위 납입인정 내역의 기준일', '법정 확인 대상 세대원이 청약에 당첨된 이력이 있나요?']) expect(html).not.toContain(old)
  })
  it('provides one common history question for multiple notices and no repeated project confirmations', () => {
    const notices = ['2026000323', '2026000324'].map((project) => notice(project, [rule('application_restriction', { restriction: 'prior_project_winner', project_id: project, scope: 'household' })]))
    const html = renderToStaticMarkup(<ApplicationFactsFields profile={profile} onChange={() => {}} today="2026-10-05" notices={notices} section="restrictions" />)
    expect(html.match(/위 사람 중 당첨·예비당첨 또는 주택 공급계약 이력이 있는 사람이 있나요\?/g)).toHaveLength(1)
    expect(html).not.toContain('이 사업의 최초 청약에서')
    expect(html).not.toContain('이력을 확인한 기준일')
  })
  it('shows neither history question nor per-project facts for a notice that waives history', () => {
    expect(renderToStaticMarkup(<ApplicationFactsFields profile={profile} onChange={() => {}} today="2026-10-05" notices={[notice('waived', [rule('age_min')])]} section="restrictions" />)).toBe('')
  })
  it('does not ask marriage duration after explicit single and keeps legitimate prospective-family facts', () => {
    const html = renderDialog('maritalStatus', [notice('families', [rule('planned_marriage'), rule('single_parent_family')])])
    expect(html).not.toContain('혼인신고일')
    expect(html).not.toContain('소득 활동·납세 사실을 확인한 기준일')
    expect(html).toContain('입주 전에 혼인신고할 예정인 상대방')
    expect(html).toContain('배우자 없이 본인이 자녀를 양육')
  })
  it('gates effective date controls to relevant past criteria and preserves known dates', () => {
    expect(renderToStaticMarkup(<FactChangeFields profile={profile} onChange={() => {}} today="2026-10-05" group="military" label="군 복무 상태" needed={false} />)).toBe('')
    const html = renderToStaticMarkup(<FactChangeFields profile={{ ...profile, factChanges: { military: { mode: 'known', date: '2020-01-01' } } }} onChange={() => {}} today="2026-10-05" group="military" label="군 복무 상태" />)
    expect(html).toContain('value="2020-01-01"')
    expect(html).toContain('변경된 적 없음')
    expect(html).toContain('날짜 모름')
  })
})
