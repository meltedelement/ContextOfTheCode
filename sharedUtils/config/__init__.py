"""Configuration module."""

from ContextOfTheCode.sharedUtils.config.loader import (
    get_config,
    get_typed_config,
    get_collector_config,
    get_local_collector_config,
    get_wikipedia_collector_config,
    get_upload_queue_config,
    get_logging_config,
    get_data_model_config,
)
from ContextOfTheCode.sharedUtils.config.models import (
    AppConfig,
    CollectorsConfig,
    LocalCollectorConfig,
    WikipediaCollectorConfig,
    UploadQueueConfig,
    LoggingConfig,
    DataModelConfig,
)

__all__ = [
    'get_config',
    'get_typed_config',
    'get_collector_config',
    'get_local_collector_config',
    'get_wikipedia_collector_config',
    'get_upload_queue_config',
    'get_logging_config',
    'get_data_model_config',
    'AppConfig',
    'CollectorsConfig',
    'LocalCollectorConfig',
    'WikipediaCollectorConfig',
    'UploadQueueConfig',
    'LoggingConfig',
    'DataModelConfig',
]
