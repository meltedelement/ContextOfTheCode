# Upload Queue Code Review

## Overview

The upload queue is the central nervous system of the client side. It sits between the collectors and the server, providing:

- **Persistent storage** via Redis (survives crashes/restarts)
- **Background worker** that drains the queue without blocking collectors
- **Batch uploads** (up to 500 snapshots per HTTP request)
- **Exponential backoff retry** with a sorted set for deferred scheduling
- **Transient failure recovery** — when the server comes back, failed messages get re-queued
- **Error classification** — permanent errors (4xx) skip retry entirely

| File | Purpose |
|---|---|
| `redis_queue.py` | Full queue implementation: put, worker loop, retry, batch upload |
| `manager.py` | Thread-safe singleton accessor for the global queue instance |
| `__init__.py` | Package exports |

### Redis Data Structures

| Key | Type | Purpose |
|---|---|---|
| `metrics:pending` | List | Main FIFO queue (LPUSH/BRPOP) |
| `metrics:retry` | Sorted Set | Deferred retries, scored by future Unix timestamp |
| `metrics:failed` | List | Messages that exhausted retries or hit permanent errors |

---

## `manager.py` — Clean Singleton

### Strengths

- **Double-checked locking** (lines 28-30). The `if is None` → `with _lock` → `if is None` pattern avoids lock contention on every call while still being thread-safe. This is the correct Python pattern for a lazy singleton.
- **Auto-starts the queue on first access** (line 34). Callers don't need to worry about lifecycle — `get_upload_queue()` always returns a ready-to-use instance.
- **`stop_upload_queue()`** properly acquires the lock, stops the queue, and sets the global to `None` so a subsequent `get_upload_queue()` would create a fresh instance.

### Issues

