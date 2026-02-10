"""
Wikipedia Edit Collector Implementation

Collects Wikipedia edit counts by polling the MediaWiki Recent Changes API
every minute to track editing activity.
"""

from collectors.base_data_collector import BaseDataCollector, DataMessage, CONFIG
from typing import Dict, Any, Optional
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
ISO_UTC_SUFFIX = "Z"  # UTC timezone suffix for ISO 8601 timestamps


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
        # API expects format: YYYY-MM-DDTHH:MM:SSZ
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
            # Log error but don't crash - return None to indicate failure
            print(f"[WARNING] Failed to query Wikipedia API: {e}")
            logger.warning("Failed to query Wikipedia API: %s", e)
            return None
        except (KeyError, ValueError) as e:
            logger.warning("Failed to parse Wikipedia API response: %s", e)
            return None

    def collect_data(self) -> Dict[str, Any]:
        """
        Collect Wikipedia edit count for the configured time window.

        Returns:
            Dictionary with metrics including:
            - edit_count_last_minute: Number of edits in the configured time window
            - wikipedia_language: Language code of Wikipedia being monitored
            - query_success: Boolean indicating if the query succeeded
            - query_timestamp: ISO timestamp of when the query was made
        """
        # Get configuration values
        precision = CONFIG.get("collectors", {}).get("metric_precision", 1)
        collection_window = CONFIG.get("wikipedia", {}).get("collection_window", 60)

        # Calculate time window using configured collection window
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(seconds=collection_window)
        logger.debug("Collecting edits between %s and %s", start_time.isoformat(), end_time.isoformat())

        # Query the API
        edit_count = self._query_recent_changes(start_time, end_time)

        data = {
            "wikipedia_language": self.wikipedia_language,
            "query_timestamp": end_time.isoformat() + ISO_UTC_SUFFIX,
        }

        if edit_count is not None:
            data["edit_count_last_minute"] = edit_count
            data["query_success"] = True
            logger.info("Edit count for last minute: %s", edit_count)
        else:
            data["edit_count_last_minute"] = 0
            data["query_success"] = False
            logger.warning("Edit count could not be retrieved — API query failed")

        return data

    # Removed export_to_data_model() - now uses default implementation from BaseDataCollector
    # which sends messages to the upload queue


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
    print(f"\nConfiguration:")
    print(f"  Metric precision: {CONFIG.get('collectors', {}).get('metric_precision')}")
    print(f"  Console export: {CONFIG.get('logging', {}).get('console_export')}")
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

            # Show summary
            edit_count = message.data.get("edit_count_last_minute", 0)
            success = message.data.get("query_success", False)
            status = "✓" if success else "✗"
            print(f"  {status} Edits in last minute: {edit_count}")

            # Wait for next poll
            print(f"  Waiting {poll_interval} seconds until next poll...\n")
            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print("\n\nStopped polling. Goodbye!")
