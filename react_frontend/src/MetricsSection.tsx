import React, { useEffect, useState, useMemo, useCallback } from "react";
import axios from "axios";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
} from "chart.js";
import { Line } from "react-chartjs-2";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip);

const API_BASE = "";

// Unix timestamps from the server are in seconds; JS Date needs milliseconds.
const MS_PER_SEC = 1000;

// If the latest snapshot for a device is older than this, it is shown as stale.
const STALENESS_SECS = 120;

const COLORS = [
  "#2196F3", "#4CAF50", "#FF9800", "#F44336",
  "#9C27B0", "#00BCD4", "#FF5722", "#607D8B",
];

// Hex opacity suffixes appended to COLORS entries
const COLOR_OPACITY_FILL   = "22"; // ~13% — chart area fill
const COLOR_OPACITY_BORDER = "55"; // ~33% — card border
const COLOR_OPACITY_BG     = "11"; // ~7%  — card background

const CHART = {
  MAX_X_TICKS:  8,
  TICK_SIZE:    10,
  LINE_TENSION: 0.2,
  POINT_RADIUS: 2,
  HEIGHT:       "140px",
};

interface Metric {
  metric_name:  string;
  metric_value: number;
  unit:         string;
}

interface Snapshot {
  snapshot_id:     string;
  collected_at:    number;
  received_at:     number;
  device_id:       string;
  device_name:     string;
  source:          string;
  aggregator_id:   string;
  aggregator_name: string;
  metrics:         Metric[];
}

// ── Chart ─────────────────────────────────────────────────────────────────────

function MetricChart({ values, labels, color }: {
  values: number[];
  labels: string[];
  color:  string;
}) {
  return (
    <div style={{ height: CHART.HEIGHT }}>
      <Line
        data={{
          labels,
          datasets: [{
            data:            values,
            borderColor:     color,
            backgroundColor: color + COLOR_OPACITY_FILL,
            fill:            false,
            tension:         CHART.LINE_TENSION,
            pointRadius:     CHART.POINT_RADIUS,
          }],
        }}
        options={{
          responsive:          true,
          maintainAspectRatio: false,
          animation:           false,
          plugins:             { legend: { display: false } },
          scales: {
            x: { ticks: { maxTicksLimit: CHART.MAX_X_TICKS, font: { size: CHART.TICK_SIZE } } },
            y: { ticks: { font: { size: CHART.TICK_SIZE } } },
          },
        }}
      />
    </div>
  );
}

// ── One device's data ─────────────────────────────────────────────────────────

