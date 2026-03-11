# Server Code Review

## Overview

The server is a Flask API backed by MySQL via SQLAlchemy. It has four files:

| File | Purpose |
|---|---|
| `database.py` | Engine, session factory, transactional context manager |
| `models.py` | ORM models: Aggregator → Device → Snapshot → Metric |
| `app.py` | Flask routes: registration, ingest, query, health |
| `reset_db.py` | One-shot script to drop/recreate all tables |

The API surface:

| Endpoint | Method | Purpose |
|---|---|---|
| `/aggregators` | POST | Register an aggregator (idempotent) |
| `/devices` | POST | Register a device under an aggregator (idempotent) |
| `/api/metrics` | POST | Ingest a single snapshot |
| `/api/metrics/batch` | POST | Ingest a batch of snapshots (primary path) |
| `/api/metrics` | GET | Query historical metrics with filtering |
| `/health` | GET | Health check |

---

## `database.py` — Clean and Minimal

### Strengths

- **Fails fast** — raises `RuntimeError` if `DATABASE_URL` is unset rather than silently defaulting to SQLite or similar. This prevents "works on my machine" issues.
- **`pool_recycle=280`** — proactively reconnects before MySQL's default 5-minute idle timeout. Shows awareness of real production MySQL behaviour.
- **`pool_pre_ping=True`** — tests connection health before each checkout, preventing "MySQL server has gone away" errors after idle periods. Belt-and-suspenders with `pool_recycle`.
- **`get_db()` context manager** — clean transactional pattern: auto-commit on success, rollback on exception, always close. Prevents session leaks.

### Issues

1. **Module-level side effect: `DATABASE_URL` is read at import time (line 8).** This means importing `database.py` — even for tests or tooling — immediately requires the env var to be set, or the import crashes with `RuntimeError`. This makes the module untestable in isolation without `DATABASE_URL`. The standard pattern is to defer engine creation to a function or make it lazy.

2. **No connection pool size configuration.** The default SQLAlchemy pool size is 5 with 10 overflow. For a server receiving batches of 500 snapshots from multiple aggregators, this may be fine, but it's worth being explicit. If someone asks "what happens under load?", you want to have an answer.

3. **`DeclarativeBase` without `__abstract__ = True`.** Minor — `Base` works fine as-is with the modern `DeclarativeBase` API, but adding `__abstract__ = True` would be more explicit about intent.

---

## `models.py` — Well-Designed Schema

### Strengths

- **Proper normalization.** Four tables in a clean hierarchy: Aggregator (1) → Device (N) → Snapshot (N) → Metric (N). This avoids the common mistake of a flat "dump everything" table.
- **Dual timestamps on Snapshot** — `collected_at` (when the data was measured) vs `received_at` (when the server got it). The docstring explicitly notes that queries should sort by `collected_at` to handle out-of-order delivery from the retry queue. This is a thoughtful design that anticipates real-world conditions.
- **Composite index `idx_device_collected`** on `(device_id, collected_at)` — this directly supports the most common query pattern (get recent metrics for a device). Good index design.
- **`idx_collected_at`** — supports time-range queries across all devices.
- **`UniqueConstraint` on Device** — `(aggregator_id, name, source)` prevents duplicate device registration, which matches the idempotent POST /devices endpoint.
- **`cascade="all, delete-orphan"`** on relationships — deleting an aggregator cascades through devices, snapshots, and metrics. Clean tear-down.
- **`server_default=""` on Metric.unit** — handles the database default at the SQL level, not just the Python level.

### Issues

4. **UUIDs stored as `String(36)` (lines 14, 31, 55, 76).** MySQL has no native UUID type, so this is technically correct, but `String(36)` means every primary key, foreign key, and index is operating on a 36-byte string comparison instead of a 16-byte binary one. For a high-throughput system (transport collector sends hundreds of bus snapshots per minute), this adds up. Using `BINARY(16)` with a UUID adapter or MySQL 8's `UUID_TO_BIN()` would halve index size and improve join performance. Worth mentioning if asked about scalability.

5. **`collected_at` and `received_at` use `Double` (line 58-59).** Unix timestamps as IEEE 754 doubles work, but lose precision beyond ~15 significant digits. A timestamp like `1710000000.123456` has 16 significant digits — you're right at the edge. MySQL's `TIMESTAMP` or `DATETIME(3)` would be more idiomatic and give you native time functions in queries. Not a bug today, but a design choice worth defending.

6. **No index on `Metric.snapshot_id` beyond the foreign key.** MySQL/InnoDB automatically creates an index for `ForeignKey` columns, so this is actually fine — but it's implicit. Adding an explicit `Index("idx_metric_snapshot", "snapshot_id")` would make the intent clear to anyone reading the model.

7. **`received_at` default is `time.time` (line 59) — a callable, not a value.** This is correct for SQLAlchemy's `default=` parameter (it calls the function at insert time). But it's a Python-side default, not a `server_default`. If rows are ever inserted via raw SQL (as the batch endpoint does!), this default won't apply. The batch endpoint manually passes `received_at`, so this works, but the mismatch between the ORM model's default and the raw SQL insert is fragile.

