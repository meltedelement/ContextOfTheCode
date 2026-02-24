"""Upload queue for collector data."""

from ContextOfTheCode.sharedUtils.upload_queue.base_queue import UploadQueue
from ContextOfTheCode.sharedUtils.upload_queue.redis_queue import RedisUploadQueue
from ContextOfTheCode.sharedUtils.upload_queue.manager import get_upload_queue, stop_upload_queue

__all__ = ['UploadQueue', 'RedisUploadQueue', 'get_upload_queue', 'stop_upload_queue']