function DeviceSection({ snaps }: { snaps: Snapshot[] }) {
  const latest    = snaps[snaps.length - 1];
  const latencyMs = Math.round((latest.received_at - latest.collected_at) * MS_PER_SEC);
  const isStale   = (Date.now() / MS_PER_SEC - latest.collected_at) > STALENESS_SECS;

  const metricNames = useMemo(() => {
    const seen = new Set<string>();
    snaps.forEach((s) => s.metrics.forEach((m) => seen.add(m.metric_name)));
    return Array.from(seen).sort();
  }, [snaps]);

  return (
    <div style={{ border: "1px solid #e0e0e0", borderRadius: "10px", marginBottom: "40px", overflow: "hidden" }}>

      {/* Device header */}
      <div style={{
        background: "#f0f4f8", borderBottom: "1px solid #e0e0e0",
        padding: "16px 20px", display: "flex", justifyContent: "space-between",
        alignItems: "flex-start", flexWrap: "wrap", gap: "8px",
      }}>
        <div>
          <div style={{ fontSize: "17px", fontWeight: 700, color: "#1a1a1a" }}>
            {latest.device_name || "–"}
          </div>
          <div style={{ fontSize: "12px", color: "#666", marginTop: "2px" }}>
            Collected by <strong>{latest.aggregator_name || latest.aggregator_id || "–"}</strong>
          </div>
        </div>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <span style={{
            fontSize: "11px", fontWeight: 600,
            color: isStale ? "#FF9800" : "#4CAF50",
          }}>
            {isStale ? "● Stale" : "● Live"}
          </span>
          <span style={{
            fontSize: "11px", fontWeight: 600, background: "#e3edf7",
            color: "#2563a8", borderRadius: "4px", padding: "3px 8px",
          }}>
            {latest.source}
          </span>
        </div>
      </div>

      <div style={{ padding: "16px 20px" }}>

        {/* Snapshot metadata */}
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))",
          gap: "6px 20px", marginBottom: "20px", fontSize: "12px", color: "#555",
        }}>
          <div>
            <span style={{ color: "#999" }}>Device</span><br />
            <span style={{ fontFamily: "monospace", fontSize: "11px", color: "#222" }}>{latest.device_name || "–"}</span>
          </div>
          <div>
            <span style={{ color: "#999" }}>Source</span><br />
            <span style={{ fontFamily: "monospace", fontSize: "11px", color: "#222" }}>{latest.source}</span>
          </div>
          <div>
            <span style={{ color: "#999" }}>Aggregator</span><br />
            <span style={{ fontFamily: "monospace", fontSize: "11px", color: "#222" }}>{latest.aggregator_name || "–"}</span>
          </div>
          <div>
            <span style={{ color: "#999" }}>Device ID</span><br />
            <span style={{ fontFamily: "monospace", fontSize: "11px", color: "#222" }}>{latest.device_id}</span>
          </div>
          <div>
            <span style={{ color: "#999" }}>Aggregator ID</span><br />
            <span style={{ fontFamily: "monospace", fontSize: "11px", color: "#222" }}>{latest.aggregator_id}</span>
          </div>
          <div>
            <span style={{ color: "#999" }}>Snapshot ID</span><br />
            <span style={{ fontFamily: "monospace", fontSize: "11px", color: "#222" }}>{latest.snapshot_id}</span>
          </div>
          <div>
            <span style={{ color: "#999" }}>Collected at</span><br />
            <span style={{ fontSize: "12px", color: "#222" }}>{new Date(latest.collected_at * MS_PER_SEC).toLocaleString()}</span>
          </div>
          <div>
            <span style={{ color: "#999" }}>Received at</span><br />
            <span style={{ fontSize: "12px", color: "#222" }}>{new Date(latest.received_at * MS_PER_SEC).toLocaleString()}</span>
          </div>
          <div>
            <span style={{ color: "#999" }}>Latency</span><br />
            <span style={{ fontSize: "12px", color: "#222" }}>{latencyMs} ms</span>
          </div>
          <div>
            <span style={{ color: "#999" }}>Snapshots loaded</span><br />
            <span style={{ fontSize: "12px", color: "#222" }}>{snaps.length}</span>
          </div>
        </div>

        {/* Current metric value cards */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", marginBottom: "24px" }}>
          {metricNames.map((name, i) => {
            const m     = latest.metrics.find((m) => m.metric_name === name);
            if (!m) return null;
            const color = COLORS[i % COLORS.length];
            return (
              <div key={name} style={{
                flex: "1 1 130px", padding: "12px 14px", borderRadius: "8px",
                border: `1px solid ${color}${COLOR_OPACITY_BORDER}`, background: color + COLOR_OPACITY_BG,
              }}>
                <div style={{ fontSize: "10px", color: "#888", letterSpacing: "0.5px", marginBottom: "4px" }}>
                  {name.replace(/_/g, " ").toUpperCase()}
                </div>
                <div style={{ fontSize: "20px", fontWeight: 700, color: "#111" }}>
                  {m.metric_value % 1 === 0 ? m.metric_value : m.metric_value.toFixed(2)}
                  <span style={{ fontSize: "12px", fontWeight: 400, color: "#888", marginLeft: "3px" }}>
                    {m.unit}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Historical charts */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "16px" }}>
          {metricNames.map((name, i) => {
            const values: number[] = [];
            const labels: string[] = [];
            snaps.forEach((s) => {
              const m = s.metrics.find((m) => m.metric_name === name);
              if (m) {
                values.push(m.metric_value);
                labels.push(new Date(s.collected_at * MS_PER_SEC).toLocaleTimeString());
              }
            });
            const unit = latest.metrics.find((m) => m.metric_name === name)?.unit ?? "";
            return (
              <div key={name}>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "#444", marginBottom: "4px" }}>
                  {name.replace(/_/g, " ").toUpperCase()}{unit ? ` (${unit})` : ""}
                </div>
                <MetricChart values={values} labels={labels} color={COLORS[i % COLORS.length]} />
              </div>
            );
          })}
        </div>

      </div>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

interface MetricsSectionProps {
  source:        string;
  limit?:        number;
  pollInterval?: number;
}

export default function MetricsSection({ source, limit = 50, pollInterval = 5000 }: MetricsSectionProps) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [fetchError, setFetchError] = useState(false);

  const fetchSnapshots = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/api/metrics`, { params: { source, limit } });
      setSnapshots(res.data.snapshots);
      setFetchError(false);
    } catch (err) {
      console.error(`Failed to fetch metrics for source "${source}":`, err);
      setFetchError(true);
    }
  }, [source, limit]);

  useEffect(() => {
    fetchSnapshots();
    const interval = setInterval(fetchSnapshots, pollInterval);
    return () => clearInterval(interval);
  }, [fetchSnapshots, pollInterval]);

  const deviceGroups = useMemo(() => {
    const groups: Record<string, Snapshot[]> = {};
    for (const snap of snapshots) {
      if (!groups[snap.device_id]) groups[snap.device_id] = [];
      groups[snap.device_id].push(snap);
    }
    return Object.values(groups).sort((a, b) =>
      (a[0].device_name || "").localeCompare(b[0].device_name || "")
    );
  }, [snapshots]);

  if (fetchError)           return <p style={{ color: "red",  fontSize: "14px" }}>Failed to load data for source "{source}".</p>;
  if (deviceGroups.length === 0) return <p style={{ color: "#999", fontSize: "14px" }}>No data yet for source "{source}".</p>;

  return (
    <div>
      {deviceGroups.map((snaps) => (
        <DeviceSection key={snaps[0].device_id} snaps={snaps} />
      ))}
    </div>
  );
}
