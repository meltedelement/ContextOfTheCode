"""
System Data Collector Implementation

Collects real system metrics including CPU temperature and RAM usage.
All metric values are floats to keep the data model simple and consistent.
"""

from collectors.base_data_collector import BaseDataCollector, DataMessage, MetricEntry, CONFIG
from typing import List, Optional
import psutil
from sharedUtils.logger.logger import get_logger


# Constants
logger = get_logger(__name__)
BYTES_TO_MB = 1024 * 1024  # Conversion factor from bytes to megabytes
SENSOR_NAMES = ['coretemp', 'k10temp', 'zenpower']  # CPU temperature sensor names (Intel, AMD)
SOURCE_TYPE = "local"  # Source identifier for local system collector


class LocalDataCollector(BaseDataCollector):
    """Local system data collector that reads real system metrics."""

    def __init__(self, device_id: str):
        """
        Initialize local data collector.

        Args:
            device_id: Unique identifier for the device
        """
        logger.debug("Initialising LocalCollector")
        super().__init__(source=SOURCE_TYPE, device_id=device_id)

    def _get_cpu_temperature(self) -> Optional[float]:
        """
        Get CPU temperature in Celsius with psutil

        Returns:
            CPU temperature in Celsius, or None if unavailable
        """
        logger.debug("Collecting local system cpu temperature")
        precision = CONFIG.get("collectors", {}).get("metric_precision", 1)

        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if temps:
                # Try known sensor names first (Intel, AMD)
                for sensor_name in SENSOR_NAMES:
                    if sensor_name in temps and temps[sensor_name]:
                        return round(temps[sensor_name][0].current, precision)
                # Fallback to first available sensor
                first_sensor = next(iter(temps.values()))
                if first_sensor:
                    logger.info("CPU temperature: %s", first_sensor[0].current)
                    return round(first_sensor[0].current, precision)
        return None

    def collect_data(self) -> List[MetricEntry]:
        """
        Collect data from local system.

        Returns:
            List of MetricEntry objects with float values for:
            - ram_usage_percent: RAM usage percentage
            - ram_used_mb: RAM used in MB
            - cpu_usage_percent: CPU usage percentage
            - cpu_temp_celsius: CPU temperature in Celsius (if available)
        """
        # Get config values
        precision = CONFIG.get("collectors", {}).get("metric_precision", 1)
        cpu_interval = CONFIG.get("collectors", {}).get("cpu_sample_interval", 1.0)

        # Get memory information
        memory = psutil.virtual_memory()

        # Get CPU usage (sample over configured interval for accuracy)
        cpu_percent = psutil.cpu_percent(interval=cpu_interval)

        # Build metrics list — all values are floats
        metrics = [
            MetricEntry(metric_name="ram_usage_percent", metric_value=round(memory.percent, precision)),
            MetricEntry(metric_name="ram_used_mb", metric_value=round(memory.used / BYTES_TO_MB, precision)),
            MetricEntry(metric_name="cpu_usage_percent", metric_value=round(cpu_percent, precision)),
        ]

        logger.info("Collected local metrics: %s", [(m.metric_name, m.metric_value) for m in metrics])

        # Only include CPU temp if available
        cpu_temp = self._get_cpu_temperature()
        if cpu_temp is not None:
            metrics.append(MetricEntry(metric_name="cpu_temp_celsius", metric_value=cpu_temp))
            logger.info("Including CPU temperature: %s°C", cpu_temp)

        return metrics

    def export_to_data_model(self, message: DataMessage) -> None:
        """
        Export the message to the data model format.

        Serializes the Pydantic message to JSON and logs it to console
        if console_export is enabled in config. In the future, this will
        send the message to the upload queue.

        Args:
            message: DataMessage Pydantic model with metadata and collected metrics
        """
        # Get JSON formatting from config
        json_indent = CONFIG.get("logging", {}).get("json_indent", 2)

        # Use Pydantic's built-in JSON serialization
        json_output = message.model_dump_json(indent=json_indent)

        # Log to console if enabled in config (simulating upload queue)
        if CONFIG.get("logging", {}).get("console_export", True):
            logger.debug("Exporting data model to console: %s", message.device_id)
            print(f"\n[DATA MODEL EXPORT - {self.source.upper()}]")
            print(json_output)
            print(f"[END EXPORT]\n")


# Example usage
if __name__ == "__main__":
    # Create a local system data collector
    collector = LocalDataCollector(device_id="local-system-001")

    # Generate and print a message with system metrics
    print("System Data Collector Message:")
    message = collector.generate_message()

    # Pretty print the message using Pydantic serialization
    json_indent = CONFIG.get("logging", {}).get("json_indent", 2)
    print(message.model_dump_json(indent=json_indent))

    print("\nCollector Info:")
    print(f"  Device ID: {collector.device_id}")
    print(f"  Source: {collector.source}")
    print(f"  Metrics collected: {len(message.metrics)}")
    for m in message.metrics:
        print(f"    {m.metric_name}: {m.metric_value}")
