import React, { useContext, useEffect, useState, useCallback, useMemo, useRef } from "react";
import { GoogleMap, useJsApiLoader, Marker, InfoWindow, Polyline } from "@react-google-maps/api";
import axios from "axios";
import { ConfigContext } from "./ConfigContext";


// If the newest snapshot is older than this, the feed is considered stale
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

interface LatLng { lat: number; lng: number; }
interface SnappedPoint extends LatLng { originalIndex?: number; }

/** Raw GPS point with its collection timestamp. */
interface RawPoint { lat: number; lng: number; t: number; }

/**
 * A road-snapped point. `originalIndex` is the index into the input RawPoint
 * array this was snapped from; absent for interpolated geometry points added
 * by the Roads API to follow the road between consecutive waypoints.
 */
interface SnappedPoint { lat: number; lng: number; originalIndex?: number; }

/** Atomic unit stored per vehicle — raw inputs and their snapped road geometry. */
interface VehicleRoute {
  raw:     RawPoint[];
  snapped: SnappedPoint[];
}

// ── Helpers ──────────────────────────────────────────────────────────────────

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

function haversineM(a: LatLng, b: LatLng): number {
  const R  = 6371000;
  const φ1 = (a.lat * Math.PI) / 180;
  const φ2 = (b.lat * Math.PI) / 180;
  const Δφ = ((b.lat - a.lat) * Math.PI) / 180;
  const Δλ = ((b.lng - a.lng) * Math.PI) / 180;
  const x  = Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}

function deduplicateByDistance(pts: LatLng[], minM: number): LatLng[] {
  if (pts.length === 0) return [];
  const out = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    if (haversineM(out[out.length - 1], pts[i]) >= minM) out.push(pts[i]);
  }
  return out;
}

function evenlyDownsample(pts: LatLng[], maxN: number): LatLng[] {
  if (pts.length <= maxN) return pts;
  const step = (pts.length - 1) / (maxN - 1);
  return Array.from({ length: maxN }, (_, i) => pts[Math.round(i * step)]);
}

/**
 * Call Roads API snapToRoads with `interpolate=true`.
 * Returns snapped points, each optionally tagged with `originalIndex` of the
 * corresponding input point (absent on interpolated geometry-only points).
 * Handles chunking across the 100-point API limit, keeping originalIndex
 * values globally consistent across chunks.
 */
async function snapToRoads(pts: LatLng[], apiKey: string): Promise<SnappedPoint[]> {
<<<<<<< HEAD
  const CHUNK  = 100;
  const result: SnappedPoint[] = [];

  for (let i = 0; i < pts.length; i += CHUNK) {
    const chunk = pts.slice(i, i + CHUNK);
    const chunkOffset = i; // offset so originalIndex is global, not per-chunk
    const path  = chunk.map(p => `${p.lat},${p.lng}`).join("|");
=======
  const CHUNK = 100;
  const result: SnappedPoint[] = [];
  let chunkOffset = 0;

  for (let i = 0; i < pts.length; i += CHUNK) {
    const chunk  = pts.slice(i, i + CHUNK);
    const path   = chunk.map((p) => `${p.lat},${p.lng}`).join("|");
    const offset = chunkOffset; // capture before any await so callbacks close over the right value
>>>>>>> 617ade88e6c1bdd7597b78274bfbed84f9e4c397
    try {
      const res  = await fetch(
        `https://roads.googleapis.com/v1/snapToRoads?path=${path}&interpolate=true&key=${apiKey}`,
      );
      const data = await res.json();
      if (data.snappedPoints?.length) {
        result.push(
          ...data.snappedPoints.map((sp: any) => ({
            lat: sp.location.latitude,
            lng: sp.location.longitude,
<<<<<<< HEAD
            ...(sp.originalIndex !== undefined
              ? { originalIndex: sp.originalIndex + chunkOffset }
              : {}),
=======
            originalIndex: sp.originalIndex !== undefined
              ? (sp.originalIndex as number) + offset
              : undefined,
>>>>>>> 617ade88e6c1bdd7597b78274bfbed84f9e4c397
          })),
        );
      } else {
        console.warn("snapToRoads: empty response", data);
<<<<<<< HEAD
        result.push(...chunk.map((p, j) => ({ ...p, originalIndex: chunkOffset + j })));
      }
    } catch (err) {
      console.warn("snapToRoads: request failed", err);
      result.push(...chunk.map((p, j) => ({ ...p, originalIndex: chunkOffset + j })));
=======
        result.push(...chunk.map((p, j) => ({ ...p, originalIndex: offset + j })));
      }
    } catch (err) {
      console.warn("snapToRoads: request failed", err);
      result.push(...chunk.map((p, j) => ({ ...p, originalIndex: offset + j })));
>>>>>>> 617ade88e6c1bdd7597b78274bfbed84f9e4c397
    }
    chunkOffset += chunk.length;
  }

  return result;
}

