"""Unit tests for batch upload functionality in redis_queue.py.

Tests cover:
- _process_pending_batch(): queue draining, batch size, return value
- Successful batch: session called once, correct endpoint, flag/recovery behaviour
- Failed batch: per-envelope routing to retry/failed queues with correct failure_class
- _attempt_batch_upload(): HTTP success, 4xx/5xx, timeout, connection error, no endpoint
- batch_endpoint derivation from api_endpoint (trailing slash handling)

All tests mock Redis and HTTP — no live infrastructure needed.
"""

import json
import time
from unittest.mock import MagicMock, patch, call

import pytest

from sharedUtils.upload_queue.redis_queue import RedisUploadQueue


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.redis_host = "localhost"
    config.redis_port = 6379
    config.redis_db = 0
    config.redis_password = None
    config.api_endpoint = "http://localhost:8080/api/metrics"
    config.api_key = None
    config.timeout = 5
    config.max_retry_attempts = 3
    config.backoff_base = 1.0
    config.backoff_multiplier = 2.0
    config.worker_sleep = 0.1
    config.batch_size = 3
    return config


@pytest.fixture
def queue(mock_config):
    """RedisUploadQueue with mocked Redis and HTTP session (not started)."""
    q = RedisUploadQueue(mock_config)
    q.redis_client = MagicMock()
    q.session = MagicMock()
    return q


def _make_envelope(snapshot_id="snap-001", retry_count=0, from_failed=False, failure_class=None):
    env = {
        "retry_count": retry_count,
        "first_queued_at": time.time(),
        "last_error": None,
        "payload": json.dumps({
            "snapshot_id": snapshot_id,
            "timestamp": time.time(),
            "device_id": "device-001",
            "metrics": [{"metric_name": "cpu", "metric_value": 10.0, "unit": "%"}],
        }),
    }
    if from_failed:
        env["from_failed"] = True
    if failure_class:
        env["failure_class"] = failure_class
    return env


def _setup_batch(queue, envelopes):
    """
    Configure redis mocks so brpop returns the first envelope and the pipeline
    returns the rest (padded with None to simulate an empty queue tail).
    """
    jsons = [json.dumps(e) for e in envelopes]

    queue.redis_client.brpop.return_value = ("metrics:pending", jsons[0])

    mock_pipeline = MagicMock()
    # Pipeline returns the remaining items then None for any extra rpop calls
    remaining = jsons[1:] + [None] * (queue.batch_size - 1)
    mock_pipeline.execute.return_value = remaining
    queue.redis_client.pipeline.return_value = mock_pipeline

    return jsons, mock_pipeline


# ── _process_pending_batch: basic behaviour ───────────────────────────────────


class TestProcessPendingBatchBasic:

    def test_empty_queue_returns_zero(self, queue):
        queue.redis_client.brpop.return_value = None

        result = queue._process_pending_batch()

        assert result == 0
        queue.session.post.assert_not_called()

    def test_single_item_returns_one(self, queue):
        env = _make_envelope("snap-001")
        _setup_batch(queue, [env])
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")

        result = queue._process_pending_batch()

        assert result == 1

    def test_three_items_returns_three(self, queue):
        envs = [_make_envelope(f"snap-{i:03d}") for i in range(3)]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")

        result = queue._process_pending_batch()

        assert result == 3

    def test_batch_size_caps_items_popped(self, queue):
        """With batch_size=3, pipeline should make exactly 2 rpop calls (brpop got the first)."""
        envs = [_make_envelope(f"snap-{i:03d}") for i in range(3)]
        _, mock_pipeline = _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")

        queue._process_pending_batch()

        assert mock_pipeline.rpop.call_count == queue.batch_size - 1

    def test_fewer_items_than_batch_size(self, queue):
        """Queue with 2 items and batch_size=3 should process the 2 available."""
        envs = [_make_envelope(f"snap-{i:03d}") for i in range(2)]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")

        result = queue._process_pending_batch()

        assert result == 2


# ── _process_pending_batch: correct endpoint ──────────────────────────────────


class TestBatchEndpointUsed:

    def test_posts_to_batch_endpoint_not_single(self, queue):
        envs = [_make_envelope("snap-001")]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")

        queue._process_pending_batch()

        call_url = queue.session.post.call_args[0][0]
        assert call_url == queue.batch_endpoint
        assert call_url.endswith("/batch")

    def test_single_http_call_for_full_batch(self, queue):
        """Regardless of batch size, only one HTTP POST should be made."""
        envs = [_make_envelope(f"snap-{i:03d}") for i in range(3)]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")

        queue._process_pending_batch()

        assert queue.session.post.call_count == 1

    def test_post_body_is_json_list(self, queue):
        """The POST body should be a JSON-encoded list of snapshot payloads."""
        envs = [_make_envelope(f"snap-{i:03d}") for i in range(2)]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")

        queue._process_pending_batch()

        posted_data = queue.session.post.call_args[1]["data"]
        parsed = json.loads(posted_data)
        assert isinstance(parsed, list)
        assert len(parsed) == 2


