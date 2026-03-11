# Collectors Code Review

## Overview

The collectors package implements a three-tier data collection system using an abstract base class pattern. Three concrete collectors gather metrics from different sources and push them through a shared upload queue.

| Collector | Source | Interval | Output |
|---|---|---|---|
| `LocalDataCollector` | CPU, RAM, temp via `psutil` | 10s | 3-4 metrics per snapshot |
| `TransportCollector` | Irish National Transport GTFS-R API | 60s | One snapshot per bus (lat, lon, delay) |
| `MobileAppCollector` | Supabase `device_stats` table | 60s | ~8 metrics per mobile device |

---

## `base_data_collector.py` — Solid Foundation

### Strengths

- **Clean ABC pattern** — `collect_data()` is the only thing subclasses need to implement. The template method (`generate_message` → `collect_data` → `export_to_data_model`) keeps the flow consistent.
- **`MetricEntry` as a Pydantic model** enforces float-only values at the boundary, preventing garbage data from propagating into the queue and database.
- **`SnapshotMessage`** uses `Field(default_factory=...)` for `snapshot_id` and `timestamp` — clean, immutable defaults without the mutable-default-argument trap.
- **Backpressure check** (`BACKPRESSURE_THRESHOLD = 5000`) skips collection cycles when the queue is clogged, preventing runaway memory growth.
- **Interruptible sleep loop** (lines 171-174) checks `_running` every second, allowing sub-second shutdown instead of blocking for the full interval.
- **Thread naming** (line 193: `f"{self.__class__.__name__}-Thread"`) makes debugging threaded issues trivial in logs and profilers.
- **Named constants** at module level (`THREAD_SHUTDOWN_GRACE_SECONDS`, `BACKPRESSURE_THRESHOLD`) — no magic numbers.

### Issues

1. **`_running` is not thread-safe (line 79).** It's a plain `bool` read from the collection thread and written from `stop()`. On CPython this works due to the GIL, but it's technically a data race. A `threading.Event` would be both correct and cleaner — replace the sleep loop with `self._stop_event.wait(self.collection_interval)`, which is also more responsive to shutdown signals.

2. **`daemon=False` threads (line 194).** Non-daemon threads mean that if `stop()` is never called (e.g. unhandled exception in the caller), the process will hang forever. This is deliberate given the `wait_for_shutdown` pattern in `run_all.py`, but it's fragile — anyone using `BaseDataCollector` outside of `run_all.py` who forgets `stop()` gets a zombie process.

3. **`collect_data()` abstract method has a body (lines 101-102).** The `logger.debug` + `pass` inside an `@abstractmethod` will never execute — Python prevents instantiation of classes that don't override it. This is dead code.

4. **`generate_message()` always queues (line 123).** There's no way to collect data and inspect the `SnapshotMessage` without also pushing it to the upload queue. Testing or debugging requires calling `collect_data()` directly, bypassing the snapshot construction entirely. A minor design rigidity.

---

## `transport_collector.py` — Most Complex, Most Issues

### Strengths

- **Joins two API responses** (vehicle positions + trip updates) intelligently via a `(trip_id, vehicle_id)` lookup dict — O(1) per vehicle instead of nested iteration.
- **Per-vehicle snapshot emission** (`generate_message` override) emits one `SnapshotMessage` per bus rather than one giant snapshot. This maps cleanly to the database schema and makes per-vehicle queries trivial.
- **Graceful degradation** — returns empty metrics on API failure rather than crashing the collection loop.

### Issues

5. **Duplicated API query methods (lines 63-111).** `_query_transport_api()` and `_query_tripupdates_api()` are near-identical — same headers, same error handling, same timeout. Only the URL differs. Should be a single `_query_api(url: str) -> Optional[dict]` method. If you ever need to change auth headers or error handling, you'll fix one and forget the other.

6. **`format_param` is accepted but never used (line 60).** The constructor takes it, stores it as `self.format_param`, but nothing reads it anywhere. Dead weight in the API surface.

7. **Mixed indentation — tabs instead of spaces.** This file uses tabs while `base_data_collector.py` and `local_collector.py` use 4-space indentation. PEP 8 mandates spaces. Judges/reviewers will notice this immediately.

8. **`generate_message()` double-calls the API when metrics is empty (line 191).** When `collect_data()` returns an empty list, it falls through to `super().generate_message()`, which calls `collect_data()` *again* — a second pair of HTTP requests for zero benefit. Should construct and return an empty `SnapshotMessage` directly.

9. **`_last_bus_count` is a hacky dynamically-assigned attribute (line 218).** Storing state via `self._last_bus_count = len(groups)` and reading it with `getattr(collector, "_last_bus_count", "?")` in `__main__` is fragile. If `generate_message` is part of the public API, the bus count should be returned properly (e.g. as part of a named return type, or stored in a declared `__init__` attribute).

