import { describe, expect, it } from 'vitest'
import type { EligibilityReason } from './eligibility'
import { deduplicateUnavailablePreviewRegions } from './previewReasonDedup'
import type { NoticeRule } from './types'

const regions = [{ region_code: '11', region_name: '서울특별시' }, { region_code: '28', region_name: '인천광역시' }, { region_code: '41', region_name: '경기도' }]
const provenance = { verification: 'official' as const, criterion_date: '2026-10-06', criterion_basis: 'announcement', document_hash: 'fixture-document' }
const applicant: NoticeRule = { ...provenance, id: 'applicant-scope', kind: 'applicant_regions', effect: 'metadata', scope_complete: true, regions }
const group: NoticeRule = { ...provenance, id: 'region-alternatives', kind: 'any', supply_type: '일반공급', conditions: regions.map((region) => ({ ...provenance, ...region, kind: 'residence_region' })) }
const applicantReason: EligibilityReason = { status: 'fail', category: 'condition', ruleId: applicant.id, criterionDate: '2026-10-06', label: '신청 가능한 지역', detail: '내 거주지는 공식 수도권 신청 범위 밖입니다.' }
const groupReason: EligibilityReason = { ...applicantReason, ruleId: group.id, label: '신청 가능한 거주지역', detail: '거주지역: 서울 불일치 / 거주지역: 인천 불일치 / 거주지역: 경기 불일치' }
const otherReason: EligibilityReason = { ...applicantReason, ruleId: 'another-condition', label: '부모 만 나이', detail: '내 입력 60세 · 공고 요구 >= 65세' }
const reasons = [applicantReason, groupReason, otherReason]

describe('compact preview of duplicate official regional requirements', () => {
  it('keeps the clear applicant scope and other failures while retaining the original detailed reasons', () => {
    expect(deduplicateUnavailablePreviewRegions(reasons, [applicant, group])).toEqual([applicantReason, otherReason])
    expect(reasons).toEqual([applicantReason, groupReason, otherReason])
    expect((group.conditions as NoticeRule[])).toHaveLength(3)
  })

  it('compares OR alternatives as a set and allows children to inherit the same source and criterion', () => {
    const reordered: NoticeRule = { ...group, conditions: [...regions].reverse().map((region) => ({ ...region, kind: 'residence_region' })) }
    expect(deduplicateUnavailablePreviewRegions(reasons, [applicant, reordered])).toEqual([applicantReason, otherReason])
    expect(deduplicateUnavailablePreviewRegions(reasons, [{ ...applicant, supply_type: '일반공급' }, reordered])).toEqual([applicantReason, otherReason])
  })

  it.each([
    ['different announcement date', { ...group, criterion_date: '2026-10-02' }],
    ['different document hash', { ...group, document_hash: 'another-document' }],
    ['different criterion basis', { ...group, criterion_basis: 'contract_date' }],
    ['different regional alternatives', { ...group, conditions: [{ ...provenance, kind: 'residence_region', region_code: '27', region_name: '대구광역시' }] }],
    ['a mixed OR group', { ...group, conditions: [...(group.conditions as NoticeRule[]), { ...provenance, kind: 'household_head', value: true }] }],
    ['a residence duration alternative', { ...group, conditions: [{ ...provenance, kind: 'residence_months', region_code: '41', region_name: '경기도', value: 12 }] }],
    ['a duration attached to a region', { ...group, conditions: regions.map((region) => ({ ...provenance, ...region, kind: 'residence_region', min_months: 12 })) }],
    ['an official exception', { ...group, exceptions: [{ kind: 'military_service_years', min_years: 10 }] }],
    ['a narrower child supply scope', { ...group, conditions: regions.map((region) => ({ ...provenance, ...region, kind: 'residence_region', supply_type: '특별공급' })) }],
  ])('retains the expanded comparison in the preview for %s', (_label, changed) => {
    expect(deduplicateUnavailablePreviewRegions(reasons, [applicant, changed])).toEqual(reasons)
  })

  it.each([
    ['an explicitly different supply branch', { ...applicant, supply_type: '특별공급' }, group],
    ['an explicitly different unit branch', { ...applicant, unit_type: '084' }, { ...group, unit_type: '059' }],
    ['a different domestic qualification', { ...applicant, domestic_only: true }, group],
    ['a regional exception in metadata', { ...applicant, exceptions: [{ kind: 'military_service_years', min_years: 10 }] }, group],
    ['an incomplete applicant scope', { ...applicant, scope_complete: false }, group],
    ['missing document identity', { ...applicant, document_hash: null }, { ...group, document_hash: null }],
  ])('preserves both reasons with %s', (_label, changedApplicant, changedGroup) => {
    expect(deduplicateUnavailablePreviewRegions(reasons, [changedApplicant, changedGroup])).toEqual(reasons)
  })

  it('does not hide a regional OR when the clear applicant scope is outside the three visible reasons', () => {
    const ordered = [otherReason, { ...otherReason, label: '다른 조건' }, groupReason, applicantReason]
    expect(deduplicateUnavailablePreviewRegions(ordered, [applicant, group])).toEqual(ordered)
  })

  it('requires exact source-linked reason identities and failed facts', () => {
    expect(deduplicateUnavailablePreviewRegions([{ ...applicantReason, ruleId: undefined }, groupReason], [applicant, group])).toHaveLength(2)
    expect(deduplicateUnavailablePreviewRegions([{ ...applicantReason, status: 'review' }, groupReason], [applicant, group])).toHaveLength(2)
    expect(deduplicateUnavailablePreviewRegions([applicantReason, { ...groupReason, status: 'review' }], [applicant, group])).toHaveLength(2)
    expect(deduplicateUnavailablePreviewRegions([{ ...applicantReason, criterionDate: '2026-10-02' }, groupReason], [applicant, group])).toHaveLength(2)
  })
})
