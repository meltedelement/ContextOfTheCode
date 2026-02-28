#!/usr/bin/env python3
"""
System Monitoring Tool - Main Orchestrator

Starts and manages all components:
- Upload queue worker (auto-started by queue manager)
- Data collectors (LocalCollector, WikipediaCollector)

The Flask API server runs separately on the remote server.

Usage:
    python run_all.py
"""

import sys
import time
import signal

try:
    import redis as redis_lib
except ImportError:
    redis_lib = None

try:
    import requests as requests_lib
except ImportError:
    requests_lib = None

from collectors.local_collector import LocalDataCollector
from collectors.wikipedia_collector import WikipediaCollector
from sharedUtils.logger.logger import get_logger
from sharedUtils.upload_queue.manager import stop_upload_queue
from sharedUtils.config import (
    get_typed_config,
    get_local_collector_config,
    get_wikipedia_collector_config,
)

logger = get_logger(__name__)

FLASK_HEALTH_POLL_INTERVAL = 0.5    # Seconds between /health polls
FLASK_HEALTH_TIMEOUT = 30           # Max seconds to wait for Flask to become healthy
REDIS_CHECK_TIMEOUT_SECONDS = 2     # Socket connect timeout when verifying Redis is reachable
SHUTDOWN_POLL_INTERVAL_SECONDS = 1  # How often the main loop checks for a stop signal

running = True


def check_redis_running() -> bool:
    """Check if Redis is running on configured host/port."""
    config = get_typed_config()
    redis_config = config.upload_queue

    logger.info("Checking Redis connection at %s:%d...", redis_config.redis_host, redis_config.redis_port)

    if redis_lib is None:
        logger.error("✗ redis package is not installed — cannot check Redis")
        return False

    try:
        client = redis_lib.Redis(
            host=redis_config.redis_host,
            port=redis_config.redis_port,
            db=redis_config.redis_db,
            password=redis_config.redis_password,
            socket_connect_timeout=REDIS_CHECK_TIMEOUT_SECONDS
        )
        client.ping()
        logger.info("✓ Redis is running")
        return True
    except Exception as e:
        logger.error("✗ Redis not running: %s", e)
        logger.error("")
        logger.error("Please start Redis before running this script:")
        logger.error("  sudo systemctl start redis")
        logger.error("  OR")
        logger.error("  redis-server")
        return False


def wait_for_flask_healthy(base_url: str) -> bool:
    """
    Poll GET /health until Flask responds 200 or timeout expires.

    Returns True if Flask became healthy within FLASK_HEALTH_TIMEOUT seconds.
    """
    if requests_lib is None:
        logger.error("requests package not available — cannot poll /health")
        return False

    health_url = f"{base_url}/health"
    deadline = time.time() + FLASK_HEALTH_TIMEOUT

    while time.time() < deadline:
        try:
            resp = requests_lib.get(health_url, timeout=2)
            if resp.status_code == 200:
                logger.info("✓ Flask API server is healthy")
                return True
        except Exception:
            pass  # Not ready yet
        time.sleep(FLASK_HEALTH_POLL_INTERVAL)

    logger.error("✗ Flask did not become healthy within %ds", FLASK_HEALTH_TIMEOUT)
    return False


# Collector registry — each entry maps a collector class to the function
# that returns its typed config.  Adding a new collector means adding one
# entry here; enable/disable lives in that collector's own config section.
COLLECTOR_REGISTRY = [
    (LocalDataCollector,  get_local_collector_config),
    (WikipediaCollector,  get_wikipedia_collector_config),
]


