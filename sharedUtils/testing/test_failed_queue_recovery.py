"""Unit tests for failed queue recovery feature in redis_queue.py.

Tests cover:
- _classify_error() error classification
- Failure routing (permanent vs transient, from_failed handling)
- Recovery sweep (_recover_transient_failures)
- Flag management (_had_transient_failures)
- Legacy envelope handling (missing failure_class / from_failed)

All tests mock Redis and HTTP — no live infrastructure needed.
"""

import json
import time
from unittest.mock import MagicMock, patch, call

import pytest

from sharedUtils.upload_queue.redis_queue import RedisUploadQueue, _classify_error


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_config():
    """Minimal UploadQueueConfig-like object."""
    config = MagicMock()
    config.redis_host = "localhost"
    config.redis_port = 6379
    config.redis_db = 0
    config.redis_password = None
    config.api_endpoint = "http://localhost:8080/api/upload"
    config.api_key = None
    config.timeout = 5
    config.max_retry_attempts = 3
    config.backoff_base = 1.0
    config.backoff_multiplier = 2.0
    config.worker_sleep = 0.1
    return config


@pytest.fixture
def queue(mock_config):
    """RedisUploadQueue with mocked Redis client and HTTP session (not started)."""
    q = RedisUploadQueue(mock_config)
    q.redis_client = MagicMock()
    q.session = MagicMock()
    return q


def _make_envelope(retry_count=0, last_error=None, failure_class=None, from_failed=False):
    """Build a test envelope dict."""
    env = {
        "retry_count": retry_count,
        "first_queued_at": time.time(),
        "last_error": last_error,
        "payload": json.dumps({"snapshot_id": "test-snap-001"}),
    }
    if failure_class is not None:
        env["failure_class"] = failure_class
    if from_failed:
        env["from_failed"] = True
    return env


# ── _classify_error tests ────────────────────────────────────────────────────


class TestClassifyError:
    def test_4xx_is_permanent(self):
        assert _classify_error("HTTP 400: Bad Request") == "permanent"
        assert _classify_error("HTTP 404: Not Found") == "permanent"
        assert _classify_error("HTTP 422: Unprocessable Entity") == "permanent"

    def test_5xx_is_transient(self):
        assert _classify_error("HTTP 500: Internal Server Error") == "transient"
        assert _classify_error("HTTP 502: Bad Gateway") == "transient"
        assert _classify_error("HTTP 503: Service Unavailable") == "transient"

    def test_timeout_is_transient(self):
        assert _classify_error("Request timed out") == "transient"

    def test_connection_error_is_transient(self):
        assert _classify_error("ConnectionError: Connection refused") == "transient"

    def test_unexpected_error_is_transient(self):
        assert _classify_error("Unexpected error: something broke") == "transient"

    def test_no_endpoint_is_permanent(self):
        assert _classify_error("No api_endpoint configured") == "permanent"

    def test_empty_string_is_transient(self):
        assert _classify_error("") == "transient"

    def test_none_is_transient(self):
        assert _classify_error(None) == "transient"

    def test_http_edge_cases(self):
        # 3xx — not 4xx, so transient (unusual but safe default)
        assert _classify_error("HTTP 301: Moved") == "transient"
        # Malformed HTTP status line
        assert _classify_error("HTTP abc: weird") == "transient"


# ── Failure routing tests ─────────────────────────────────────────────────────