# ── _process_pending_batch: success behaviour ─────────────────────────────────


class TestBatchSuccess:

    def test_success_does_not_push_to_any_queue(self, queue):
        envs = [_make_envelope("snap-001")]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")

        queue._process_pending_batch()

        queue.redis_client.lpush.assert_not_called()
        queue.redis_client.zadd.assert_not_called()

    def test_success_triggers_recovery_when_flag_set(self, queue):
        queue._had_transient_failures = True
        envs = [_make_envelope("snap-001")]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")
        queue.redis_client.llen.return_value = 0  # empty failed queue

        queue._process_pending_batch()

        queue.redis_client.llen.assert_called_with("metrics:failed")
        assert queue._had_transient_failures is False

    def test_success_skips_recovery_when_flag_not_set(self, queue):
        queue._had_transient_failures = False
        envs = [_make_envelope("snap-001")]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")

        queue._process_pending_batch()

        queue.redis_client.llen.assert_not_called()

    def test_2xx_variants_all_succeed(self, queue):
        for status in [200, 201, 204]:
            queue.redis_client.reset_mock()
            queue.session.reset_mock()
            envs = [_make_envelope("snap-001")]
            _setup_batch(queue, envs)
            queue.session.post.return_value = MagicMock(status_code=status, text="OK")

            result = queue._process_pending_batch()

            assert result == 1, f"Expected success for HTTP {status}"
            queue.redis_client.lpush.assert_not_called()


# ── _process_pending_batch: failure routing ───────────────────────────────────


class TestBatchFailureRouting:

    def test_permanent_failure_all_envelopes_to_failed(self, queue):
        envs = [_make_envelope(f"snap-{i:03d}") for i in range(3)]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=400, text="Bad Request")

        queue._process_pending_batch()

        failed_calls = [c for c in queue.redis_client.lpush.call_args_list
                        if c[0][0] == "metrics:failed"]
        assert len(failed_calls) == 3
        queue.redis_client.zadd.assert_not_called()

    def test_permanent_failure_does_not_set_transient_flag(self, queue):
        envs = [_make_envelope("snap-001")]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=400, text="Bad Request")
        queue._had_transient_failures = False

        queue._process_pending_batch()

        assert queue._had_transient_failures is False

    def test_transient_failure_retries_remaining_go_to_retry_queue(self, queue):
        envs = [_make_envelope(f"snap-{i:03d}", retry_count=0) for i in range(3)]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=503, text="Unavailable")

        queue._process_pending_batch()

        assert queue.redis_client.zadd.call_count == 3
        queue.redis_client.lpush.assert_not_called()

    def test_transient_failure_sets_flag(self, queue):
        envs = [_make_envelope("snap-001", retry_count=0)]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=500, text="Error")
        queue._had_transient_failures = False

        queue._process_pending_batch()

        assert queue._had_transient_failures is True

    def test_transient_exhausted_retries_go_to_failed(self, queue):
        # max_retry_attempts=3, retry_count=2 means next attempt is the 3rd (exhausted)
        envs = [_make_envelope(f"snap-{i:03d}", retry_count=2) for i in range(2)]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=500, text="Error")

        queue._process_pending_batch()

        failed_calls = [c for c in queue.redis_client.lpush.call_args_list
                        if c[0][0] == "metrics:failed"]
        assert len(failed_calls) == 2
        queue.redis_client.zadd.assert_not_called()

    def test_from_failed_envelope_goes_to_failed_on_any_error(self, queue):
        """Recovered envelopes that fail again must not enter the retry queue."""
        envs = [_make_envelope("snap-001", retry_count=0, from_failed=True)]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=503, text="Still down")

        queue._process_pending_batch()

        failed_calls = [c for c in queue.redis_client.lpush.call_args_list
                        if c[0][0] == "metrics:failed"]
        assert len(failed_calls) == 1
        queue.redis_client.zadd.assert_not_called()

    def test_failure_class_stored_in_re_queued_envelope(self, queue):
        envs = [_make_envelope("snap-001", retry_count=0)]
        _setup_batch(queue, envs)
        queue.session.post.return_value = MagicMock(status_code=500, text="Error")

        queue._process_pending_batch()

        zadd_args = queue.redis_client.zadd.call_args[0]
        stored = json.loads(list(zadd_args[1].keys())[0])
        assert stored["failure_class"] == "transient"
        assert stored["retry_count"] == 1

    def test_mixed_retry_counts_routed_correctly(self, queue):
        """One envelope with retries left, one exhausted — should split correctly."""
        env_retry = _make_envelope("snap-001", retry_count=0)   # goes to retry
        env_exhausted = _make_envelope("snap-002", retry_count=2)  # goes to failed
        _setup_batch(queue, [env_retry, env_exhausted])
        queue.session.post.return_value = MagicMock(status_code=503, text="Error")

        queue._process_pending_batch()

        failed_calls = [c for c in queue.redis_client.lpush.call_args_list
                        if c[0][0] == "metrics:failed"]
        retry_calls = queue.redis_client.zadd.call_args_list
        assert len(failed_calls) == 1
        assert len(retry_calls) == 1


