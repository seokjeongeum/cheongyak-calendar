import { describe, expect, it } from 'vitest'
import {
  REGION_CATALOG_METADATA, districtOptions, matchesRegionScope, parentCityCode,
  provinceAliases, provinceOptions, resolveLegacyRegion, scopeIsDistrict,
} from './regions'

const suwon = { region: '경기도', regionCode: '41', district: '수원시 영통구', districtCode: '41117' }

describe('official province and city catalog', () => {
  it('bundles the dated official source and hashes', () => {
    expect(REGION_CATALOG_METADATA.effectiveDate).toBe('2026-09-30')
    expect(REGION_CATALOG_METADATA.sourceFile).toBe('KIKcd_B.20260930.xlsx')
    expect(REGION_CATALOG_METADATA.sourceFileSha256).toMatch(/^[a-f0-9]{64}$/)
    expect(REGION_CATALOG_METADATA.sourceArchiveSha256).toBe('c9c2583919adfff992edc098fe7ea522e625fedabbfefedbd85564942c059d43')
  })

  it('contains current provinces and no superseded merged province choices', () => {
    const options = provinceOptions()
    expect(options).toContainEqual({ code: '12', name: '전남광주통합특별시' })
    expect(options).toContainEqual({ code: '51', name: '강원특별자치도' })
    expect(options).toContainEqual({ code: '52', name: '전북특별자치도' })
    expect(options.some((option) => ['29', '42', '45', '46'].includes(option.code))).toBe(false)
  })

  it('keeps city parents while excluding 읍면동 and branch offices', () => {
    const cities = districtOptions('41')
    expect(cities).toContainEqual({ code: '41110', name: '수원시', displayName: '수원시' })
    expect(cities.some((item) => !!item.parentCityCode)).toBe(false)
    expect(districtOptions('41', { includeOrdinaryDistricts: true })).toContainEqual({ code: '41117', name: '수원시 영통구', displayName: '수원시 영통구', parentCityCode: '41110' })
    expect(parentCityCode('41117')).toBe('41110')
    expect(cities.every((item) => item.code.length === 5 && !/[읍면동리]$|출장/.test(item.name))).toBe(true)
    expect(districtOptions('28').some((item) => /출장/.test(item.name))).toBe(false)
  })

  it('provides one Sejong option and 제주 administrative cities', () => {
    expect(districtOptions('36')).toEqual([{ code: '36110', name: '세종특별자치시', displayName: '세종특별자치시' }])
    expect(districtOptions('50').map((item) => item.name)).toEqual(['제주시', '서귀포시'])
  })

  it('uses current 인천 and 화성 districts', () => {
    expect(districtOptions('28').map((item) => item.name)).toEqual(expect.arrayContaining(['제물포구', '영종구', '서해구', '검단구']))
    expect(districtOptions('28').some((item) => ['중구', '서구'].includes(item.name))).toBe(false)
    expect(districtOptions('41', { includeOrdinaryDistricts: true })).toContainEqual({ code: '41597', name: '화성시 동탄구', displayName: '화성시 동탄구', parentCityCode: '41590' })
  })
})

describe('legacy profile migration', () => {
  it('migrates an exact unique official name', () => {
    expect(resolveLegacyRegion('경기도', '수원시 영통구')).toEqual({ ...suwon, needsReview: false })
    expect(resolveLegacyRegion('경기도', '수원시')).toMatchObject({ districtCode: '41110', needsReview: false })
  })

  it('does not guess a parent city from an abbreviated 구', () => {
    expect(resolveLegacyRegion('경기도', '영통구')).toMatchObject({ regionCode: '41', districtCode: '', district: '영통구', needsReview: true })
  })

  it('keeps ambiguous split and merged input for re-selection', () => {
    expect(resolveLegacyRegion('인천광역시', '중구')).toMatchObject({ regionCode: '28', districtCode: '', needsReview: true })
    expect(resolveLegacyRegion('광주광역시', '북구')).toMatchObject({ regionCode: '', districtCode: '', region: '광주광역시', needsReview: true })
    expect(resolveLegacyRegion('전라남도', '목포시')).toMatchObject({ regionCode: '', districtCode: '', needsReview: true })
  })

  it('supports geographic identity renames without treating merged territory as an alias', () => {
    expect(resolveLegacyRegion('강원도', '춘천시')).toMatchObject({ region: '강원특별자치도', regionCode: '51', districtCode: '51110', needsReview: false })
    expect(resolveLegacyRegion('전라북도', '익산시')).toMatchObject({ regionCode: '52', needsReview: false })
    expect(provinceAliases('전남광주통합특별시')).not.toContain('광주광역시')
  })
})

