import type { GetMetricsResponse } from './types'

const defaultLimit = 100

export interface GetMetricsParams {
  device_id?: string
  source?: string
  limit?: number
  since?: number
}

/** Fetch metrics from the backend API. Uses Vite proxy in dev so /api goes to Flask. */
export async function getMetrics(params: GetMetricsParams = {}): Promise<GetMetricsResponse> {
  const search = new URLSearchParams()
  if (params.device_id) search.set('device_id', params.device_id)
  if (params.source) search.set('source', params.source)
  search.set('limit', String(params.limit ?? defaultLimit))
  if (params.since != null) search.set('since', String(params.since))

  const url = `/api/metrics?${search.toString()}`
  const res = await fetch(url)
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API error ${res.status}: ${body || res.statusText}`)
  }
  return res.json() as Promise<GetMetricsResponse>
}
