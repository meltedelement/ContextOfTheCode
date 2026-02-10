"""
System Data Collector Implementation

Collects real system metrics including CPU temperature and RAM usage.
"""

from collectors.base_data_collector import BaseDataCollector, DataMessage, CONFIG
from typing import Dict, Any, Optional
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
                    logger.info("CPU temperature: %s", (first_sensor[0].current, precision))
                    return round(first_sensor[0].current, precision)
        return None

    def collect_data(self) -> Dict[str, Any]:
        """
        Collect data from local system.

        Returns:
            Dictionary with system metrics including:
            - cpu_temp_celsius: CPU temperature in Celsius (if available)
            - ram_usage_percent: RAM usage percentage
            - ram_used_mb: RAM used in MB
            - cpu_usage_percent: CPU usage percentage
        """
        # Get config values
        precision = CONFIG.get("collectors", {}).get("metric_precision", 1)
        cpu_interval = CONFIG.get("collectors", {}).get("cpu_sample_interval", 1.0)

        # Get memory information
        memory = psutil.virtual_memory()

        # Get CPU usage (sample over configured interval for accuracy)
        cpu_percent = psutil.cpu_percent(interval=cpu_interval)

        # Get CPU temperature
        cpu_temp = self._get_cpu_temperature()

        data = {
            "ram_usage_percent": round(memory.percent, precision),
            "ram_used_mb": round(memory.used / BYTES_TO_MB, precision),
            "cpu_usage_percent": round(cpu_percent, precision),
        }

        logger.info("Collected local metrics: %s", data)

        # Only include CPU temp if available
        if cpu_temp is not None:
            data["cpu_temp_celsius"] = cpu_temp
            logger.info("Including CPU temperature: %s°C", cpu_temp)

        return data

    # Removed export_to_data_model() - now uses default implementation from BaseDataCollector
    # which sends messages to the upload queue


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
    print(f"\nConfiguration:")
    print(f"  Schema path: {CONFIG.get('data_model', {}).get('schema_path')}")
    print(f"  Metric precision: {CONFIG.get('collectors', {}).get('metric_precision')}")
    print(f"  CPU sample interval: {CONFIG.get('collectors', {}).get('cpu_sample_interval')}s")
