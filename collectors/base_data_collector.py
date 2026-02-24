"""Base class for data collectors."""

from abc import ABC, abstractmethod
from typing import List, Optional
import uuid
import time
import threading
from pydantic import BaseModel, Field
from sharedUtils.logger.logger import get_logger
from sharedUtils.upload_queue.manager import get_upload_queue
from sharedUtils.config import get_config

logger = get_logger(__name__)

# Config is now loaded lazily via get_config()
# Kept for backwards compatibility
CONFIG = get_config()


class MetricEntry(BaseModel):
    """
    A single metric reading with an enforced float value.

    Using a structured entry rather than a freeform dict ensures that
    all metric values are floats — no strings or booleans can sneak in.
    This also maps cleanly to a normalised database table later
    (one row per metric per reading).

    Attributes:
        metric_name: Identifier for the metric (e.g., 'ram_usage_percent')
        metric_value: The measured value, always a float
        unit: Short string describing the measurement unit (e.g. '%', 'MB', '°C')
    """
    metric_name: str
    metric_value: float
    unit: str = ""


class DataMessage(BaseModel):
    """Data message from collectors."""
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    device_id: str
    source: str
    metrics: List[MetricEntry]


class BaseDataCollector(ABC):
    """
    Abstract base class for data collectors with threading support.

    This class should not be instantiated directly. Instead, create subclasses
    that implement the collect_data() method for specific data sources.

    Collectors can run in two modes:
    1. Manual: Call generate_message() directly when needed
    2. Async: Call start() to run in background thread with automatic collection

    Attributes:
        source (str): The data source identifier (e.g., 'mobile', 'local', 'third_party')
        device_id (str): identifier for the data source
        collection_interval (int): How often to collect data in seconds (for async mode)
    """

    def __init__(self, source: str, device_id: str, collection_interval: int):
        """
        Initialize the base data collector.

        Args:
            source: String identifier for the data source type
            device_id: Device identifier
            collection_interval: Collection interval in seconds for async mode
        """
        logger.debug("Initialised BaseDataCollector")

        self.source = source
        self.device_id = device_id
        self.collection_interval = collection_interval

        # Threading state
        self._running = False
        self._thread: Optional[threading.Thread] = None

        logger.debug(
            "Collector init with source=%s, device_id=%s, interval=%d",
            source, device_id, collection_interval
        )

    @abstractmethod
    def collect_data(self) -> List[MetricEntry]:
        """
        Collect data from the specific source.

        This method must be implemented by subclasses to define how data
        is collected from their specific source. All values must be floats.

        Returns:
            List of MetricEntry objects with float-only values

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
        metrics = self.collect_data()

        message = DataMessage(
            device_id=self.device_id,
            source=self.source,
            metrics=metrics,
        )

        self.export_to_data_model(message)
        return message

    def __repr__(self) -> str:
        """String representation of the collector."""
        return f"{self.__class__.__name__}(source='{self.source}', device_id={self.device_id})"

    def _collection_loop(self) -> None:
        """
        Background thread loop for automatic data collection.

        Continuously collects data at the configured interval until stop() is called.
        """
        logger.info(
            "%s: Starting collection loop (interval=%ds)",
            self.__class__.__name__,
            self.collection_interval
        )

        while self._running:
            try:
                # Collect and queue data
                message = self.generate_message()
                logger.debug(
                    "%s: Collected %d metrics (message_id=%s)",
                    self.__class__.__name__,
                    len(message.metrics),
                    message.message_id[:8] + "..."
                )

            except Exception as e:
                logger.error(
                    "%s: Error during collection: %s",
                    self.__class__.__name__,
                    e,
                    exc_info=True
                )

            # Sleep with interrupt checking (check every second)
            for _ in range(self.collection_interval):
                if not self._running:
                    break
                time.sleep(1)

        logger.info("%s: Collection loop stopped", self.__class__.__name__)

    def start(self) -> None:
        """
        Start the collector in async mode (background thread).

        Spawns a background thread that continuously collects data
        at the configured interval.
        """
        if self._running:
            logger.warning("%s: Already running", self.__class__.__name__)
            return

        logger.info("%s: Starting async collection", self.__class__.__name__)
        self._running = True
        self._thread = threading.Thread(
            target=self._collection_loop,
            name=f"{self.__class__.__name__}-Thread",
            daemon=False
        )
        self._thread.start()

    def stop(self) -> None:
        """
        Stop the collector and wait for background thread to finish.

        Signals the collection loop to stop and waits for clean shutdown.
        """
        if not self._running:
            logger.debug("%s: Not running", self.__class__.__name__)
            return

        logger.info("%s: Stopping async collection...", self.__class__.__name__)
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.collection_interval + 5)
            if self._thread.is_alive():
                logger.warning("%s: Thread did not stop cleanly", self.__class__.__name__)
            else:
                logger.info("%s: Stopped successfully", self.__class__.__name__)

        self._thread = None

    def is_running(self) -> bool:
        """Check if collector is currently running in async mode."""
        return self._running