8. **No `created_at` on Aggregator or Device.** You know when data was collected and received, but not when the aggregator or device was first registered. Minor, but useful for auditing.

---

## `app.py` — The Core, Most to Discuss

### Strengths

- **Idempotent registration endpoints.** Both `POST /aggregators` and `POST /devices` check for existing records before inserting and handle `IntegrityError` for race conditions. This means collectors can restart freely without breaking registration.
- **Race condition handling** (lines 57-63, 114-122). On `IntegrityError`, the endpoint re-queries and returns the existing record. This is the textbook pattern for idempotent upserts in SQL without `ON CONFLICT`.
- **Batch endpoint with device cache** (lines 223-224). `known_devices` dict avoids repeated `SELECT` queries for the same `device_id` within a batch. Smart optimisation for batches of 500.
- **Raw SQL in GET /api/metrics** with a subquery that applies `LIMIT` on snapshots *before* joining metrics (lines 321-330). This prevents the common N+1-turned-cartesian-product problem where `LIMIT 100` on a joined query gives you 100 *rows* (not 100 snapshots). Good SQL.
- **Collapse logic** (lines 339-364) — flat SQL rows are collapsed into per-snapshot dicts with nested metrics arrays. Maintains insertion order via `order` list. Clean.
- **`CORS(app)`** — enabled for the React frontend.
- **Health check endpoint** — simple, does the job, used by `run_all.py` for startup sequencing.

### Issues

#### Validation & Safety

9. **`not all([snapshot_id, device_id, timestamp is not None])` is misleading (lines 157, 236).** This mixes truthiness checks with an explicit `is not None` check. The list evaluates to `[<snapshot_id>, <device_id>, True/False]`. If `snapshot_id` is `""` (empty string), `all()` correctly rejects it. But `timestamp is not None` evaluates to a boolean *before* going into the list — the reader has to think hard about what this does. Clearer:
   ```python
   if not snapshot_id or not device_id or timestamp is None:
   ```

10. **No input validation on `metric_value` (line 181, 262).** The server calls `float(entry.get("metric_value", 0.0))` — if a malformed payload sends `metric_value: "not_a_number"`, this raises `ValueError` which is caught by the blanket `except Exception`, returning a 500. This should be a 400. More importantly, the default of `0.0` silently inserts zeros for missing values instead of rejecting the payload.

11. **No validation on `metric_name` (lines 180, 261).** An empty `metric_name` (the default if the key is missing) is silently accepted. The database allows it (`nullable=False` but `""` is not null). This could lead to mysterious empty-named metrics in query results.

12. **No max payload size enforcement.** The batch endpoint accepts arbitrarily large arrays. A single malformed or malicious request with 100,000 snapshots would hammer the database. Flask's default `MAX_CONTENT_LENGTH` is unlimited. Consider setting `app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024` (16 MB) or similar.

13. **`sys` is imported but never used (line 5).** Dead import.

#### Database & SQL

14. **`INSERT IGNORE` is MySQL-specific (lines 268-274).** The rest of the server uses SQLAlchemy's ORM for portability, but the batch endpoint drops to MySQL-specific raw SQL. If you ever need to switch to PostgreSQL (or a judge asks about portability), this breaks. PostgreSQL uses `ON CONFLICT DO NOTHING`. SQLAlchemy's `insert().prefix_with("IGNORE")` or dialect-aware `on_conflict_do_nothing()` would be more portable.

15. **`INSERT IGNORE` on the metrics table is incorrect (line 272-274).** `metrics.metric_id` is an auto-increment primary key, so there's never a duplicate key to ignore on that table. The `IGNORE` is doing nothing — it only matters for the snapshots table where `snapshot_id` is the PK and retried batches could send the same ID. Misleading.

16. **The single-snapshot `POST /api/metrics` doesn't handle duplicate `snapshot_id` (lines 160-198).** If the upload queue retries a message (which the Redis queue is designed to do), the same `snapshot_id` gets inserted again, causing an `IntegrityError` that's caught as a generic 500. Meanwhile, the batch endpoint handles this correctly with `INSERT IGNORE`. Inconsistent retry behaviour.

17. **Device lookup in `POST /api/metrics` happens inside the transaction (line 162).** This means the database session is held open during the SELECT + INSERT. For the single-snapshot endpoint this is fine, but it's worth noting that the batch endpoint is strictly better — it caches device lookups and uses bulk inserts.

#### Query Endpoint

18. **`LIMIT` is applied in the subquery with `DESC` ordering, then the outer query re-orders `ASC` (lines 329, 335).** This means "get the N most recent snapshots, then return them in chronological order." This is correct and intentional but non-obvious — a comment explaining this would help.

19. **No pagination support.** The `since` parameter provides cursor-like filtering, but there's no `offset` or `before` parameter. For a dashboard polling every few seconds with `since=last_timestamp`, this works. But for historical browsing, you'd need pagination. Acceptable for current scope, but worth knowing.

20. **The `since` filter uses `>` not `>=` (line 328: `sn.collected_at > :since`).** This means if two snapshots share the exact same `collected_at` timestamp (possible with transport collector emitting many bus snapshots at once), and you use the last seen timestamp as `since`, you'll miss all but the first. Should be `>=` with deduplication, or include `snapshot_id` in the cursor.

