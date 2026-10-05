import type { LocalProfile } from './types'
import type { OpportunityResult } from './opportunity'
import { POINTS_SOURCE } from './points'

function Evidence({ url }: { url?: string }) { return url && /^https:\/\//.test(url) ? <a href={url} target="_blank" rel="noopener noreferrer">공식 근거 ↗</a> : null }
export function OpportunityPanel({ value, onProfile }: { value: OpportunityResult; onProfile: (field?: keyof LocalProfile) => void }) {
  if (!value.rows.length && !value.unavailableMethod) return null
  return <section className="opportunity-panel" aria-label="지역·가점 당첨 기회"><h5>지역·가점 당첨 기회</h5><p className="opportunity-help">신청 자격과 별도로 보는 선정 방식입니다.</p>
    {value.rows.map((row, i) => <div className={`opportunity-row${row.limited ? ' limited' : ''}`} key={i}><small>{row.units.join(' · ')} · {row.supplyTypes.join(' · ')}</small><strong>{row.label}</strong><p>{row.detail}</p><Evidence url={row.evidenceUrl} />{row.benchmark && <p className="points-benchmark"><strong>{row.benchmark.label}</strong> · {row.benchmark.minimum}점{row.benchmark.difference != null ? ` · 내 가점 ${row.benchmark.difference >= 0 ? '+' : ''}${row.benchmark.difference}점` : ' · 내 가점 미확정'}<Evidence url={row.benchmark.evidenceUrl} /><small>같은 공고·주택형·지역의 공식 가점제 결과입니다. 미래 당첨확률을 뜻하지 않습니다.</small></p>}</div>)}
    {value.points && <div className="my-points"><strong>내 가점 {value.points.total !== null ? `${value.points.total} / 84점` : `총점 미확정 · 확인된 항목 ${value.points.confirmed}점`}</strong><small>공고 기준일 {value.points.date || '미확인'}</small>{value.points.parts.map((part) => <div className="points-part" key={part.label}><span>{part.label} <b>{part.score === null ? '미확인' : `${part.score} / ${part.maximum}점`}</b></span><p>{part.detail}</p>{part.score === null && part.field && <button type="button" className="text-button" onClick={() => onProfile(part.field)}>필요한 사실 입력하기</button>}</div>)}<Evidence url={POINTS_SOURCE} />{!value.rows.some((row) => row.benchmark) && <p className="opportunity-help">동일 주택형·지역의 공식 당첨 최저가점 비교 자료가 없습니다.</p>}</div>}
    {value.unavailableMethod && <p className="opportunity-help">일부 주택형의 공식 가점·추첨 비율은 아직 확보하지 못했습니다.</p>}
  </section>
}
