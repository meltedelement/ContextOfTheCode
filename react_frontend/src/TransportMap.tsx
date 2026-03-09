import React, { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { GoogleMap, useJsApiLoader, Marker, InfoWindow } from "@react-google-maps/api";
import axios from "axios";

const API_BASE = "";

interface Metric {
  metric_name: string;
  metric_value: number;
  unit: string;
}

interface Snapshot {
  snapshot_id:     string;
  device_id:       string;
  device_name:     string;
  source:          string;
  aggregator_id:   string;
  aggregator_name: string;
  collected_at:    number;
  received_at:     number;
  metrics:         Metric[];
}

interface VehicleTrack {
  id: string;
  positions: Array<{ lat: number; lng: number; timestamp: number; delay?: number }>;
}

function buildVehicleTracks(snapshots: Snapshot[]): VehicleTrack[] {
  const tracks: Record<string, VehicleTrack> = {};

  for (const snap of snapshots) {
    const seen: Record<string, { lat?: number; lng?: number; delay?: number }> = {};

    for (const m of snap.metrics) {
      const latMatch   = m.metric_name.match(/^(.+)_latitude$/);
      const lngMatch   = m.metric_name.match(/^(.+)_longitude$/);
      const delayMatch = m.metric_name.match(/^(.+)_last_arrival_delay$/);

      if (latMatch)        seen[latMatch[1]]   = { ...seen[latMatch[1]],   lat:   m.metric_value };
      else if (lngMatch)   seen[lngMatch[1]]   = { ...seen[lngMatch[1]],   lng:   m.metric_value };
      else if (delayMatch) seen[delayMatch[1]] = { ...seen[delayMatch[1]], delay: m.metric_value };
    }

    for (const [id, pos] of Object.entries(seen)) {
      if (pos.lat !== undefined && pos.lng !== undefined && !(pos.lat === 0 && pos.lng === 0)) {
        if (!tracks[id]) tracks[id] = { id, positions: [] };
        tracks[id].positions.push({
          lat: pos.lat,
          lng: pos.lng,
          timestamp: snap.collected_at,
          delay: pos.delay,
        });
      }
    }
  }

  return Object.values(tracks);
}

function positionAtTime(track: VehicleTrack, time: number) {
  let best: { lat: number; lng: number; delay?: number } | null = null;
  for (const p of track.positions) {
    if (p.timestamp <= time) best = p;
  }
  return best;
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
  const [tracks, setTracks]             = useState<VehicleTrack[]>([]);
  const [latestSnap, setLatestSnap]     = useState<Snapshot | null>(null);
  const [timeRange, setTimeRange]       = useState<{ min: number; max: number } | null>(null);
  const [selectedTime, setSelectedTime] = useState<number>(0);
  const [isLive, setIsLive]             = useState(true);
  const [selectedId, setSelectedId]     = useState<string | null>(null);

  const isLiveRef = useRef(true);

  const { isLoaded, loadError } = useJsApiLoader({
    googleMapsApiKey: process.env.REACT_APP_GOOGLE_MAPS_API_KEY ?? "",
  });

  const fetchPositions = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/api/metrics`, { params: { source, limit } });
      const snapshots: Snapshot[] = res.data.snapshots;
      if (snapshots.length === 0) return;

      const timestamps = snapshots.map((s) => s.collected_at);
      const min = Math.min(...timestamps);
      const max = Math.max(...timestamps);

      setTracks(buildVehicleTracks(snapshots));
      setLatestSnap(snapshots[snapshots.length - 1]);
      setTimeRange({ min, max });
      if (isLiveRef.current) setSelectedTime(max);
    } catch (err) {
      console.error("Failed to fetch transport data:", err);
    }
  }, [source, limit]);

  useEffect(() => {
    fetchPositions();
    const interval = setInterval(fetchPositions, pollInterval);
    return () => clearInterval(interval);
  }, [fetchPositions, pollInterval]);

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const t = Number(e.target.value);
    setSelectedTime(t);
    const live = timeRange !== null && t === timeRange.max;
    setIsLive(live);
    isLiveRef.current = live;
  };

  const displayedVehicles = useMemo(() => {
    if (!timeRange) return [];
    return tracks
      .map((t) => ({ id: t.id, pos: positionAtTime(t, selectedTime) }))
      .filter((v): v is { id: string; pos: NonNullable<ReturnType<typeof positionAtTime>> } =>
        v.pos !== null
      );
  }, [tracks, selectedTime, timeRange]);

  if (loadError) return <p style={{ color: "red" }}>Failed to load Google Maps.</p>;
  if (!isLoaded) return <p>Loading map...</p>;
  if (!timeRange || !latestSnap) return <p style={{ color: "#999", fontSize: "14px" }}>No data yet for source "{source}".</p>;

  const selected = displayedVehicles.find((v) => v.id === selectedId);
  const latencyMs = Math.round((latestSnap.received_at - latestSnap.collected_at) * 1000);

  return (
    <div style={{ border: "1px solid #e0e0e0", borderRadius: "10px", marginBottom: "40px", overflow: "hidden" }}>

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
            {latestSnap.device_name || "–"}
          </div>
          <div style={{ fontSize: "12px", color: "#666", marginTop: "2px" }}>
            Collected by <strong>{latestSnap.aggregator_name || latestSnap.aggregator_id || "–"}</strong>
          </div>
        </div>
        <span style={{
          fontSize: "11px", fontWeight: 600,
          background: "#e3edf7", color: "#2563a8",
          borderRadius: "4px", padding: "3px 8px", letterSpacing: "0.3px",
        }}>
          {latestSnap.source}
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
          {([
            ["Device ID",        latestSnap.device_id,       true],
            ["Aggregator ID",    latestSnap.aggregator_id,   true],
            ["Snapshot ID",      latestSnap.snapshot_id,     true],
            ["Collected at",     new Date(latestSnap.collected_at * 1000).toLocaleString()],
            ["Received at",      new Date(latestSnap.received_at  * 1000).toLocaleString()],
            ["Latency",          `${latencyMs} ms`],
            ["Snapshots loaded", String(tracks.length > 0 ? limit : 0)],
            ["Vehicles tracked", String(displayedVehicles.length)],
          ] as [string, string, boolean?][]).map(([label, value, mono]) => (
            <div key={label}>
              <span style={{ color: "#999" }}>{label}: </span>
              <span style={{ fontFamily: mono ? "monospace" : "inherit", fontSize: mono ? "11px" : "12px" }}>
                {value}
              </span>
            </div>
          ))}
        </div>

        {/* ── Datetime slider ── */}
        <div style={{ marginBottom: "12px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
            <span style={{ fontSize: "13px", color: "#333" }}>
              {new Date(selectedTime * 1000).toLocaleString()}
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              {!isLive && (
                <button
                  onClick={() => {
                    setSelectedTime(timeRange.max);
                    setIsLive(true);
                    isLiveRef.current = true;
                  }}
                  style={{ fontSize: "11px", padding: "2px 8px", cursor: "pointer", borderRadius: "4px", border: "1px solid #4CAF50", background: "#fff", color: "#4CAF50", fontWeight: 600 }}
                >
                  Resume Live
                </button>
              )}
              <span style={{ fontSize: "12px", fontWeight: isLive ? 600 : 400, color: isLive ? "#4CAF50" : "#999" }}>
                {isLive ? "● Live" : `${displayedVehicles.length} vehicle${displayedVehicles.length !== 1 ? "s" : ""} at this time`}
              </span>
            </div>
          </div>
          <input
            type="range"
            min={timeRange.min}
            max={timeRange.max}
            value={selectedTime}
            step={1}
            onChange={handleSliderChange}
            style={{ width: "100%" }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#aaa", marginTop: "2px" }}>
            <span>{new Date(timeRange.min * 1000).toLocaleString()}</span>
            <span>{new Date(timeRange.max * 1000).toLocaleString()}</span>
          </div>
        </div>

        {/* ── Map ── */}
        <GoogleMap mapContainerStyle={mapContainerStyle} center={defaultCenter} zoom={defaultZoom}>
          {displayedVehicles.map((v) => (
            <Marker
              key={v.id}
              position={{ lat: v.pos.lat, lng: v.pos.lng }}
              onClick={() => setSelectedId(v.id)}
            />
          ))}
          {selected && selectedId && (
            <InfoWindow
              position={{ lat: selected.pos.lat, lng: selected.pos.lng }}
              onCloseClick={() => setSelectedId(null)}
            >
              <div>
                <strong style={{ fontSize: "13px" }}>{selectedId}</strong>
                {selected.pos.delay !== undefined && (
                  <p style={{ margin: "4px 0 0", fontSize: "12px" }}>Delay: {selected.pos.delay}s</p>
                )}
                <p style={{ margin: "4px 0 0", fontSize: "11px", color: "#666" }}>
                  {selected.pos.lat.toFixed(5)}, {selected.pos.lng.toFixed(5)}
                </p>
              </div>
            </InfoWindow>
          )}
        </GoogleMap>
      </div>
    </div>
  );
}
