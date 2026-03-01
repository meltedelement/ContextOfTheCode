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

const API_BASE = "http://localhost:5001";

interface Metric {
  metric_name: string;
  metric_value: number;
  unit: string;
}

interface Snapshot {
  snapshot_id: string;
  device_id: string;
  collected_at: number;
  metrics: Metric[];
}

function App() {
  const [cpuValues, setCpuValues] = useState<number[]>([]);
  const [labels, setLabels] = useState<string[]>([]);

  const fetchMetrics = async () => {
    try {
      const response = await axios.get(`${API_BASE}/api/metrics`, {
        params: { limit: 20 },
      });

      const snapshots: Snapshot[] = response.data.snapshots;

      const newCpu: number[] = [];
      const newLabels: string[] = [];

      snapshots.forEach((snap) => {
        const cpuMetric = snap.metrics.find(
          (m) => m.metric_name === "cpu_usage_percent"
        );

        if (cpuMetric) {
          newCpu.push(cpuMetric.metric_value);
          newLabels.push(
            new Date(snap.collected_at * 1000).toLocaleTimeString()
          );
        }
      });

      setCpuValues(newCpu);
      setLabels(newLabels);
    } catch (error) {
      console.error("Failed to fetch metrics:", error);
    }
  };

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 2000);
    return () => clearInterval(interval);
  }, []);

  const data = {
    labels: labels,
    datasets: [
      {
        label: "CPU Usage (%)",
        data: cpuValues,
        borderColor: "blue",
        fill: false,
      },
    ],
  };

  return (
    <div style={{ padding: "40px" }}>
      <h1>Live CPU Metrics</h1>
      <Line data={data} />
    </div>
  );
}

export default App;