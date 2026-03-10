import React, { useEffect, useState } from "react";
import { parse } from "smol-toml";
import MetricsSection from "./MetricsSection";
import TransportMap from "./TransportMap";

interface FrontendConfig {
  system: { source: string; limit: number };
  transport: { source: string; map: { centre_lat: number; centre_lng: number; zoom: number } };
}

export default function App() {
  const [config, setConfig] = useState<FrontendConfig | null>(null);

  useEffect(() => {
    fetch("/config.toml")
      .then((r) => r.text())
      .then((text) => setConfig(parse(text) as FrontendConfig))
      .catch((err) => console.error("Failed to load frontend config:", err));
  }, []);

  if (!config) return null;

  return (
    <div style={{ padding: "40px", maxWidth: "960px", margin: "0 auto" }}>
      <h1>Context of the Code</h1>

      <h2>System</h2>
      <MetricsSection source={config.system.source} limit={config.system.limit} />

      <h2 style={{ marginTop: "40px" }}>Transport</h2>
      <TransportMap
        source={config.transport.source}
        defaultCenter={{ lat: config.transport.map.centre_lat, lng: config.transport.map.centre_lng }}
        defaultZoom={config.transport.map.zoom}
      />
    </div>
  );
}
