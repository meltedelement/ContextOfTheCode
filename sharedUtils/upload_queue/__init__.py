"""Upload queue for collector data."""

from sharedUtils.upload_queue.redis_queue import RedisUploadQueue
from sharedUtils.upload_queue.manager import get_upload_queue, stop_upload_queue

__all__ = ['RedisUploadQueue', 'get_upload_queue', 'stop_upload_queue']
