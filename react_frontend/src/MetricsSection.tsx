import React, { useEffect, useState, useMemo, useCallback } from "react";
import axios from "axios";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from "chart.js";
import { Line } from "react-chartjs-2";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

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
  snapshot_id: string;
  device_id: string;
  source: string;
  collected_at: number;
  received_at: number;
  metrics: Metric[];
}

function extractMetric(snapshots: Snapshot[], metricName: string) {
  const values: number[] = [];
  const labels: string[] = [];
  snapshots.forEach((snap) => {
    const m = snap.metrics.find((m) => m.metric_name === metricName);
    if (m !== undefined) {
      values.push(m.metric_value);
      labels.push(new Date(snap.collected_at * 1000).toLocaleTimeString());
    }
  });
  return { values, labels };
}

function MetricChart({
  title,
  label,
  values,
  labels,
  color,
}: {
  title: string;
  label: string;
  values: number[];
  labels: string[];
  color: string;
}) {
  const data = {
    labels,
    datasets: [
      {
        label,
        data: values,
        borderColor: color,
        backgroundColor: color + "33",
        fill: false,
        tension: 0.2,
      },
    ],
  };
  const options = {
    responsive: true,
    animation: false as const,
    plugins: {
      legend: { position: "top" as const },
      title: { display: true, text: title },
    },
  };
  return <Line key={labels[labels.length - 1]} data={data} options={options} />;
}

interface MetricsSectionProps {
  source: string;
  limit?: number;
  pollInterval?: number;
}

export default function MetricsSection({
  source,
  limit = 50,
  pollInterval = 5000,
}: MetricsSectionProps) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);

  const fetchSnapshots = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/api/metrics`, {
        params: { source, limit },
      });
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

  const metricNames = useMemo(() => {
    const seen = new Set<string>();
    snapshots.forEach((s) => s.metrics.forEach((m) => seen.add(m.metric_name)));
    return Array.from(seen);
  }, [snapshots]);

  if (metricNames.length === 0) {
    return <p style={{ color: "#999", fontSize: "14px" }}>No data yet for source "{source}".</p>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "40px" }}>
      {metricNames.map((name, i) => {
        const { values, labels } = extractMetric(snapshots, name);
        const pretty = name.replace(/_/g, " ");
        return (
          <MetricChart
            key={name}
            title={pretty}
            label={pretty}
            values={values}
            labels={labels}
            color={COLORS[i % COLORS.length]}
          />
        );
      })}
    </div>
  );
}