class TestFailureRouting:
    """Tests for the failure routing logic in _process_pending_queue."""

    def _setup_brpop(self, queue, envelope):
        """Configure redis brpop to return a single envelope, then empty."""
        envelope_json = json.dumps(envelope)
        queue.redis_client.brpop.return_value = ("metrics:pending", envelope_json)

    def test_permanent_failure_skips_retry(self, queue):
        """4xx error should go straight to failed queue, never to retry queue."""
        envelope = _make_envelope(retry_count=0)
        self._setup_brpop(queue, envelope)

        queue.session.post.return_value = MagicMock(status_code=400, text="Bad Request")

        queue._process_pending_queue()

        # Should have pushed to failed queue
        failed_calls = [c for c in queue.redis_client.lpush.call_args_list
                        if c[0][0] == "metrics:failed"]
        assert len(failed_calls) == 1

        pushed_envelope = json.loads(failed_calls[0][0][1])
        assert pushed_envelope["failure_class"] == "permanent"

        # Should NOT have added to retry queue
        queue.redis_client.zadd.assert_not_called()

    def test_transient_failure_with_retries_remaining(self, queue):
        """5xx error with retries left should go to retry queue and set flag."""
        envelope = _make_envelope(retry_count=0)
        self._setup_brpop(queue, envelope)

        queue.session.post.return_value = MagicMock(status_code=503, text="Unavailable")

        queue._process_pending_queue()

        # Should have added to retry queue
        queue.redis_client.zadd.assert_called_once()
        zadd_args = queue.redis_client.zadd.call_args[0]
        assert zadd_args[0] == "metrics:retry"

        scheduled_envelope = json.loads(list(zadd_args[1].keys())[0])
        assert scheduled_envelope["failure_class"] == "transient"
        assert scheduled_envelope["retry_count"] == 1

        # Flag should be set
        assert queue._had_transient_failures is True

    def test_transient_failure_retries_exhausted(self, queue):
        """Transient error with no retries left should go to failed queue."""
        envelope = _make_envelope(retry_count=2)  # max_retry_attempts=3, so this is the last
        self._setup_brpop(queue, envelope)

        queue.session.post.return_value = MagicMock(status_code=500, text="Error")

        queue._process_pending_queue()

        failed_calls = [c for c in queue.redis_client.lpush.call_args_list
                        if c[0][0] == "metrics:failed"]
        assert len(failed_calls) == 1

        pushed_envelope = json.loads(failed_calls[0][0][1])
        assert pushed_envelope["failure_class"] == "transient"
        assert pushed_envelope["retry_count"] == 3
        assert queue._had_transient_failures is True

    def test_from_failed_message_fails_again_goes_to_failed_permanently(self, queue):
        """A recovered message that fails again should go straight to failed."""
        envelope = _make_envelope(retry_count=0, from_failed=True)
        self._setup_brpop(queue, envelope)

        queue.session.post.return_value = MagicMock(status_code=503, text="Still down")

        queue._process_pending_queue()

        # Should go to failed, not retry
        failed_calls = [c for c in queue.redis_client.lpush.call_args_list
                        if c[0][0] == "metrics:failed"]
        assert len(failed_calls) == 1
        queue.redis_client.zadd.assert_not_called()

    def test_from_failed_message_succeeds(self, queue):
        """A recovered message that succeeds should just complete normally."""
        envelope = _make_envelope(retry_count=0, from_failed=True)
        self._setup_brpop(queue, envelope)

        queue.session.post.return_value = MagicMock(status_code=200, text="OK")

        result = queue._process_pending_queue()

        assert result is True
        # Nothing pushed to failed or retry
        queue.redis_client.lpush.assert_not_called()
        queue.redis_client.zadd.assert_not_called()


# ── Recovery sweep tests ──────────────────────────────────────────────────────


