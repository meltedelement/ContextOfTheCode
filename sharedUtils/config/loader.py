"""Configuration loader with lazy singleton pattern."""

from typing import Dict, Any, Optional
import tomllib
from pathlib import Path
from sharedUtils.logger.logger import get_logger
from sharedUtils.config.models import (
    AppConfig,
    CollectorsConfig,
    LocalCollectorConfig,
    WikipediaCollectorConfig,
    UploadQueueConfig,
    LoggingConfig,
    DataModelConfig,
)

logger = get_logger(__name__)

# Global config cache (singleton)
_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_TYPED_CONFIG_CACHE: Optional[AppConfig] = None


def get_config() -> Dict[str, Any]:
    """
    Get configuration dictionary (lazy-loaded singleton).

    Loads config from sharedUtils/config/config.toml on first access
    and caches it for subsequent calls.

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
    """
    global _CONFIG_CACHE

    if _CONFIG_CACHE is None:
        config_path = Path(__file__).parent / "config.toml"

        logger.debug("Loading config from: %s", config_path)

        if not config_path.exists():
            logger.error("Config file not found: %s", config_path)
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "rb") as f:
            _CONFIG_CACHE = tomllib.load(f)
            logger.debug("Configuration loaded successfully")

    return _CONFIG_CACHE


def get_typed_config() -> AppConfig:
    """
    Get typed configuration (lazy-loaded singleton with validation).

    Loads config from sharedUtils/config/config.toml on first access,
    validates it using Pydantic models, and caches it for subsequent calls.

    Returns:
        Validated AppConfig instance with type-safe access

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValidationError: If config doesn't match expected schema
    """
    global _TYPED_CONFIG_CACHE

    if _TYPED_CONFIG_CACHE is None:
        config_dict = get_config()  # Reuse dict loading logic
        _TYPED_CONFIG_CACHE = AppConfig(**config_dict)
        logger.debug("Configuration validated with Pydantic models")

    return _TYPED_CONFIG_CACHE


def get_collector_config() -> CollectorsConfig:
    """Get typed collector configuration section (shared settings)."""
    return get_typed_config().collectors


def get_local_collector_config() -> LocalCollectorConfig:
    """Get typed local collector configuration section."""
    return get_typed_config().local_collector


def get_wikipedia_collector_config() -> WikipediaCollectorConfig:
    """Get typed Wikipedia collector configuration section."""
    return get_typed_config().wikipedia_collector


def get_upload_queue_config() -> UploadQueueConfig:
    """Get typed upload queue configuration section."""
    return get_typed_config().upload_queue


def get_logging_config() -> LoggingConfig:
    """Get typed logging configuration section."""
    return get_typed_config().logging


def get_data_model_config() -> DataModelConfig:
    """Get typed data model configuration section."""
    return get_typed_config().data_model
