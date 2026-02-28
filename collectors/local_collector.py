"""Local system metrics collector (CPU, RAM, temperature)."""

from collectors.base_data_collector import BaseDataCollector, MetricEntry
from typing import List, Optional
import psutil
from sharedUtils.logger.logger import get_logger
from sharedUtils.config import get_collector_config, get_local_collector_config


# Constants
logger = get_logger(__name__)
BYTES_TO_MB = 1024 * 1024  # Conversion factor from bytes to megabytes
SENSOR_NAMES = ['coretemp', 'k10temp', 'zenpower']  # CPU temperature sensor names (Intel, AMD)


class LocalDataCollector(BaseDataCollector):
    """Local system data collector that reads real system metrics."""

    SOURCE = "local"
    DEVICE_NAME = "local-system"

    def __init__(self, device_id: str):
        """Initialize local data collector."""
        # Load collector-specific config
        config = get_local_collector_config()

        # Initialize base with collection interval
        super().__init__(
            source=self.SOURCE,
            device_id=device_id,
            collection_interval=config.collection_interval
        )

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

    def collect_data(self) -> List[MetricEntry]:
        """Collect system metrics (CPU, RAM, temperature)."""
        config = get_collector_config()
        precision = config.metric_precision
        cpu_interval = config.cpu_sample_interval

        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=cpu_interval)
        cpu_temp = self._get_cpu_temperature()

        metrics = [
            MetricEntry(metric_name="ram_usage_percent", metric_value=round(memory.percent, precision),          unit="%"),
            MetricEntry(metric_name="ram_used_mb",        metric_value=round(memory.used / BYTES_TO_MB, precision), unit="MB"),
            MetricEntry(metric_name="cpu_usage_percent",  metric_value=round(cpu_percent, precision),            unit="%"),
        ]

        if cpu_temp is not None:
            metrics.append(MetricEntry(metric_name="cpu_temp_celsius", metric_value=cpu_temp, unit="°C"))

        return metrics


if __name__ == "__main__":
    collector = LocalDataCollector(device_id="local-system-001")
    message = collector.generate_message()

    print(f"Local Collector - {collector.device_id}")
    print(f"Metrics collected: {len(message.metrics)}")
    for metric in message.metrics:
        print(f"  {metric.metric_name}: {metric.metric_value} {metric.unit}")