# ── _process_pending_batch: malformed envelopes ───────────────────────────────


class TestMalformedEnvelopes:

    def test_malformed_json_is_discarded(self, queue):
        """A non-parseable envelope should be skipped without crashing."""
        bad_json = "not valid json {"
        queue.redis_client.brpop.return_value = ("metrics:pending", bad_json)
        mock_pipeline = MagicMock()
        mock_pipeline.execute.return_value = [None, None]
        queue.redis_client.pipeline.return_value = mock_pipeline

        # Should not raise
        result = queue._process_pending_batch()

        # No upload attempted, nothing queued
        assert result == 0
        queue.session.post.assert_not_called()

    def test_valid_and_malformed_mixed(self, queue):
        """Valid envelope after a bad one should still be uploaded."""
        bad = "{{broken"
        good = json.dumps(_make_envelope("snap-good"))

        queue.redis_client.brpop.return_value = ("metrics:pending", good)
        mock_pipeline = MagicMock()
        mock_pipeline.execute.return_value = [bad, None]
        queue.redis_client.pipeline.return_value = mock_pipeline
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")

        result = queue._process_pending_batch()

        # Only the good envelope makes it through
        assert result == 1
        posted = json.loads(queue.session.post.call_args[1]["data"])
        assert len(posted) == 1


# ── _attempt_batch_upload ─────────────────────────────────────────────────────


class TestAttemptBatchUpload:

    def test_no_endpoint_returns_failure(self, queue):
        queue.batch_endpoint = None

        success, error = queue._attempt_batch_upload([{"snapshot_id": "x"}])

        assert success is False
        assert "No api_endpoint" in error

    def test_201_returns_success(self, queue):
        queue.session.post.return_value = MagicMock(status_code=201, text="Created")

        success, error = queue._attempt_batch_upload([{"snapshot_id": "x"}])

        assert success is True
        assert error is None

    def test_500_returns_failure_with_error_string(self, queue):
        queue.session.post.return_value = MagicMock(status_code=500, text="Internal Error")

        success, error = queue._attempt_batch_upload([{"snapshot_id": "x"}])

        assert success is False
        assert "HTTP 500" in error

    def test_400_returns_failure(self, queue):
        queue.session.post.return_value = MagicMock(status_code=400, text="Bad Request")

        success, error = queue._attempt_batch_upload([{"snapshot_id": "x"}])

        assert success is False
        assert "HTTP 400" in error

    def test_timeout_returns_failure(self, queue):
        import requests as req_lib
        queue.session.post.side_effect = req_lib.exceptions.Timeout()

        success, error = queue._attempt_batch_upload([{"snapshot_id": "x"}])

        assert success is False
        assert "timed out" in error

    def test_connection_error_returns_failure(self, queue):
        import requests as req_lib
        queue.session.post.side_effect = req_lib.exceptions.ConnectionError("refused")

        success, error = queue._attempt_batch_upload([{"snapshot_id": "x"}])

        assert success is False
        assert "ConnectionError" in error


# ── batch_endpoint derivation ─────────────────────────────────────────────────


class TestBatchEndpointDerivation:

    def test_endpoint_without_trailing_slash(self, mock_config):
        mock_config.api_endpoint = "http://localhost:5000/api/metrics"
        q = RedisUploadQueue(mock_config)
        assert q.batch_endpoint == "http://localhost:5000/api/metrics/batch"

    def test_endpoint_with_trailing_slash(self, mock_config):
        mock_config.api_endpoint = "http://localhost:5000/api/metrics/"
        q = RedisUploadQueue(mock_config)
        assert q.batch_endpoint == "http://localhost:5000/api/metrics/batch"

    def test_no_api_endpoint_gives_none_batch_endpoint(self, mock_config):
        mock_config.api_endpoint = None
        q = RedisUploadQueue(mock_config)
        assert q.batch_endpoint is None
