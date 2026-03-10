import React from "react";
import MetricsSection from "./MetricsSection";
import TransportMap from "./TransportMap";

const SOURCE_SYSTEM    = "local";
const SOURCE_TRANSPORT = "transport_api";

const SYSTEM_LIMIT  = 50;
const DUBLIN_CENTER = { lat: 53.3498, lng: -6.2603 };
const DUBLIN_ZOOM   = 11;

function App() {
  return (
    <div style={{ padding: "40px", maxWidth: "960px", margin: "0 auto" }}>
      <h1>Context of the Code</h1>

      <h2>System</h2>
      <MetricsSection source={SOURCE_SYSTEM} limit={SYSTEM_LIMIT} />

      <h2 style={{ marginTop: "40px" }}>Transport</h2>
      <TransportMap
        source={SOURCE_TRANSPORT}
        defaultCenter={DUBLIN_CENTER}
        defaultZoom={DUBLIN_ZOOM}
      />
    </div>
  );
}

export default App;
