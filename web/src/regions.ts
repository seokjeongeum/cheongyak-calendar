import data from './data/regions.json'

export interface ProvinceOption { code: string; name: string }
export interface DistrictOption {
  code: string
  name: string
  displayName: string
  parentCityCode?: string
}
export interface RegionProfile {
  region: string
  regionCode?: string
  district: string
  districtCode?: string
}
export interface RegionScope { region_code?: string | null; region_name?: string | null }
export interface ResolvedRegion extends RegionProfile {
  regionCode: string
  districtCode: string
  needsReview: boolean
}

export const REGION_CATALOG_METADATA = {
  effectiveDate: data.effectiveDate,
  sourceTitle: data.sourceTitle,
  sourceUrl: data.sourceUrl,
  downloadUrl: data.downloadUrl,
  sourceFile: data.sourceFile,
  sourceFileSha256: data.sourceFileSha256,
  sourceArchiveSha256: data.sourceArchiveSha256,
}

const provinces = data.provinces
const districts = data.districts
const provinceByCode = new Map(provinces.map((item) => [item.code, item]))
const districtByCode = new Map(districts.map((item) => [item.code, item]))
const districtOptionsByProvince = new Map<string, DistrictOption[]>()
const compact = (value: string) => value.replace(/\s+/g, '')
// Province renames retain their geographic identity. A merger or a boundary
// split does not: former 광주/전남 and 인천 중구/서구 require re-selection.
const ALIASES: Record<string, string[]> = {
  '11': ['서울특별시', '서울'],
  '12': ['전남광주통합특별시'],
  '26': ['부산광역시', '부산'],
  '27': ['대구광역시', '대구'],
  '28': ['인천광역시', '인천'],
  '30': ['대전광역시', '대전'],
  '31': ['울산광역시', '울산'],
  '36': ['세종특별자치시', '세종시', '세종'],
  '41': ['경기도', '경기'],
  '43': ['충청북도', '충북'],
  '44': ['충청남도', '충남'],
  '47': ['경상북도', '경북'],
  '48': ['경상남도', '경남'],
  '50': ['제주특별자치도', '제주도', '제주'],
  '51': ['강원특별자치도', '강원도', '강원'],
  '52': ['전북특별자치도', '전라북도', '전북'],
}

const provinceByAlias = new Map(provinces.flatMap((province) => (ALIASES[province.code] || [province.name]).map((alias) => [alias, province] as const)))
const sortedAliases = provinces.map((province) => ({ province, aliases: [...(ALIASES[province.code] || [province.name])].sort((a, b) => b.length - a.length) }))
const districtsByName = new Map<string, (typeof districts)[number][]>()
for (const district of districts) {
  const key = `${district.provinceCode}:${compact(district.name)}`
  districtsByName.set(key, [...(districtsByName.get(key) || []), district])
}
function provinceFromName(name: string) { return provinceByAlias.get(compact(name)) }

export function provinceOptions(): ProvinceOption[] {
  return provinces.map(({ code, name }) => ({ code, name }))
}

export function districtOptions(provinceCode: string, options: { includeOrdinaryDistricts?: boolean } = {}): DistrictOption[] {
  const key = `${provinceCode}:${!!options.includeOrdinaryDistricts}`
  const cached = districtOptionsByProvince.get(key)
  if (cached) return cached
  const result = districts.filter((district) => district.provinceCode === provinceCode && (options.includeOrdinaryDistricts || !('parentCityCode' in district && district.parentCityCode))).map((district) => ({
    code: district.code, name: district.name, displayName: district.name,
    ...('parentCityCode' in district ? { parentCityCode: district.parentCityCode } : {}),
  }))
  districtOptionsByProvince.set(key, result)
  return result
}

export function provinceName(code: string): string {
  return provinceByCode.get(code)?.name || ''
}

export function districtName(code: string): string {
  return districtByCode.get(code)?.name || ''
}

export function provinceCode(regionName: string): string {
  return provinceFromName(regionName)?.code || ''
}

export function provinceAliases(regionName: string): string[] {
  const province = provinceFromName(regionName)
  return province ? [...(ALIASES[province.code] || [province.name])] : []
}

export function parentCityCode(districtCode: string): string | null {
  const district = districtByCode.get(districtCode)
  return district && 'parentCityCode' in district ? district.parentCityCode || null : null
}

export function resolveLegacyRegion(regionName: string, districtName: string): ResolvedRegion {
  const province = provinceFromName(regionName)
  if (!province) return { regionCode: '', districtCode: '', region: regionName, district: districtName, needsReview: !!regionName || !!districtName }
  if (!districtName.trim()) return { regionCode: province.code, districtCode: '', region: province.name, district: '', needsReview: false }
  const found = districtsByName.get(`${province.code}:${compact(districtName)}`) || []
  if (found.length !== 1) return { regionCode: province.code, districtCode: '', region: province.name, district: districtName, needsReview: true }
  return { regionCode: province.code, districtCode: found[0].code, region: province.name, district: found[0].name, needsReview: false }
}

type ScopeIdentity = { provinceCode: string; districtCode?: string }

