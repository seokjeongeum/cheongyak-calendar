import { describe, expect, it } from 'vitest'
import { hogangnonoDetailUrl } from './hogangnono'

describe('verified Hogangnono detail links', () => {
  it.each([
    ['더샵 오산역아크시티 오피스텔', 'officetel', 'gZL96'],
    ['산곡역자이힐스테이트앤하늘채', 'apt', 'faQec'],
    ['옥정중앙역 대방 디에트르Ⅱ', 'officetel', 'gXLb8'],
    ['옥정중앙역 대방 디에트르II', 'officetel', 'gXLb8'],
    ['도안 푸르지오 디아델 29블록', 'unsold', 'gxh04'],
    ['도안 푸르지오 디아델 31블록', 'unsold', 'gzsac'],
    ['세종 리더스포레 나릿재마을 1단지', 'unsold', 'ctId8'],
    ['천안 아이파크 시티 2단지(2회차)', 'apt', 'ghL9c'],
    ['선운지구다사로움 일반공급 잔여세대 (선착순) 입주자 모집공고', 'public_sale', '9HJc2'],
    ['수원당수 A-3블록 신혼희망타운(공공분양) 잔여세대 추가입주자 모집공고(입주 후 해약세대)', 'public_sale', 'dQ82e'],
    ['더샵 동인센트리체', 'apt', 'fq81f'],
    ['진도 승원팰리체 더 테라스', 'apt', 'gWT61'],
    ['제주시 이도이동 아이린8차 아파트', 'apt', 'gZV3d'],
    ['청주 가경 아이파크 7단지', 'apt', 'gNvd8'],
    ['청주 가경 아이파크 8단지', 'apt', 'gNwa8'],
  ])('links %s to its verified complex', (title, category, id) => {
    expect(hogangnonoDetailUrl({ title, category })).toBe(`https://hogangnono.com/apt/${id}`)
  })

  it.each([
    ['더샵 오산역아크시티', 'apt'], ['더샵 오산역아크시티 오피스텔', 'apt'],
    ['옥정중앙역 대방 디에트르', 'officetel'], ['옥정중앙역 대방 디에트르Ⅰ', 'officetel'],
    ['천안 아이파크 시티 1단지', 'apt'], ['도안 푸르지오 디아델 28블록', 'unsold'],
    ['광주선운2 A-1,3블록 신혼희망타운', 'public_sale'], ['제주시 이도이동 아이린4차 아파트', 'apt'],
    ['', 'apt'],
  ])('does not replace an unresolved complex or category with a nearby result: %s', (title, category) => {
    expect(hogangnonoDetailUrl({ title, category })).toBeUndefined()
  })

  it('binds Asan to its verified current official project despite the detail page older parcel label', () => {
    const notice = { title: '아산 그랑시티필하우스', category: 'apt' }
    expect(hogangnonoDetailUrl({ ...notice, official_url: 'https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2026000267&pblancNo=2026000267' })).toBe('https://hogangnono.com/apt/gR477')
    expect(hogangnonoDetailUrl(notice)).toBeUndefined()
    expect(hogangnonoDetailUrl({ ...notice, official_url: 'https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2026000468&pblancNo=2026000468' })).toBeUndefined()
  })
})
