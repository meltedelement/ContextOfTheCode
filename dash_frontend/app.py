import time
import requests
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objects as go


# Your existing Flask API
API_BASE = "http://localhost:5001"


# Dash App
app = dash.Dash(__name__)
server = app.server  # Flask server inside Dash


# Layout
app.layout = html.Div([
    html.H2("Live System Metrics"),

    dcc.Interval(
        id="interval-component",
        interval=2000,  # 2 seconds
        n_intervals=0
    ),

    dcc.Graph(id="ram-gauge"),

    dcc.Graph(id="cpu-timeseries"),
])


# -------- RAM GAUGE --------
@app.callback(
    Output("ram-gauge", "figure"),
    Input("interval-component", "n_intervals")
)
def update_ram_gauge(n):

    try:
        response = requests.get(
            f"{API_BASE}/api/metrics",
            params={"limit": 1}
        )

        data = response.json()
        snapshots = data.get("snapshots", [])

        if not snapshots:
            value = 0
        else:
            metrics = snapshots[0]["metrics"]
            value = next(
                (
                    m["metric_value"]
                    for m in metrics
                    if m["metric_name"] == "ram_usage_percent"
                ),
                0
            )

    except Exception:
        value = 0

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={"text": "RAM Usage (%)"},
        gauge={"axis": {"range": [0, 100]}}
    ))

    return fig


# -------- CPU TIME SERIES --------
@app.callback(
    Output("cpu-timeseries", "figure"),
    Input("interval-component", "n_intervals")
)
def update_cpu_chart(n):

    try:
        response = requests.get(
            f"{API_BASE}/api/metrics",
            params={"limit": 50}
        )

        data = response.json()
        snapshots = data.get("snapshots", [])

        timestamps = []
        cpu_values = []

        for snap in snapshots:
            timestamps.append(snap["collected_at"])

            cpu = next(
                (
                    m["metric_value"]
                    for m in snap["metrics"]
                    if m["metric_name"] == "cpu_usage_percent"
                ),
                None
            )

            cpu_values.append(cpu)

    except Exception:
        timestamps = []
        cpu_values = []

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=cpu_values,
        mode="lines+markers",
        name="CPU Usage (%)"
    ))

    fig.update_layout(
        title="CPU Usage Over Time",
        xaxis_title="Timestamp",
        yaxis_title="CPU %",
        yaxis_range=[0, 100]
    )

    return fig


if __name__ == "__main__":
    app.run(debug=True)