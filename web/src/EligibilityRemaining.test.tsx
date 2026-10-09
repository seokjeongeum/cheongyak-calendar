import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { EligibilityBrief, EligibilityDetails, ReasonList, comparedConditionsLabel } from './EligibilityDetails'
import { applicationInstructions, conditionSourceStatus, evaluateEligibility, supplyInventorySummary } from './eligibility'
import { EMPTY_PROFILE, type Notice, type NoticeRule } from './types'
import type { EligibilityReason } from './qualification'

const evidence = 'https://apply.lh.or.kr/lhapply/lhFile.do?fileid=68804506'
const hash = 'a'.repeat(64)
const rule = (kind: string, patch: Partial<NoticeRule> = {}): NoticeRule => ({ kind, verification: 'official', document_hash: hash, evidence_url: evidence, ...patch })
const notice = (rules: NoticeRule[]): Notice => ({ id: 'gajeong', title: '인천가정2 B2', category: 'public_sale', source: 'lh', provider: 'LH', address: null, region_code: null, region_name: null, announcement_date: '2026-10-02', official_url: evidence, price_cap_status: 'unknown', events: [], prices: [], rules, updated_at: null, version: 1 })
const profile = { ...EMPTY_PROFILE, dateOfBirth: '1990-01-01' }

describe('specific remaining clauses and personal facts', () => {
  it('does not present a recovered page lookup as a missing attachment', () => {
    const item = notice([rule('document_diagnostics', { effect: 'metadata', status: 'partial', diagnostics: [
      { stage: 'discovery', code: 'announcement_download_failed', status: 'resolved', message: '공식 공고 페이지를 가져오지 못했습니다.', resolved_document_hash: hash, resolved_evidence_url: evidence },
      { stage: 'discovery', code: 'attachment_found', status: 'ok', message: '공식 첨부를 확보했습니다.' },
      { stage: 'interpretation', code: 'context_not_supported', status: 'partial', message: '소득 분기의 원문 검토가 필요합니다.' },
    ] })])
    expect(conditionSourceStatus(item).diagnostics.map((entry) => entry.code)).toEqual(['context_not_supported'])
    const html = renderToStaticMarkup(<EligibilityDetails notice={item} profile={profile} onProfile={() => {}} />)
    expect(html).not.toContain('공식 공고 페이지를 가져오지 못했습니다')
    expect(html).toContain('소득 분기의 원문 검토가 필요합니다')
  })
  it('retains actual attachment failures when a different file succeeds', () => {
    const item = notice([rule('document_diagnostics', { effect: 'metadata', status: 'partial', diagnostics: [
      { stage: 'discovery', code: 'announcement_download_failed', status: 'error', message: '공식 공고 페이지를 가져오지 못했습니다.', missing_items: ['현재 모집공고문의 첨부 주소'] },
      { stage: 'download', code: 'document_download_failed', status: 'error', message: '정정 공고문을 다운로드하지 못했습니다.', evidence_url: 'https://example.org/corrected.pdf', missing_items: ['정정 공고문'] },
      { stage: 'download', code: 'document_read', status: 'ok', message: '다른 파일을 읽었습니다.' },
    ] })])
    expect(conditionSourceStatus(item).diagnostics.map((entry) => entry.code)).toEqual(['announcement_download_failed', 'document_download_failed'])
  })
  it('shows an active legal exception alongside another supply’s mandatory source topic once', () => {
    const label = '생애최초의 제53조 과거 주택 소유 예외'
    const item = notice([
      rule('age_min', { value: 19, supply_type: '생애최초 특별공급' }),
      rule('unparsed', { label, text: '모든 과거 취득·처분에 대한 소유 예외 적용을 확인하지 못했습니다.', supply_type: '생애최초 특별공급' }),
      rule('condition_coverage', { effect: 'metadata', scopes: [
        { supply_type: '생애최초 특별공급', complete: true, topics: [] },
        { supply_type: '신혼부부 특별공급', complete: false, topics: [{ topic: '동일 배우자와 재혼한 경우 이전 혼인기간 합산', status: 'missing', required: true }] },
      ] }),
    ])
    const html = renderToStaticMarkup(<EligibilityDetails notice={item} profile={profile} onProfile={() => {}} />)
    expect(html).toContain('동일 배우자와 재혼한 경우 이전 혼인기간 합산')
    expect(html.match(new RegExp(`서비스 원문 검토 부족 · ${label}`, 'g'))).toHaveLength(1)
    expect(html).toContain('모든 과거 취득·처분에 대한 소유 예외 적용을 확인하지 못했습니다.')
    expect(html).not.toContain(`${label} 입력하기`)
    expect(html.match(/class="qualification-source-gap"/g)).toHaveLength(1)
  })
  it('distinguishes missing input, unknown past facts, and service source review', () => {
    const reasons: EligibilityReason[] = [
      { status: 'review', category: 'missing_input', label: '부양 시작일', detail: '같은 등본에서 부양을 시작한 날짜가 필요합니다.', profileField: 'parentSupportSince' },
      { status: 'review', category: 'past_fact', label: '세대주 상태 변경일', detail: '오늘의 세대주 상태를 과거 공고일까지 소급할 수 없습니다.', profileField: 'isHouseholdHead', historyGroup: 'household_head' },
      { status: 'review', category: 'source_gap', label: '해외 연속체류 예외', detail: '이 분기의 예외 조항을 아직 확보하지 못했습니다.' },
    ]
    const html = renderToStaticMarkup(<ReasonList reasons={reasons} onProfile={() => {}} />)
    expect(html).toContain('내 입력 부족 · 부양 시작일')
    expect(html).toContain('과거 사실 미확인 · 세대주 상태 변경일')
    expect(html).toContain('서비스 원문 검토 부족 · 해외 연속체류 예외')
    expect(html).toContain('부양 시작일 입력하기')
    expect(html).toContain('세대주 상태 변경일 입력하기')
    expect(html).not.toContain('해외 연속체류 예외 입력하기')
    expect(comparedConditionsLabel({ status: 'review', reasons })).toBe('내 입력 1개 필요 · 과거 사실 1개 확인 필요')
  })
  it('consolidates an unreviewed clause across actual supplies and exposes its evidence', () => {
    const supplies = ['신혼부부', '예비신혼부부']
    const item = notice([
      ...supplies.map((supply_type) => rule('age_min', { value: 19, supply_type })),
      rule('condition_coverage', { effect: 'metadata', scopes: supplies.map((supply_type) => ({ supply_type, complete: false, topics: [{ topic: '해외 연속체류 90일 초과 예외', status: 'missing', required: true, reason: '생업 체류 예외의 적용 대상 미확보', evidence_text: '90일을 초과하여 해외에 체류한 경우', evidence_page: 1 }] })) }),
    ])
    const source = conditionSourceStatus(item)
    expect(source.topics).toHaveLength(1)
    expect(source.topics[0]).toMatchObject({ scopes: supplies, evidenceUrl: evidence, documentHash: hash, evidencePage: 1 })
    const result = evaluateEligibility(item, profile)
    const closed = renderToStaticMarkup(<EligibilityBrief notice={item} profile={profile} result={result} onProfile={() => {}} />)
    expect(closed.match(/class="qualification-gap-note"/g)).toHaveLength(1)
    expect(closed.match(/<strong>해외 연속체류 90일 초과 예외<\/strong>/g)).toHaveLength(1)
    expect(closed).toContain('생업 체류 예외의 적용 대상 미확보')
    const expanded = renderToStaticMarkup(<><EligibilityBrief sourceDetailsOpen notice={item} profile={profile} result={result} onProfile={() => {}} /><EligibilityDetails notice={item} profile={profile} onProfile={() => {}} /></>)
    expect(expanded).not.toContain('class="qualification-gap-note"')
    expect(expanded.match(/class="qualification-source-gap"/g)).toHaveLength(1)
    expect(expanded).toContain('검토할 원문 1쪽')
  })
  it('does not revive paperwork or application instructions from legacy missing topics', () => {
    const item = notice([rule('condition_coverage', { effect: 'metadata', scopes: [{ complete: false, missing_topics: ['서류 제출', '중복 신청'], topics: [
      { topic: '서류 제출', status: 'missing', required: true, phase: 'post_selection' },
      { topic: '동일 블록 중복 신청', status: 'missing', required: true, phase: 'application' },
      { topic: '면제된 소득 요건', status: 'missing', required: false },
    ] }] })])
    expect(conditionSourceStatus(item).topics).toEqual([])
  })
  it('identifies a missing review record when an older document has no specific clause review', () => {
    const item = notice([rule('condition_coverage', { effect: 'metadata', scopes: [{ complete: false, missing_topics: ['문서의 나머지 신청 제한·예외 검토'] }] })])
    expect(conditionSourceStatus(item).topics[0].label).toBe('신청자격 문단의 필수 조건·면제 검토 기록 미확보')
    const html = renderToStaticMarkup(<EligibilityDetails notice={item} profile={profile} onProfile={() => {}} />)
    expect(html).not.toContain('문서의 나머지 신청 제한·예외 검토')
    expect(html).toContain('필수 조건·면제 검토 기록 미확보')
  })
})

