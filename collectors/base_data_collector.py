"""
Base Data Collector Module

This module provides an abstract base class for data collectors that inherit
from it to target specific data sources (mobile, local, third_party, etc.).
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
import uuid
import time
import tomllib
from pathlib import Path
from pydantic import BaseModel, Field
from sharedUtils.logger.logger import get_logger

logger = get_logger(__name__)


def load_config(config_path: str = None) -> Dict[str, Any]:
    """
    Load configuration from TOML file.

    Args:
        config_path: Path to the configuration file (defaults to sharedUtils/config/config.toml)

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
    """
    if config_path is None:
        # Default to sharedUtils/config/config.toml relative to project root
        project_root = Path(__file__).parent.parent
        config_path = project_root / "sharedUtils" / "config" / "config.toml"
    else:
        config_path = Path(config_path)

    logger.debug("Loading config from: %s", config_path)

    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        raise FileNotFoundError("Configuration file not found: %s" % config_path)

    with open(config_path, "rb") as f:
        logger.debug("Configuration loaded successfully")
        return tomllib.load(f)


# Load configuration at module level
CONFIG = load_config()


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
    """
    metric_name: str
    metric_value: float


class DataMessage(BaseModel):
    """
    Pydantic model for data collector messages.

    This model ensures type validation and provides automatic serialization
    for messages sent to the upload queue. All metric values are enforced
    as floats via MetricEntry to avoid mixed-type complexity.

    Attributes:
        message_id: Unique identifier for the message (auto-generated UUID)
        timestamp: Unix timestamp when the message was created (auto-generated)
        device_id: Identifier for the data source device
        source: Data source type (e.g., 'mobile', 'local', 'third_party')
        metrics: List of MetricEntry objects with float-only values
    """
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

    @abstractmethod
    def export_to_data_model(self, message: DataMessage) -> None:
        """
        Export the generated message to the data model format.

        This method must be implemented by subclasses to define how they
        serialize and export their data. The message is a validated Pydantic
        model ready for the upload queue.

        Args:
            message: DataMessage Pydantic model with metadata and collected data

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        pass

    def generate_message(self) -> DataMessage:
        """
        Generate a complete message with collected data.

        This method calls collect_data() and wraps the result in the
        standard message format with metadata. It automatically exports
        the message to the data model via export_to_data_model().

        Returns:
            DataMessage Pydantic model with validated data following the schema
        """
        metrics = self.collect_data()
        logger.debug("Collected %d metrics", len(metrics))

        # Create validated Pydantic message — MetricEntry enforces float values
        message = DataMessage(
            device_id=self.device_id,
            source=self.source,
            metrics=metrics
        )
        logger.debug("Generated message: %s", message.message_id)

        # Automatically export to data model
        self.export_to_data_model(message)
        logger.debug("Message exported to data model")

        return message

    def validate_metrics(self, metrics: List[MetricEntry]) -> bool:
        """
        Validate collected metrics.

        Can be overridden by subclasses for custom validation logic.

        Args:
            metrics: The list of MetricEntry objects to validate

        Returns:
            True if metrics are valid, False otherwise
        """
        return isinstance(metrics, list) and len(metrics) > 0

    def __repr__(self) -> str:
        """String representation of the collector."""
        return f"{self.__class__.__name__}(source='{self.source}', device_id={self.device_id})"
