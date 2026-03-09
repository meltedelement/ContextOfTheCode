import React, { useEffect, useState, useCallback } from "react";
import { GoogleMap, useJsApiLoader, Marker, InfoWindow, Polyline } from "@react-google-maps/api";
import axios from "axios";

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

interface VehicleHistory {
  id: string;
  positions: Array<{ lat: number; lng: number }>;
  currentDelay?: number;
}

// Parses all snapshots to build per-vehicle position histories.
// Matches any metric ending in _latitude / _longitude / _last_arrival_delay.
function parseVehicleHistories(snapshots: Snapshot[]): VehicleHistory[] {
  const histories: Record<string, VehicleHistory> = {};

  for (const snap of snapshots) {
    const seen: Record<string, { lat?: number; lng?: number; delay?: number }> = {};

    for (const m of snap.metrics) {
      const latMatch = m.metric_name.match(/^(.+)_latitude$/);
      const lngMatch = m.metric_name.match(/^(.+)_longitude$/);
      const delayMatch = m.metric_name.match(/^(.+)_last_arrival_delay$/);

      if (latMatch) {
        const id = latMatch[1];
        seen[id] = { ...seen[id], lat: m.metric_value };
      } else if (lngMatch) {
        const id = lngMatch[1];
        seen[id] = { ...seen[id], lng: m.metric_value };
      } else if (delayMatch) {
        const id = delayMatch[1];
        seen[id] = { ...seen[id], delay: m.metric_value };
      }
    }

    for (const [id, pos] of Object.entries(seen)) {
      if (pos.lat !== undefined && pos.lng !== undefined) {
        if (!histories[id]) histories[id] = { id, positions: [] };
        histories[id].positions.push({ lat: pos.lat, lng: pos.lng });
        if (pos.delay !== undefined) histories[id].currentDelay = pos.delay;
      }
    }
  }

  return Object.values(histories);
}

interface TransportMapProps {
  source: string;
  limit?: number;
  pollInterval?: number;
  defaultCenter?: { lat: number; lng: number };
  defaultZoom?: number;
}

const mapContainerStyle = { width: "100%", height: "500px" };

export default function TransportMap({
  source,
  limit = 100,
  pollInterval = 30000,
  defaultCenter = { lat: 53.3498, lng: -6.2603 },
  defaultZoom = 11,
}: TransportMapProps) {
  const [histories, setHistories] = useState<VehicleHistory[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const { isLoaded, loadError } = useJsApiLoader({
    googleMapsApiKey: process.env.REACT_APP_GOOGLE_MAPS_API_KEY ?? "",
  });

  const fetchPositions = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/api/metrics`, {
        params: { source, limit },
      });
      const snapshots: Snapshot[] = res.data.snapshots;
      if (snapshots.length === 0) return;
      setHistories(parseVehicleHistories(snapshots));
      setLastUpdated(new Date(snapshots[snapshots.length - 1].collected_at * 1000));
    } catch (err) {
      console.error("Failed to fetch transport data:", err);
    }
  }, [source, limit]);

  useEffect(() => {
    fetchPositions();
    const interval = setInterval(fetchPositions, pollInterval);
    return () => clearInterval(interval);
  }, [fetchPositions, pollInterval]);

  if (loadError) return <p style={{ color: "red" }}>Failed to load Google Maps.</p>;
  if (!isLoaded) return <p>Loading map...</p>;

  const selected = histories.find((v) => v.id === selectedId);

  return (
    <div>
      <div
        style={{
          marginBottom: "8px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: "14px", color: "#555" }}>
          {histories.length} vehicle{histories.length !== 1 ? "s" : ""} tracked
        </span>
        {lastUpdated && (
          <span style={{ fontSize: "12px", color: "#999" }}>
            Last update: {lastUpdated.toLocaleTimeString()}
          </span>
        )}
      </div>
      <GoogleMap
        mapContainerStyle={mapContainerStyle}
        center={defaultCenter}
        zoom={defaultZoom}
      >
        {histories.map((v, i) => {
          const color = COLORS[i % COLORS.length];
          const current = v.positions[v.positions.length - 1];
          return (
            <React.Fragment key={v.id}>
              {v.positions.length > 1 && (
                <Polyline
                  path={v.positions}
                  options={{ strokeColor: color, strokeOpacity: 0.6, strokeWeight: 2 }}
                />
              )}
              <Marker
                position={current}
                onClick={() => setSelectedId(v.id)}
              />
            </React.Fragment>
          );
        })}
        {selected && selectedId && (
          <InfoWindow
            position={selected.positions[selected.positions.length - 1]}
            onCloseClick={() => setSelectedId(null)}
          >
            <div>
              <strong style={{ fontSize: "13px" }}>{selectedId}</strong>
              {selected.currentDelay !== undefined && (
                <p style={{ margin: "4px 0 0", fontSize: "13px" }}>
                  Delay: {selected.currentDelay}s
                </p>
              )}
              <p style={{ margin: "4px 0 0", fontSize: "11px", color: "#666" }}>
                {selected.positions[selected.positions.length - 1].lat.toFixed(5)},{" "}
                {selected.positions[selected.positions.length - 1].lng.toFixed(5)}
              </p>
              <p style={{ margin: "4px 0 0", fontSize: "11px", color: "#999" }}>
                {selected.positions.length} position{selected.positions.length !== 1 ? "s" : ""} recorded
              </p>
            </div>
          </InfoWindow>
        )}
      </GoogleMap>
    </div>
  );
}
