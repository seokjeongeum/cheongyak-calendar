import type { Notice } from './types'

// Detail pages checked by name, location and housing category. IDs are
// published Hogangnono links; never derive an ID or substitute a nearby phase.
const VERIFIED_COMPLEXES: { id: string; names: string[]; office?: boolean; titlePattern?: RegExp; officialNumber?: string }[] = [
  { id: 'gZL96', names: ['더샵 오산역아크시티 오피스텔', '더샵오산역아크시티(오)'], office: true },
  { id: 'faQec', names: ['산곡역자이힐스테이트앤하늘채', '산곡역자이힐스테이트&하늘채'] },
  { id: 'gXLb8', names: ['옥정중앙역 대방 디에트르Ⅱ'], office: true },
  { id: '9HJc2', names: ['선운지구다사로움', '선운다사로움'], titlePattern: /^선운(?:지구)?다사로움(?:일반공급)?잔여세대\(선착순\)입주자모집공고$/u },
  { id: 'fq81f', names: ['더샵 동인센트리체'] },
  { id: 'gxh04', names: ['도안 푸르지오 디아델 29블록', '도안푸르지오디아델(29블록)'] },
  { id: 'gzsac', names: ['도안 푸르지오 디아델 31블록', '도안푸르지오디아델(31블록)'] },
  { id: 'ctId8', names: ['세종 리더스포레 나릿재마을 1단지', '나릿재마을1단지세종리더스포레'] },
  { id: 'dQ82e', names: ['수원당수 A-3블록', '서수원한라비발디3단지'], titlePattern: /^수원당수A-3블록신혼희망타운\(공공분양\)잔여세대추가입주자모집공고\(입주후해약세대\)$/u },
  { id: 'ghL9c', names: ['천안 아이파크 시티 2단지'] },
  { id: 'gWT61', names: ['진도 승원팰리체 더 테라스', '진도팰리체4차'] },
  { id: 'gOO8d', names: ['향남역 그로브 스위첸'] },
  { id: 'fee66', names: ['잠실에떼르넬비욘드'], office: true },
  { id: 'gWN71', names: ['쌍용 더 플래티넘 한강'] },
  { id: 'gHV66', names: ['당산역 더클래스 한강', '소미더클래스한강'], office: true },
  { id: 'gNhd0', names: ['상동역 롯데캐슬 시그니처'] },
  { id: 'gA2fa', names: ['오남역 서희스타힐스 여의재 1단지'] },
  { id: 'gsv5a', names: ['용인 양지 서희스타힐스 하이뷰'] },
  { id: 'gNvd8', names: ['청주 가경 아이파크 7단지'] },
  { id: 'gNwa8', names: ['청주 가경 아이파크 8단지'] },
  { id: 'gEy40', names: ['한양립스 에듀포레'] },
  { id: 'gNOf2', names: ['힐스테이트 거제시그니처'] },
  { id: 'gR477', names: ['아산 그랑시티필하우스'], officialNumber: '2026000267' },
  { id: 'gZV3d', names: ['제주시 이도이동 아이린8차 아파트', '제주시이도이동아이린8차'] },
  { id: 'gKS2f', names: ['연제갤러리자이'] },
]

function normalizedTitle(title: string): string {
  return title.normalize('NFKC')
    .replace(/\s*\((?:\d+회차|조합원\s*취소분|계약취소주택|무순위|임의공급)\)\s*$/u, '')
    .replace(/\s+/gu, '').trim()
}

const complexes = VERIFIED_COMPLEXES.map((entry) => ({ ...entry, names: entry.names.map(normalizedTitle) }))

/** A verified detail URL only; unresolved complexes have no search fallback. */
export function hogangnonoDetailUrl(notice: Pick<Notice, 'title' | 'category'> & Partial<Pick<Notice, 'official_url'>>): string | undefined {
  const title = normalizedTitle(notice.title)
  const found = complexes.find((entry) => entry.names.includes(title) || entry.titlePattern?.test(title))
  if (!found || (found.office === true) !== (notice.category === 'officetel')) return undefined
  if (found.officialNumber) {
    try {
      const source = new URL(notice.official_url || '')
      if (source.protocol !== 'https:' || !['www.applyhome.co.kr', 'applyhome.co.kr'].includes(source.hostname)
        || source.searchParams.get('houseManageNo') !== found.officialNumber || source.searchParams.get('pblancNo') !== found.officialNumber) return undefined
    } catch { return undefined }
  }
  return `https://hogangnono.com/apt/${found.id}`
}
