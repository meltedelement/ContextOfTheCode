"""
Database module for storing collector metrics.

Provides SQLite database initialization and data insertion functions.
Uses a normalized schema with separate tables for messages and metrics.
"""

import sqlite3
from typing import Dict, Any, List
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

# Database file path - will be created if it doesn't exist
DB_PATH = 'metrics.db'


@contextmanager
def get_db_connection():
    """
    Context manager for database connections.

    Yields:
        sqlite3.Connection: Database connection with row factory enabled

    Example:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM messages")
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("Database error: %s", str(e))
        raise
    finally:
        conn.close()


def init_db():
    """
    Initialize the database schema.

    Creates two tables:
    - messages: Stores message metadata (message_id, timestamp, device_id, source)
    - metrics: Stores individual metrics (message_id FK, metric_name, metric_value)

    This normalized schema allows efficient querying by device, time range, or metric name.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Create messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                device_id TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create metrics table with foreign key to messages
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages (message_id)
            )
        """)

        # Create indexes for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_timestamp
            ON messages (timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_device_id
            ON messages (device_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_message_id
            ON metrics (message_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_name
            ON metrics (metric_name)
        """)

        logger.info("Database schema initialized successfully")


def insert_message(message_data: Dict[str, Any]) -> bool:
    """
    Insert a message and its metrics into the database.

    Args:
        message_data: Dictionary containing:
            - message_id: str
            - timestamp: float
            - device_id: str
            - source: str
            - metrics: List[Dict] with 'metric_name' and 'metric_value'

    Returns:
        True if insertion was successful, False otherwise

    Example:
        message_data = {
            "message_id": "550e8400-e29b-41d4-a716-446655440000",
            "timestamp": 1642534800.123,
            "device_id": "local-system-001",
            "source": "local",
            "metrics": [
                {"metric_name": "cpu_usage", "metric_value": 45.2},
                {"metric_name": "ram_usage", "metric_value": 7234.5}
            ]
        }
        success = insert_message(message_data)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Insert message metadata
            cursor.execute("""
                INSERT INTO messages (message_id, timestamp, device_id, source)
                VALUES (?, ?, ?, ?)
            """, (
                message_data['message_id'],
                message_data['timestamp'],
                message_data['device_id'],
                message_data['source']
            ))

            # Insert all metrics for this message
            metrics: List[Dict[str, Any]] = message_data.get('metrics', [])
            for metric in metrics:
                cursor.execute("""
                    INSERT INTO metrics (message_id, metric_name, metric_value)
                    VALUES (?, ?, ?)
                """, (
                    message_data['message_id'],
                    metric['metric_name'],
                    metric['metric_value']
                ))

            logger.info("Inserted message %s with %d metrics",
                       message_data['message_id'], len(metrics))
            return True

    except sqlite3.IntegrityError as e:
        logger.warning("Message %s already exists: %s",
                      message_data.get('message_id'), str(e))
        return False

    except Exception as e:
        logger.error("Failed to insert message: %s", str(e))
        return False


def get_message_count() -> int:
    """
    Get the total number of messages in the database.

    Returns:
        Total count of messages
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        return count


def get_recent_messages(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get the most recent messages with their metrics.

    Args:
        limit: Maximum number of messages to return (default: 10)

    Returns:
        List of message dictionaries with nested metrics
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get recent messages
        cursor.execute("""
            SELECT message_id, timestamp, device_id, source
            FROM messages
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))

        messages = []
        for row in cursor.fetchall():
            message = dict(row)

            # Get metrics for this message
            cursor.execute("""
                SELECT metric_name, metric_value
                FROM metrics
                WHERE message_id = ?
            """, (message['message_id'],))

            message['metrics'] = [dict(metric_row) for metric_row in cursor.fetchall()]
            messages.append(message)

        return messages


if __name__ == "__main__":
    # Initialize database when run directly
    logging.basicConfig(level=logging.INFO)
    init_db()
    print(f"Database initialized at {DB_PATH}")
    print(f"Current message count: {get_message_count()}")
