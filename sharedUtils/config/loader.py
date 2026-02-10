"""Configuration loader with lazy singleton pattern."""

from typing import Dict, Any, Optional
import tomllib
from pathlib import Path
from sharedUtils.logger.logger import get_logger

logger = get_logger(__name__)

# Global config cache (singleton)
_CONFIG_CACHE: Optional[Dict[str, Any]] = None


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


def get_collector_config() -> dict:
    """Get collector configuration section."""
    return get_config().get("collectors", {})


def get_wikipedia_config() -> dict:
    """Get Wikipedia configuration section."""
    return get_config().get("wikipedia", {})


def get_upload_queue_config() -> dict:
    """Get upload queue configuration section."""
    return get_config().get("upload_queue", {})


def get_logging_config() -> dict:
    """Get logging configuration section."""
    return get_config().get("logging", {})


def get_data_model_config() -> dict:
    """Get data model configuration section."""
    return get_config().get("data_model", {})
