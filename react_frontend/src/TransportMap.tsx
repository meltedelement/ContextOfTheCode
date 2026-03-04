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

// Generic parser: matches any metric ending in _latitude / _longitude / _last_arrival_delay
// Works for any vehicle type (bus, car, plane, etc.)
function parseVehiclePositions(metrics: Metric[]): VehiclePosition[] {
  const vehicles: Record<string, { id: string; lat?: number; lng?: number; delay?: number }> = {};

  for (const m of metrics) {
    const latMatch = m.metric_name.match(/^(.+)_latitude$/);
    const lngMatch = m.metric_name.match(/^(.+)_longitude$/);
    const delayMatch = m.metric_name.match(/^(.+)_last_arrival_delay$/);

    if (latMatch) {
      const id = latMatch[1];
      vehicles[id] = { ...vehicles[id], id, lat: m.metric_value };
    } else if (lngMatch) {
      const id = lngMatch[1];
      vehicles[id] = { ...vehicles[id], id, lng: m.metric_value };
    } else if (delayMatch) {
      const id = delayMatch[1];
      vehicles[id] = { ...vehicles[id], id, delay: m.metric_value };
    }
  }

  return Object.values(vehicles).filter(
    (v): v is VehiclePosition =>
      v.id !== undefined && v.lat !== undefined && v.lng !== undefined
  );
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
        params: { source, limit: 5 },
      });
      const snapshots: Snapshot[] = res.data.snapshots;
      if (snapshots.length === 0) return;
      const latest = snapshots[snapshots.length - 1];
      setVehicles(parseVehiclePositions(latest.metrics));
      setLastUpdated(new Date(latest.collected_at * 1000));
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