def register_aggregator_and_devices(base_url: str, aggregator_name: str) -> dict:
    """
    Register this aggregator and its devices with the server.

    1. POST /aggregators → receive aggregator_id (idempotent)
    2. For each enabled collector, POST /devices → receive device_id UUID

    Returns a dict mapping source name to server-issued device_id UUID,
    e.g. {"local": "uuid-a", "wikipedia": "uuid-b"}.
    """
    if requests_lib is None:
        raise RuntimeError("requests package not available — cannot register")

    session = requests_lib.Session()
    session.headers.update({"Content-Type": "application/json"})

    # 1. Register aggregator
    resp = session.post(f"{base_url}/aggregators", json={"name": aggregator_name}, timeout=10)
    resp.raise_for_status()
    aggregator_id = resp.json()["aggregator_id"]
    logger.info("Aggregator '%s' registered: %s", aggregator_name, aggregator_id)

    # 2. Register each enabled device
    device_ids = {}

    for collector_cls, get_config_fn in COLLECTOR_REGISTRY:
        if not get_config_fn().enabled:
            logger.info("Collector '%s' is disabled — skipping", collector_cls.__name__)
            continue

        resp = session.post(
            f"{base_url}/devices",
            json={
                "aggregator_id": aggregator_id,
                "name": collector_cls.DEVICE_NAME,
                "source": collector_cls.SOURCE,
            },
            timeout=10,
        )
        resp.raise_for_status()
        device_id = resp.json()["device_id"]
        device_ids[collector_cls.SOURCE] = device_id
        logger.info("Device '%s' (source=%s) registered: %s",
                     collector_cls.DEVICE_NAME, collector_cls.SOURCE, device_id)

    session.close()
    return device_ids


def start_collectors(device_ids: dict):
    """
    Initialize and start all enabled collectors in async mode.

    Each collector runs in its own background thread with its own
    collection interval, pushing data to the upload queue autonomously.

    Args:
        device_ids: Mapping of source → server-issued device UUID

    Returns:
        List of (name, collector) tuples for active collectors
    """
    collectors = []

    for collector_cls, get_config_fn in COLLECTOR_REGISTRY:
        config = get_config_fn()
        if not config.enabled:
            continue

        device_id = device_ids.get(collector_cls.SOURCE)
        if not device_id:
            logger.error("No device_id for %s — skipping", collector_cls.__name__)
            continue

        logger.info("Initializing %s (interval=%ds)...",
                     collector_cls.__name__, config.collection_interval)
        collector = collector_cls(device_id=device_id)
        collectors.append((collector_cls.__name__, collector))

    if not collectors:
        logger.warning("No collectors enabled in config.toml")
        return collectors

    logger.info("")
    logger.info("=" * 60)
    logger.info("Starting collectors in async mode")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    logger.info("")

    for name, collector in collectors:
        logger.info("Starting %s...", name)
        collector.start()

    logger.info("")
    logger.info("All collectors started successfully")
    logger.info("")

    return collectors


def wait_for_shutdown(collectors):
    """
    Wait for shutdown signal while collectors run in background.

    Args:
        collectors: List of (name, collector) tuples
    """
    global running

    try:
        while running:
            time.sleep(SHUTDOWN_POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("")
        logger.info("Interrupted by user")

    logger.info("Stopping collectors...")
    for name, collector in collectors:
        logger.info("Stopping %s...", name)
        collector.stop()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    _ = signum, frame  # Unused but required by signal.signal
    logger.info("")
    logger.info("Received shutdown signal. Stopping...")
    running = False


def cleanup():
    """Clean up resources on shutdown."""
    logger.info("Cleaning up resources...")

    try:
        stop_upload_queue()
        logger.info("✓ Upload queue stopped")
    except Exception as e:
        logger.error("Error stopping upload queue: %s", e)

    logger.info("Shutdown complete")


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("System Monitoring Tool - Starting All Components")
    logger.info("=" * 60)
    logger.info("")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Step 1: Check Redis
        if not check_redis_running():
            logger.error("")
            return 1

        logger.info("")

        # Step 2: Check remote Flask server is reachable
        config = get_typed_config()
        registration_base_url = config.upload_queue.registration_base_url
        if not wait_for_flask_healthy(registration_base_url):
            logger.error("Flask health check failed — aborting")
            return 1

        logger.info("")

        # Step 3: Register aggregator and devices
        aggregator_name = config.aggregator.name
        logger.info("Registering aggregator '%s'...", aggregator_name)
        device_ids = register_aggregator_and_devices(registration_base_url, aggregator_name)
        logger.info("Device IDs: %s", device_ids)
        logger.info("")

        # Step 4: Start collectors with server-issued UUIDs
        collectors = start_collectors(device_ids)

        if not collectors:
            logger.error("No collectors started")
            return 1

        logger.info("✓ All components initialized successfully")
        logger.info("")

        wait_for_shutdown(collectors)

    except KeyboardInterrupt:
        logger.info("")
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        return 1
    finally:
        cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
