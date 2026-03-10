import React, { useContext, useEffect, useState, useCallback, useMemo, useRef } from "react";
import { GoogleMap, useJsApiLoader, Marker, InfoWindow } from "@react-google-maps/api";
import axios from "axios";
import { ConfigContext } from "./ConfigContext";


const MAP_HEIGHT = "500px";

// Tracks whose most recent position is older than this (relative to the current
// live max) are considered stale and hidden in live mode. Set to 3× the
// collection interval to tolerate a missed cycle without ghosting old buses.
const LIVE_STALE_SECS = 180;

// If the newest snapshot is older than this, the feed is considered stale
// (i.e. collection is not running) and the Live indicator is suppressed.
const LIVE_FRESHNESS_SECS = 60;

// Timestamps within 30 s of each other are considered one collection cycle.
const CLUSTER_GAP_SECS = 30;

interface Metric {
  metric_name: string;
  metric_value: number;
  unit: string;
}

interface Snapshot {
  snapshot_id:     string;
  device_id:       string;
  vehicle_id:      string | null;
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
    const find = (name: string) => snap.metrics.find((m) => m.metric_name === name)?.metric_value;

    const lat = find("latitude");
    const lng = find("longitude");
    if (lat === undefined || lng === undefined || (lat === 0 && lng === 0)) continue;

    const id = snap.vehicle_id ?? snap.snapshot_id.slice(0, 8);

    if (!tracks[id]) tracks[id] = { id, positions: [] };
    tracks[id].positions.push({
      lat,
      lng,
      timestamp: snap.collected_at,
      delay: find("arrival_delay"),
    });
  }

  return Object.values(tracks);
}

function clusterTimestamps(timestamps: number[]): number[] {
  const sorted = Array.from(new Set(timestamps)).sort((a, b) => a - b);
  if (sorted.length === 0) return [];
  const times: number[] = [];
  let groupMax = sorted[0];
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] - sorted[i - 1] > CLUSTER_GAP_SECS) {
      times.push(groupMax);
      groupMax = sorted[i];
    } else {
      groupMax = sorted[i];
    }
  }
  times.push(groupMax);
  return times;
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
  initialLimit?: number;
  maxSnapshots?: number;
  pollInterval?: number;
  defaultCenter?: { lat: number; lng: number };
  defaultZoom?: number;
}

const mapContainerStyle = { width: "100%", height: MAP_HEIGHT };