class TestRecoverTransientFailures:
    """Tests for the _recover_transient_failures method."""

    def test_moves_transient_to_pending(self, queue):
        """Transient failures should be moved to pending with from_failed=True."""
        envelope = _make_envelope(retry_count=3, failure_class="transient",
                                  last_error="HTTP 503: Unavailable")
        queue.redis_client.llen.return_value = 1
        queue.redis_client.rpop.side_effect = [json.dumps(envelope), None]

        queue._recover_transient_failures()

        pending_calls = [c for c in queue.redis_client.lpush.call_args_list
                         if c[0][0] == "metrics:pending"]
        assert len(pending_calls) == 1

        recovered = json.loads(pending_calls[0][0][1])
        assert recovered["from_failed"] is True
        assert recovered["retry_count"] == 0

    def test_leaves_permanent_in_failed(self, queue):
        """Permanent failures should stay in the failed queue."""
        envelope = _make_envelope(retry_count=1, failure_class="permanent",
                                  last_error="HTTP 400: Bad Request")
        queue.redis_client.llen.return_value = 1
        queue.redis_client.rpop.side_effect = [json.dumps(envelope), None]

        queue._recover_transient_failures()

        # Should push back to failed, not to pending
        failed_calls = [c for c in queue.redis_client.lpush.call_args_list
                        if c[0][0] == "metrics:failed"]
        pending_calls = [c for c in queue.redis_client.lpush.call_args_list
                         if c[0][0] == "metrics:pending"]
        assert len(failed_calls) == 1
        assert len(pending_calls) == 0

    def test_leaves_already_recovered_in_failed(self, queue):
        """Envelopes with from_failed=True should not be recovered again."""
        envelope = _make_envelope(retry_count=1, failure_class="transient",
                                  from_failed=True, last_error="HTTP 503: Unavailable")
        queue.redis_client.llen.return_value = 1
        queue.redis_client.rpop.side_effect = [json.dumps(envelope), None]

        queue._recover_transient_failures()

        failed_calls = [c for c in queue.redis_client.lpush.call_args_list
                        if c[0][0] == "metrics:failed"]
        pending_calls = [c for c in queue.redis_client.lpush.call_args_list
                         if c[0][0] == "metrics:pending"]
        assert len(failed_calls) == 1
        assert len(pending_calls) == 0

    def test_legacy_envelope_treated_as_permanent(self, queue):
        """Pre-existing envelopes without failure_class should not be recovered."""
        envelope = {
            "retry_count": 3,
            "first_queued_at": time.time(),
            "last_error": "HTTP 500: Error",
            "payload": json.dumps({"snapshot_id": "legacy-001"}),
        }
        queue.redis_client.llen.return_value = 1
        queue.redis_client.rpop.side_effect = [json.dumps(envelope), None]

        queue._recover_transient_failures()

        failed_calls = [c for c in queue.redis_client.lpush.call_args_list
                        if c[0][0] == "metrics:failed"]
        pending_calls = [c for c in queue.redis_client.lpush.call_args_list
                         if c[0][0] == "metrics:pending"]
        assert len(failed_calls) == 1
        assert len(pending_calls) == 0

    def test_bounded_by_llen(self, queue):
        """Sweep should only process the number of items present at the start."""
        env1 = _make_envelope(failure_class="transient", retry_count=3)
        env2 = _make_envelope(failure_class="transient", retry_count=3)

        # llen returns 1, but rpop returns 2 items — second should not be processed
        queue.redis_client.llen.return_value = 1
        queue.redis_client.rpop.side_effect = [json.dumps(env1), json.dumps(env2)]

        queue._recover_transient_failures()

        # Only 1 call to lpush (the recovered one), not 2
        pending_calls = [c for c in queue.redis_client.lpush.call_args_list
                         if c[0][0] == "metrics:pending"]
        assert len(pending_calls) == 1

    def test_empty_failed_queue_is_noop(self, queue):
        """No work when the failed queue is empty."""
        queue.redis_client.llen.return_value = 0

        queue._recover_transient_failures()

        queue.redis_client.rpop.assert_not_called()

    def test_mixed_envelopes(self, queue):
        """Sweep with a mix of transient, permanent, and already-recovered."""
        transient = _make_envelope(failure_class="transient", retry_count=3)
        permanent = _make_envelope(failure_class="permanent", retry_count=1)
        already_recovered = _make_envelope(failure_class="transient", retry_count=1,
                                           from_failed=True)

        queue.redis_client.llen.return_value = 3
        queue.redis_client.rpop.side_effect = [
            json.dumps(transient),
            json.dumps(permanent),
            json.dumps(already_recovered),
            None,
        ]

        queue._recover_transient_failures()

        pending_calls = [c for c in queue.redis_client.lpush.call_args_list
                         if c[0][0] == "metrics:pending"]
        failed_calls = [c for c in queue.redis_client.lpush.call_args_list
                        if c[0][0] == "metrics:failed"]
        assert len(pending_calls) == 1  # only the transient one
        assert len(failed_calls) == 2   # permanent + already-recovered


# ── Flag management tests ─────────────────────────────────────────────────────


class TestTransientFailureFlag:
    """Tests for _had_transient_failures flag triggering recovery."""

    def _setup_brpop(self, queue, envelope):
        envelope_json = json.dumps(envelope)
        queue.redis_client.brpop.return_value = ("metrics:pending", envelope_json)

    def test_success_triggers_recovery_when_flag_set(self, queue):
        """Successful upload with flag=True should call recovery and reset flag."""
        queue._had_transient_failures = True
        envelope = _make_envelope(retry_count=0)
        self._setup_brpop(queue, envelope)

        queue.session.post.return_value = MagicMock(status_code=200, text="OK")
        # Mock llen for recovery sweep (empty failed queue — just verify it's called)
        queue.redis_client.llen.return_value = 0

        queue._process_pending_queue()

        queue.redis_client.llen.assert_called_with("metrics:failed")
        assert queue._had_transient_failures is False

    def test_success_skips_recovery_when_flag_not_set(self, queue):
        """Successful upload with flag=False should not attempt recovery."""
        queue._had_transient_failures = False
        envelope = _make_envelope(retry_count=0)
        self._setup_brpop(queue, envelope)

        queue.session.post.return_value = MagicMock(status_code=200, text="OK")

        queue._process_pending_queue()

        # llen should NOT be called (recovery not triggered)
        queue.redis_client.llen.assert_not_called()
        assert queue._had_transient_failures is False

    def test_flag_not_set_on_permanent_failure(self, queue):
        """Permanent failures should not set the transient flag."""
        queue._had_transient_failures = False
        envelope = _make_envelope(retry_count=0)
        self._setup_brpop(queue, envelope)

        queue.session.post.return_value = MagicMock(status_code=400, text="Bad Request")

        queue._process_pending_queue()

        assert queue._had_transient_failures is False
