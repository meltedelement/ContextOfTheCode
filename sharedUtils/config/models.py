"""Type-safe Pydantic models for configuration."""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class LoggingConfig(BaseModel):
    """Configuration for logging settings."""
    level: str = Field(default="INFO", description="Logging level")
    file: str = Field(description="Log file path")
    format: str = Field(description="Log message format")
    console_export: bool = Field(default=True, description="Enable console output")
    json_indent: int = Field(default=2, description="JSON output indentation")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v.upper()


class DataModelConfig(BaseModel):
    """Configuration for data model schema."""
    schema_path: str = Field(description="Path to JSON schema file")


class CollectorsConfig(BaseModel):
    """Configuration for data collectors (shared settings)."""
    default_interval: int = Field(default=60, description="Collection interval in seconds")
    default_collection_interval: int = Field(default=60, description="Default collection interval fallback")
    enabled_collectors: List[str] = Field(default_factory=list, description="Enabled collector types")
    cpu_sample_interval: float = Field(default=1.0, description="CPU sampling interval in seconds")
    metric_precision: int = Field(default=1, description="Decimal precision for metrics")

    @field_validator("default_interval", "default_collection_interval")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError("interval must be at least 1 second")
        return v

    @field_validator("metric_precision")
    @classmethod
    def validate_precision(cls, v: int) -> int:
        if v < 0:
            raise ValueError("metric_precision cannot be negative")
        return v


class LocalCollectorConfig(BaseModel):
    """Configuration for local system collector."""
    collection_interval: int = Field(default=10, description="Collection interval in seconds")

    @field_validator("collection_interval")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError("collection_interval must be at least 1 second")
        return v


class WikipediaCollectorConfig(BaseModel):
    """Configuration for Wikipedia collector."""
    collection_interval: int = Field(default=60, description="Collection interval in seconds")
    collection_window: int = Field(default=60, description="Time window in seconds")
    user_agent: str = Field(description="User-Agent for API requests")

    @field_validator("collection_interval", "collection_window")
    @classmethod
    def validate_intervals(cls, v: int) -> int:
        if v < 1:
            raise ValueError("interval must be at least 1 second")
        return v


class UploadQueueConfig(BaseModel):
    """Configuration for upload queue system."""
    implementation: str = Field(default="redis", description="Queue implementation type")
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_db: int = Field(default=0, description="Redis database number")
    redis_password: Optional[str] = Field(default=None, description="Redis password")
    api_endpoint: str = Field(description="Database API endpoint")
    api_key: Optional[str] = Field(default=None, description="API key for authentication")
    max_retry_attempts: int = Field(default=5, description="Maximum retry attempts")
    backoff_base: int = Field(default=1, description="Base delay in seconds")
    backoff_multiplier: int = Field(default=2, description="Exponential backoff multiplier")
    timeout: int = Field(default=10, description="HTTP request timeout")
    worker_sleep: int = Field(default=1, description="Worker sleep time when queue is empty")
    registration_base_url: str = Field(default="http://100.67.157.90:5000", description="Base URL for /aggregators and /devices registration")

    @field_validator("redis_port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("redis_port must be between 1 and 65535")
        return v

    @field_validator("max_retry_attempts")
    @classmethod
    def validate_retries(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_retry_attempts cannot be negative")
        return v


class AggregatorConfig(BaseModel):
    """Configuration for aggregator identity."""
    name: str = Field(description="Human-readable name for this aggregator")


class AppConfig(BaseModel):
    """Root configuration model containing all sections."""
    logging: LoggingConfig
    data_model: DataModelConfig
    collectors: CollectorsConfig
    local_collector: LocalCollectorConfig
    wikipedia_collector: WikipediaCollectorConfig
    upload_queue: UploadQueueConfig
    aggregator: AggregatorConfig