10. **`import json` inside the `__main__` try block (line 243).** Inconsistent with the rest of the file where all imports are at module level. Minor but sloppy.

11. **No rate limiting or caching for API calls.** The config interval is 60s, but nothing prevents manual calls. Two HTTP requests per cycle with no backoff on repeated API failures.

12. **`vehicle_data` could be `None` at line 175.** If `_query_transport_api()` returns `None`, the `else` branch tries `vehicle_data.keys()` which would raise `AttributeError`. The `isinstance(vehicle_data, dict)` guard technically catches this, but the logic is convoluted. Cleaner: add `if vehicle_data is None: return metrics` as an early return before the `if "entity" in vehicle_data` check.

---

## `local_collector.py` — Cleanest of the Three

### Strengths

- Simple, focused, does one thing well.
- Graceful temperature sensor fallback chain: known sensors (`coretemp`, `k10temp`, `zenpower`) → first available sensor → `None`. Handles Intel, AMD, and unknown platforms.
- Config-driven precision and sampling interval — no hardcoded values.
- Clean `__main__` block for standalone testing.

### Issues

13. **`collect_data()` calls `get_collector_config()` on every invocation (line 69).** The config is a cached singleton so this is cheap, but fetching config inside a method called every 10 seconds is unnecessary overhead. Store `precision` and `cpu_interval` in `__init__`.

14. **`_get_cpu_temperature()` also calls `get_collector_config()` (line 38).** Same issue — config is fetched twice per collection cycle for no reason.

15. **`psutil.cpu_percent(interval=cpu_interval)` blocks the thread (line 82)** for `cpu_sample_interval` seconds (default 1.0s). The actual collection time is `collection_interval + cpu_sample_interval`, not just `collection_interval`. Worth documenting or accounting for.

---

## `mobile_app_collector.py` — Good but Inconsistent

### Strengths

- Clean row-to-metric mapping with proper null handling per field.
- Per-field `try/except (ValueError, TypeError)` prevents one bad value from killing the entire collection cycle.
- `query_limit` config prevents full table scans on Supabase.

### Issues

16. **Mixed indentation — tabs instead of spaces.** Same issue as `transport_collector.py`.

17. **All mobile device metrics go into a single `SnapshotMessage`.** Metric names are prefixed `mobile_{user_id}_{col}`, which embeds the device identity into the metric name. Unlike `TransportCollector` which correctly emits one snapshot per vehicle, this shoves all devices into one snapshot. Inconsistent, and makes per-device queries harder at the database level.

18. **No `__main__` block** for standalone testing, unlike the other two collectors.

19. **`SOURCE_TYPE` module constant vs `SOURCE` class attribute.** `TransportCollector` and `MobileAppCollector` use a module-level `SOURCE_TYPE` string, while `LocalDataCollector` uses class attributes `SOURCE` and `DEVICE_NAME`. The lack of a consistent pattern means `COLLECTOR_REGISTRY` in `run_all.py` can't generically access these — `TransportCollector` and `MobileAppCollector` are handled with bespoke code instead.

---

## `__init__.py`

Exports `BaseDataCollector` and `MetricEntry` but not `SnapshotMessage`. Since `SnapshotMessage` is the primary data type that flows through the entire system (collectors → queue → server), it should be exported here too.

---

## Cross-Collector Consistency Issues

| Aspect | LocalDataCollector | TransportCollector | MobileAppCollector |
|---|---|---|---|
| Indentation | 4 spaces | Tabs | Tabs |
| Source identifier | Class attr `SOURCE` | Module const `SOURCE_TYPE` | Module const `SOURCE_TYPE` |
| Device name | Class attr `DEVICE_NAME` | Hardcoded in `run_all.py` | Hardcoded in `run_all.py` |
| Per-entity snapshots | N/A (single device) | Yes (one per bus) | No (all devices in one) |
| `__main__` block | Yes | Yes | No |
| In `COLLECTOR_REGISTRY` | Yes | No | No |

---

## Priority Fixes Before Presenting

### Must-fix (judges will notice)
- Fix mixed tabs/spaces in `transport_collector.py` and `mobile_app_collector.py`
- Extract duplicated `_query_transport_api` / `_query_tripupdates_api` into one method
- Remove unused `format_param` parameter

### Should-fix (shows polish)
- Unify source/device_name patterns across all collectors (class attributes)
- Add all collectors to `COLLECTOR_REGISTRY` in `run_all.py`
- Use `threading.Event` instead of bare `_running` bool
- Fix the double API call in `TransportCollector.generate_message()` when metrics is empty
- Export `SnapshotMessage` from `__init__.py`

### Be ready to discuss
- Why the base class uses a template method pattern (consistency, single queue integration point)
- Why `MetricEntry` enforces floats (prevents type confusion in the database, simplifies aggregation)
- The backpressure mechanism and why it matters
- Per-vehicle vs per-collection-cycle snapshot design tradeoff
