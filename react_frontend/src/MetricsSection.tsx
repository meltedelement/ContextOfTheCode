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

const COLORS = [
  "#2196F3", "#4CAF50", "#FF9800", "#F44336",
  "#9C27B0", "#00BCD4", "#FF5722", "#607D8B",
];

interface Metric {
  metric_name: string;
  metric_value: number;
  unit: string;
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

function MetricChart({ values, labels, color }: { values: number[]; labels: string[]; color: string }) {
  const data = {
    labels,
    datasets: [{ data: values, borderColor: color, backgroundColor: color + "22", fill: false, tension: 0.2, pointRadius: 2 }],
  };
  const options = {
    responsive: true,
    animation: false as const,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { maxTicksLimit: 8, font: { size: 10 } } },
      y: { ticks: { font: { size: 10 } } },
    },
  };
  return <Line data={data} options={options} />;
}

function DeviceSection({ snaps }: { snaps: Snapshot[] }) {
  const latest = snaps[snaps.length - 1];
  const latencyMs = Math.round((latest.received_at - latest.collected_at) * 1000);

  const metricNames = useMemo(() => {
    const seen = new Set<string>();
    snaps.forEach((s) => s.metrics.forEach((m) => seen.add(m.metric_name)));
    return Array.from(seen);
  }, [snaps]);

  return (
    <div style={{
      border: "1px solid #e0e0e0",
      borderRadius: "10px",
      marginBottom: "40px",
      overflow: "hidden",
    }}>
      {/* ── Device header ── */}
      <div style={{
        background: "#f0f4f8",
        borderBottom: "1px solid #e0e0e0",
        padding: "16px 20px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        flexWrap: "wrap",
        gap: "8px",
      }}>
        <div>
          <div style={{ fontSize: "17px", fontWeight: 700, color: "#1a1a1a" }}>
            {latest.device_name || "–"}
          </div>
          <div style={{ fontSize: "12px", color: "#666", marginTop: "2px" }}>
            Collected by <strong>{latest.aggregator_name || latest.aggregator_id}</strong>
          </div>
        </div>
        <span style={{
          fontSize: "11px",
          fontWeight: 600,
          background: "#e3edf7",
          color: "#2563a8",
          borderRadius: "4px",
          padding: "3px 8px",
          letterSpacing: "0.3px",
        }}>
          {latest.source}
        </span>
      </div>

      <div style={{ padding: "16px 20px" }}>
        {/* ── Snapshot metadata ── */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))",
          gap: "6px 20px",
          marginBottom: "20px",
          fontSize: "12px",
          color: "#555",
        }}>
          {(([
            ["Device ID",        latest.device_id,       true],
            ["Aggregator ID",    latest.aggregator_id,   true],
            ["Snapshot ID",      latest.snapshot_id,     true],
            ["Collected at",     new Date(latest.collected_at * 1000).toLocaleString()],
            ["Received at",      new Date(latest.received_at  * 1000).toLocaleString()],
            ["Latency",          `${latencyMs} ms`],
            ["Snapshots loaded", String(snaps.length)],
          ]) as [string, string, boolean?][]).map(([label, value, mono]) => (
            <div key={label}>
              <span style={{ color: "#999" }}>{label}: </span>
              <span style={{ fontFamily: mono ? "monospace" : "inherit", fontSize: mono ? "11px" : "12px" }}>
                {value}
              </span>
            </div>
          ))}
        </div>

        {/* ── Current metric values ── */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", marginBottom: "24px" }}>
          {metricNames.map((name, i) => {
            const m = latest.metrics.find((m) => m.metric_name === name);
            if (!m) return null;
            const color = COLORS[i % COLORS.length];
            return (
              <div key={name} style={{
                flex: "1 1 130px",
                padding: "12px 14px",
                borderRadius: "8px",
                border: `1px solid ${color}55`,
                background: color + "11",
              }}>
                <div style={{ fontSize: "10px", color: "#888", letterSpacing: "0.5px", marginBottom: "4px" }}>
                  {name.replace(/_/g, " ").toUpperCase()}
                </div>
                <div style={{ fontSize: "20px", fontWeight: 700, color: "#111" }}>
                  {m.metric_value % 1 === 0 ? m.metric_value : m.metric_value.toFixed(2)}
                  <span style={{ fontSize: "12px", fontWeight: 400, color: "#888", marginLeft: "3px" }}>{m.unit}</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Historical charts ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
          {metricNames.map((name, i) => {
            const values: number[] = [];
            const labels: string[] = [];
            snaps.forEach((s) => {
              const m = s.metrics.find((m) => m.metric_name === name);
              if (m) {
                values.push(m.metric_value);
                labels.push(new Date(s.collected_at * 1000).toLocaleTimeString());
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

interface MetricsSectionProps {
  source: string;
  limit?: number;
  pollInterval?: number;
}

export default function MetricsSection({ source, limit = 50, pollInterval = 5000 }: MetricsSectionProps) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);

  const fetchSnapshots = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/api/metrics`, { params: { source, limit } });
      setSnapshots(res.data.snapshots);
    } catch (err) {
      console.error(`Failed to fetch metrics for source "${source}":`, err);
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
    return Object.values(groups);
  }, [snapshots]);

  if (deviceGroups.length === 0) {
    return <p style={{ color: "#999", fontSize: "14px" }}>No data yet for source "{source}".</p>;
  }

  return (
    <div>
      {deviceGroups.map((snaps) => (
        <DeviceSection key={snaps[0].device_id} snaps={snaps} />
      ))}
    </div>
  );
}
