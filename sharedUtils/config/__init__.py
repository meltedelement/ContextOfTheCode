"""Configuration module."""

from sharedUtils.config.loader import (
    get_config,
    get_typed_config,
    get_collector_config,
    get_wikipedia_config,
    get_upload_queue_config,
    get_logging_config,
    get_data_model_config,
)
from sharedUtils.config.models import (
    AppConfig,
    CollectorsConfig,
    WikipediaConfig,
    UploadQueueConfig,
    LoggingConfig,
    DataModelConfig,
)

__all__ = [
    'get_config',
    'get_typed_config',
    'get_collector_config',
    'get_wikipedia_config',
    'get_upload_queue_config',
    'get_logging_config',
    'get_data_model_config',
    'AppConfig',
    'CollectorsConfig',
    'WikipediaConfig',
    'UploadQueueConfig',
    'LoggingConfig',
    'DataModelConfig',
]
