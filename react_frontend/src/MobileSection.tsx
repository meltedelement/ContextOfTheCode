import React, { useContext, useEffect, useState, useMemo, useCallback } from "react";
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
import { ConfigContext } from "./ConfigContext";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip);


const CHART = {
  MAX_X_TICKS:  8,
  TICK_SIZE:    10,
  LINE_TENSION: 0.2,
  POINT_RADIUS: 2,
  HEIGHT:       "140px",
};

// Prefix applied by mobile_app_collector to every metric name.
const MOBILE_METRIC_PREFIX = "mobile_";

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

// ── Metric name parsing ────────────────────────────────────────────────────────

/**
 * Extract (userId, fieldName) from a mobile metric name.
 *
 * Collector format: "mobile_{user_id}_{field_name}"
 * user_id is a UUID (no underscores), so the first underscore after the
 * "mobile_" prefix separates the user_id from the field name.
 */
function parseMobileMetric(metricName: string): { userId: string; field: string } | null {
  if (!metricName.startsWith(MOBILE_METRIC_PREFIX)) return null;
  const withoutPrefix = metricName.slice(MOBILE_METRIC_PREFIX.length);
  const idx = withoutPrefix.indexOf("_");
  if (idx === -1) return null;
  return {
    userId: withoutPrefix.slice(0, idx),
    field:  withoutPrefix.slice(idx + 1),
  };
}

// ── Chart ─────────────────────────────────────────────────────────────────────

