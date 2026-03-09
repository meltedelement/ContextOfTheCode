import React from "react";
import MetricsSection from "./MetricsSection";
import TransportMap from "./TransportMap";

function App() {
  return (
    <div style={{ padding: "40px", maxWidth: "960px", margin: "0 auto" }}>
      <h1>Context of the Code</h1>

      <h2>System</h2>
      <MetricsSection source="local" limit={50} />

      <h2 style={{ marginTop: "40px" }}>Transport</h2>
      <TransportMap
        source="transport_api"
        defaultCenter={{ lat: 53.3498, lng: -6.2603 }}
        defaultZoom={11}
      />
    </div>
  );
}

export default App;
