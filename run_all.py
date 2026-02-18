#!/usr/bin/env python3
"""
System Monitoring Tool - Main Orchestrator

Starts and manages all components:
- Flask API server (receives and stores metrics)
- Upload queue worker (auto-started by queue manager)
- Data collectors (LocalCollector, WikipediaCollector)

Usage:
    python run_all.py
"""

import sys
import time
import signal
import subprocess
import socket
from typing import Optional
from pathlib import Path

from collectors.LocalCollector import LocalDataCollector
from collectors.WikipediaCollector import WikipediaCollector
from sharedUtils.logger.logger import get_logger
from sharedUtils.upload_queue.manager import stop_upload_queue
from sharedUtils.config import get_typed_config

logger = get_logger(__name__)

# Global state for graceful shutdown
flask_process: Optional[subprocess.Popen] = None
running = True


def check_redis_running() -> bool:
    """Check if Redis is running on configured host/port."""
    config = get_typed_config()
    redis_config = config.upload_queue

    logger.info("Checking Redis connection at %s:%d...", redis_config.redis_host, redis_config.redis_port)

    try:
        import redis
        client = redis.Redis(
            host=redis_config.redis_host,
            port=redis_config.redis_port,
            db=redis_config.redis_db,
            password=redis_config.redis_password,
            socket_connect_timeout=2
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


def check_port_available(port: int, host: str = 'localhost') -> bool:
    """Check if a port is available."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        return result != 0  # Port is available if connection fails
    finally:
        sock.close()


def start_flask_server() -> Optional[subprocess.Popen]:
    """Start the Flask API server in a subprocess."""
    logger.info("Starting Flask API server...")

    # Check if port 5000 is already in use
    if not check_port_available(5000):
        logger.warning("⚠ Port 5000 is already in use - Flask may already be running")
        logger.warning("Continuing without starting new Flask instance...")
        return None

    try:
        flask_script = Path(__file__).parent / "server" / "app.py"
        process = subprocess.Popen(
            [sys.executable, str(flask_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1  # Line buffered
        )

        # Give Flask a moment to start
        time.sleep(2)

        # Check if process is still running
        if process.poll() is None:
            logger.info("✓ Flask API server started (PID: %d)", process.pid)
            logger.info("  Endpoint: http://localhost:5000/api/metrics")
            return process
        else:
            stderr = process.stderr.read() if process.stderr else ""
            logger.error("✗ Flask server failed to start: %s", stderr)
            return None

    except Exception as e:
        logger.error("✗ Failed to start Flask server: %s", e)
        return None


def start_collectors():
    """
    Initialize and start all enabled collectors in async mode.

    Each collector runs in its own background thread with its own
    collection interval, pushing data to the upload queue autonomously.

    Returns:
        List of (name, collector) tuples for active collectors
    """
    config = get_typed_config()
    collectors = []

    if "local" in config.collectors.enabled_collectors:
        logger.info("Initializing LocalDataCollector (interval=%ds)...", config.local_collector.collection_interval)
        local_collector = LocalDataCollector(device_id="local-pc-001")
        collectors.append(("LocalCollector", local_collector))

    if "third_party" in config.collectors.enabled_collectors:
        logger.info("Initializing WikipediaCollector (interval=%ds)...", config.wikipedia_collector.collection_interval)
        wiki_collector = WikipediaCollector(device_id="wikipedia-api-001")
        collectors.append(("WikipediaCollector", wiki_collector))

    # Note: Mobile collector would go here when implemented
    # if "mobile" in config.collectors.enabled_collectors:
    #     mobile_collector = MobileCollector(device_id="mobile-device-001")
    #     collectors.append(("MobileCollector", mobile_collector))

    if not collectors:
        logger.warning("No collectors enabled in config.toml")
        return collectors

    logger.info("")
    logger.info("=" * 60)
    logger.info("Starting collectors in async mode")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    logger.info("")

    # Start all collectors
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
        # Just sleep while collectors run in background
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("")
        logger.info("Interrupted by user")

    # Stop all collectors
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
    global flask_process

    logger.info("Cleaning up resources...")

    # Stop upload queue worker
    try:
        stop_upload_queue()
        logger.info("✓ Upload queue stopped")
    except Exception as e:
        logger.error("Error stopping upload queue: %s", e)

    # Stop Flask server
    if flask_process and flask_process.poll() is None:
        logger.info("Stopping Flask server...")
        flask_process.terminate()
        try:
            flask_process.wait(timeout=5)
            logger.info("✓ Flask server stopped")
        except subprocess.TimeoutExpired:
            logger.warning("Flask server did not stop gracefully, forcing shutdown...")
            flask_process.kill()

    logger.info("Shutdown complete")


def main():
    """Main entry point."""
    global flask_process

    logger.info("=" * 60)
    logger.info("System Monitoring Tool - Starting All Components")
    logger.info("=" * 60)
    logger.info("")

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Step 1: Check Redis
        if not check_redis_running():
            logger.error("")
            return 1

        logger.info("")

        # Step 2: Start Flask API server
        flask_process = start_flask_server()
        logger.info("")

        # Step 3: Start collectors (each runs in its own thread)
        # The upload queue worker auto-starts when first collector queues data
        collectors = start_collectors()

        if not collectors:
            logger.error("No collectors started")
            return 1

        logger.info("✓ All components initialized successfully")
        logger.info("")

        # Wait for shutdown signal
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
