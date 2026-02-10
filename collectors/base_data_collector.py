"""Base class for data collectors."""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
import uuid
import time
from pydantic import BaseModel, Field
from sharedUtils.logger.logger import get_logger
from sharedUtils.upload_queue.manager import get_upload_queue
from sharedUtils.config import get_config

logger = get_logger(__name__)

# Config is now loaded lazily via get_config()
# Kept for backwards compatibility
CONFIG = get_config()


class MetricEntry(BaseModel):
    """Single metric entry with name and value."""
    metric_name: str
    metric_value: float


class DataMessage(BaseModel):
    """Data message from collectors."""
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    device_id: str
    source: str
    metrics: List[MetricEntry]


class BaseDataCollector(ABC):
    """
    Abstract base class for data collectors.

    This class should not be instantiated directly. Instead, create subclasses
    that implement the collect_data() method for specific data sources.

    Attributes:
        source (str): The data source identifier (e.g., 'mobile', 'local', 'third_party')
        device_id (str): identifier for the data source
    """

    def __init__(self, source: str, device_id: str):        
        """
        Initialize the base data collector.

        Args:
            source: String identifier for the data source type
            device_id:  device identifier
        """
        logger.debug("Initialised BaseDataCollector")

        self.source = source
        self.device_id = device_id

        logger.debug("Collector init with source = %s, device_id = %s", source, device_id)

    @abstractmethod
    def collect_data(self) -> Dict[str, Any]:
        """
        Collect data from the specific source.

        This method must be implemented by subclasses to define how data
        is collected from their specific source.

        Returns:
            Dictionary containing the collected sensor/data readings

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        logger.debug("BaseDataCollector.collect_data() called — should be overridden.")
        pass

    def export_to_data_model(self, message: DataMessage) -> None:
        """Export message to upload queue."""
        queue = get_upload_queue()
        success = queue.put(message)

        if success:
            logger.info("Queued message %s with %d metrics", message.message_id, len(message.metrics))
        else:
            logger.error("Failed to queue message %s", message.message_id)

    def generate_message(self) -> DataMessage:
        """Generate message with collected data and send to queue."""
        data = self.collect_data()

        # Convert dict to metrics list
        metrics = [
            MetricEntry(metric_name=key, metric_value=float(value))
            for key, value in data.items()
            if isinstance(value, (int, float))
        ]

        message = DataMessage(
            device_id=self.device_id,
            source=self.source,
            metrics=metrics
        )

        self.export_to_data_model(message)
        return message

    def __repr__(self) -> str:
        """String representation of the collector."""
        return f"{self.__class__.__name__}(source='{self.source}', device_id={self.device_id})"
