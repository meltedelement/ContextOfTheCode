"""
Integration test for upload queue functionality.

Tests that collectors can instantiate and attempt to send data to the queue.
This will fail to send if the API endpoint is not configured, but should not crash.
"""

import sys
from collectors.LocalCollector import LocalDataCollector

def test_collector_with_queue():
    """Test that LocalCollector can use upload queue."""
    print("=" * 60)
    print("Testing LocalCollector with Upload Queue")
    print("=" * 60)

    try:
        # Create collector
        print("\n1. Creating LocalDataCollector...")
        collector = LocalDataCollector(device_id="test-device-001")
        print("   ✓ Collector created successfully")

        # Check if queue was initialized
        if collector.upload_queue:
            print("   ✓ Upload queue initialized")
            print(f"   - Type: {type(collector.upload_queue).__name__}")
            print(f"   - Endpoint: {collector.upload_queue.api_endpoint}")
        else:
            print("   ✗ No upload queue initialized")
            return False

        # Generate a message (this will attempt to send to queue)
        print("\n2. Generating and sending message...")
        message = collector.generate_message()
        print(f"   ✓ Message generated: {message.message_id}")
        print(f"   - Device ID: {message.device_id}")
        print(f"   - Source: {message.source}")
        print(f"   - Metrics count: {len(message.metrics)}")

        print("\n3. Message content:")
        for metric in message.metrics:
            print(f"   - {metric.metric_name}: {metric.metric_value}")

        print("\n" + "=" * 60)
        print("Integration test completed!")
        print("=" * 60)
        print("\nNote: If API endpoint is not reachable, you'll see connection")
        print("errors above, but the code should not crash.")
        print("\nNext steps:")
        print("1. Deploy the Flask app to PythonAnywhere")
        print("2. Update config.toml with your PythonAnywhere URL and API key")
        print("3. Run this test again to verify end-to-end connectivity")

        return True

    except Exception as e:
        print(f"\n✗ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_collector_with_queue()
    sys.exit(0 if success else 1)