1. **Hardcoded to `RedisUploadQueue` (line 6, 33).** The config has `implementation = "redis"` which implies other implementations might exist, but the manager always creates `RedisUploadQueue`. The `implementation` field is never checked. Either remove the config field (it's misleading) or add a factory dispatch. For the presentation, this is a question waiting to happen: "what's the `implementation` field for?"

2. **No restart protection.** If `stop_upload_queue()` is called and then `get_upload_queue()` is called again, a brand-new queue instance is created and started. This is by design (the global is set to `None`), but it means any code that calls `get_upload_queue()` after shutdown will silently spin up a new worker thread. In the normal flow (`run_all.py`), this doesn't happen, but it's a footgun for anyone reusing the module.

---

## `redis_queue.py` — The Centrepiece

This is the most sophisticated component in the entire project. 700 lines of queue management with retry logic, error classification, batch uploads, and failure recovery.

### Architecture Strengths

3. **Envelope pattern (lines 260-267).** Messages are wrapped in an envelope that carries `retry_count`, `first_queued_at`, `last_error`, `failure_class`, and `from_failed`. This metadata travels with the message through the entire retry lifecycle without polluting the `SnapshotMessage` payload. Clean separation of transport concerns from domain data.

4. **Non-blocking retry via sorted set (lines 358-395, 466-469).** Instead of sleeping in the worker thread during backoff, failed messages are `ZADD`-ed to `metrics:retry` with a future timestamp as the score. The worker polls this set each loop and promotes expired entries back to `pending`. This means the worker is never blocked — it's always processing other messages while retries wait.

5. **Batch upload (lines 397-482).** The worker pops up to `batch_size` (500) messages using `brpop` + a pipeline of `rpop` calls, then sends them in a single HTTP request. This dramatically reduces HTTP overhead — instead of 500 round trips, it's one. The pipeline pattern (line 417-420) is the correct Redis idiom for non-blocking multi-pop.

6. **Error classification (lines 56-73).** `_classify_error()` distinguishes permanent errors (4xx, missing endpoint) from transient errors (5xx, timeouts, connection errors). Permanent errors skip the retry queue entirely and go straight to `failed`. This prevents wasting retry attempts on unrecoverable errors (e.g. 400 Bad Request).

7. **Transient failure recovery (lines 604-648).** After a successful upload, if there had been transient failures, the worker sweeps the `failed` queue and re-enqueues transient failures with `from_failed=True`. This means if the server was down for an hour and 1000 messages ended up in `failed`, they all get a second chance once connectivity is restored. The `from_failed` flag ensures they only get one retry — if they fail again, they're permanently dead.

8. **Bounded recovery sweep (line 615).** `queue_len` is captured at the start of the sweep, so messages added to `failed` during the sweep are not processed. Prevents infinite loops.

9. **Heartbeat logging (lines 335-345).** The worker logs stats every 60 seconds so you can verify it's alive and see queue depths without enabling debug logging.

10. **`brpop` with timeout (line 409).** Uses blocking pop with a 1-second timeout rather than polling with sleep. This is the correct Redis pattern — it's event-driven when messages are available and falls back to periodic checks when idle.

11. **Context manager support (lines 234-239).** `__enter__` / `__exit__` for `with` statement usage. Clean resource management.

12. **`socket_keepalive=True` on the Redis connection (line 182).** Prevents TCP idle disconnections from firewalls or NAT devices. Production-aware.

### Issues

#### Critical

13. **`_classify_error` is defined twice (lines 56-73 and 76-93).** The exact same function appears twice in sequence. The second definition silently shadows the first. This is a copy-paste error. It works (the second one is identical), but it's the kind of thing that makes a code reviewer wince. **Remove the duplicate.**

14. **`_process_pending_queue()` is dead code (lines 504-602).** This is the old single-message processing method. The worker loop (line 329) calls `_process_pending_batch()` instead. The old method is ~100 lines of unreachable code. It should be removed — dead code in the most critical component is a red flag. If you want to keep it for reference, put it in a comment or a git tag, not in production code.

#### Design

15. **Batch failure treats all messages the same (lines 455-469).** When a batch upload fails, every envelope in the batch gets the same error and failure class, and they're all individually routed to retry or failed. But a 400 error might mean one malformed snapshot in the batch poisoned the whole request. The server's batch endpoint skips malformed items (it returns 201 even if some items were skipped), so this is unlikely to be a real problem — but if the server ever starts returning 400 for a single bad item in a batch, all 500 messages get classified as permanent failures and go to the dead letter queue.

16. **No batch partial-success handling.** The `_attempt_batch_upload` returns a single `(bool, error)` for the entire batch. If the server stored 499 out of 500 and returned an error for one, the client retries all 500. The `INSERT IGNORE` on the server side makes this idempotent (duplicates are skipped), so it's safe, but it's wasteful. A more sophisticated approach would have the server return which `snapshot_id`s succeeded.

17. **`_had_transient_failures` is an instance variable, not thread-safe (line 163).** It's written by the worker thread and never read from another thread, so in practice this is fine. But if the queue were ever extended to multiple workers, it would be a race condition.

18. **Recovery sweep reads and re-pushes to the same queue (lines 620-643).** The sweep pops from `FAILED_QUEUE`, inspects each envelope, and either pushes it back to `FAILED_QUEUE` (permanent) or to `PENDING_QUEUE` (transient). For permanent failures, it does `rpop` then `lpush` — moving the item from the tail to the head, which reverses the order. This doesn't cause data loss, but the `failed` queue order becomes scrambled after a recovery sweep. Minor, since the failed queue is mainly for debugging/auditing.

19. **No TTL or max size on the failed queue.** If the server is misconfigured and every message is a permanent failure, the `metrics:failed` list grows without bound in Redis. Over days, this could consume significant Redis memory. A periodic trim or TTL on old failed messages would be prudent.

#### Robustness

20. **`put()` serializes the entire SnapshotMessage twice (lines 266-268).** `message.model_dump_json()` serializes the Pydantic model to a JSON string (the payload). Then `json.dumps(envelope)` serializes the envelope (which contains the payload string). So each message in Redis is a JSON string containing a JSON string. This double-encoding means every message is parsed twice on read (`json.loads(envelope_json)` then `json.loads(env["payload"])`). For correctness this is fine, but it's ~2x the CPU cost of serialization. The alternative (embedding the payload as a dict rather than a string) would be cleaner.

21. **`session` (requests.Session) is created in `start()` but used across the worker thread (lines 193-198, 489).** `requests.Session` is not documented as thread-safe, though in practice it works for simple use (single worker thread). If multiple workers were ever added, this would need a per-thread session or connection pooling.

22. **No max message size validation in `put()` (lines 243-281).** A `SnapshotMessage` with thousands of metrics would produce a very large envelope. Redis can handle it (up to 512 MB per value), but an extremely large message could cause the batch upload to exceed the server's `MAX_CONTENT_LENGTH` (if one were ever set). A size check or warning in `put()` would be defensive.

23. **`_process_retry_queue` has a TOCTOU issue (lines 370-380).** It `zrangebyscore` to get ready messages, then `zrem` each one individually. Between the `zrangebyscore` and `zrem`, another process (if there were multiple workers) could have already removed it. In the current single-worker design this can't happen, but the code isn't self-evidently safe for multi-worker extension. A `ZPOPMIN`-based approach or Lua script would be atomic.

---

## `__init__.py` — Clean Exports

Exports the right things: `RedisUploadQueue`, `get_upload_queue`, `stop_upload_queue`. No issues.

---

## Data Flow Summary

```
Collector.generate_message()
  → BaseDataCollector.export_to_data_model()
    → get_upload_queue().put(message)         # LPUSH to metrics:pending
      ↓
Worker thread (_worker_loop):
  1. _process_retry_queue()                   # ZRANGEBYSCORE metrics:retry → LPUSH metrics:pending
  2. _process_pending_batch()                 # BRPOP metrics:pending (+ pipeline RPOP ×499)
     → _attempt_batch_upload(payloads)        # POST /api/metrics/batch
        Success → done
        Failure:
          _classify_error()
          permanent → LPUSH metrics:failed
          transient, retries left → ZADD metrics:retry (score = now + backoff)
          transient, retries exhausted → LPUSH metrics:failed
     → On first success after failures:
        _recover_transient_failures()         # Sweep metrics:failed → metrics:pending
```

---

## Summary Table

| Severity | Issue | File | Line(s) |
|---|---|---|---|
| **Must-fix** | `_classify_error` defined twice (copy-paste duplicate) | `redis_queue.py` | 56-93 |
| **Must-fix** | `_process_pending_queue()` is 100 lines of dead code | `redis_queue.py` | 504-602 |
| **Design** | `implementation` config field is never checked | `manager.py` | — |
| **Design** | Batch failure treats all messages identically | `redis_queue.py` | 455-469 |
| **Design** | No TTL/max-size on failed queue (unbounded growth) | `redis_queue.py` | — |
| **Design** | Double JSON serialization of every message | `redis_queue.py` | 266-268 |
| **Design** | Recovery sweep scrambles failed queue order | `redis_queue.py` | 620-643 |
| **Robustness** | No max message size validation in `put()` | `redis_queue.py` | 243-281 |
| **Robustness** | TOCTOU in `_process_retry_queue` (safe with single worker) | `redis_queue.py` | 370-380 |
| **Minor** | `_had_transient_failures` not thread-safe (safe with single worker) | `redis_queue.py` | 163 |

---

## Priority Fixes Before Presenting

### Must-fix (judges will immediately notice)
- Remove the duplicate `_classify_error` function
- Remove the dead `_process_pending_queue()` method

### Should-fix
- Either remove the `implementation` config field or add a comment explaining it's reserved for future use
- Add a comment to `_process_retry_queue` noting it's safe because of single-worker design

### Be ready to discuss
- Why Redis over an in-process queue (persistence across crashes, atomic operations, observable via `redis-cli`)
- The envelope pattern and why transport metadata is separated from domain data
- Why `ZADD` with timestamp scores for retry scheduling instead of sleeping in the worker
- Batch upload trade-offs: efficiency vs partial-failure handling
- The transient recovery sweep: when it triggers, what `from_failed` prevents, why the sweep is bounded
- Exponential backoff calculation: `base * (multiplier ^ (retry_count - 1))` → 1s, 2s, 4s, 8s, 16s
- What happens if Redis goes down (the `put()` call returns `False`, the collector logs an error but keeps running — data is lost for that cycle but the system doesn't crash)