// ── Component ─────────────────────────────────────────────────────────────────

interface TransportMapProps {
  source: string;
  limit?: number;
  initialLimit?: number;
  maxSnapshots?: number;
  pollInterval?: number;
  defaultCenter?: LatLng;
  defaultZoom?: number;
}

export default function TransportMap({
  source,
  limit = 100,
  initialLimit = 20000,
  maxSnapshots = 30000,
  pollInterval = 30000,
  defaultCenter = { lat: 53.3498, lng: -6.2603 },
  defaultZoom = 11,
}: TransportMapProps) {
  const [snapshots, setSnapshots]             = useState<Snapshot[]>([]);
  const [timeRange, setTimeRange]             = useState<{ min: number; max: number } | null>(null);
  const [collectionTimes, setCollectionTimes] = useState<number[]>([]);
  const [selectedIndex, setSelectedIndex]     = useState<number>(0);
  const [isLive, setIsLive]                   = useState(true);
  const [selectedId, setSelectedId]           = useState<string | null>(null);
  const [snapshotCount, setSnapshotCount]     = useState<number>(0);
<<<<<<< HEAD
  const [vehicleRoutes, setVehicleRoutes]     = useState<Map<string, SnappedPoint[]>>(new Map());
  const [routesLoading, setRoutesLoading]     = useState(false);
=======
>>>>>>> 617ade88e6c1bdd7597b78274bfbed84f9e4c397

  // Atomic per-vehicle route state: raw inputs + snapped road geometry stored together
  // so there is never a render where one is stale relative to the other.
  const [vehicleRoutes, setVehicleRoutes] = useState<Map<string, VehicleRoute>>(new Map());
  const [routesLoading, setRoutesLoading] = useState(false);

<<<<<<< HEAD
  const isLiveRef           = useRef(true);
  const maxCollectedAtRef   = useRef<number | null>(null);
  const routePointCounts    = useRef<Map<string, number>>(new Map());
  /** Per-vehicle sorted timestamps matching the raw input points fed to snapToRoads */
  const vehicleRawTimestamps = useRef<Map<string, number[]>>(new Map());
=======
  const selectedTime      = collectionTimes[selectedIndex] ?? 0;
  const isLiveRef         = useRef(true);
  const maxCollectedAtRef = useRef<number | null>(null);
  // Per-vehicle: raw point count at the time of the last successful snap.
  // Updated only when a full batch completes without cancellation, so a
  // cancelled run never poisons the cache and forces a re-snap next time.
  const routePointCounts  = useRef<Map<string, number>>(new Map());
>>>>>>> 617ade88e6c1bdd7597b78274bfbed84f9e4c397

  const { isLoaded, loadError } = useJsApiLoader({
    googleMapsApiKey: process.env.REACT_APP_GOOGLE_MAPS_API_KEY ?? "",
  });

  const config = useContext(ConfigContext)!;
  const { ui, transport } = config;
  const routeCfg = transport.route;
  const mapHeight = `${transport.map.height_px}px`;
  const mapContainerStyle = useMemo(
    () => ({ width: "100%", height: mapHeight }),
    [mapHeight],
  );

  // ── Derive time range / cluster list ──
  useEffect(() => {
    if (snapshots.length === 0) return;
    const timestamps = snapshots.map((s) => s.collected_at);
    const min  = timestamps.reduce((a, b) => Math.min(a, b));
    const max  = timestamps.reduce((a, b) => Math.max(a, b));
    const times = clusterTimestamps(timestamps);
    setTimeRange({ min, max });
    setSnapshotCount(snapshots.length);
    setCollectionTimes(times);
    if (isLiveRef.current) setSelectedIndex(times.length - 1);
  }, [snapshots]);

  // ── Compute road-snapped routes ──
  useEffect(() => {
    if (snapshots.length === 0) return;

    const apiKey   = process.env.REACT_APP_GOOGLE_MAPS_API_KEY ?? "";
    const minMoveM = routeCfg.min_move_m;
    const maxPts   = routeCfg.max_points;
    const batchSz  = routeCfg.batch_size;

    // Build per-vehicle chronological GPS arrays from all snapshots
    const byVehicle = new Map<string, RawPoint[]>();
    for (const snap of snapshots) {
      const id   = snap.vehicle_id ?? snap.snapshot_id.slice(0, 8);
      const find = (n: string) => snap.metrics.find((m) => m.metric_name === n)?.metric_value;
      const lat  = find("latitude");
      const lng  = find("longitude");
      if (lat === undefined || lng === undefined || (lat === 0 && lng === 0)) continue;
      if (!byVehicle.has(id)) byVehicle.set(id, []);
      byVehicle.get(id)!.push({ lat, lng, t: snap.collected_at });
    }
    byVehicle.forEach((pts) => pts.sort((a, b) => a.t - b.t));

<<<<<<< HEAD
    // Only process vehicles that have new or more points since last snap
    const toProcess: Array<[string, LatLng[], number, number[]]> = [];
=======
    // Determine which vehicles need (re-)snapping
    const toProcess: Array<{ id: string; sampled: RawPoint[]; rawCount: number }> = [];
>>>>>>> 617ade88e6c1bdd7597b78274bfbed84f9e4c397
    byVehicle.forEach((rawPts, id) => {
      if (rawPts.length < 2) return;
      const prev = routePointCounts.current.get(id) ?? 0;
      if (rawPts.length <= prev) return;

      const deduped = deduplicateByDistance(rawPts, minMoveM);
      // Always preserve the most recent GPS point as the route head — deduplication
      // drops it when the bus moved less than minMoveM since the previous kept point.
      const lastRaw = rawPts[rawPts.length - 1];
      if (deduped[deduped.length - 1] !== lastRaw) deduped.push(lastRaw);
      if (deduped.length < 2) return;
<<<<<<< HEAD
      const sampled = evenlyDownsample(deduped, ROUTE_MAX_POINTS);
      // Extract timestamps for the sampled points (they're a subset of rawPts, same refs)
      const sampledTimestamps = (sampled as Array<LatLng & { t: number }>).map(p => p.t);
      toProcess.push([id, sampled, rawPts.length, sampledTimestamps]);
=======

      // evenlyDownsample returns references to the original objects, preserving `.t`
      const sampled = evenlyDownsample(deduped as RawPoint[], maxPts) as RawPoint[];
      toProcess.push({ id, sampled, rawCount: rawPts.length });
>>>>>>> 617ade88e6c1bdd7597b78274bfbed84f9e4c397
    });

    if (toProcess.length === 0) return;

    let cancelled = false;
    setRoutesLoading(true);

    (async () => {
<<<<<<< HEAD
      const updates = new Map<string, SnappedPoint[]>();
=======
      // Collect all updates locally; only write to state and routePointCounts if
      // the entire run completes without cancellation. This prevents a cancelled
      // mid-run from poisoning the count cache and skipping those vehicles forever.
      const updates  = new Map<string, VehicleRoute>();
      const newCounts = new Map<string, number>();
>>>>>>> 617ade88e6c1bdd7597b78274bfbed84f9e4c397

      for (let i = 0; i < toProcess.length; i += batchSz) {
        if (cancelled) break;
        const batch = toProcess.slice(i, i + batchSz);
        await Promise.all(
<<<<<<< HEAD
          batch.map(async ([id, pts, rawCount, timestamps]) => {
            const snapped = await snapToRoads(pts, apiKey);
            routePointCounts.current.set(id, rawCount);
            vehicleRawTimestamps.current.set(id, timestamps as number[]);
            updates.set(id, snapped);
=======
          batch.map(async ({ id, sampled, rawCount }) => {
            const snapped = await snapToRoads(sampled, apiKey);
            updates.set(id, { raw: sampled, snapped });
            newCounts.set(id, rawCount);
>>>>>>> 617ade88e6c1bdd7597b78274bfbed84f9e4c397
          }),
        );
      }

      if (!cancelled) {
        // Apply count cache only on full success
        newCounts.forEach((count, id) => routePointCounts.current.set(id, count));
        setVehicleRoutes((prev) => {
          const next = new Map(prev);
          updates.forEach((v, k) => next.set(k, v));
          return next;
        });
        setRoutesLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [snapshots, routeCfg.min_move_m, routeCfg.max_points, routeCfg.batch_size]);

  // ── Data fetching ──
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
    setCollectionTimes([]);
    setTimeRange(null);
    setVehicleRoutes(new Map());
    routePointCounts.current = new Map();
    vehicleRawTimestamps.current = new Map();
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
    const i   = Number(e.target.value);
    setSelectedIndex(i);
    const live = i === collectionTimes.length - 1;
    setIsLive(live);
    isLiveRef.current = live;
  };

  // ── Vehicles at selected time ──
  const displayedVehicles = useMemo(() => {
    if (!timeRange || collectionTimes.length === 0) return [];
    const intervalSnaps = snapshots.filter(
      (s) => Math.abs(s.collected_at - selectedTime) <= CLUSTER_GAP_SECS,
    );
    const byVehicle = new Map<string, Snapshot>();
    for (const snap of intervalSnaps) {
      const id       = snap.vehicle_id ?? snap.snapshot_id.slice(0, 8);
      const existing = byVehicle.get(id);
      if (!existing || snap.collected_at > existing.collected_at) byVehicle.set(id, snap);
    }
    const result: { id: string; pos: { lat: number; lng: number; delay?: number } }[] = [];
    byVehicle.forEach((snap, id) => {
      const find = (name: string) => snap.metrics.find((m: Metric) => m.metric_name === name)?.metric_value;
      const lat  = find("latitude");
      const lng  = find("longitude");
      if (lat === undefined || lng === undefined || (lat === 0 && lng === 0)) return;
      result.push({ id, pos: { lat, lng, delay: find("arrival_delay") } });
    });
    return result;
  }, [snapshots, selectedTime, timeRange, collectionTimes]);

  /**
   * Trim each vehicle's snapped road geometry to exactly the path travelled
   * up to selectedTime. Never shows future road segments.
   *
   * Strategy:
   *   1. Find lastRawIdx — the last raw input point whose timestamp ≤ selectedTime
   *   2. Find the last snapped point whose originalIndex ≤ lastRawIdx (cutoffSnappedIdx)
   *   3. slice(0, cutoffSnappedIdx + 1) naturally includes all interpolated road-geometry
   *      points that precede it (road the bus has already traveled) while excluding any
   *      interpolated points after the last in-range original (road ahead of the bus).
   */
  const displayedRoutes = useMemo(() => {
    const routes     = new Map<string, LatLng[]>();
    const cutoffTime = selectedTime;

    vehicleRoutes.forEach(({ raw: rawPts, snapped }, id) => {
      if (snapped.length === 0) return;

      let lastRawIdx = -1;
      for (let i = 0; i < rawPts.length; i++) {
        if (rawPts[i].t <= cutoffTime) lastRawIdx = i;
      }
      if (lastRawIdx < 0) return;

      let cutoffSnappedIdx = -1;
      for (let i = 0; i < snapped.length; i++) {
        const oi = snapped[i].originalIndex;
        if (oi !== undefined) {
          if (oi <= lastRawIdx) {
            cutoffSnappedIdx = i;
          } else {
            break;
          }
        }
      }

      if (cutoffSnappedIdx >= 1) {
        routes.set(id, snapped.slice(0, cutoffSnappedIdx + 1));
      }
    });

    return routes;
  }, [vehicleRoutes, selectedTime]);

  // ── Stable colour assignment ──
  const vehicleColors = useMemo(() => {
    const palette = ui.colours?.length ? ui.colours : [
      "#2196F3", "#4CAF50", "#FF9800", "#E91E63", "#9C27B0",
      "#00BCD4", "#FF5722", "#607D8B", "#8BC34A", "#FFC107",
    ];
    const map = new Map<string, string>();
    let i = 0;
    vehicleRoutes.forEach((_, id) => { map.set(id, palette[i++ % palette.length]); });
    displayedVehicles.forEach((v) => {
      if (!map.has(v.id)) map.set(v.id, palette[i++ % palette.length]);
    });
    return map;
  }, [vehicleRoutes, displayedVehicles, ui.colours]);

  // ── Clip routes to selectedTime when viewing history ──
  const displayedRoutes = useMemo(() => {
    if (isLive) return vehicleRoutes; // live → show full route

    const clipped = new Map<string, LatLng[]>();
    vehicleRoutes.forEach((snapped, id) => {
      const timestamps = vehicleRawTimestamps.current.get(id);
      if (!timestamps || timestamps.length === 0) {
        clipped.set(id, snapped);
        return;
      }

      // Find the last raw input point whose timestamp ≤ selectedTime
      let lastRawIdx = -1;
      for (let i = 0; i < timestamps.length; i++) {
        if (timestamps[i] <= selectedTime) lastRawIdx = i;
        else break;
      }
      if (lastRawIdx < 0) return; // no points at or before selectedTime → hide route

      // Find the last snapped point whose originalIndex ≤ lastRawIdx.
      // Interpolated points (no originalIndex) between in-range originals are
      // included by the slice; interpolated points after the cutoff are excluded.
      let cutoffSnappedIdx = -1;
      for (let i = 0; i < snapped.length; i++) {
        const oi = snapped[i].originalIndex;
        if (oi !== undefined) {
          if (oi <= lastRawIdx) {
            cutoffSnappedIdx = i;
          } else {
            break;
          }
        }
      }

      if (cutoffSnappedIdx >= 0) {
        clipped.set(id, snapped.slice(0, cutoffSnappedIdx + 1));
      }
    });
    return clipped;
  }, [isLive, vehicleRoutes, selectedTime]);

  // ── Guards ──
  if (loadError)  return <p style={{ color: "red" }}>Failed to load Google Maps.</p>;
  if (!isLoaded)  return <p>Loading map...</p>;
  if (!timeRange || snapshots.length === 0)
    return <p style={{ color: "#999", fontSize: "14px" }}>No data yet for source "{source}".</p>;

  const selectedSnap = snapshots.filter((s) => s.collected_at <= selectedTime).at(-1)
    ?? snapshots[snapshots.length - 1];
  const selected     = displayedVehicles.find((v) => v.id === selectedId) ?? null;
  const latencyMs    = Math.round((selectedSnap.received_at - selectedSnap.collected_at) * ui.ms_per_sec);
  const isDataFresh  = (Date.now() / ui.ms_per_sec - timeRange.max) <= LIVE_FRESHNESS_SECS;

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
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {routesLoading && (
            <span style={{ fontSize: "11px", color: "#888" }}>Snapping routes to roads…</span>
          )}
          <span style={{
            fontSize: "11px", fontWeight: 600,
            background: "#e3edf7", color: "#2563a8",
            borderRadius: "4px", padding: "3px 8px", letterSpacing: "0.3px",
          }}>
            {selectedSnap.source}
          </span>
        </div>
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
            ["Routes snapped",   `${vehicleRoutes.size}${routesLoading ? "…" : ""}`],
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

<<<<<<< HEAD
          {/* Road-snapped route polylines (rendered under markers) */}
=======
          {/* Road-snapped route polylines — rendered under markers */}
>>>>>>> 617ade88e6c1bdd7597b78274bfbed84f9e4c397
          {Array.from(displayedRoutes.entries()).map(([id, path]) => (
            <Polyline
              key={`route-${id}`}
              path={path}
              options={{
                strokeColor:   vehicleColors.get(id) ?? "#2196F3",
                strokeWeight:  routeCfg.stroke_weight,
                strokeOpacity: routeCfg.stroke_opacity,
              }}
            />
          ))}

          {/* Current-position markers */}
          {displayedVehicles.map((v) => (
            <Marker
              key={v.id}
              position={{ lat: v.pos.lat, lng: v.pos.lng }}
              onClick={() => setSelectedId(v.id)}
            />
          ))}

          {/* Info window */}
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
                {displayedRoutes.has(selectedId) && (
                  <p style={{ margin: "4px 0 0", fontSize: "11px", color: "#888" }}>
                    {displayedRoutes.get(selectedId)!.length} road pts
                  </p>
                )}
              </div>
            </InfoWindow>
          )}
        </GoogleMap>
      </div>
    </div>
  );
}
