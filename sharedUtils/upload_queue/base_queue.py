"""
Base Upload Queue Interface

Abstract base class defining the interface for upload queue implementations.
All queue implementations must inherit from this class and implement its methods.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collectors.base_data_collector import DataMessage


class UploadQueue(ABC):
    """
    Abstract base class for upload queue implementations.

    This interface allows collectors to send data without knowing the underlying
    queue mechanism. Implementations can be swapped (e.g., SimpleQueue, RabbitMQ,
    Redis) without changing collector code.
    """

    @abstractmethod
    def put(self, message: 'DataMessage') -> bool:
        """
        Add a message to the upload queue.

        Args:
            message: DataMessage object to be queued for upload

        Returns:
            True if message was successfully queued, False otherwise

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        pass

    @abstractmethod
    def start(self) -> None:
        """
        Start the queue (e.g., open connections, start worker threads).

        Called once during initialization before any messages are put.

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """
        Stop the queue gracefully (e.g., flush pending messages, close connections).

        Called during shutdown to ensure all messages are processed.

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        pass

    def __enter__(self):
        """Context manager entry - starts the queue."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stops the queue."""
        self.stop()
        return False
