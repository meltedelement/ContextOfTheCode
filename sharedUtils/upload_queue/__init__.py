"""
Upload Queue Module

Provides queue interfaces for uploading data from collectors to remote endpoints.
Supports multiple queue implementations that can be swapped without changing collector code.
"""

from sharedUtils.upload_queue.base_queue import UploadQueue
from sharedUtils.upload_queue.redis_queue import RedisUploadQueue

__all__ = ['UploadQueue', 'RedisUploadQueue']