function identityFromCode(value: string): ScopeIdentity | null {
  // Official legal-district codes are represented as 2/5 digits or their
  // zero-padded 10-digit form. 읍면동/리 are deliberately unsupported.
  let code = value.trim()
  if (/^\d{10}$/.test(code)) {
    if (!code.endsWith('00000')) return null
    code = code.endsWith('00000000') ? code.slice(0, 2) : code.slice(0, 5)
  }
  if (/^\d{2}000$/.test(code)) code = code.slice(0, 2)
  if (code.length === 2 && provinceByCode.has(code)) return { provinceCode: code }
  const district = districtByCode.get(code)
  return district ? { provinceCode: district.provinceCode, districtCode: district.code } : null
}

function identityFromName(name: string, homeProvinceCode: string): ScopeIdentity | null {
  const normalized = compact(name)
  if (!normalized || /[,/·]|또는|및|부터|까지/.test(normalized)) return null
  let matchedProvince: (typeof provinces)[number] | undefined
  let tail = normalized
  for (const { province, aliases } of sortedAliases) {
    const alias = aliases.find((value) => normalized.startsWith(value))
    if (alias) { matchedProvince = province; tail = normalized.slice(alias.length); break }
  }
  if (matchedProvince && (!tail || ['전체', '전지역'].includes(tail))) return { provinceCode: matchedProvince.code }
  if (!matchedProvince && (/^(광주광역시|전라남도|전남)/.test(normalized) || normalized === '광주')) return null
  const candidates = districtsByName.get(`${matchedProvince?.code || homeProvinceCode}:${tail}`) || []
  if (candidates.length !== 1) return null
  return { provinceCode: candidates[0].provinceCode, districtCode: candidates[0].code }
}

function districtInScope(homeDistrict: string, scopeDistrict: string): boolean {
  return homeDistrict === scopeDistrict || parentCityCode(homeDistrict) === scopeDistrict
}

export function scopeIsDistrict(scope: RegionScope): boolean {
  const code = scope.region_code?.trim()
  if (code) {
    const identity = identityFromCode(code)
    if (identity) return !!identity.districtCode && identity.provinceCode !== '36'
  }
  const name = compact(scope.region_name || '')
  if (!name) return false
  if (provinceFromName(name)) return false
  return /[시군구]$/.test(name)
}

/** null means geography is insufficient or changed, never an assumed mismatch. */
export function matchesRegionScope(profile: RegionProfile, scope: RegionScope, announcementDate?: string | null): boolean | null {
  const resolved = profile.regionCode && (!profile.district || profile.districtCode) ? { regionCode: profile.regionCode, districtCode: profile.districtCode || '' } : resolveLegacyRegion(profile.region, profile.district)
  const homeProvinceCode = profile.regionCode || resolved.regionCode
  const province = provinceByCode.get(homeProvinceCode)
  if (!province || (profile.region && provinceFromName(profile.region)?.code !== province.code)) return null
  const homeDistrictCode = profile.districtCode || resolved.districtCode
  const candidateDistrict = districtByCode.get(homeDistrictCode)
  const homeDistrict = candidateDistrict?.provinceCode === province.code ? candidateDistrict : undefined
  if (homeDistrictCode && !homeDistrict) return null
  const code = scope.region_code?.trim()
  const name = scope.region_name?.trim()
  if (!code && !name) return null
  const coded = code ? identityFromCode(code) : null
  const named = name ? identityFromName(name, province.code) : null
  // An unresolved historical or multi-region name must not be broadened by a
  // province code. Non-boundary provider codes can still use an explicit name.
  if (name && !named) return null
  if (code && !coded && !named) return null
  if (coded && named && (coded.provinceCode !== named.provinceCode ||
    (coded.districtCode && named.districtCode && !districtInScope(named.districtCode, coded.districtCode) && !districtInScope(coded.districtCode, named.districtCode)))) return null
  const target = coded?.districtCode && named?.districtCode
    ? districtInScope(coded.districtCode, named.districtCode) ? coded : named
    : named?.districtCode ? named : coded || named
  if (!target) return null
  if (announcementDate && homeDistrict && announcementDate < homeDistrict.validFrom && !['51', '52'].includes(homeDistrict.provinceCode)) {
    const parent = parentCityCode(homeDistrict.code)
    const parentCity = parent ? districtByCode.get(parent) : undefined
    // The parent city can establish an unchanged broader scope for a newly
    // added ordinary 구. A reassigned city/county has no such proof here.
    if (!parentCity || announcementDate < parentCity.validFrom) return null
  }
  // Never apply the post-merger province to a notice published before it existed.
  if (announcementDate && target.provinceCode === '12' && announcementDate < '2026-07-01') return null
  if (target.provinceCode !== province.code) {
    // Current merged territory cannot prove whether an old notice meant its
    // former 광주 or 전남 portion, even when the strings look related.
    return false
  }
  if (!target.districtCode) return true
  if (target.provinceCode === '36') return true
  if (!homeDistrict) return null
  const targetDistrict = districtByCode.get(target.districtCode)!
  if (announcementDate && announcementDate < targetDistrict.validFrom && !['51', '52'].includes(targetDistrict.provinceCode)) return null
  if (parentCityCode(targetDistrict.code) === homeDistrict.code) return null
  return districtInScope(homeDistrict.code, targetDistrict.code)
}
