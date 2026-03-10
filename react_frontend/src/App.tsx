import React, { useCallback, useEffect, useState } from "react";
import { parse } from "smol-toml";
import MetricsSection from "./MetricsSection";
import TransportMap from "./TransportMap";
import MobileSection from "./MobileSection";
import { ConfigContext, FrontendConfig } from "./ConfigContext";

type RestartStatus = "idle" | "loading" | "ok" | "error";

export default function App() {
  const [config, setConfig] = useState<FrontendConfig | null>(null);
  const [restartStatus, setRestartStatus] = useState<Record<string, RestartStatus>>({});

  useEffect(() => {
    fetch("/config.toml")
      .then((r) => r.text())
      .then((text) => setConfig(parse(text) as unknown as FrontendConfig))
      .catch((err) => console.error("Failed to load frontend config:", err));
  }, []);

  const handleRestart = useCallback((name: string, url: string) => {
    setRestartStatus((prev) => ({ ...prev, [name]: "loading" }));
    fetch(url, { method: "POST" })
      .then((r) => {
        setRestartStatus((prev) => ({ ...prev, [name]: r.ok ? "ok" : "error" }));
      })
      .catch(() => setRestartStatus((prev) => ({ ...prev, [name]: "error" })))
      .finally(() => {
        setTimeout(() => setRestartStatus((prev) => ({ ...prev, [name]: "idle" })), 3000);
      });
  }, []);

  if (!config) return null;

  console.log("config.aggregators:", config.aggregators);

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

        <h2 style={{ marginTop: "40px" }}>Stretch Goal</h2>
        <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
          {(config.aggregators?.list ?? []).map(({ name, restart_url }) => {
            const status = restartStatus[name] ?? "idle";
            return (
              <button
                key={name}
                onClick={() => handleRestart(name, restart_url)}
                disabled={status === "loading"}
                style={{
                  padding: "10px 20px",
                  borderRadius: "8px",
                  border: "none",
                  cursor: status === "loading" ? "not-allowed" : "pointer",
                  fontWeight: 600,
                  background: status === "ok" ? "#4CAF50" : status === "error" ? "#F44336" : "#2196F3",
                  color: "#fff",
                }}
              >
                {status === "loading" ? "Restarting..." : status === "ok" ? "Restarted!" : status === "error" ? "Failed" : `Restart ${name}`}
              </button>
            );
          })}
        </div>
      </div>
    </ConfigContext.Provider>
  );
}
