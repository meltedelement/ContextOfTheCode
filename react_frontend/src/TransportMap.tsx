import React, { useEffect, useState, useCallback } from "react";
import { GoogleMap, useJsApiLoader, Marker, InfoWindow } from "@react-google-maps/api";
import axios from "axios";

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

interface VehiclePosition {
  id: string;
  lat: number;
  lng: number;
  delay?: number;
}

// Each snapshot is one bus. Snapshots are ordered newest-first, so the first
// occurrence of each vehicle_id is the most recent position.
function parseVehiclePositions(snapshots: Snapshot[]): VehiclePosition[] {
  const seen = new Set<string>();
  const vehicles: VehiclePosition[] = [];

  for (const snapshot of snapshots) {
    const find = (name: string) =>
      snapshot.metrics.find((m) => m.metric_name === name)?.metric_value;

    const lat = find("latitude");
    const lng = find("longitude");
    if (lat === undefined || lng === undefined) continue;

    const vidRaw = find("vehicle_id");
    const id =
      vidRaw !== undefined
        ? String(Math.round(vidRaw))
        : snapshot.snapshot_id.slice(0, 8);

    if (seen.has(id)) continue;
    seen.add(id);

    vehicles.push({ id, lat, lng, delay: find("arrival_delay") });
  }

  return vehicles;
}

interface TransportMapProps {
  source: string;
  pollInterval?: number;
  defaultCenter?: { lat: number; lng: number };
  defaultZoom?: number;
}

const mapContainerStyle = { width: "100%", height: "500px" };

export default function TransportMap({
  source,
  pollInterval = 30000,
  defaultCenter = { lat: 53.3498, lng: -6.2603 },
  defaultZoom = 11,
}: TransportMapProps) {
  const [vehicles, setVehicles] = useState<VehiclePosition[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const { isLoaded, loadError } = useJsApiLoader({
    googleMapsApiKey: process.env.REACT_APP_GOOGLE_MAPS_API_KEY ?? "",
  });

  const fetchPositions = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/api/metrics`, {
        params: { source, limit: 1500 },
      });
      const snapshots: Snapshot[] = res.data.snapshots;
      if (snapshots.length === 0) return;
      setVehicles(parseVehiclePositions(snapshots));
      // snapshots[0] is the most recent (server returns DESC order)
      setLastUpdated(new Date(snapshots[0].collected_at * 1000));
    } catch (err) {
      console.error("Failed to fetch transport data:", err);
    }
  }, [source]);

  useEffect(() => {
    fetchPositions();
    const interval = setInterval(fetchPositions, pollInterval);
    return () => clearInterval(interval);
  }, [fetchPositions, pollInterval]);

  if (loadError) return <p style={{ color: "red" }}>Failed to load Google Maps.</p>;
  if (!isLoaded) return <p>Loading map...</p>;

  const selected = vehicles.find((v) => v.id === selectedId);

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
          {vehicles.length} vehicle{vehicles.length !== 1 ? "s" : ""} tracked
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
        {vehicles.map((v) => (
          <Marker
            key={v.id}
            position={{ lat: v.lat, lng: v.lng }}
            onClick={() => setSelectedId(v.id)}
          />
        ))}
        {selected && selectedId && (
          <InfoWindow
            position={{ lat: selected.lat, lng: selected.lng }}
            onCloseClick={() => setSelectedId(null)}
          >
            <div>
              <strong style={{ fontSize: "13px" }}>{selectedId}</strong>
              {selected.delay !== undefined && (
                <p style={{ margin: "4px 0 0", fontSize: "13px" }}>
                  Delay: {selected.delay}s
                </p>
              )}
              <p style={{ margin: "4px 0 0", fontSize: "11px", color: "#666" }}>
                {selected.lat.toFixed(5)}, {selected.lng.toFixed(5)}
              </p>
            </div>
          </InfoWindow>
        )}
      </GoogleMap>
    </div>
  );
}
