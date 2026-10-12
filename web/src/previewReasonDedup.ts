import type { EligibilityReason } from './eligibility'
import { inheritedCondition } from './qualification'
import type { NoticeRule } from './types'

const bareRegionKeys = new Set([
  'id', 'kind', 'verification', 'source', 'parser_version', 'document_hash',
  'evidence_url', 'evidence_text', 'evidence_page', 'evidence_section', 'text', 'label',
  'criterion_date', 'reference_date', 'criterion_basis', 'housing_kind', 'applicable_law',
  'supply_type', 'supply_types', 'unit_type', 'unit_types', 'region_code', 'region_name', 'exceptions',
])

function noExceptions(rule: NoticeRule): boolean {
  return rule.exceptions == null || Array.isArray(rule.exceptions) && rule.exceptions.length === 0
}

function scope(rule: NoticeRule, singular: 'supply_type' | 'unit_type'): string[] | null | undefined {
  const one = rule[singular], many = rule[singular === 'supply_type' ? 'supply_types' : 'unit_types']
  if (one != null && typeof one !== 'string' || many != null && (!Array.isArray(many) || many.some((item) => typeof item !== 'string'))) return undefined
  const compact = (value: string) => value.replace(/\s+/g, '')
  const single = typeof one === 'string' && compact(one) ? [compact(one)] : null
  const multiple = Array.isArray(many) ? [...new Set(many.map((item) => compact(item as string)))].sort() : null
  return single && multiple ? single.filter((value) => multiple.includes(value)) : single || multiple
}

function sameScope(a: NoticeRule, b: NoticeRule): boolean {
  return (['supply_type', 'unit_type'] as const).every((field) => {
    const x = scope(a, field), y = scope(b, field)
    return x !== undefined && y !== undefined && JSON.stringify(x) === JSON.stringify(y)
  })
}

function applicantCoversGroup(applicant: NoticeRule, group: NoticeRule): boolean {
  return (['supply_type', 'unit_type'] as const).every((field) => {
    const accepted = scope(applicant, field), requested = scope(group, field)
    // An unscoped applicant requirement applies to every supply/unit. Two
    // explicitly scoped requirements must describe the same branch.
    return accepted !== undefined && requested !== undefined && (accepted === null || JSON.stringify(accepted) === JSON.stringify(requested))
  })
}

function regionKey(value: unknown): string | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const item = value as Record<string, unknown>
  if (Object.keys(item).some((key) => !['region_code', 'region_name'].includes(key))) return null
  if (typeof item.region_code !== 'string' || !item.region_code.trim()) return null
  if (item.region_name != null && typeof item.region_name !== 'string') return null
  return JSON.stringify([item.region_code.trim(), typeof item.region_name === 'string' ? item.region_name.normalize('NFKC').replace(/\s+/g, '') : ''])
}

function sameRegionalRequirement(group: NoticeRule, applicant: NoticeRule, groupReason: EligibilityReason, applicantReason: EligibilityReason): boolean {
  if (groupReason.status !== 'fail' || applicantReason.status !== 'fail') return false
  if (group.kind !== 'any' || group.verification !== 'official' || group.effect || group.purpose || !noExceptions(group)) return false
  if (applicant.kind !== 'applicant_regions' || applicant.verification !== 'official' || applicant.effect !== 'metadata' || applicant.scope_complete !== true || applicant.unrestricted === true || applicant.domestic_only === true || !noExceptions(applicant)) return false
  if (typeof group.document_hash !== 'string' || !group.document_hash || group.document_hash !== applicant.document_hash) return false
  if (typeof group.criterion_date !== 'string' || !group.criterion_date || group.criterion_date !== applicant.criterion_date || group.criterion_basis !== applicant.criterion_basis) return false
  if (groupReason.criterionDate !== group.criterion_date || applicantReason.criterionDate !== applicant.criterion_date || !applicantCoversGroup(applicant, group)) return false
  if (!Array.isArray(applicant.regions) || !applicant.regions.length || !Array.isArray(group.conditions) || !group.conditions.length) return false
  const accepted = applicant.regions.map(regionKey)
  const alternatives = group.conditions.map((value) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null
    const child = inheritedCondition(group, value as NoticeRule)
    if (child.kind !== 'residence_region' || child.verification !== 'official' || !noExceptions(child) || Object.keys(child).some((key) => !bareRegionKeys.has(key))) return null
    if (child.document_hash !== group.document_hash || child.criterion_date !== group.criterion_date || child.criterion_basis !== group.criterion_basis || !sameScope(child, group)) return null
    return regionKey({ region_code: child.region_code, region_name: child.region_name })
  })
  return !accepted.includes(null) && !alternatives.includes(null) && JSON.stringify([...new Set(accepted)].sort()) === JSON.stringify([...new Set(alternatives)].sort())
}

/** Only remove a repeated regional OR from the compact preview. Its complete
 * branch result, quotations and expanded evidence remain unchanged.
 */
export function deduplicateUnavailablePreviewRegions(reasons: EligibilityReason[], rules: NoticeRule[]): EligibilityReason[] {
  const byId = new Map(rules.filter((rule) => rule.id).map((rule) => [rule.id, rule]))
  const visibleApplicants = reasons.slice(0, 3).filter((reason) => reason.status === 'fail' && byId.get(reason.ruleId)?.kind === 'applicant_regions')
  if (!visibleApplicants.length) return reasons
  return reasons.filter((reason) => {
    const group = byId.get(reason.ruleId)
    return !group || !visibleApplicants.some((visible) => sameRegionalRequirement(group, byId.get(visible.ruleId)!, reason, visible))
  })
}