describe('announcement residence scopes', () => {
  it('matches a selected ordinary 구 to its parent city', () => {
    expect(matchesRegionScope(suwon, { region_name: '경기도 수원시' }, '2026-10-03')).toBe(true)
    expect(matchesRegionScope(suwon, { region_code: '4111000000' }, '2026-10-03')).toBe(true)
    expect(matchesRegionScope(suwon, { region_code: '41110', region_name: '수원시' })).toBe(true)
    expect(matchesRegionScope(suwon, { region_name: '수원시 권선구' })).toBe(false)
  })

  it('does not treat a city-only selection as proof of a 구-specific condition', () => {
    expect(matchesRegionScope({ region: '경기도', district: '수원시' }, { region_name: '수원시 영통구' })).toBeNull()
    expect(matchesRegionScope({ region: '경기도', district: '' }, { region_code: '41117' })).toBeNull()
  })

  it('distinguishes a different province from unrecognizable geography', () => {
    expect(matchesRegionScope(suwon, { region_code: '11', region_name: '서울특별시' })).toBe(false)
    expect(matchesRegionScope(suwon, { region_name: '경기도/서울특별시' })).toBeNull()
    expect(matchesRegionScope(suwon, { region_code: '4111710100' })).toBeNull()
    expect(matchesRegionScope({ region: '', district: '' }, { region_name: '경기도' })).toBeNull()
  })

  it('matches zero-padded province codes and provider codes with explicit official names', () => {
    expect(matchesRegionScope(suwon, { region_code: '4100000000' })).toBe(true)
    expect(matchesRegionScope(suwon, { region_code: '41000' })).toBe(true)
    expect(matchesRegionScope(suwon, { region_code: '410', region_name: '경기도' })).toBe(true)
    expect(matchesRegionScope(suwon, { region_code: '410' })).toBeNull()
  })

  it('rejects contradictory code and name while keeping the narrowest consistent scope', () => {
    expect(matchesRegionScope(suwon, { region_code: '11', region_name: '경기도' })).toBeNull()
    expect(matchesRegionScope(suwon, { region_code: '41113', region_name: '수원시' })).toBe(false)
    expect(matchesRegionScope(suwon, { region_code: '41', region_name: '수원시' })).toBe(true)
  })

  it('does not expand historical 광주 or 전남 conditions to the merged province', () => {
    const merged = { region: '전남광주통합특별시', regionCode: '12', district: '북구', districtCode: '12300' }
    expect(matchesRegionScope(merged, { region_name: '광주광역시' }, '2026-05-01')).toBeNull()
    expect(matchesRegionScope(merged, { region_code: '29' }, '2026-05-01')).toBeNull()
    expect(matchesRegionScope(merged, { region_name: '전라남도' }, '2026-10-03')).toBeNull()
    expect(matchesRegionScope(merged, { region_code: '12' }, '2026-05-01')).toBeNull()
    expect(matchesRegionScope(merged, { region_code: '12' }, '2026-10-03')).toBe(true)
  })

  it('guards newly split districts using the announcement date but keeps stable parent-city scope', () => {
    const dongtan = { region: '경기도', district: '화성시 동탄구' }
    expect(matchesRegionScope(dongtan, { region_name: '화성시 동탄구' }, '2026-01-01')).toBeNull()
    expect(matchesRegionScope(dongtan, { region_name: '화성시' }, '2026-01-01')).toBe(true)
    expect(matchesRegionScope(dongtan, { region_name: '화성시 동탄구' }, '2026-10-03')).toBe(true)
    expect(matchesRegionScope({ region: '인천광역시', district: '영종구' }, { region_name: '인천광역시 중구' }, '2026-10-03')).toBeNull()
  })

  it('handles plain 경기도 광주시 separately from former 광주광역시', () => {
    const home = { region: '경기도', district: '광주시' }
    expect(matchesRegionScope(home, { region_name: '광주시' })).toBe(true)
    expect(matchesRegionScope(home, { region_name: '경기도 광주시' })).toBe(true)
    expect(matchesRegionScope(home, { region_name: '광주광역시' })).toBeNull()
  })

  it('does not apply a current province to a county reassigned after the announcement', () => {
    const gunwi = { region: '대구광역시', district: '군위군' }
    expect(matchesRegionScope(gunwi, { region_name: '대구광역시' }, '2023-05-01')).toBeNull()
    expect(matchesRegionScope(gunwi, { region_name: '경상북도' }, '2023-05-01')).toBeNull()
    expect(matchesRegionScope(gunwi, { region_name: '대구광역시' }, '2026-10-03')).toBe(true)
  })

  it('identifies district scopes for choosing the correct continuous residence start date', () => {
    expect(scopeIsDistrict({ region_name: '세종특별자치시' })).toBe(false)
    expect(scopeIsDistrict({ region_name: '경기도' })).toBe(false)
    expect(scopeIsDistrict({ region_name: '경기도 수원시' })).toBe(true)
    expect(scopeIsDistrict({ region_code: '4111000000' })).toBe(true)
  })
})
