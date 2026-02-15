"""
Redis Upload Queue Implementation

A production-grade queue implementation using Redis for persistent message storage.
This queue survives crashes/restarts and handles retries with exponential backoff.

Architecture:
- Redis List (metrics:pending) for main queue
- Redis Sorted Set (metrics:retry) for delayed retries with timestamps
- Background worker thread continuously processes messages
- Exponential backoff for failed uploads
- Persistent storage survives crashes
"""

import redis
import requests
import time
import threading
import json
from typing import TYPE_CHECKING, Optional, Dict, Any
from sharedUtils.upload_queue.base_queue import UploadQueue
from sharedUtils.config.models import UploadQueueConfig
from sharedUtils.logger.logger import get_logger

if TYPE_CHECKING:
    from collectors.base_data_collector import DataMessage

logger = get_logger(__name__)


class RedisUploadQueue(UploadQueue):
    """
    Redis-based upload queue with persistent storage and retry logic.

    This implementation provides:
    - Persistent message storage (survives crashes)
    - Background worker thread for continuous processing
    - Exponential backoff retry mechanism
    - Failed message tracking
    - Graceful shutdown

    Attributes:
        redis_client: Redis connection client
        session: HTTP session for database uploads
        worker_thread: Background thread processing the queue
        running: Flag to control worker thread lifecycle
    """

    # Redis key names
    PENDING_QUEUE = "metrics:pending"
    RETRY_QUEUE = "metrics:retry"
    FAILED_QUEUE = "metrics:failed"

    def __init__(self, config: UploadQueueConfig):
        """
        Initialize the Redis upload queue.

        Args:
            config: Typed configuration with validated settings:
                - redis_host: Redis server hostname
                - redis_port: Redis server port
                - redis_db: Redis database number
                - redis_password: Redis password (optional)
                - api_endpoint: URL to POST messages to
                - api_key: API key for authentication (optional)
                - timeout: Request timeout in seconds
                - max_retry_attempts: Max retries per message
                - backoff_base: Base delay for exponential backoff in seconds
                - backoff_multiplier: Multiplier for exponential backoff
                - worker_sleep: Worker sleep time when queue is empty in seconds
        """
        # Redis connection settings
        self.redis_host = config.redis_host
        self.redis_port = config.redis_port
        self.redis_db = config.redis_db
        self.redis_password = config.redis_password

        # API settings
        self.api_endpoint = config.api_endpoint
        self.api_key = config.api_key
        self.timeout = config.timeout

        # Retry policy settings
        self.max_retry_attempts = config.max_retry_attempts
        self.backoff_base = config.backoff_base
        self.backoff_multiplier = config.backoff_multiplier
        self.worker_sleep = config.worker_sleep

        # Runtime state
        self.redis_client: Optional[redis.Redis] = None
        self.session: Optional[requests.Session] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.running = False

        if not self.api_endpoint:
            logger.warning("No api_endpoint configured - messages will be queued but not uploaded")

        logger.debug("RedisUploadQueue initialized with endpoint: %s", self.api_endpoint)

    def start(self) -> None:
        """
        Start the queue by connecting to Redis and launching the worker thread.
        """
        # Connect to Redis
        self.redis_client = redis.Redis(
            host=self.redis_host,
            port=self.redis_port,
            db=self.redis_db,
            password=self.redis_password,
            decode_responses=True,  # Automatically decode bytes to strings
            socket_connect_timeout=5,
            socket_keepalive=True
        )

        # Test connection
        try:
            self.redis_client.ping()
            logger.info("Successfully connected to Redis at %s:%s", self.redis_host, self.redis_port)
        except redis.ConnectionError as e:
            logger.error("Failed to connect to Redis: %s", str(e))
            raise

        # Create HTTP session
        self.session = requests.Session()
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['X-API-Key'] = self.api_key
        self.session.headers.update(headers)

        # Start worker thread
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=False, name="RedisQueueWorker")
        self.worker_thread.start()

        logger.info("RedisUploadQueue started with worker thread")

    def stop(self) -> None:
        """
        Stop the queue gracefully by shutting down worker and closing connections.
        """
        logger.info("Stopping RedisUploadQueue...")

        # Signal worker to stop
        self.running = False

        # Wait for worker thread to finish (with timeout)
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)
            if self.worker_thread.is_alive():
                logger.warning("Worker thread did not stop gracefully")

        # Close HTTP session
        if self.session:
            self.session.close()
            self.session = None

        # Close Redis connection
        if self.redis_client:
            self.redis_client.close()
            self.redis_client = None

        logger.info("RedisUploadQueue stopped")

    def put(self, message: 'DataMessage') -> bool:
        """
        Add a message to the Redis queue (non-blocking).

        Args:
            message: DataMessage object to queue

        Returns:
            True if message was successfully queued, False otherwise
        """
        if not self.redis_client:
            logger.error("Queue not started - call start() before put()")
            return False

        try:
            # Serialize message to JSON using Pydantic
            json_data = message.model_dump_json()

            # Push to Redis list (LPUSH adds to left/head, RPOP removes from right/tail = FIFO)
            self.redis_client.lpush(self.PENDING_QUEUE, json_data)

            logger.debug("Queued message %s to Redis", message.message_id)
            return True

        except redis.RedisError as e:
            logger.error("Failed to queue message %s: %s", message.message_id, str(e))
            return False
        except Exception as e:
            logger.error("Unexpected error queuing message %s: %s", message.message_id, str(e))
            return False

    def _worker_loop(self) -> None:
        """
        Background worker thread that continuously processes the queue.

        This method runs in a separate thread and:
        1. Checks retry queue for messages ready to retry
        2. Pops messages from pending queue
        3. Attempts to upload with exponential backoff
        4. Handles failures by re-queuing or moving to failed queue
        """
        logger.info("Worker thread started")

        while self.running:
            try:
                # Process retry queue first (messages with scheduled retry time)
                self._process_retry_queue()

                # Process main pending queue
                processed = self._process_pending_queue()

                # Sleep if no work was done
                if not processed:
                    time.sleep(self.worker_sleep)

            except Exception as e:
                logger.error("Unexpected error in worker loop: %s", str(e))
                time.sleep(self.worker_sleep)

        logger.info("Worker thread stopped")

    def _process_retry_queue(self) -> None:
        """
        Process the retry queue by checking for messages ready to retry.

        Uses Redis Sorted Set with timestamp as score. Messages with
        score <= current time are ready to retry.
        """
        try:
            current_time = time.time()

            # Get all messages ready to retry (score <= current_time)
            ready_messages = self.redis_client.zrangebyscore(
                self.RETRY_QUEUE,
                min=0,
                max=current_time,
                start=0,
                num=10  # Process up to 10 at a time
            )

            for message_json in ready_messages:
                # Remove from retry queue
                self.redis_client.zrem(self.RETRY_QUEUE, message_json)

                # Add back to pending queue
                self.redis_client.lpush(self.PENDING_QUEUE, message_json)

                logger.debug("Moved message from retry queue back to pending")

        except redis.RedisError as e:
            logger.error("Error processing retry queue: %s", str(e))

    def _process_pending_queue(self) -> bool:
        """
        Process one message from the pending queue.

        Returns:
            True if a message was processed, False if queue was empty
        """
        try:
            # Pop one message from the right (FIFO: LPUSH + RPOP)
            # Use blocking pop with timeout to avoid busy-waiting
            result = self.redis_client.brpop(self.PENDING_QUEUE, timeout=1)

            if not result:
                return False  # Queue is empty

            # result is a tuple: (queue_name, message_json)
            _, message_json = result

            # Parse message
            message_dict = json.loads(message_json)
            message_id = message_dict.get('message_id', 'unknown')

            # Attempt upload with retries
            success = self._upload_with_retry(message_json, message_id)

            if not success:
                # All retries failed - move to failed queue
                self.redis_client.lpush(self.FAILED_QUEUE, message_json)
                logger.error("Message %s moved to failed queue after exhausting retries", message_id)

            return True

        except redis.RedisError as e:
            logger.error("Error processing pending queue: %s", str(e))
            return False
        except json.JSONDecodeError as e:
            logger.error("Failed to parse message JSON: %s", str(e))
            return True  # Consume the bad message
        except Exception as e:
            logger.error("Unexpected error processing message: %s", str(e))
            return False

    def _upload_with_retry(self, message_json: str, message_id: str) -> bool:
        """
        Attempt to upload a message with exponential backoff retries.

        Args:
            message_json: Serialized JSON message
            message_id: Message ID for logging

        Returns:
            True if upload succeeded, False if all retries failed
        """
        if not self.api_endpoint:
            logger.warning("No api_endpoint - cannot upload message %s", message_id)
            return False

        for attempt in range(1, self.max_retry_attempts + 1):
            try:
                logger.debug("Uploading message %s (attempt %d/%d)",
                           message_id, attempt, self.max_retry_attempts)

                response = self.session.post(
                    self.api_endpoint,
                    data=message_json,
                    timeout=self.timeout
                )

                # Accept any 2xx status code as success (200, 201, 204, etc.)
                if 200 <= response.status_code < 300:
                    logger.info("Successfully uploaded message %s (HTTP %d)", message_id, response.status_code)
                    return True
                else:
                    logger.warning("Upload failed for message %s: HTTP %d - %s",
                                 message_id, response.status_code, response.text[:200])

            except requests.exceptions.Timeout:
                logger.warning("Timeout uploading message %s (attempt %d/%d)",
                             message_id, attempt, self.max_retry_attempts)

            except requests.exceptions.ConnectionError as e:
                logger.warning("Connection error uploading message %s (attempt %d/%d): %s",
                             message_id, attempt, self.max_retry_attempts, str(e))

            except Exception as e:
                logger.error("Unexpected error uploading message %s: %s", message_id, str(e))
                break  # Don't retry on unexpected errors

            # Exponential backoff before next retry
            if attempt < self.max_retry_attempts:
                delay = self.backoff_base * (self.backoff_multiplier ** (attempt - 1))
                logger.debug("Waiting %s seconds before retry...", delay)

                # Sleep in small chunks to allow graceful shutdown
                sleep_remaining = delay
                while sleep_remaining > 0 and self.running:
                    time.sleep(min(0.5, sleep_remaining))
                    sleep_remaining -= 0.5

        # All retries failed
        logger.error("Failed to upload message %s after %d attempts",
                   message_id, self.max_retry_attempts)
        return False

    def get_stats(self) -> Dict[str, int]:
        """
        Get current queue statistics.

        Returns:
            Dictionary with queue sizes:
            - pending: Number of messages in pending queue
            - retry: Number of messages in retry queue
            - failed: Number of messages in failed queue
        """
        if not self.redis_client:
            return {"pending": 0, "retry": 0, "failed": 0}

        try:
            return {
                "pending": self.redis_client.llen(self.PENDING_QUEUE),
                "retry": self.redis_client.zcard(self.RETRY_QUEUE),
                "failed": self.redis_client.llen(self.FAILED_QUEUE)
            }
        except redis.RedisError as e:
            logger.error("Failed to get queue stats: %s", str(e))
            return {"pending": 0, "retry": 0, "failed": 0}
