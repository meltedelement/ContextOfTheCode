"""
Simple Upload Queue Implementation

A minimal queue implementation that immediately POSTs messages to a remote API endpoint.
This is a placeholder that provides the queue interface but doesn't actually queue messages.
Later, this can be replaced with a proper queue (RabbitMQ, Redis, etc.) without changing
collector code.
"""

import requests
from typing import Dict, Any, TYPE_CHECKING
from sharedUtils.upload_queue.base_queue import UploadQueue
from sharedUtils.logger.logger import get_logger

if TYPE_CHECKING:
    from collectors.base_data_collector import DataMessage

logger = get_logger(__name__)


class SimpleUploadQueue(UploadQueue):
    """
    Simple upload queue that immediately POSTs messages to an API endpoint.

    This implementation doesn't actually queue messages - it sends them immediately
    when put() is called. This allows us to get data flowing while maintaining the
    queue interface that can be swapped for a real queue implementation later.

    Attributes:
        api_endpoint: URL of the remote API endpoint
        api_key: API key for authentication
        timeout: Request timeout in seconds
        retry_attempts: Number of retry attempts on failure
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the simple upload queue.

        Args:
            config: Configuration dictionary with keys:
                - api_endpoint: URL to POST messages to
                - api_key: API key for authentication
                - timeout: Request timeout in seconds (default: 10)
                - retry_attempts: Number of retries on failure (default: 3)
        """
        self.api_endpoint = config.get('api_endpoint')
        self.api_key = config.get('api_key')
        self.timeout = config.get('timeout', 10)
        self.retry_attempts = config.get('retry_attempts', 3)
        self.session = None

        if not self.api_endpoint:
            logger.warning("No api_endpoint configured - messages will only be logged")

        logger.debug("SimpleUploadQueue initialized with endpoint: %s", self.api_endpoint)

    def start(self) -> None:
        """
        Start the queue by creating a requests session for connection pooling.
        """
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'X-API-Key': self.api_key
        })
        logger.info("SimpleUploadQueue started")

    def stop(self) -> None:
        """
        Stop the queue by closing the requests session.
        """
        if self.session:
            self.session.close()
            self.session = None
        logger.info("SimpleUploadQueue stopped")

    def put(self, message: 'DataMessage') -> bool:
        """
        Immediately POST the message to the configured API endpoint.

        Args:
            message: DataMessage object to send

        Returns:
            True if message was successfully sent, False otherwise
        """
        if not self.api_endpoint:
            logger.warning("No api_endpoint configured - message %s not sent", message.message_id)
            return False

        if not self.session:
            logger.error("Queue not started - call start() before put()")
            return False

        # Convert Pydantic model to JSON
        json_data = message.model_dump_json()

        # Attempt to send with retries
        for attempt in range(1, self.retry_attempts + 1):
            try:
                logger.debug("Sending message %s (attempt %d/%d)",
                           message.message_id, attempt, self.retry_attempts)

                response = self.session.post(
                    self.api_endpoint,
                    data=json_data,
                    timeout=self.timeout
                )

                if response.status_code == 200:
                    logger.info("Successfully sent message %s to %s",
                              message.message_id, self.api_endpoint)
                    return True
                else:
                    logger.warning("Failed to send message %s: HTTP %d - %s",
                                 message.message_id, response.status_code, response.text)

            except requests.exceptions.Timeout:
                logger.error("Timeout sending message %s (attempt %d/%d)",
                           message.message_id, attempt, self.retry_attempts)

            except requests.exceptions.ConnectionError as e:
                logger.error("Connection error sending message %s (attempt %d/%d): %s",
                           message.message_id, attempt, self.retry_attempts, str(e))

            except Exception as e:
                logger.error("Unexpected error sending message %s: %s",
                           message.message_id, str(e))
                break  # Don't retry on unexpected errors

        # All retries failed
        logger.error("Failed to send message %s after %d attempts",
                   message.message_id, self.retry_attempts)
        return False
