import React, { useEffect, useState } from "react";
import { parse } from "smol-toml";
import MetricsSection from "./MetricsSection";
import TransportMap from "./TransportMap";
import MobileSection from "./MobileSection";
import { ConfigContext, FrontendConfig } from "./ConfigContext";

export default function App() {
  const [config, setConfig] = useState<FrontendConfig | null>(null);

  useEffect(() => {
    fetch("/config.toml")
      .then((r) => r.text())
      .then((text) => setConfig(parse(text) as unknown as FrontendConfig))
      .catch((err) => console.error("Failed to load frontend config:", err));
  }, []);

  if (!config) return null;

  return (
    <ConfigContext.Provider value={config}>
      <div style={{ padding: "40px", maxWidth: "960px", margin: "0 auto" }}>
        <h1>Context of the Code</h1>

        <h2>System</h2>
        <MetricsSection source={config.system.source} limit={config.system.snapshot_limit} />

        <h2 style={{ marginTop: "40px" }}>Transport</h2>
        <TransportMap
          source={config.transport.source}
          limit={config.transport.snapshot_limit}
          initialLimit={config.transport.initial_limit}
          maxSnapshots={config.transport.max_snapshots}
          defaultCenter={{ lat: config.transport.map.centre_lat, lng: config.transport.map.centre_lng }}
          defaultZoom={config.transport.map.zoom}
        />

        <h2 style={{ marginTop: "40px" }}>Mobile Devices</h2>
        <MobileSection
          source={config.mobile_app.source}
          limit={config.mobile_app.snapshot_limit}
          pollInterval={config.mobile_app.poll_interval}
          stalenessSecs={config.mobile_app.staleness_secs}
        />

      </div>
    </ConfigContext.Provider>
  );
}
