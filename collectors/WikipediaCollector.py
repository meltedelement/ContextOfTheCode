"""
Wikipedia Edit Collector Implementation

Collects Wikipedia edit counts by polling the MediaWiki Recent Changes API
every minute to track editing activity. Only emits float metric values.
"""

from collectors.base_data_collector import BaseDataCollector, DataMessage, MetricEntry, CONFIG
from typing import List, Optional
from datetime import datetime, timedelta, timezone
import requests
import sys
import time
from sharedUtils.logger.logger import get_logger

# Constants
logger = get_logger(__name__)
SOURCE_TYPE = "wikipedia"  # Source identifier for Wikipedia collector
DEFAULT_LANGUAGE = "en"  # Default to English Wikipedia
API_TIMEOUT = 10  # HTTP request timeout in seconds
NAMESPACE_ARTICLES = 0  # Namespace 0 = article pages (not talk pages, etc.)


class WikipediaCollector(BaseDataCollector):
    """Wikipedia edit collector that monitors editing activity via MediaWiki API."""

    def __init__(self, device_id: str, wikipedia_language: str = DEFAULT_LANGUAGE):
        """
        Initialize Wikipedia edit collector.

        Args:
            device_id: Unique identifier for the collector instance
            wikipedia_language: Language code for Wikipedia (e.g., 'en', 'fr', 'de')
        """
        logger.debug("Initialising WikipediaCollector for %s", wikipedia_language)
        super().__init__(source=SOURCE_TYPE, device_id=device_id)
        self.wikipedia_language = wikipedia_language
        self.api_url = f"https://{wikipedia_language}.wikipedia.org/w/api.php"

    def _query_recent_changes(self, start_time: datetime, end_time: datetime) -> Optional[int]:
        """
        Query Wikipedia Recent Changes API for edit count in time range.

        Args:
            start_time: Beginning of time window
            end_time: End of time window

        Returns:
            Number of edits in the time window, or None if query failed
        """
        # Format timestamps for MediaWiki API (ISO 8601 format)
        rc_start = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        rc_end = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.debug("Querying Wikipedia API from %s to %s", rc_start, rc_end)

        params = {
            "action": "query",
            "list": "recentchanges",
            "rcstart": rc_start,  # Start of time range
            "rcend": rc_end,      # End of time range
            "rcnamespace": NAMESPACE_ARTICLES,  # Only article edits
            "rclimit": "max",     # Get as many results as allowed (500 for users, 5000 for bots)
            "format": "json",
            "rctype": "edit|new",  # Include both edits and new pages
        }

        try:
            # Get User-Agent from config
            user_agent = CONFIG.get("wikipedia", {}).get(
                "user_agent",
                "WikipediaDataCollector/1.0 (Educational Project)"
            )

            response = requests.get(
                self.api_url,
                params=params,
                timeout=API_TIMEOUT,
                headers={"User-Agent": user_agent}
            )
            response.raise_for_status()

            data = response.json()

            # Count the number of changes returned
            if "query" in data and "recentchanges" in data["query"]:
                logger.info("API returned %s changes", len(data["query"]["recentchanges"]))
                return len(data["query"]["recentchanges"])
            else:
                logger.warning("Wikipedia API response missing 'recentchanges'")
                return 0

        except requests.exceptions.RequestException as e:
            logger.warning("Failed to query Wikipedia API: %s", e)
            return None
        except (KeyError, ValueError) as e:
            logger.warning("Failed to parse Wikipedia API response: %s", e)
            return None

    def collect_data(self) -> List[MetricEntry]:
        """
        Collect Wikipedia edit count for the configured time window.

        Returns:
            List of MetricEntry objects with float values for:
            - edit_count: Number of edits in the configured time window
            - query_success: 1.0 if query succeeded, 0.0 if it failed
        """
        # Get configuration values
        collection_window = CONFIG.get("wikipedia", {}).get("collection_window", 60)

        # Calculate time window using configured collection window
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(seconds=collection_window)
        logger.debug("Collecting edits between %s and %s", start_time.isoformat(), end_time.isoformat())

        # Query the API
        edit_count = self._query_recent_changes(start_time, end_time)

        # Build metrics — all values are floats
        if edit_count is not None:
            metrics = [
                MetricEntry(metric_name="edit_count", metric_value=float(edit_count)),
                MetricEntry(metric_name="query_success", metric_value=1.0),
            ]
            logger.info("Edit count for last %ds: %s", collection_window, edit_count)
        else:
            metrics = [
                MetricEntry(metric_name="edit_count", metric_value=0.0),
                MetricEntry(metric_name="query_success", metric_value=0.0),
            ]
            logger.warning("Edit count could not be retrieved — API query failed")

        return metrics

    def export_to_data_model(self, message: DataMessage) -> None:
        """
        Export the message to the data model format.

        Serializes the Pydantic message to JSON and logs it to console
        if console_export is enabled in config. In the future, this will
        send the message to the upload queue.

        Args:
            message: DataMessage Pydantic model with metadata and collected metrics
        """
        # Get JSON formatting from config
        json_indent = CONFIG.get("logging", {}).get("json_indent", 2)

        # Use Pydantic's built-in JSON serialization
        json_output = message.model_dump_json(indent=json_indent)

        # Log to console if enabled in config (simulating upload queue)
        if CONFIG.get("logging", {}).get("console_export", True):
            logger.debug("Exporting message from %s to console", self.source)
            print(f"\n[DATA MODEL EXPORT - {self.source.upper()}]")
            print(json_output)
            print(f"[END EXPORT]\n")


# Example usage
if __name__ == "__main__":
    # Allow language to be specified via command line
    language = sys.argv[1] if len(sys.argv) > 1 else "en"

    # Create a Wikipedia edit collector
    collector = WikipediaCollector(
        device_id=f"wikipedia-monitor-{language}",
        wikipedia_language=language
    )

    print(f"Wikipedia Edit Collector")
    print(f"Monitoring: {language}.wikipedia.org")
    print(f"Device ID: {collector.device_id}")
    print(f"Source: {collector.source}")
    print(f"\n{'='*60}\n")

    # Single collection example
    print("Single collection example:")
    message = collector.generate_message()

    # Continuous polling example
    print(f"\n{'='*60}")
    print("Starting continuous polling (every 60 seconds)...")
    print("Press Ctrl+C to stop\n")

    try:
        poll_interval = CONFIG.get("collectors", {}).get("default_interval", 60)

        while True:
            print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] Collecting data...")
            message = collector.generate_message()

            # Show summary from metrics list
            edit_metric = next((m for m in message.metrics if m.metric_name == "edit_count"), None)
            success_metric = next((m for m in message.metrics if m.metric_name == "query_success"), None)
            edit_count = edit_metric.metric_value if edit_metric else 0
            success = success_metric.metric_value == 1.0 if success_metric else False
            status = "✓" if success else "✗"
            print(f"  {status} Edits in last minute: {int(edit_count)}")

            # Wait for next poll
            print(f"  Waiting {poll_interval} seconds until next poll...\n")
            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print("\n\nStopped polling. Goodbye!")
