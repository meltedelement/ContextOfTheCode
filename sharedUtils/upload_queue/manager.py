"""Queue manager for singleton upload queue instance."""

from typing import Optional, Dict, Any
import tomllib
from pathlib import Path
from sharedUtils.upload_queue.base_queue import UploadQueue
from sharedUtils.upload_queue.redis_queue import RedisUploadQueue
from sharedUtils.logger.logger import get_logger

logger = get_logger(__name__)

# Global queue instance (singleton)
_QUEUE_INSTANCE: Optional[UploadQueue] = None


def _load_config() -> Dict[str, Any]:
    """Load configuration from TOML file."""
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "sharedUtils" / "config" / "config.toml"

    with open(config_path, "rb") as f:
        return tomllib.load(f)


def get_upload_queue() -> UploadQueue:
    """
    Get or create the global upload queue instance (singleton).

    Returns:
        UploadQueue instance configured from config.toml
    """
    global _QUEUE_INSTANCE

    if _QUEUE_INSTANCE is None:
        config = _load_config()
        queue_config = config.get("upload_queue", {})

        logger.info("Initializing RedisUploadQueue")
        _QUEUE_INSTANCE = RedisUploadQueue(queue_config)
        _QUEUE_INSTANCE.start()
        logger.info("Upload queue started successfully")

    return _QUEUE_INSTANCE


def stop_upload_queue() -> None:
    """Stop the global upload queue instance if it exists."""
    global _QUEUE_INSTANCE

    if _QUEUE_INSTANCE is not None:
        logger.info("Stopping upload queue")
        _QUEUE_INSTANCE.stop()
        _QUEUE_INSTANCE = None
        logger.info("Upload queue stopped")
