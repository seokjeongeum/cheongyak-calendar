import { evaluateCatalog, type EvaluationRequest, type EvaluationResponse } from './evaluation'
import type { Notice } from './types'
const scope = globalThis as unknown as { onmessage: ((event: MessageEvent<EvaluationRequest>) => void) | null; postMessage: (data: EvaluationResponse) => void }
let catalog: Notice[] = []
scope.onmessage = ({ data }) => {
  if (data.catalog) catalog = data.catalog
  try { scope.postMessage(evaluateCatalog(catalog, data)) }
  catch { scope.postMessage({ revision: data.revision, evaluations: {}, elapsedMs: 0, error: '조건 계산을 완료하지 못했습니다. 입력은 브라우저에 보존됩니다.' }) }
}
