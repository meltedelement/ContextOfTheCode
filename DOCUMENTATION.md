# Context of the Code - Complete System Documentation

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture & Data Flow](#2-architecture--data-flow)
3. [Startup & Orchestration (run_all.py)](#3-startup--orchestration-run_allpy)
4. [Configuration System](#4-configuration-system)
5. [Data Collectors](#5-data-collectors)
6. [Upload Queue (Redis)](#6-upload-queue-redis)
7. [Flask API Server](#7-flask-api-server)
8. [Database Schema](#8-database-schema)
9. [React Frontend](#9-react-frontend)
10. [Logging System](#10-logging-system)
11. [Error Handling & Resilience](#11-error-handling--resilience)
12. [Threading Model](#12-threading-model)
13. [Deployment](#13-deployment)
14. [Testing](#14-testing)
15. [Key Design Decisions & Interview Talking Points](#15-key-design-decisions--interview-talking-points)

---

## 1. Project Overview

This is a **distributed system monitoring and data collection platform**. It collects metrics from three heterogeneous sources (local system hardware, a public transport real-time API, and mobile devices via Supabase), queues them in Redis for resilient delivery, uploads them to a remote Flask API, stores them in MySQL, and visualises them in a React dashboard with real-time charts and a Google Maps transport view.

### High-Level Components

| Component | Technology | Runs On | Purpose |
|-----------|-----------|---------|---------|
| **Orchestrator** | Python (`run_all.py`) | Local machine | Starts collectors, manages lifecycle |
| **Collectors** | Python (psutil, requests, supabase) | Local machine (threads) | Gather metrics from 3 sources |
| **Upload Queue** | Redis + Python worker thread | Local machine | Persistent, retry-capable message queue |
| **API Server** | Flask + Gunicorn | Remote VM (`100.67.157.90`) | REST API for registration & metrics |
| **Database** | MySQL via SQLAlchemy | Remote VM | Persistent metric storage |
| **Frontend** | React + TypeScript + Chart.js + Google Maps | Browser | Real-time dashboard |
| **Shared Utilities** | Python (`sharedUtils/`) | Local machine | Config, logging, queue management |

### Project Structure

```
Context-of-the-code-project/
├── run_all.py                          # Main orchestrator
├── .env                                # API keys (not in git)
├── pyproject.toml / requirements.txt   # Dependencies
├── restart_server.sh                   # Gunicorn restart script
│
├── collectors/
│   ├── base_data_collector.py          # Abstract base class
│   ├── local_collector.py              # CPU/RAM/temp via psutil
│   ├── transport_collector.py          # NTA GTFS-R vehicle positions
│   └── mobile_app_collector.py         # Supabase device_stats
│
├── server/
│   ├── app.py                          # Flask API (all routes)
│   ├── models.py                       # SQLAlchemy ORM models
│   └── database.py                     # Engine, session, context manager
│
├── sharedUtils/
│   ├── config/
│   │   ├── config.toml                 # Central configuration file
│   │   ├── loader.py                   # Thread-safe lazy singleton loader
│   │   ├── models.py                   # Pydantic validation models
│   │   └── data_model.json             # JSON schema for messages
│   ├── logger/
│   │   └── logger.py                   # Rotating file + console logger
│   ├── upload_queue/
│   │   ├── redis_queue.py              # RedisUploadQueue implementation
│   │   └── manager.py                  # Singleton queue factory
│   └── testing/                        # Unit & integration tests
│
├── react_frontend/
│   ├── public/config.toml              # Frontend-specific config
│   └── src/
│       ├── App.tsx                      # Root component
│       ├── MetricsSection.tsx           # Charts for system metrics
│       └── TransportMap.tsx             # Google Maps vehicle tracker
│
└── logs/                               # Runtime log files
```

---

## 2. Architecture & Data Flow

### End-to-End Data Flow

```
[Data Sources]         [Local Machine]              [Remote Server]         [Browser]

psutil (CPU/RAM) ──┐
                   ├─► Collector Thread ─► SnapshotMessage ─► Redis Queue
NTA GTFS-R API ────┤                                             │
                   │                                    Worker Thread
Supabase DB ───────┘                                             │
                                                    HTTP POST (batch)
                                                             │
                                                    Flask API (/api/metrics/batch)
                                                             │
                                                    SQLAlchemy ─► MySQL
                                                             │
                                                    GET /api/metrics
                                                             │
                                                    React Dashboard
                                                    ├── Line Charts
                                                    └── Google Maps
```

### Detailed Process Flow

1. **Startup**: `run_all.py` checks Redis is running, polls Flask `/health`, registers the aggregator and each device with the server, receives UUIDs back.
2. **Collection**: Each collector runs in its own thread on a configurable interval (local: 10s, transport: 60s, mobile: 60s). Each produces `SnapshotMessage` objects containing `MetricEntry` lists.
3. **Queuing**: Snapshots are serialized to JSON, wrapped in an envelope with retry metadata, and pushed to the `metrics:pending` Redis list.
4. **Upload**: A background worker thread pops up to 50 messages at a time from Redis and POSTs them as a batch to `/api/metrics/batch`.
5. **Storage**: Flask validates device existence, creates `Snapshot` and `Metric` rows in MySQL within a transaction.
6. **Visualisation**: React polls `GET /api/metrics` every 5s (system) or 30s (transport), renders charts and map markers.
7. **Shutdown**: SIGTERM or Ctrl+C triggers graceful shutdown: collectors stop, queue drains, connections close.

---

## 3. Startup & Orchestration (run_all.py)

`run_all.py` is the **single entry point** for the data collection side. It coordinates every moving part.

### Startup Sequence (in order)

| Step | What Happens | Why |
|------|-------------|-----|
| 1. Load `.env` | `load_dotenv()` reads API keys into `os.environ` | Transport API needs `PRIMARY_KEY`/`SECONDARY_KEY`; mobile needs Supabase creds |
| 2. Redis health check | Socket connect to `redis_host:redis_port` with 2s timeout | Queue is mandatory; no point starting collectors without it |
| 3. Flask health check | Poll `GET /health` for up to 30s (every 0.5s) | Server must be accepting requests before we register devices |
| 4. Register aggregator | `POST /aggregators {"name": "SavageLaptop"}` | Idempotent; returns existing `aggregator_id` if already registered |
| 5. Register devices | `POST /devices` for each enabled collector | Server issues `device_id` UUIDs that collectors embed in every snapshot |
| 6. Start collectors | `collector.start()` for each → spawns background threads | Async collection begins immediately |
| 7. Main loop | Sleep 1s, check `running` flag | Waits for shutdown signal |

### Shutdown Sequence

1. SIGTERM handler or `KeyboardInterrupt` sets `running = False`
2. Each `collector.stop()` signals its thread to finish current cycle, joins with timeout
3. `stop_upload_queue()` signals worker thread, joins with 5s timeout
4. Redis connection and HTTP session closed
5. Exit code 0

### Key Constants

```python
FLASK_HEALTH_POLL_INTERVAL = 0.5   # seconds between health check attempts
FLASK_HEALTH_TIMEOUT = 30          # max wait for server
REDIS_CHECK_TIMEOUT_SECONDS = 2    # socket timeout for Redis check
SHUTDOWN_POLL_INTERVAL_SECONDS = 1  # main loop sleep
```

### Collector Registry

Collectors are registered conditionally:
- **LocalDataCollector**: always (unless `enabled = false` in config)
- **TransportCollector**: always (uses `PRIMARY_KEY`/`SECONDARY_KEY` from `.env`)
- **MobileAppCollector**: only if `SUPABASE_URL` and `SUPABASE_KEY` are in `.env`

---

## 4. Configuration System

### Architecture

Located in `sharedUtils/config/`. Three layers:

1. **TOML file** (`config.toml`) — the single source of truth
2. **Pydantic models** (`models.py`) — type-safe validation with custom validators
3. **Loader** (`loader.py`) — thread-safe lazy singleton with double-checked locking

### How Config is Loaded

```python
# loader.py (simplified)
_TYPED_CONFIG_CACHE = None
_lock = threading.Lock()

def get_typed_config() -> AppConfig:
    global _TYPED_CONFIG_CACHE
    if _TYPED_CONFIG_CACHE is None:          # First check (no lock)
        with _lock:
            if _TYPED_CONFIG_CACHE is None:  # Second check (under lock)
                with open(CONFIG_PATH, "rb") as f:
                    config_dict = tomllib.load(f)
                _TYPED_CONFIG_CACHE = AppConfig(**config_dict)
    return _TYPED_CONFIG_CACHE
```

**Why double-checked locking?** Multiple collector threads may call `get_typed_config()` simultaneously at startup. The outer check avoids acquiring the lock on every call after the first. The inner check prevents two threads from both loading config if they both passed the outer check before either acquired the lock.

### Config Sections & Pydantic Models

| TOML Section | Pydantic Model | Key Fields | Validators |
|-------------|----------------|------------|------------|
| `[logging]` | `LoggingConfig` | level, file, format, console_export, json_indent | level must be DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `[data_model]` | `DataModelConfig` | schema_path | — |
| `[collectors]` | `CollectorsConfig` | default_interval, cpu_sample_interval, metric_precision | intervals >= 1, precision >= 0 |
| `[local_collector]` | `LocalCollectorConfig` | collection_interval | >= 1 second |
| `[transport_collector]` | `TransportCollectorConfig` | collection_interval, api_url, tripupdates_url | >= 1 second |
| `[mobile_app_collector]` | `MobileAppCollectorConfig` | collection_interval, query_limit | interval >= 1, query_limit >= 1 |
| `[aggregator]` | `AggregatorConfig` | name | — |
| `[upload_queue]` | `UploadQueueConfig` | redis_host/port/db, api_endpoint, retry policy, batch_size | port 1-65535, retries >= 0 |

### Convenience Accessors

Each section has a dedicated getter function exported from `sharedUtils/config/__init__.py`:

```python
get_typed_config()              # → AppConfig (full config)
get_collector_config()          # → CollectorsConfig
get_local_collector_config()    # → LocalCollectorConfig
get_upload_queue_config()       # → UploadQueueConfig
get_logging_config()            # → LoggingConfig
get_data_model_config()         # → DataModelConfig
get_mobile_app_collector_config() # → MobileAppCollectorConfig
```

### Data Model Schema (data_model.json)

Defines the expected message format:
```json
{
  "message_id": "UUID v4",
  "timestamp": "Unix float",
  "device_id": "string",
  "source": "string",
  "metrics": [
    {"metric_name": "string", "metric_value": "float", "unit": "string"}
  ]
}
```

All metric values are strictly **floats** — booleans are coerced to 1.0/0.0, strings are excluded.

---

## 5. Data Collectors

### Inheritance Hierarchy

```
BaseDataCollector (ABC)
├── LocalDataCollector      — CPU, RAM, temperature via psutil
├── TransportCollector      — GTFS-R vehicle positions & trip updates
└── MobileAppCollector      — Supabase device_stats table
```

### BaseDataCollector — The Template

Located at `collectors/base_data_collector.py`. Defines the contract all collectors follow.

**Data Models (Pydantic):**

```python
class MetricEntry(BaseModel):
    metric_name: str        # e.g. "cpu_usage_percent"
    metric_value: float     # always numeric
    unit: str = ""          # e.g. "%", "MB", "°C", "deg", "s"

class SnapshotMessage(BaseModel):
    snapshot_id: str        # UUID, auto-generated
    timestamp: float        # Unix time, auto-populated
    device_id: str          # server-issued UUID
    metrics: List[MetricEntry]
```

**Key Methods:**

| Method | Purpose |
|--------|---------|
| `collect_data()` (abstract) | Returns `List[MetricEntry]`. Each subclass implements its own data source logic. |
| `generate_message()` | Calls `collect_data()`, wraps results in `SnapshotMessage`, exports to upload queue. |
| `export_to_data_model(msg)` | Gets singleton queue via `get_upload_queue()`, calls `queue.put(msg)`. Fire-and-forget. |
| `start()` | Sets `_running = True`, spawns thread running `_collection_loop()`. |
| `stop()` | Sets `_running = False`, joins thread with timeout = `collection_interval + 5s`. |
| `_collection_loop()` | Infinite loop: `generate_message()`, then interruptible sleep (checks `_running` every 1s). |

**Why interruptible sleep?** Instead of `time.sleep(60)` which would block shutdown for up to 60 seconds, the loop checks `_running` every 1 second: `for _ in range(interval): if not _running: break; time.sleep(1)`. This ensures shutdown completes within ~1 second of the signal.

---

### LocalDataCollector

**Source**: `psutil` library (direct system calls)
**Interval**: 10 seconds (configurable)
**Metrics produced per cycle**: 3-4

| Metric | How Collected | Unit |
|--------|--------------|------|
| `ram_usage_percent` | `psutil.virtual_memory().percent` | % |
| `ram_used_mb` | `psutil.virtual_memory().used / (1024*1024)` | MB |
| `cpu_usage_percent` | `psutil.cpu_percent(interval=1.0)` | % |
| `cpu_temp_celsius` | `psutil.sensors_temperatures()` | °C |

**CPU temperature lookup order**: `coretemp` (Intel) → `k10temp` (AMD) → `zenpower` (AMD) → first available sensor. Returns `None` on platforms without sensor support (the metric is simply omitted).

**CPU sampling**: `psutil.cpu_percent(interval=1.0)` blocks for 1 second to measure actual CPU usage between two sample points. This is configurable via `cpu_sample_interval` in config.

---

### TransportCollector

**Source**: Ireland's National Transport Authority GTFS-Realtime API
**Interval**: 60 seconds (configurable)
**Metrics produced per cycle**: N vehicles x 3-4 metrics each

**Two API endpoints**:
1. **Vehicle Positions** (`/gtfsr/v2/Vehicles`) — live lat/lng of every bus
2. **Trip Updates** (`/gtfsr/v2/TripUpdates`) — schedule delay information

**Authentication**: `x-api-key` header with `PRIMARY_KEY` from `.env`, plus `X-Secondary-Key` with `SECONDARY_KEY`.

**Data Processing in `collect_data()`:**

1. Query both APIs (with 10s timeout each)
2. Build a lookup dict: `{(trip_id, vehicle_id): trip_update_entity}` from trip updates
3. For each vehicle entity in positions response:
   - Extract `latitude`, `longitude`, `trip_id`, `vehicle_id`
   - Create `MetricEntry` for latitude (unit: "deg") and longitude (unit: "deg")
   - Try to create `vehicle_id` metric (must be numeric; warns if not)
   - Look up trip update by `(trip_id, vehicle_id)`, extract last stop's `arrival_delay` (unit: "s")

**Critical Override — `generate_message()`:**

Unlike the base class which produces **one snapshot per collection cycle**, TransportCollector produces **one snapshot per vehicle**. This is the key architectural decision:

```python
def generate_message(self):
    metrics = self.collect_data()  # flat list with "vehicleId__metricName" format
    # Group by vehicle prefix (split on "__")
    for vehicle_id, vehicle_metrics in grouped.items():
        snapshot = SnapshotMessage(metrics=vehicle_metrics, ...)
        self.export_to_data_model(snapshot)  # queue each separately
```

**Why per-vehicle snapshots?** Each bus is logically independent. Grouping all buses into one massive snapshot would make querying, retry, and frontend rendering harder. One bus failing to parse shouldn't lose data for the others.

---

### MobileAppCollector

**Source**: Supabase `device_stats` table
**Interval**: 60 seconds (configurable)
**Metrics produced per cycle**: N devices x up to 8 metrics each

**Supabase query**: `SELECT * FROM device_stats LIMIT query_limit` (default 30 rows). The limit prevents full table scans.

**Metrics per device:**

| Metric Name Pattern | Source Column | Unit |
|-------------------|---------------|------|
| `mobile_{user_id}_battery_level` | battery_level | % |
| `mobile_{user_id}_is_charging` | is_charging (bool → 1.0/0.0) | "" |
| `mobile_{user_id}_ram_total_mb` | ram_total_mb | MB |
| `mobile_{user_id}_ram_available_mb` | ram_available_mb | MB |
| `mobile_{user_id}_ram_used_mb` | ram_used_mb | MB |
| `mobile_{user_id}_storage_total_gb` | storage_total_gb | GB |
| `mobile_{user_id}_storage_free_gb` | storage_free_gb | GB |
| `mobile_{user_id}_storage_used_gb` | storage_used_gb | GB |

String columns (`device_model`, `os_name`, `network_type`, `wifi_name`) are ignored because all metric values must be floats.

---

## 6. Upload Queue (Redis)

### Why Redis?

- **Persistence**: Messages survive process crashes (Redis is disk-backed)
- **Atomic operations**: `LPUSH`, `BRPOP`, `ZADD`, `ZRANGEBYSCORE` are all atomic
- **No external broker needed**: Simpler than RabbitMQ/Kafka for this scale
- **Sorted sets for retry scheduling**: Score = future timestamp makes deferred retry trivial

### Redis Data Structures

| Key | Type | Purpose |
|-----|------|---------|
| `metrics:pending` | List | FIFO queue of messages ready for upload |
| `metrics:retry` | Sorted Set | Deferred retries (score = retry-at Unix timestamp) |
| `metrics:failed` | List | Exhausted retries or permanent errors |

### Message Envelope

Every `SnapshotMessage` is wrapped in an envelope before entering Redis:

```json
{
  "retry_count": 0,
  "first_queued_at": 1700000000.123,
  "last_error": null,
  "payload": "{...serialized SnapshotMessage...}",
  "failure_class": null,
  "from_failed": false
}
```

| Field | Purpose |
|-------|---------|
| `retry_count` | Tracks attempts; compared against `max_retry_attempts` |
| `first_queued_at` | When the message first entered the system (for latency tracking) |
| `last_error` | String describing most recent failure (truncated to 200 chars) |
| `payload` | The actual SnapshotMessage as a JSON string |
| `failure_class` | `"transient"` (5xx, timeout) or `"permanent"` (4xx) — set on failure |
| `from_failed` | `true` if this was recovered from the failed queue — gets one final retry only |

### Worker Loop

The worker thread runs continuously:

```
while self.running:
    1. _process_retry_queue()       # Check sorted set for expired retries
    2. _process_pending_batch()     # Pop up to batch_size from pending, upload
    3. Log heartbeat every 60s     # Queue stats: pending, retry, failed counts
    4. Sleep 1s if no work done
```

### Batch Upload Flow

`_process_pending_batch()`:

1. `BRPOP metrics:pending` (blocks up to 1s if empty)
2. Pipeline `RPOP` up to `batch_size - 1` more messages (non-blocking)
3. Extract payloads from all envelopes
4. Single `POST /api/metrics/batch` with JSON array of all payloads
5. **On success**: messages are done; trigger recovery if transient failures existed
6. **On failure**: route each envelope individually based on error classification

### Error Classification

```python
def _classify_error(error) -> str:
    if HTTP status 4xx → "permanent"   # Client error, retrying won't help
    if HTTP status 5xx → "transient"   # Server error, may recover
    if timeout/connection error → "transient"
    else → "transient"                 # Default to retriable
```

### Retry with Exponential Backoff

When a transient error occurs and retries remain:

```
delay = backoff_base * (backoff_multiplier ^ (retry_count - 1))

With defaults (base=1, multiplier=2):
  Attempt 1 fails → retry after 1s
  Attempt 2 fails → retry after 2s
  Attempt 3 fails → retry after 4s
  Attempt 4 fails → retry after 8s
  Attempt 5 fails → retry after 16s
  Attempt 6 fails → moved to failed queue (max_retry_attempts=5 exhausted)
```

The retry envelope is added to `metrics:retry` sorted set with `score = time.time() + delay`. Each worker loop iteration checks `ZRANGEBYSCORE(0, now)` and promotes expired entries back to `metrics:pending`.

### Transient Failure Recovery

When a batch upload **succeeds** after there had been transient failures:

1. Worker sweeps `metrics:failed` queue
2. Re-enqueues messages with `failure_class == "transient"` back to `metrics:pending`
3. Sets `from_failed = true` on recovered envelopes — they get **one final attempt only**
4. Messages with `failure_class == "permanent"` or `from_failed == true` stay in failed queue

**Why this design?** If the server was down for a while (5xx errors), many messages may have exhausted retries and landed in the failed queue. When the server comes back (first successful upload), those messages deserve another chance. But we limit to one retry to avoid infinite loops.

### Queue Manager (Singleton)

```python
# manager.py
_queue_instance = None
_lock = threading.Lock()

def get_upload_queue() -> RedisUploadQueue:
    # Double-checked locking (same pattern as config loader)
    ...
```

Called by `BaseDataCollector.export_to_data_model()`. Ensures only one queue instance exists across all collector threads.

---

## 7. Flask API Server

Located at `server/app.py`. Runs on the remote VM behind Gunicorn.

### Routes

#### `POST /aggregators` — Register Aggregator

```
Request:  {"name": "SavageLaptop"}
Response: {"aggregator_id": "uuid"}  (200 if existing, 201 if new)
```

Idempotent: if an aggregator with that name already exists, returns the existing UUID. This handles restarts gracefully — the collector machine can re-register without creating duplicates. Race condition handled: if two concurrent requests try to create the same aggregator, catches `IntegrityError` and returns the existing record.

#### `POST /devices` — Register Device

```
Request:  {"aggregator_id": "uuid", "name": "local-system", "source": "local"}
Response: {"device_id": "server-generated-uuid"}  (201)
Errors:   400 (missing fields), 404 (aggregator not found)
```

Each collector type gets a server-issued `device_id` that it includes in every snapshot.

#### `POST /api/metrics` — Single Snapshot Upload

```
Request:
{
  "snapshot_id": "uuid",
  "timestamp": 1700000000.123,
  "device_id": "uuid",
  "metrics": [
    {"metric_name": "cpu_usage_percent", "metric_value": 45.2, "unit": "%"}
  ]
}
Response: {"status": "success", "snapshot_id": "uuid", "metrics_received": 4}  (201)
Errors:   400 (missing fields), 404 (unknown device_id)
```

#### `POST /api/metrics/batch` — Batch Snapshot Upload

```
Request:  [snapshot1, snapshot2, ...]  (JSON array of snapshot objects)
Response: {"status": "success", "snapshots_received": 50}  (201)
```

Processes valid items, **skips** malformed or unknown-device items (logs warnings, doesn't fail the whole batch). This is important for resilience — one bad message shouldn't block 49 good ones.

#### `GET /api/metrics` — Query Stored Metrics

```
Query params: ?device_id=uuid&source=local&limit=100&since=1700000000.0
Response:
{
  "status": "success",
  "count": 42,
  "snapshots": [
    {
      "snapshot_id": "...",
      "device_id": "...",
      "device_name": "local-system",
      "source": "local",
      "aggregator_id": "...",
      "aggregator_name": "SavageLaptop",
      "collected_at": 1700000000.123,
      "received_at": 1700000002.456,
      "metrics": [...]
    }
  ]
}
```

**Important detail**: Results are queried `ORDER BY collected_at DESC` (newest first for `LIMIT`), then **reversed to ascending** before returning. This ensures the dashboard gets data in chronological measurement order, even if messages arrived out of order due to retry queue delays.

Uses SQLAlchemy `joinedload` for `Snapshot.metrics` and `Snapshot.device` to avoid N+1 query problems.

#### `GET /health` — Health Check

```
Response: {"status": "healthy"}  (200)
```

Used by `run_all.py` to verify the server is ready before starting collectors.

### CORS

```python
CORS(app)  # Allows all origins
```

Required because the React frontend may be served from a different port/domain.

---

## 8. Database Schema

MySQL via SQLAlchemy ORM. Located in `server/models.py` and `server/database.py`.

### Entity Relationship

```
Aggregator (1) ──── (N) Device (1) ──── (N) Snapshot (1) ──── (N) Metric
```

### Tables

#### `aggregators`

| Column | Type | Constraints |
|--------|------|-------------|
| `aggregator_id` | String(36) | PK (UUID) |
| `name` | String(255) | UNIQUE |

#### `devices`

| Column | Type | Constraints |
|--------|------|-------------|
| `device_id` | String(36) | PK (UUID) |
| `aggregator_id` | String(36) | FK → aggregators |
| `name` | String(255) | — |
| `source` | String(50) | "local", "transport_api", "mobile_app" |

#### `snapshots`

| Column | Type | Constraints |
|--------|------|-------------|
| `snapshot_id` | String(36) | PK (UUID) |
| `device_id` | String(36) | FK → devices |
| `collected_at` | Double | Unix timestamp (when measured) |
| `received_at` | Double | Unix timestamp (when server got it) |

Indexes: `idx_device_collected (device_id, collected_at)`, `idx_collected_at (collected_at)`

#### `metrics`

| Column | Type | Constraints |
|--------|------|-------------|
| `metric_id` | Integer | PK (auto-increment) |
| `snapshot_id` | String(36) | FK → snapshots |
| `metric_name` | String(255) | — |
| `metric_value` | Float | — |
| `unit` | String(50) | default "" |

Index: `idx_metric_name (metric_name)`

### Cascade Deletes

All relationships use cascade delete: deleting an aggregator deletes all its devices, snapshots, and metrics. This keeps referential integrity.

### Connection Configuration

```python
engine = create_engine(
    DATABASE_URL,              # mysql+pymysql://user:pass@host/db
    pool_recycle=280,          # Reconnect before MySQL's 5-min idle timeout
    pool_pre_ping=True         # Test connection health before use
)
```

**Why `pool_recycle=280`?** MySQL closes idle connections after ~300 seconds. By recycling at 280s, SQLAlchemy replaces stale connections before MySQL drops them, preventing "MySQL server has gone away" errors.

**Why `pool_pre_ping=True`?** Extra safety — tests connection is alive before handing it to application code.

### Session Management

```python
@contextmanager
def get_db():
    session = SessionLocal()
    try:
        yield session
        session.commit()       # Auto-commit on success
    except Exception:
        session.rollback()     # Auto-rollback on error
        raise
    finally:
        session.close()        # Always close
```

---

## 9. React Frontend

### Technology Stack

- **React 19** with TypeScript
- **Chart.js 4.5** + react-chartjs-2 for line charts
- **@react-google-maps/api** for Google Maps
- **Axios** for API calls
- **smol-toml** for parsing frontend config
- **Create React App** (react-scripts) build system

### Component Architecture

```
App
├── MetricsSection (polls /api/metrics?source=local every 5s)
│   └── Per device:
│       ├── Device header (name, aggregator, source)
│       ├── Metadata grid (IDs, timestamps, latency)
│       ├── Current metric value cards (colored)
│       └── MetricChart (Line chart per metric type)
│
└── TransportMap (polls /api/metrics?source=transport_api every 30s)
    ├── Map header with metadata
    ├── Timeline slider (playback through historical positions)
    └── GoogleMap with Markers + InfoWindows
```

### MetricsSection

- Fetches `GET /api/metrics?source=local&limit=50` every 5 seconds
- Groups snapshots by `device_id`
- For each device, renders:
  - Header with device name, aggregator name, source type
  - Metadata grid: device_id, aggregator_id, collected_at, received_at, latency (received - collected)
  - **Current values**: Colored cards showing latest value for each metric
  - **Charts**: One `<Line>` chart per unique metric name, showing values over time
- Chart config: no animation (real-time), max 8 x-axis ticks, tension 0.2
- Color palette rotates through 8 colours

### TransportMap

- Fetches `GET /api/metrics?source=transport_api&limit=100` every 30 seconds
- `buildVehicleTracks()` processes snapshots into per-vehicle position histories:
  - Parses metric names: `{id}_latitude`, `{id}_longitude`, `{id}_last_arrival_delay`
  - Builds `VehicleTrack { id, positions: [{lat, lng, timestamp, delay}] }`
- **Timeline slider**: Range from min to max `collected_at` across all data
  - Step: 1 second granularity
  - "Resume Live" button when user scrubs to historical time
  - Live mode auto-advances to latest data
- **Map**: Default centre Dublin (53.3498, -6.2603), zoom 11
- **Markers**: One per vehicle at selected time, click shows InfoWindow with vehicle ID, delay, coordinates

### Frontend Config

`public/config.toml` (loaded at runtime via fetch + smol-toml):

```toml
[system]
source = "local"
limit = 50

[transport]
source = "transport_api"

[transport.map]
centre_lat = 53.3498
centre_lng = -6.2603
zoom = 11
```

### Proxy (Development)

`package.json`: `"proxy": "http://100.67.157.90:5000"` — proxies API requests to the Flask server during development.

---

## 10. Logging System

Located at `sharedUtils/logger/logger.py`.

### Configuration (from config.toml)

```toml
[logging]
level = "INFO"
file = "logger/logs/system_metrics.log"
format = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
console_export = true
```

### Features

- **Rotating file handler**: 5 MB max per file, keeps 3 backups (`.log.1`, `.log.2`, `.log.3`)
- **Console output**: Enabled by `console_export` flag
- **Thread-safe**: Double-checked locking for config load; lock-guarded handler registration
- **Fallback**: If TOML fails to load, uses hardcoded defaults

### Usage Pattern

```python
from sharedUtils.logger.logger import get_logger
logger = get_logger(__name__)
logger.info("Collector started")
```

`get_logger(name)` returns a `logging.Logger` with handlers already configured. Safe to call multiple times (handlers only added once per logger).

---

## 11. Error Handling & Resilience

### Collector Level

| Scenario | Handling |
|----------|---------|
| `collect_data()` throws exception | `_collection_loop()` catches it, logs with `exc_info=True`, continues to next cycle |
| API call fails (Transport/Mobile) | Returns `None`/empty list, collector produces empty or partial snapshot |
| Individual metric parse fails | Logs warning, skips that metric, continues with others |
| Thread won't stop | `stop()` logs warning after timeout, continues shutdown |

### Queue Level

| Scenario | Handling |
|----------|---------|
| Redis connection fails at startup | Exception raised, `run_all.py` aborts |
| Redis operation fails during runtime | Caught, logged, worker continues |
| HTTP 4xx from server (permanent) | Message moved to `metrics:failed` immediately |
| HTTP 5xx/timeout (transient) | Exponential backoff retry (up to 5 attempts) |
| Retries exhausted | Message moved to `metrics:failed` |
| Server recovers after outage | `_recover_transient_failures()` sweeps failed queue, re-enqueues transient failures |
| Malformed envelope in Redis | Skipped with warning, worker continues |

### Server Level

| Scenario | Handling |
|----------|---------|
| Invalid JSON body | 400 response |
| Missing required fields | 400 response |
| Unknown device_id | 404 (single) or skip (batch) |
| Database error | 500 response, auto-rollback, logged |
| Concurrent aggregator registration | `IntegrityError` caught, returns existing record |
| Batch with mixed valid/invalid items | Valid items stored, invalid items skipped |

### Key Resilience Pattern

The system is designed so that **no single failure loses data permanently**:

1. Collectors fire-and-forget to Redis (fast, local)
2. Redis persists messages to disk
3. Worker retries transient failures with backoff
4. Failed messages are recoverable when server returns
5. Batch endpoint skips bad items instead of rejecting entire batches

---

## 12. Threading Model

```
Main Thread (run_all.py)
│
├── LocalDataCollector Thread
│   └── Loop: collect_data() → queue.put() → sleep(10s)
│
├── TransportCollector Thread
│   └── Loop: collect_data() → queue.put() per vehicle → sleep(60s)
│
├── MobileAppCollector Thread (optional)
│   └── Loop: collect_data() → queue.put() → sleep(60s)
│
└── RedisQueueWorker Thread
    └── Loop: check retries → batch pop → HTTP POST → sleep(1s if idle)
```

### Thread Safety Mechanisms

| Resource | Protection |
|----------|-----------|
| Config cache | `threading.Lock()` with double-checked locking |
| Logger handlers | `threading.Lock()` with `hasHandlers()` guard |
| Queue singleton | `threading.Lock()` with double-checked locking |
| Redis operations | Atomic Redis commands (no application-level locks needed) |
| Collector `_running` flag | Simple boolean (read/write is atomic in CPython) |
| HTTP Session | Created once in queue worker, reused (requests.Session is thread-safe for single-thread use) |

### No Deadlock Risk

Collectors and the queue worker are fully decoupled:
- Collectors push to Redis (`LPUSH`) — non-blocking
- Worker pops from Redis (`BRPOP`) — blocks only on itself
- No shared locks between collectors and worker

---

## 13. Deployment

### Remote Server (Flask API)

- **Machine**: `100.67.157.90` (Tailscale VPN address)
- **WSGI server**: Gunicorn with 4 workers, bound to `0.0.0.0:5000`
- **Database**: MySQL (connection string in `DATABASE_URL` env var)
- **Restart script**: `restart_server.sh` — kills existing, starts new, verifies PID

```bash
gunicorn -w 4 -b 0.0.0.0:5000 server.app:app \
    --access-logfile "$LOG_FILE" \
    --error-logfile "$LOG_FILE"
```

### Local Machine (Data Collection)

Requirements:
1. Python 3.11+
2. Redis server running on localhost:6379
3. Remote Flask server reachable
4. `.env` with `PRIMARY_KEY`, `SECONDARY_KEY` (and optionally Supabase creds)

```bash
pip install -r requirements.txt
redis-server &                    # Start Redis
python run_all.py                 # Start collecting
```

### React Frontend

```bash
cd react_frontend
npm install
npm start                         # Dev server with proxy to Flask
npm run build                     # Production build
```

---

## 14. Testing

Located in `sharedUtils/testing/`. All tests use `unittest` with `unittest.mock`.

### Test Files

| File | Focus | Approx Tests |
|------|-------|-------------|
| `test_batch_upload.py` | Batch upload: size limits, HTTP responses, error routing | 50+ |
| `test_failed_queue_recovery.py` | Error classification, retry logic, recovery sweep | 60+ |
| `test_transport_collector.py` | Per-bus snapshot generation, metric naming | ~10 |
| `test_integration.py` | End-to-end: collector → queue flow | ~5 |
| `test_upload_queue_integration.py` | Queue statistics, persistence, monitoring | ~10 |

### What's Tested

- **Batch upload**: empty queue, batch size limits, 2xx/4xx/5xx handling, timeout/connection errors, malformed envelopes, endpoint derivation
- **Error classification**: every HTTP status maps correctly to permanent/transient
- **Retry routing**: transient with retries → retry queue; exhausted → failed; permanent → failed; from_failed → failed on second failure
- **Recovery**: transient failures re-enqueued, permanent stay failed, sweep bounded by queue length at start
- **Transport collector**: N buses → N snapshots, metric naming without prefixes, missing trip updates handled, empty API response fallback
- **Integration**: Full path from collector through queue with real Redis

### Running Tests

```bash
python -m pytest sharedUtils/testing/ -v
```

---

## 15. Key Design Decisions & Interview Talking Points

### Why Redis over a simpler queue (e.g., Python Queue)?

Python's `queue.Queue` is in-memory only — if the process crashes, all pending messages are lost. Redis provides **persistence** (RDB/AOF), **atomic operations**, and **sorted sets** for retry scheduling. It's much simpler than deploying RabbitMQ or Kafka at this scale.

### Why batch uploads instead of individual POSTs?

Each HTTP request has overhead (TCP handshake, headers, server-side session creation). Batching 50 snapshots into one POST reduces network round-trips by 50x and database transaction overhead. The batch endpoint also enables partial success — one bad message doesn't block the others.

### Why per-vehicle snapshots for transport data?

The TransportCollector overrides `generate_message()` to create one snapshot per bus. This keeps each snapshot small and self-contained. If one bus has parsing issues, only that bus's snapshot is affected. It also maps cleanly to the database model (one snapshot = one device at one point in time).

### Why double-checked locking for singletons?

Multiple threads (collectors + queue worker) may simultaneously call `get_typed_config()` or `get_upload_queue()` at startup. Double-checked locking ensures thread-safe initialization without the overhead of acquiring a lock on every subsequent access. The outer check is lock-free; the inner check prevents duplicate initialization.

### Why `collected_at` vs `received_at`?

Messages may arrive at the server out of order due to retry queue delays. `collected_at` is when the data was actually measured; `received_at` is when the server got it. The GET endpoint sorts by `collected_at` so the frontend sees data in true measurement order, not arrival order.

### Why exponential backoff?

If the server is overloaded or down, hammering it with retries makes things worse. Exponential backoff (1s, 2s, 4s, 8s, 16s) gives the server progressively more time to recover. Combined with the recovery mechanism, this ensures no permanent data loss for transient issues.

### Why Pydantic for config validation?

Configuration errors are a common source of production bugs. Pydantic catches them at startup with clear error messages ("port must be 1-65535", "interval must be >= 1") rather than failing silently at runtime with confusing exceptions. It also provides type safety and IDE autocompletion.

### Why the Template Method pattern for collectors?

All collectors share the same lifecycle (start/stop/collect loop/export) but differ in what they collect. The abstract `collect_data()` method enforces this contract. Adding a new collector requires only implementing `collect_data()` — threading, queuing, and lifecycle management are inherited.

### Why CORS with all origins?

Development convenience — the React dev server runs on a different port (3000) from the Flask API (5000). In production, this could be tightened to specific origins.

### Why `pool_pre_ping` and `pool_recycle` for MySQL?

Long-running server processes can hold database connections for hours. MySQL drops idle connections after ~300 seconds. `pool_recycle=280` proactively refreshes connections before MySQL cuts them. `pool_pre_ping` adds a safety check before each query. Together they prevent "MySQL server has gone away" errors.

### Why interruptible sleep in collectors?

A simple `time.sleep(60)` would block shutdown for up to 60 seconds. The 1-second granular sleep with `_running` check ensures the collector thread exits within ~1 second of a shutdown signal, making the system responsive to SIGTERM.

### Why not use Celery/task queue?

The system has a small, fixed number of periodic tasks. Celery would add operational complexity (broker, worker processes, monitoring) for little benefit. Python threads + Redis provide exactly what's needed with minimal moving parts.
