import React, { useEffect, useState } from "react";
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

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
);

const API_BASE = "";

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
    plugins: {
      legend: { position: "top" as const },
      title: { display: true, text: title },
    },
  };
  return <Line data={data} options={options} />;
}

function App() {
  const [localSnapshots, setLocalSnapshots] = useState<Snapshot[]>([]);
  const [wikiSnapshots, setWikiSnapshots] = useState<Snapshot[]>([]);

  const fetchMetrics = async () => {
    try {
      const [localRes, wikiRes] = await Promise.all([
        axios.get(`${API_BASE}/api/metrics`, {
          params: { source: "local", limit: 50 },
        }),
        axios.get(`${API_BASE}/api/metrics`, {
          params: { source: "wikipedia", limit: 20 },
        }),
      ]);
      setLocalSnapshots(localRes.data.snapshots);
      setWikiSnapshots(wikiRes.data.snapshots);
    } catch (error) {
      console.error("Failed to fetch metrics:", error);
    }
  };

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 5000);
    return () => clearInterval(interval);
  }, []);

  const cpu = extractMetric(localSnapshots, "cpu_usage_percent");
  const ramPct = extractMetric(localSnapshots, "ram_usage_percent");
  const ramMb = extractMetric(localSnapshots, "ram_used_mb");
  const cpuTemp = extractMetric(localSnapshots, "cpu_temp_celsius");
  const wikiEdits = extractMetric(wikiSnapshots, "edit_count_last_minute");

  return (
    <div style={{ padding: "40px", maxWidth: "700px", margin: "0 auto" }}>
      <h1>Live System Metrics</h1>

      <h2>System</h2>
      <div style={{ display: "flex", flexDirection: "column", gap: "40px" }}>
        <MetricChart
          title="CPU Usage"
          label="CPU (%)"
          values={cpu.values}
          labels={cpu.labels}
          color="#2196F3"
        />
        <MetricChart
          title="RAM Usage"
          label="RAM (%)"
          values={ramPct.values}
          labels={ramPct.labels}
          color="#4CAF50"
        />
        <MetricChart
          title="RAM Used"
          label="RAM (MB)"
          values={ramMb.values}
          labels={ramMb.labels}
          color="#FF9800"
        />
        {cpuTemp.values.length > 0 && (
          <MetricChart
            title="CPU Temperature"
            label="Temp (°C)"
            values={cpuTemp.values}
            labels={cpuTemp.labels}
            color="#F44336"
          />
        )}
      </div>

      <h2 style={{ marginTop: "40px" }}>Wikipedia</h2>
      <MetricChart
        title="Wikipedia Edits"
        label="Edits/min"
        values={wikiEdits.values}
        labels={wikiEdits.labels}
        color="#9C27B0"
      />
    </div>
  );
}

export default App;
