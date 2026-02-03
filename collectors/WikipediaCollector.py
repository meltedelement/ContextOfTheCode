"""
Wikipedia Edit Collector Implementation

Collects Wikipedia edit counts by polling the MediaWiki Recent Changes API
every minute to track editing activity.
"""

from collectors.base_data_collector import BaseDataCollector, DataMessage, CONFIG
from typing import Dict, Any, Optional
import requests
import time
from datetime import datetime, timedelta, timezone

# Constants
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
            response = requests.get(
                self.api_url,
                params=params,
                timeout=API_TIMEOUT,
                headers={"User-Agent": "WikipediaDataCollector/1.0 (Educational Project)"}
            )
            response.raise_for_status()

            data = response.json()

            # Count the number of changes returned
            if "query" in data and "recentchanges" in data["query"]:
                return len(data["query"]["recentchanges"])
            else:
                return 0

        except requests.exceptions.RequestException as e:
            # Log error but don't crash - return None to indicate failure
            print(f"[WARNING] Failed to query Wikipedia API: {e}")
            return None
        except (KeyError, ValueError) as e:
            print(f"[WARNING] Failed to parse Wikipedia API response: {e}")
            return None

    def collect_data(self) -> Dict[str, Any]:
        """
        Collect Wikipedia edit count for the last minute.

        Returns:
            Dictionary with metrics including:
            - edit_count_last_minute: Number of edits in the past 60 seconds
            - wikipedia_language: Language code of Wikipedia being monitored
            - query_success: Boolean indicating if the query succeeded
            - query_timestamp: ISO timestamp of when the query was made
        """
        # Get precision from config
        precision = CONFIG.get("collectors", {}).get("metric_precision", 1)

        # Calculate time window: last 60 seconds
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(seconds=60)

        # Query the API
        edit_count = self._query_recent_changes(start_time, end_time)

        data = {
            "wikipedia_language": self.wikipedia_language,
            "query_timestamp": end_time.isoformat() + "Z",
        }

        if edit_count is not None:
            data["edit_count_last_minute"] = edit_count
            data["query_success"] = True
        else:
            data["edit_count_last_minute"] = 0
            data["query_success"] = False

        return data

    def export_to_data_model(self, message: DataMessage) -> None:
        """
        Export the message to the data model format.

        Serializes the Pydantic message to JSON and logs it to console
        if console_export is enabled in config. In the future, this will
        send the message to the upload queue.

        Args:
            message: DataMessage Pydantic model with metadata and collected data
        """
        # Get JSON formatting from config
        json_indent = CONFIG.get("logging", {}).get("json_indent", 2)

        # Use Pydantic's built-in JSON serialization
        json_output = message.model_dump_json(indent=json_indent)

        # Log to console if enabled in config (simulating upload queue)
        if CONFIG.get("logging", {}).get("console_export", True):
            print(f"\n[DATA MODEL EXPORT - {self.source.upper()}]")
            print(json_output)
            print(f"[END EXPORT]\n")


# Example usage
if __name__ == "__main__":
    import sys

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
