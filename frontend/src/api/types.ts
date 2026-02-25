/** Matches the Flask GET /api/metrics response and message shape. */

export interface MetricEntry {
  metric_name: string
  metric_value: number
}

export interface MetricsMessage {
  message_id: string
  device_id: string
  source: string
  collected_at: number
  received_at: number
  metrics: MetricEntry[]
}

export interface GetMetricsResponse {
  status: string
  count: number
  messages: MetricsMessage[]
}
