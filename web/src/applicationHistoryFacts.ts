import { getEvaluationToday } from './factTimeline'
import type { ApplicationHistoryEvent, LocalProfile } from './types'

const EVENT_KINDS = ['winning', 'reserve_winning', 'contract', 'additional_resident_contract']
function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [y, m, d] = value.split('-').map(Number), parsed = new Date(Date.UTC(y, m - 1, d))
  return parsed.getUTCFullYear() === y && parsed.getUTCMonth() === m - 1 && parsed.getUTCDate() === d
}
export function applicationHistoryEventComplete(event: ApplicationHistoryEvent, today = getEvaluationToday()): boolean {
  return !!event.personId && /^(?:\d{10}|LH-[A-Z0-9-]{1,64})$/.test(event.projectId) && EVENT_KINDS.includes(event.eventKind) && validDate(event.eventDate) && event.eventDate <= today
}
function recordedAbsencePeople(profile: LocalProfile): Set<string> {
  const absent = new Set(profile.applicationHistoryAbsencePeople || [])
  // Saved no-history answers and earlier complete rosters already describe
  // those exact people. Preserve them without asking a second affirmation.
  if (profile.applicationHistoryPresence === false || profile.applicationHistoryComplete === true && profile.applicationHistoryEvents?.length > 0) for (const person of profile.applicationHistoryPeople || []) {
    if (!(profile.applicationHistoryEvents || []).some((event) => event.personId === person)) absent.add(person)
  }
  return absent
}
export function applicationHistoryPersonPresence(profile: LocalProfile, personId: string): boolean | null {
  if ((profile.applicationHistoryEvents || []).some((event) => event.personId === personId)) return true
  return recordedAbsencePeople(profile).has(personId) ? false : null
}
/** Dated events and explicit absence cover exact identities, never new family. */
export function applicationHistoryCoveredPeople(profile: LocalProfile, today = getEvaluationToday()): Set<string> {
  const covered = recordedAbsencePeople(profile)
  const events = profile.applicationHistoryEvents || []
  if (events.some((event) => !event.personId)) return new Set()
  for (const person of new Set(events.map((event) => event.personId).filter(Boolean))) {
    if (events.filter((event) => event.personId === person).every((event) => applicationHistoryEventComplete(event, today))) covered.add(person)
    else covered.delete(person)
  }
  return covered
}
