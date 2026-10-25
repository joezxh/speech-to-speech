import { api } from './client'
import type { AnalyzeBody, LogAnalysis, LogPage, LogQuery } from '@/types/logs'

/**
 * A.15. The multi-value filters are repeated keys (`process=a&process=b`), not
 * a comma list and not axios' default `process[]=`: this endpoint takes
 * `list[str] = Query(...)`, so a bracketed key would be ignored and the panel
 * would show everything while its chips said otherwise.
 */
function queryString(query: LogQuery): string {
  const params = new URLSearchParams()
  for (const value of query.process) params.append('process', value)
  for (const value of query.level) params.append('level', value)
  if (query.from) params.set('from', query.from)
  if (query.to) params.set('to', query.to)
  if (query.q) params.set('q', query.q)
  if (query.after) params.set('after', query.after)
  if (query.limit) params.set('limit', String(query.limit))
  return params.toString()
}

export const fetchLogs = (query: LogQuery): Promise<LogPage> =>
  api.get<LogPage>(`/logs?${queryString(query)}`)

/** A.16. One call, one LLM analysis, one audit row. */
export const analyzeLogs = (body: AnalyzeBody): Promise<LogAnalysis> =>
  api.post<LogAnalysis>('/logs/analyze', body)
