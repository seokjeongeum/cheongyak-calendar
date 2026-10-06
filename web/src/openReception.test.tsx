import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { activeApplicationEvents, applicationAvailabilityInMonth, applicationDatesInMonth, dateIsInEvent, hasVisibleApplication, MiniCalendar, NoticeCard } from './App'
import { hasResidenceCandidate } from './candidates'
import { isOpenEndedReception, nextDeadline } from './deadlines'
import { candidateInRange, evaluateNotice } from './evaluation'
import { demoNotices } from './demo'
import { EMPTY_PROFILE, type Notice, type NoticeEvent } from './types'

const today = '2026-10-06'
const profile = { ...EMPTY_PROFILE, region: '서울특별시', district: '강남구', regionCode: '11', districtCode: '11680' }
const event = (label = '상시 접수', start_date = '2026-09-01'): NoticeEvent => ({ kind: 'application', label, start_date, end_date: null })
const notice = (events: NoticeEvent[] = [event()]): Notice => ({
  ...demoNotices(new Date('2026-10-06T12:00:00+09:00'))[0], id: 'open-reception',
  title: '상시 접수 공고', category: 'unsold', application_method: 'unranked_after', housing_kind: 'not_applicable',
  region_name: '서울특별시 강남구', region_code: '11680', address: '서울특별시 강남구',
  events, rules: [], prices: [], offered_supplies: [], competitions: [], rules_complete: false,
})

describe('explicit official ongoing reception', () => {
  it.each(['상시 접수', '마감 시까지', '소진\t시까지', '종료일 미공개'])('keeps %s visible without inventing an end', (label) => {
    const item = notice([event(label)])
    expect(isOpenEndedReception(item.events[0])).toBe(true)
    expect(hasVisibleApplication(item, today, '2026-11-30')).toBe(true)
    expect(activeApplicationEvents(item, today)).toEqual(item.events)
    expect(dateIsInEvent(item.events[0], '2026-11-30')).toBe(true)
    expect(nextDeadline(item, today)).toBeNull()
    expect(item.events[0].end_date).toBeNull()
  })

  it('keeps ordinary missing ends as single-day schedules and respects published ends', () => {
    const absentEnd = { kind: 'application', label: '상시 접수', start_date: '2026-09-01' } as NoticeEvent
    expect(isOpenEndedReception(absentEnd)).toBe(true)
    expect(dateIsInEvent(absentEnd, today)).toBe(true)
    const daily = event('1순위')
    expect(hasVisibleApplication(notice([daily]), today, '2026-11-30')).toBe(false)
    expect(dateIsInEvent(daily, daily.start_date)).toBe(true)
    expect(dateIsInEvent(daily, today)).toBe(false)
    expect(isOpenEndedReception({ ...event(), end_date: '2026-09-30' })).toBe(false)
    expect(isOpenEndedReception(event('상시 계약일'))).toBe(false)
    expect(isOpenEndedReception({ ...event(), kind: 'contract' })).toBe(false)
    expect(hasVisibleApplication(notice([{ ...event(), end_date: '2026-09-30' }]), today, '2026-11-30')).toBe(false)
    expect(hasVisibleApplication(notice([event('상시 접수', '2026-12-01')]), today, '2026-11-30')).toBe(false)
  })

  it('bounds ongoing calendar dots and availability to the selected month and today', () => {
    const item = notice()
    const dates = applicationDatesInMonth([item], '2026-10', today)
    expect(dates.size).toBe(26)
    expect([...dates][0]).toBe(today)
    expect([...dates].at(-1)).toBe('2026-10-31')
    expect(applicationAvailabilityInMonth([item], '2026-10', today, profile).size).toBe(26)
    const evaluation = evaluateNotice(item, profile, today, Date.parse(`${today}T00:00:00+09:00`))
    const html = renderToStaticMarkup(<MiniCalendar month="2026-10" today={today} selectedDate={null} notices={[item]} evaluations={{ [item.id]: evaluation }} onMonth={() => {}} onSelect={() => {}} />)
    expect(html.match(/<i aria-hidden="true"/g)?.length).toBe(26)
    expect(applicationDatesInMonth([notice([event('1순위', '2026-10-08')])], '2026-10', today)).toEqual(new Set(['2026-10-08']))
  })

  it('counts ongoing candidate events and shows an explicit missing end on the card', () => {
    const item = notice()
    const evaluation = evaluateNotice(item, profile, today, Date.parse(`${today}T00:00:00+09:00`))
    expect(hasResidenceCandidate(item, profile, today, '2026-11-30')).toBe(true)
    expect(candidateInRange(item, evaluation, today, '2026-11-30')).toBe(true)
    const html = renderToStaticMarkup(<NoticeCard notice={item} profile={profile} demoMode={false} today={today} viewStart={today} viewEnd="2026-11-30" decision={evaluation.decision} evaluation={evaluation} now={0} onProfile={() => {}} />)
    expect(html).toContain('현재 접수 중')
    expect(html).toContain('접수 중 · 종료일 미공개')
    expect(html).toContain('접수일 후보 · 원문 확인')
    const dated = notice([{ ...event('1순위', '2026-10-08'), end_date: '2026-10-08' }])
    expect(nextDeadline(dated, today)!.localeCompare(nextDeadline(item, today) || '9999-12-31')).toBeLessThan(0)
  })
})
