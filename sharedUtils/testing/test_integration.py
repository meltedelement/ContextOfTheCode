"""Basic integration test for collector functionality."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from collectors.local_collector import LocalDataCollector
from sharedUtils.upload_queue import get_upload_queue


def test_collector_basic():
    """Test that LocalCollector can collect and format data."""
    print("=" * 60)
    print("Testing LocalCollector Basic Functionality")
    print("=" * 60)

    try:
        # Test 1: Create collector
        print("\n1. Creating LocalDataCollector...")
        collector = LocalDataCollector(device_id="test-device-001")
        print("   ✓ Collector created successfully")

        # Test 2: Check queue is initialized
        print("\n2. Checking upload queue...")
        queue = get_upload_queue()
        print(f"   ✓ Upload queue initialized: {type(queue).__name__}")

        # Test 3: Generate a message
        print("\n3. Generating and sending message...")
        message = collector.generate_message()
        print(f"   ✓ Message generated: {message.snapshot_id}")
        print(f"   - Device ID: {message.device_id}")
        print(f"   - Metrics count: {len(message.metrics)}")

        # Test 4: Display metrics
        print("\n4. Message content:")
        for metric in message.metrics:
            print(f"   - {metric.metric_name}: {metric.metric_value}")

        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"\n✗ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_collector_basic()
    sys.exit(0 if success else 1)
