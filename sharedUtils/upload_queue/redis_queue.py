"""
Redis Upload Queue Implementation

A production-grade queue implementation using Redis for persistent message storage.
This queue survives crashes/restarts and handles retries with exponential backoff.

Architecture:
- Redis List (metrics:pending): main FIFO queue of message envelopes
- Redis Sorted Set (metrics:retry): deferred retries, scored by future Unix timestamp
- Redis List (metrics:failed): envelopes that exhausted all retry attempts
- Background worker thread continuously processes messages without blocking

Message Envelope:
    Messages are stored as JSON envelopes wrapping the raw DataMessage payload:
    {
        "retry_count": int,         # number of failed attempts so far
        "first_queued_at": float,   # Unix timestamp when first enqueued
        "last_error": str | None,   # error string from the most recent failure
        "payload": str              # DataMessage serialised as a JSON string
    }
    The envelope is internal to this module — callers interact only with DataMessage.

Retry Flow:
    1. put() wraps DataMessage in envelope (retry_count=0) → metrics:pending
    2. Worker pops envelope, calls _attempt_upload() once (no blocking sleep)
    3. Success → done
    4. Failure, retries remaining → zadd to metrics:retry with score=now+backoff_delay
    5. Failure, retries exhausted → lpush to metrics:failed
    6. Worker polls metrics:retry each loop; expired entries move back to metrics:pending
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

        Wraps the DataMessage in an envelope that carries retry metadata.
        The envelope is internal to the queue — callers interact only with DataMessage.

        Args:
            message: DataMessage object to queue

        Returns:
            True if message was successfully queued, False otherwise
        """
        if not self.redis_client:
            logger.error("Queue not started - call start() before put()")
            return False

        try:
            # Wrap the message in an envelope that tracks retry state
            envelope = {
                "retry_count": 0,
                "first_queued_at": time.time(),
                "last_error": None,
                "payload": message.model_dump_json()
            }
            envelope_json = json.dumps(envelope)

            # Push to Redis list (LPUSH adds to left/head, BRPOP removes from right/tail = FIFO)
            self.redis_client.lpush(self.PENDING_QUEUE, envelope_json)

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

        Uses Redis Sorted Set with a future Unix timestamp as score. Messages
        whose score <= current time have passed their backoff delay and are moved
        back to the pending queue for their next upload attempt.
        """
        try:
            current_time = time.time()

            # Get up to 10 messages whose retry time has passed
            ready_messages = self.redis_client.zrangebyscore(
                self.RETRY_QUEUE,
                min=0,
                max=current_time,
                start=0,
                num=10
            )

            for envelope_json in ready_messages:
                # Remove from retry sorted set
                self.redis_client.zrem(self.RETRY_QUEUE, envelope_json)

                # Move back to pending queue for the next attempt
                self.redis_client.lpush(self.PENDING_QUEUE, envelope_json)

                try:
                    envelope = json.loads(envelope_json)
                    payload_dict = json.loads(envelope.get("payload", "{}"))
                    message_id = payload_dict.get("message_id", "unknown")
                    logger.debug("Message %s moved from retry queue to pending (retry_count=%d)",
                                 message_id, envelope.get("retry_count", "?"))
                except (json.JSONDecodeError, TypeError):
                    logger.debug("Moved message from retry queue to pending")

        except redis.RedisError as e:
            logger.error("Error processing retry queue: %s", str(e))

    def _process_pending_queue(self) -> bool:
        """
        Process one message from the pending queue.

        Pops an envelope, makes a single upload attempt, then routes:
        - Success: message is done
        - Failure, retries remaining: schedule in RETRY_QUEUE sorted set with
          exponential backoff delay as the score (future Unix timestamp)
        - Failure, retries exhausted: move envelope to FAILED_QUEUE

        Returns:
            True if a message was processed, False if queue was empty
        """
        try:
            # Pop one message from the right (FIFO: LPUSH + BRPOP)
            result = self.redis_client.brpop(self.PENDING_QUEUE, timeout=1)

            if not result:
                return False  # Queue is empty

            # result is a tuple: (queue_name, envelope_json)
            _, envelope_json = result
            envelope = json.loads(envelope_json)

            retry_count = envelope.get("retry_count", 0)
            payload_json = envelope.get("payload", envelope_json)  # fallback for legacy raw messages

            # Extract message_id from the payload for logging
            try:
                payload_dict = json.loads(payload_json)
                message_id = payload_dict.get("message_id", "unknown")
            except (json.JSONDecodeError, TypeError):
                message_id = "unknown"

            attempt_number = retry_count + 1
            logger.debug("Processing message %s (attempt %d/%d)",
                         message_id, attempt_number, self.max_retry_attempts)

            success, error = self._attempt_upload(payload_json, message_id)

            if success:
                return True

            # Upload failed — update envelope with failure info
            retry_count += 1
            envelope["retry_count"] = retry_count
            envelope["last_error"] = error

            if retry_count >= self.max_retry_attempts:
                # Retries exhausted — move to failed queue
                self.redis_client.lpush(self.FAILED_QUEUE, json.dumps(envelope))
                logger.error(
                    "Message %s moved to failed queue after %d attempts. Last error: %s",
                    message_id, retry_count, error
                )
            else:
                # Schedule a deferred retry in the sorted set
                # score = future Unix timestamp when the message becomes eligible again
                delay = self.backoff_base * (self.backoff_multiplier ** (retry_count - 1))
                retry_at = time.time() + delay
                self.redis_client.zadd(self.RETRY_QUEUE, {json.dumps(envelope): retry_at})
                logger.warning(
                    "Message %s scheduled for retry %d/%d in %.0fs",
                    message_id, retry_count, self.max_retry_attempts, delay
                )

            return True

        except redis.RedisError as e:
            logger.error("Error processing pending queue: %s", str(e))
            return False
        except json.JSONDecodeError as e:
            logger.error("Failed to parse envelope JSON: %s", str(e))
            return True  # Consume the malformed message
        except Exception as e:
            logger.error("Unexpected error processing message: %s", str(e))
            return False

    def _attempt_upload(self, payload_json: str, message_id: str) -> tuple[bool, Optional[str]]:
        """
        Make a single upload attempt for a message.

        Does not retry — retry scheduling is handled by the caller via the
        RETRY_QUEUE sorted set so the worker thread is never blocked.

        Args:
            payload_json: Serialized DataMessage JSON string (the envelope payload)
            message_id: Message ID for logging

        Returns:
            Tuple of (success, error_string). error_string is None on success.
        """
        if not self.api_endpoint:
            logger.warning("No api_endpoint - cannot upload message %s", message_id)
            return False, "No api_endpoint configured"

        try:
            response = self.session.post(
                self.api_endpoint,
                data=payload_json,
                timeout=self.timeout
            )

            # Accept any 2xx status code as success (200, 201, 204, etc.)
            if 200 <= response.status_code < 300:
                logger.info("Successfully uploaded message %s (HTTP %d)", message_id, response.status_code)
                return True, None
            else:
                error = f"HTTP {response.status_code}: {response.text[:200]}"
                logger.warning("Upload failed for message %s: %s", message_id, error)
                return False, error

        except requests.exceptions.Timeout:
            error = "Request timed out"
            logger.warning("Timeout uploading message %s", message_id)
            return False, error

        except requests.exceptions.ConnectionError as e:
            error = f"ConnectionError: {str(e)}"
            logger.warning("Connection error uploading message %s: %s", message_id, str(e))
            return False, error

        except Exception as e:
            error = f"Unexpected error: {str(e)}"
            logger.error("Unexpected error uploading message %s: %s", message_id, str(e))
            return False, error

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