function MetricChart({ values, labels, color }: {
  values: number[];
  labels: string[];
  color:  string;
}) {
  const { ui } = useContext(ConfigContext)!;
  return (
    <div style={{ height: CHART.HEIGHT }}>
      <Line
        data={{
          labels,
          datasets: [{
            data:            values,
            borderColor:     color,
            backgroundColor: color + ui.colour_opacity_fill,
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

// ── One mobile device card ─────────────────────────────────────────────────────

interface MobileDeviceData {
  userId:    string;
  // List of { snapshot timestamp, field → value } entries in time order
  history:   Array<{ collectedAt: number; fields: Record<string, { value: number; unit: string }> }>;
}

function MobileDeviceSection({ device, aggregatorName, collectorDeviceName, isStale }: {
  device:              MobileDeviceData;
  aggregatorName:      string;
  collectorDeviceName: string;
  isStale:             boolean;
}) {
  const { ui } = useContext(ConfigContext)!;
  const latest = device.history[device.history.length - 1];
  const fieldNames = useMemo(
    () => Array.from(new Set(device.history.flatMap((h) => Object.keys(h.fields)))).sort(),
    [device.history],
  );

  return (
    <div style={{ border: "1px solid #e0e0e0", borderRadius: "10px", marginBottom: "24px", overflow: "hidden" }}>

      {/* Device header */}
      <div style={{
        background: "#f0f4f8", borderBottom: "1px solid #e0e0e0",
        padding: "16px 20px", display: "flex", justifyContent: "space-between",
        alignItems: "flex-start", flexWrap: "wrap", gap: "8px",
      }}>
        <div>
          <div style={{ fontSize: "15px", fontWeight: 700, color: "#1a1a1a", fontFamily: "monospace" }}>
            {device.userId}
          </div>
          <div style={{ fontSize: "12px", color: "#666", marginTop: "2px" }}>
            Collected by <strong>{aggregatorName}</strong> via <strong>{collectorDeviceName}</strong>
          </div>
        </div>
        <span style={{
          fontSize: "11px", fontWeight: 600,
          color: isStale ? "#FF9800" : "#4CAF50",
        }}>
          {isStale ? "● Stale" : "● Live"}
        </span>
      </div>

      <div style={{ padding: "16px 20px" }}>

        {/* Current metric value cards */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", marginBottom: "24px" }}>
          {fieldNames.map((field, i) => {
            const entry = latest.fields[field];
            if (!entry) return null;
            const color = ui.colours[i % ui.colours.length];
            return (
              <div key={field} style={{
                flex: "1 1 130px", padding: "12px 14px", borderRadius: "8px",
                border: `1px solid ${color}${ui.colour_opacity_border}`, background: color + ui.colour_opacity_bg,
              }}>
                <div style={{ fontSize: "10px", color: "#888", letterSpacing: "0.5px", marginBottom: "4px" }}>
                  {field.replace(/_/g, " ").toUpperCase()}
                </div>
                <div style={{ fontSize: "20px", fontWeight: 700, color: "#111" }}>
                  {entry.value % 1 === 0 ? entry.value : entry.value.toFixed(2)}
                  <span style={{ fontSize: "12px", fontWeight: 400, color: "#888", marginLeft: "3px" }}>
                    {entry.unit}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Historical charts */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "16px" }}>
          {fieldNames.map((field, i) => {
            const values: number[] = [];
            const labels: string[] = [];
            device.history.forEach((h) => {
              const entry = h.fields[field];
              if (entry) {
                values.push(entry.value);
                labels.push(new Date(h.collectedAt * ui.ms_per_sec).toLocaleTimeString());
              }
            });
            if (values.length < 2) return null;
            const unit = latest.fields[field]?.unit ?? "";
            return (
              <div key={field}>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "#444", marginBottom: "4px" }}>
                  {field.replace(/_/g, " ").toUpperCase()}{unit ? ` (${unit})` : ""}
                </div>
                <MetricChart values={values} labels={labels} color={ui.colours[i % ui.colours.length]} />
              </div>
            );
          })}
        </div>

      </div>
    </div>
  );
}

// ── Main export ────────────────────────────────────────────────────────────────

interface MobileSectionProps {
  source:        string;
  limit:         number;
  pollInterval:  number;
  stalenessSecs: number;
}

export default function MobileSection({ source, limit, pollInterval, stalenessSecs }: MobileSectionProps) {
  const { ui } = useContext(ConfigContext)!;
  const [snapshots,   setSnapshots]   = useState<Snapshot[]>([]);
  const [fetchError,  setFetchError]  = useState(false);

  const fetchSnapshots = useCallback(async () => {
    try {
      const res = await axios.get(`${ui.api_base}/api/metrics`, { params: { source, limit } });
      setSnapshots(res.data.snapshots);
      setFetchError(false);
    } catch (err) {
      console.error(`Failed to fetch metrics for source "${source}":`, err);
      setFetchError(true);
    }
  }, [source, limit, ui.api_base]);

  useEffect(() => {
    fetchSnapshots();
    const interval = setInterval(fetchSnapshots, pollInterval);
    return () => clearInterval(interval);
  }, [fetchSnapshots, pollInterval]);

  // Build per-user device data from the flat snapshot list.
  // Each snapshot may contain metrics for many mobile users; we parse and group.
  // The mobile collector packs ALL mobile users into one snapshot per cycle.
  // We parse metric names to extract per-user data, then group by userId.
  const { devices, aggregatorName, collectorDeviceName, latestCollectedAt } = useMemo(() => {
    const byUser: Record<string, MobileDeviceData> = {};
    let aggName  = "";
    let devName  = "";
    let latestAt = 0;

    for (const snap of snapshots) {
      aggName  = snap.aggregator_name || snap.aggregator_id;
      devName  = snap.device_name;
      if (snap.collected_at > latestAt) latestAt = snap.collected_at;

      // Group this snapshot's metrics by parsed user_id
      const userFields: Record<string, Record<string, { value: number; unit: string }>> = {};
      for (const m of snap.metrics) {
        const parsed = parseMobileMetric(m.metric_name);
        if (!parsed) continue;
        if (!userFields[parsed.userId]) userFields[parsed.userId] = {};
        userFields[parsed.userId][parsed.field] = { value: m.metric_value, unit: m.unit };
      }

      for (const [userId, fields] of Object.entries(userFields)) {
        if (!byUser[userId]) byUser[userId] = { userId, history: [] };
        byUser[userId].history.push({ collectedAt: snap.collected_at, fields });
      }
    }

    const sorted = Object.values(byUser).sort((a, b) => a.userId.localeCompare(b.userId));
    return { devices: sorted, aggregatorName: aggName, collectorDeviceName: devName, latestCollectedAt: latestAt };
  }, [snapshots]);

  if (fetchError)           return <p style={{ color: "red",  fontSize: "14px" }}>Failed to load data for source "{source}".</p>;
  if (devices.length === 0) return <p style={{ color: "#999", fontSize: "14px" }}>No data yet for source "{source}".</p>;

  // Staleness is feed-level: all users appear in every snapshot, so if the
  // newest snapshot is old, the whole feed is stale — not individual devices.
  const feedIsStale = (Date.now() / ui.ms_per_sec - latestCollectedAt) > stalenessSecs;

  return (
    <div>
      {devices.map((device) => (
        <MobileDeviceSection
          key={device.userId}
          device={device}
          aggregatorName={aggregatorName}
          collectorDeviceName={collectorDeviceName}
          isStale={feedIsStale}
        />
      ))}
    </div>
  );
}