describe('official inventory and actions when applying', () => {
  it('separates the 308-home development from this 252-home recruitment', () => {
    const item = notice([rule('supply_inventory_summary', { effect: 'metadata', total_households: 308, current_supply_count: 252 })])
    expect(supplyInventorySummary(item)).toMatchObject({ totalHouseholds: 308, currentSupplyCount: 252 })
    const html = renderToStaticMarkup(<EligibilityBrief notice={item} profile={profile} result={evaluateEligibility(item, profile)} onProfile={() => {}} />)
    expect(html).toContain('단지 전체 <strong>308세대</strong> · 금회 모집 <strong>252세대</strong>')
    expect(supplyInventorySummary(notice([rule('supply_inventory_summary', { effect: 'metadata', total_households: 308, current_supply_count: 252, verification: 'ai_unverified' })]))).toBeUndefined()
  })
  it('explains duplicate applications and the official couple exception as application instructions', () => {
    const item = notice([rule('application_instructions', { effect: 'metadata', instructions: [
      { label: '동일 블록 중복 신청', detail: '신청 시 동일 블록 중복 청약에 유의하세요.', phase: 'application' },
      { label: '부부 예외', detail: '공고가 정한 부부 중복 당첨 예외와 접수 시간을 확인하세요.', phase: 'application' },
      { label: '서류 제출·납부', detail: '당첨 후 제출하고 납부하세요.', phase: 'post_selection' },
    ] })])
    expect(applicationInstructions(item).map((row) => row.label)).toEqual(['동일 블록 중복 신청', '부부 예외'])
    const html = renderToStaticMarkup(<EligibilityDetails notice={item} profile={profile} onProfile={() => {}} />)
    expect(html).toContain('신청 시 지켜야 할 조건')
    expect(html).toContain('공고가 정한 부부 중복 당첨 예외와 접수 시간')
    expect(html).not.toContain('서류 제출·납부')
    expect(html).not.toContain('중복 신청 입력하기')
  })
})