#### Architecture

21. **`Base.metadata.create_all(bind=engine)` at module level (line 25).** This runs every time `app.py` is imported — including by test runners, linters, or anything that imports from the server package. Combined with `database.py`'s module-level `DATABASE_URL` check, importing the server package requires a live database connection. This makes the server code untestable without a real MySQL instance.

22. **No rate limiting on any endpoint.** The registration endpoints are idempotent so re-calling them is harmless, but `POST /api/metrics` and the batch endpoint could be abused. For a college project this is fine, but in a production context you'd want `flask-limiter` or similar.

23. **No authentication on any endpoint.** The `api_key` config field exists in the upload queue config (and the `requests.Session` sets an `X-API-Key` header), but the server never checks it. The infrastructure for auth is half-built but not connected.

24. **`CORS(app)` with no origin restriction (line 22).** This allows any domain to call your API. Fine for development, but for a deployed system you'd want `CORS(app, origins=["https://yourdomain.com"])`.

---

## `reset_db.py` — Fine for Dev

### Strengths

- Clear warning in the docstring about data destruction.
- Imports all models with a `# noqa: F401` comment explaining why — the import registers the models with `Base.metadata` so `drop_all` / `create_all` see them.

### Issues

25. **No confirmation prompt.** Running `python -m server.reset_db` immediately drops all tables. A "type YES to confirm" prompt would prevent accidents. Even for a dev tool, this is good practice.

26. **No migration support.** The only way to change the schema is to nuke and recreate. For development this is fine, but if asked "how would you evolve the schema in production?", the answer should reference Alembic or similar. Worth mentioning proactively in a presentation.

---

## `logger.py` (sharedUtils) — Shared Across All Components

### Strengths

- Thread-safe singleton with double-checked locking.
- Rotating file handler with sensible defaults (5 MB, 3 backups).
- Graceful fallback to defaults if config file is unreadable.
- Resolves relative log paths against `PROJECT_ROOT` — logs always go to a predictable location.

### Issues

27. **Logger loads config by directly reading `config.toml` (lines 31-33) instead of using the typed config system in `sharedUtils.config`.** This is a chicken-and-egg problem — the config loader itself uses the logger, so the logger can't depend on the config loader. But it means there are two independent TOML parsers for the same file. If the config format changes, you need to update both. Worth documenting this circular dependency.

28. **`hasHandlers()` check (line 63) can be fooled by parent logger propagation.** If the root logger has handlers, `hasHandlers()` returns `True` even if this specific logger has none. This could cause missed handler setup in certain import orders. A more robust check: `if not logger.handlers:` (checks only direct handlers).

---

## Summary Table

| Severity | Issue | File | Line(s) |
|---|---|---|---|
| **Bug** | Duplicate `snapshot_id` in single POST causes 500, not handled like batch | `app.py` | 160-198 |
| **Bug** | `INSERT IGNORE` on metrics table does nothing (auto-increment PK) | `app.py` | 272-274 |
| **Bug** | `since` uses `>` — can miss same-timestamp snapshots | `app.py` | 328 |
| **Design** | `INSERT IGNORE` is MySQL-specific, breaks portability | `app.py` | 268-274 |
| **Design** | Module-level `DATABASE_URL` check + `create_all` makes code untestable | `database.py`, `app.py` | 8-14, 25 |
| **Design** | UUIDs as String(36) — 2x index size vs binary | `models.py` | 14,31,55,76 |
| **Design** | No authentication despite `api_key` config field existing | `app.py` | — |
| **Validation** | `metric_value` parse error returns 500 instead of 400 | `app.py` | 181, 262 |
| **Validation** | No max payload size on batch endpoint | `app.py` | 201 |
| **Polish** | `sys` imported but unused | `app.py` | 5 |
| **Polish** | No migration tooling (Alembic) | `reset_db.py` | — |
| **Polish** | `not all([..., timestamp is not None])` is confusing | `app.py` | 157, 236 |

---

## Priority Fixes Before Presenting

### Must-fix
- Handle duplicate `snapshot_id` in `POST /api/metrics` (catch `IntegrityError` and return 200/409 instead of 500)
- Remove unused `sys` import
- Fix or document the `since > :since` vs `>=` behaviour

### Should-fix
- Add `metric_value` type validation (return 400 on non-numeric, don't default to 0.0)
- Remove `INSERT IGNORE` from the metrics table INSERT (it's doing nothing)
- Set `MAX_CONTENT_LENGTH` on the Flask app

### Be ready to discuss
- Why normalized schema over a flat table (query flexibility, no redundant data, proper indexing)
- `collected_at` vs `received_at` and how it handles out-of-order delivery
- The batch endpoint's design: device caching, bulk insert, idempotent via INSERT IGNORE
- Why raw SQL for the GET query (subquery LIMIT prevents cartesian explosion)
- Trade-off: String UUIDs vs binary UUIDs (simplicity/debuggability vs performance)
- No Alembic — what you'd do differently in production
