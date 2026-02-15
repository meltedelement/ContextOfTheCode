"""Local system metrics collector (CPU, RAM, temperature)."""

from collectors.base_data_collector import BaseDataCollector, DataMessage
from typing import Dict, Any, Optional
import psutil
from sharedUtils.logger.logger import get_logger
from sharedUtils.config import get_collector_config


# Constants
logger = get_logger(__name__)
BYTES_TO_MB = 1024 * 1024  # Conversion factor from bytes to megabytes
SENSOR_NAMES = ['coretemp', 'k10temp', 'zenpower']  # CPU temperature sensor names (Intel, AMD)
SOURCE_TYPE = "local"  # Source identifier for local system collector


class LocalDataCollector(BaseDataCollector):
    """Local system data collector that reads real system metrics."""

    def __init__(self, device_id: str):
        """Initialize local data collector."""
        super().__init__(source=SOURCE_TYPE, device_id=device_id)

    def _get_cpu_temperature(self) -> Optional[float]:
        """Get CPU temperature in Celsius, or None if unavailable."""
        precision = get_collector_config().metric_precision

        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if temps:
                for sensor_name in SENSOR_NAMES:
                    if sensor_name in temps and temps[sensor_name]:
                        return round(temps[sensor_name][0].current, precision)
                first_sensor = next(iter(temps.values()))
                if first_sensor:
                    return round(first_sensor[0].current, precision)
        return None

    def collect_data(self) -> Dict[str, Any]:
        """Collect system metrics (CPU, RAM, temperature)."""
        config = get_collector_config()
        precision = config.metric_precision
        cpu_interval = config.cpu_sample_interval

        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=cpu_interval)
        cpu_temp = self._get_cpu_temperature()

        data = {
            "ram_usage_percent": round(memory.percent, precision),
            "ram_used_mb": round(memory.used / BYTES_TO_MB, precision),
            "cpu_usage_percent": round(cpu_percent, precision),
        }

        if cpu_temp is not None:
            data["cpu_temp_celsius"] = cpu_temp

        return data


if __name__ == "__main__":
    collector = LocalDataCollector(device_id="local-system-001")
    message = collector.generate_message()

    print(f"Local Collector - {collector.device_id}")
    print(f"Metrics collected: {len(message.metrics)}")
    for metric in message.metrics:
        print(f"  {metric.metric_name}: {metric.metric_value}")
