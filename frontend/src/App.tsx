import { useState, useEffect, useCallback } from 'react'
import './App.css'

/* ========================= */
/* Types                     */
/* ========================= */

interface Metric {
  metric_name: string
  metric_value: number
  unit: string
}

interface MetricsMessage {
  message_id: string
  device_id: string
  source: string
  collected_at: number
  received_at: number
  metrics: Metric[]
}

interface ApiResponse {
  status: string
  count: number
  messages: MetricsMessage[]
}

/* ========================= */
/* Helpers                   */
/* ========================= */

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString()
}

function buildQuery(params: {
  source?: string
  device_id?: string
  limit?: number
  since?: number
}) {
  const query = new URLSearchParams()
  if (params.source) query.append('source', params.source)
  if (params.device_id) query.append('device_id', params.device_id)
  if (params.limit) query.append('limit', params.limit.toString())
  if (params.since) query.append('since', params.since.toString())
  return query.toString()
}

/* ========================= */
/* Component                 */
/* ========================= */

export default function App() {
  const [messages, setMessages] = useState<MetricsMessage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [source, setSource] = useState('')
  const [deviceId, setDeviceId] = useState('')

  const fetchMetrics = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const query = buildQuery({
        source: source || undefined,
        device_id: deviceId || undefined,
        limit: 100
      })

      const response = await fetch(`/api/metrics?${query}`)

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data: ApiResponse = await response.json()

      if (data.status !== 'success') {
        throw new Error('API returned failure status')
      }

      setMessages(data.messages)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch metrics')
      setMessages([])
    } finally {
      setLoading(false)
    }
  }, [source, deviceId])

  useEffect(() => {
    fetchMetrics()
  }, [fetchMetrics])

  return (
    <div className="app">
      <h1>Metrics Dashboard</h1>

      <div>
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All Sources</option>
          <option value="local">local</option>
          <option value="mobile">mobile</option>
          <option value="wikipedia">wikipedia</option>
        </select>

        <input
          type="text"
          value={deviceId}
          onChange={(e) => setDeviceId(e.target.value)}
          placeholder="Device ID"
        />

        <button onClick={fetchMetrics} disabled={loading}>
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {error && <p>{error}</p>}

      <ul>
        {messages.map((msg) => (
          <li key={msg.message_id}>
            <strong>{msg.device_id}</strong> | {msg.source} | {formatTime(msg.collected_at)}
            <ul>
              {msg.metrics.map((m) => (
                <li key={m.metric_name}>
                  {m.metric_name}: {m.metric_value} {m.unit}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  )
}