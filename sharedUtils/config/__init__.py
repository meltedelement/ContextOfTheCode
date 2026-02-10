"""Configuration module."""

from sharedUtils.config.loader import (
    get_config,
    get_collector_config,
    get_wikipedia_config,
    get_upload_queue_config,
    get_logging_config,
    get_data_model_config,
)

__all__ = [
    'get_config',
    'get_collector_config',
    'get_wikipedia_config',
    'get_upload_queue_config',
    'get_logging_config',
    'get_data_model_config',
]
