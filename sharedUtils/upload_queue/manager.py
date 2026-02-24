"""Queue manager for singleton upload queue instance."""

from typing import Optional
import threading
from ContextOfTheCode.sharedUtils.upload_queue.base_queue import UploadQueue
from ContextOfTheCode.sharedUtils.upload_queue.redis_queue import RedisUploadQueue
from ContextOfTheCode.sharedUtils.config import get_upload_queue_config
from ContextOfTheCode.sharedUtils.logger.logger import get_logger

logger = get_logger(__name__)

# Global queue instance (singleton)
_lock = threading.Lock()
_QUEUE_INSTANCE: Optional[UploadQueue] = None


def get_upload_queue() -> UploadQueue:
    """
    Get or create the global upload queue instance (singleton).

    Thread-safe via double-checked locking — only one instance will ever
    be created and started even under concurrent access.

    Returns:
        UploadQueue instance configured from config.toml
    """
    global _QUEUE_INSTANCE

    if _QUEUE_INSTANCE is None:
        with _lock:
            if _QUEUE_INSTANCE is None:
                queue_config = get_upload_queue_config()
                logger.info("Initializing RedisUploadQueue")
                _QUEUE_INSTANCE = RedisUploadQueue(queue_config)
                _QUEUE_INSTANCE.start()
                logger.info("Upload queue started successfully")

    return _QUEUE_INSTANCE


def stop_upload_queue() -> None:
    """Stop the global upload queue instance if it exists."""
    global _QUEUE_INSTANCE

    with _lock:
        if _QUEUE_INSTANCE is not None:
            logger.info("Stopping upload queue")
            _QUEUE_INSTANCE.stop()
            _QUEUE_INSTANCE = None
            logger.info("Upload queue stopped")
