"""
Integration Test for Upload Queue System

Tests the complete data flow from collectors to the upload queue.
This test demonstrates:
1. Collectors sending data to the queue
2. Queue persisting data to Redis
3. Worker thread attempting to upload to database API
4. Retry logic when database is unavailable
5. Queue statistics and monitoring

Run this test with Redis running on localhost:6379
"""

import time
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from collectors.LocalCollector import LocalDataCollector
from collectors.WikipediaCollector import WikipediaCollector
from collectors.base_data_collector import get_upload_queue
from sharedUtils.logger.logger import get_logger

logger = get_logger(__name__)


def test_collectors_to_queue():
    """
    Test that collectors can send data to the upload queue.

    This test:
    1. Creates both LocalCollector and WikipediaCollector instances
    2. Generates messages from each collector
    3. Verifies messages are queued successfully
    4. Shows queue statistics
    """
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Collectors -> Upload Queue")
    print("=" * 70)

    # Get the global queue instance (initialized automatically)
    queue = get_upload_queue()
    print(f"\nQueue type: {queue.__class__.__name__}")

    # Test 1: LocalCollector
    print("\n--- Test 1: LocalCollector ---")
    local_collector = LocalDataCollector(device_id="test-local-001")
    print(f"Created {local_collector}")

    print("Generating message from LocalCollector...")
    local_message = local_collector.generate_message()
    print(f"  Message ID: {local_message.message_id}")
    print(f"  Device ID: {local_message.device_id}")
    print(f"  Source: {local_message.source}")
    print(f"  Data keys: {list(local_message.data.keys())}")

    # Test 2: WikipediaCollector
    print("\n--- Test 2: WikipediaCollector ---")
    wiki_collector = WikipediaCollector(
        device_id="test-wikipedia-001",
        wikipedia_language="en"
    )
    print(f"Created {wiki_collector}")

    print("Generating message from WikipediaCollector...")
    wiki_message = wiki_collector.generate_message()
    print(f"  Message ID: {wiki_message.message_id}")
    print(f"  Device ID: {wiki_message.device_id}")
    print(f"  Source: {wiki_message.source}")
    print(f"  Data keys: {list(wiki_message.data.keys())}")

    # Test 3: Queue Statistics
    print("\n--- Test 3: Queue Statistics ---")

    # Wait a moment for messages to be queued
    time.sleep(0.5)

    if hasattr(queue, 'get_stats'):
        stats = queue.get_stats()
        print(f"Queue statistics:")
        print(f"  Pending messages: {stats.get('pending', 'N/A')}")
        print(f"  Retry messages: {stats.get('retry', 'N/A')}")
        print(f"  Failed messages: {stats.get('failed', 'N/A')}")
    else:
        print("Queue statistics not available for this queue type")

    # Test 4: Multiple messages
    print("\n--- Test 4: Sending Multiple Messages ---")
    print("Sending 5 messages from each collector...")

    for i in range(5):
        local_collector.generate_message()
        wiki_collector.generate_message()
        print(f"  Sent batch {i+1}/5")
        time.sleep(0.2)

    # Wait for messages to be queued
    time.sleep(1)

    if hasattr(queue, 'get_stats'):
        stats = queue.get_stats()
        print(f"\nUpdated queue statistics:")
        print(f"  Pending messages: {stats.get('pending', 'N/A')}")
        print(f"  Retry messages: {stats.get('retry', 'N/A')}")
        print(f"  Failed messages: {stats.get('failed', 'N/A')}")

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
    print("\nNotes:")
    print("- Messages are now in the upload queue")
    print("- Worker thread is attempting to upload to API endpoint")
    print("- If API endpoint is not available, messages will retry")
    print("- Check Redis with: redis-cli LLEN metrics:pending")
    print("- Monitor logs for upload attempts and retries")
    print("\nPress Ctrl+C to stop and cleanup...")

    # Keep running to allow worker thread to process messages
    try:
        while True:
            time.sleep(5)
            if hasattr(queue, 'get_stats'):
                stats = queue.get_stats()
                print(f"\n[{time.strftime('%H:%M:%S')}] Queue: "
                      f"pending={stats.get('pending', 0)}, "
                      f"retry={stats.get('retry', 0)}, "
                      f"failed={stats.get('failed', 0)}")
    except KeyboardInterrupt:
        print("\n\nStopping test...")
        queue.stop()
        print("Queue stopped. Goodbye!")


def test_queue_persistence():
    """
    Test that the queue survives process restarts.

    Run this test twice:
    1. First run: sends messages and exits without processing
    2. Second run: verifies messages are still in queue
    """
    print("\n" + "=" * 70)
    print("PERSISTENCE TEST: Queue Crash Recovery")
    print("=" * 70)

    queue = get_upload_queue()

    if hasattr(queue, 'get_stats'):
        stats = queue.get_stats()
        pending = stats.get('pending', 0)

        print(f"\nMessages in queue at startup: {pending}")

        if pending > 0:
            print("\n✓ PERSISTENCE VERIFIED!")
            print(f"  Found {pending} messages that survived restart")
        else:
            print("\nNo messages in queue. Sending test messages...")
            print("These will persist in Redis even after this script exits.")

            collector = LocalDataCollector(device_id="persistence-test")
            for i in range(3):
                collector.generate_message()
                print(f"  Sent message {i+1}/3")

            time.sleep(1)
            stats = queue.get_stats()
            print(f"\nMessages now in queue: {stats.get('pending', 0)}")
            print("\nNow kill this script (Ctrl+C) and run it again.")
            print("You should see the messages still in the queue.")

    queue.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Upload Queue Integration Tests")
    parser.add_argument(
        "--test",
        choices=["integration", "persistence"],
        default="integration",
        help="Which test to run (default: integration)"
    )

    args = parser.parse_args()

    if args.test == "integration":
        test_collectors_to_queue()
    elif args.test == "persistence":
        test_queue_persistence()