export default function TransportMap({
  source,
  limit = 100,
  initialLimit = 20000,
  maxSnapshots = 30000,
  pollInterval = 30000,
  defaultCenter = { lat: 53.3498, lng: -6.2603 },
  defaultZoom = 11,
}: TransportMapProps) {
  const [tracks, setTracks]               = useState<VehicleTrack[]>([]);
  const [snapshots, setSnapshots]         = useState<Snapshot[]>([]);
  const [timeRange, setTimeRange]         = useState<{ min: number; max: number } | null>(null);
  const [collectionTimes, setCollectionTimes] = useState<number[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number>(0);
  const [isLive, setIsLive]               = useState(true);
  const [selectedId, setSelectedId]       = useState<string | null>(null);
  const [snapshotCount, setSnapshotCount] = useState<number>(0);
  const [restartState, setRestartState]   = useState<"idle" | "pending" | "success" | "error">("idle");

  const selectedTime = collectionTimes[selectedIndex] ?? 0;

  const isLiveRef = useRef(true);
  const maxCollectedAtRef = useRef<number | null>(null);

  const { isLoaded, loadError } = useJsApiLoader({
    googleMapsApiKey: process.env.REACT_APP_GOOGLE_MAPS_API_KEY ?? "",
  });

  const { ui } = useContext(ConfigContext)!;

  const handleRestart = async () => {
    setRestartState("pending");
    try {
      await axios.post(`${ui.command_server_url}/restart`);
      setRestartState("success");
    } catch {
      setRestartState("error");
    }
    setTimeout(() => setRestartState("idle"), 3000);
  };

  // Recompute all derived state whenever the snapshots array changes.
  useEffect(() => {
    if (snapshots.length === 0) return;
    const timestamps = snapshots.map((s) => s.collected_at);
    const min = timestamps.reduce((a, b) => Math.min(a, b));
    const max = timestamps.reduce((a, b) => Math.max(a, b));
    const times = clusterTimestamps(timestamps);
    setTracks(buildVehicleTracks(snapshots));
    setTimeRange({ min, max });
    setSnapshotCount(snapshots.length);
    setCollectionTimes(times);
    if (isLiveRef.current) setSelectedIndex(times.length - 1);
  }, [snapshots]);

  const fetchInitial = useCallback(async (signal: AbortSignal) => {
    try {
      const res = await axios.get(`${ui.api_base}/api/metrics`, {
        params: { source, limit: initialLimit },
        signal,
      });
      const incoming: Snapshot[] = res.data.snapshots;
      if (incoming.length === 0) return;

      maxCollectedAtRef.current = incoming.reduce((a, b) => Math.max(a, b.collected_at), -Infinity);
      isLiveRef.current = true;
      setIsLive(true);
      setSnapshots(incoming);
    } catch (err: any) {
      if (err?.code === "ERR_CANCELED" || err?.name === "AbortError" || err?.name === "CanceledError") return;
      console.error("Failed to fetch initial transport data:", err);
    }
  }, [source, initialLimit, ui.api_base]);

  const fetchDelta = useCallback(async (signal: AbortSignal) => {
    if (maxCollectedAtRef.current === null) return;
    try {
      const res = await axios.get(`${ui.api_base}/api/metrics`, {
        params: { source, limit, since: maxCollectedAtRef.current },
        signal,
      });
      const incoming: Snapshot[] = res.data.snapshots;
      if (incoming.length === 0) return;

      const newMax = incoming.reduce((a, b) => Math.max(a, b.collected_at), -Infinity);
      maxCollectedAtRef.current = newMax;

      setSnapshots((prev) => {
        const combined = [...prev, ...incoming];
        return combined.length > maxSnapshots ? combined.slice(combined.length - maxSnapshots) : combined;
      });
    } catch (err: any) {
      if (err?.code === "ERR_CANCELED" || err?.name === "AbortError" || err?.name === "CanceledError") return;
      console.error("Failed to fetch transport delta:", err);
    }
  }, [source, limit, maxSnapshots, ui.api_base]);

  useEffect(() => {
    setSnapshots([]);
    setTracks([]);
    setCollectionTimes([]);
    setTimeRange(null);
    maxCollectedAtRef.current = null;

    const controller = new AbortController();
    fetchInitial(controller.signal);
    const interval = setInterval(() => fetchDelta(controller.signal), pollInterval);
    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, [source, initialLimit, limit, maxSnapshots, pollInterval, fetchInitial, fetchDelta]);

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const i = Number(e.target.value);
    setSelectedIndex(i);
    const live = i === collectionTimes.length - 1;
    setIsLive(live);
    isLiveRef.current = live;
  };

  const displayedVehicles = useMemo(() => {
    if (!timeRange) return [];
    return tracks
      .filter((t) => {
        const latestPos = t.positions[t.positions.length - 1];
        return latestPos && (selectedTime - latestPos.timestamp) <= LIVE_STALE_SECS;
      })
      .map((t) => ({ id: t.id, pos: positionAtTime(t, selectedTime) }))
      .filter((v): v is { id: string; pos: NonNullable<ReturnType<typeof positionAtTime>> } =>
        v.pos !== null
      );
  }, [tracks, selectedTime, timeRange]);

  if (loadError) return <p style={{ color: "red" }}>Failed to load Google Maps.</p>;
  if (!isLoaded) return <p>Loading map...</p>;
  if (!timeRange || snapshots.length === 0) return <p style={{ color: "#999", fontSize: "14px" }}>No data yet for source "{source}".</p>;

  // Pick the most recent snapshot at or before the selected interval time.
  const selectedSnap = snapshots.filter((s) => s.collected_at <= selectedTime).at(-1)
    ?? snapshots[snapshots.length - 1];

  const selected = displayedVehicles.find((v) => v.id === selectedId);
  const latencyMs = Math.round((selectedSnap.received_at - selectedSnap.collected_at) * ui.ms_per_sec);
  const isDataFresh = (Date.now() / ui.ms_per_sec - timeRange.max) <= LIVE_FRESHNESS_SECS;

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
            {selectedSnap.device_name || "–"}
          </div>
          <div style={{ fontSize: "12px", color: "#666", marginTop: "2px" }}>
            Collected by <strong>{selectedSnap.aggregator_name || selectedSnap.aggregator_id || "–"}</strong>
          </div>
        </div>
        <span style={{
          fontSize: "11px", fontWeight: 600,
          background: "#e3edf7", color: "#2563a8",
          borderRadius: "4px", padding: "3px 8px", letterSpacing: "0.3px",
        }}>
          {selectedSnap.source}
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
            ["Device ID",        selectedSnap.device_id,       true],
            ["Aggregator ID",    selectedSnap.aggregator_id,   true],
            ["Snapshot ID",      selectedSnap.snapshot_id,     true],
            ["Collected at",     new Date(selectedSnap.collected_at * ui.ms_per_sec).toLocaleString()],
            ["Received at",      new Date(selectedSnap.received_at  * ui.ms_per_sec).toLocaleString()],
            ["Latency",          `${latencyMs} ms`],
            ["Snapshots loaded", String(snapshotCount)],
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
              {new Date(selectedTime * ui.ms_per_sec).toLocaleString()}
              <span style={{ fontSize: "11px", color: "#aaa", marginLeft: "8px" }}>
                interval {selectedIndex + 1} / {collectionTimes.length}
              </span>
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              {!isLive && (
                <button
                  onClick={() => {
                    setSelectedIndex(collectionTimes.length - 1);
                    setIsLive(true);
                    isLiveRef.current = true;
                  }}
                  style={{ fontSize: "11px", padding: "2px 8px", cursor: "pointer", borderRadius: "4px", border: "1px solid #4CAF50", background: "#fff", color: "#4CAF50", fontWeight: 600 }}
                >
                  Resume Live
                </button>
              )}
              <span style={{ fontSize: "12px", fontWeight: isLive ? 600 : 400, color: isLive && isDataFresh ? "#4CAF50" : isLive ? "#FF9800" : "#999" }}>
                {isLive && isDataFresh ? "● Live" : isLive ? "● Stale" : `${displayedVehicles.length} vehicle${displayedVehicles.length !== 1 ? "s" : ""} at this time`}
              </span>
            </div>
          </div>
          <input
            type="range"
            min={0}
            max={collectionTimes.length - 1}
            value={selectedIndex}
            step={1}
            onChange={handleSliderChange}
            style={{ width: "100%" }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#aaa", marginTop: "2px" }}>
            <span>{new Date(timeRange.min * ui.ms_per_sec).toLocaleString()}</span>
            <span>{new Date(timeRange.max * ui.ms_per_sec).toLocaleString()}</span>
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

        {/* Restart button */}
        <div style={{ marginTop: "20px", display: "flex", justifyContent: "flex-end" }}>
          <button
            onClick={handleRestart}
            disabled={restartState === "pending"}
            style={{
              fontSize: "12px", padding: "6px 14px", cursor: restartState === "pending" ? "default" : "pointer",
              borderRadius: "4px", border: "1px solid #F44336",
              background: restartState === "error" ? "#fdecea" : "#fff",
              color: restartState === "error" ? "#F44336" : restartState === "success" ? "#4CAF50" : "#F44336",
              fontWeight: 600,
            }}
          >
            {restartState === "pending" ? "Restarting…" : restartState === "success" ? "Restarting…" : restartState === "error" ? "Error — try again" : "Restart Collectors"}
          </button>
        </div>

      </div>
    </div>
  );
}
