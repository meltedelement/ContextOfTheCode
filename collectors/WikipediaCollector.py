"""Wikipedia edit collector using MediaWiki Recent Changes API."""

from collectors.base_data_collector import BaseDataCollector, DataMessage
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import requests
import sys
import time
from sharedUtils.logger.logger import get_logger
from sharedUtils.config import get_wikipedia_collector_config, get_collector_config

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
        """Initialize Wikipedia edit collector."""
        # Load collector-specific config
        config = get_wikipedia_collector_config()

        # Initialize base with collection interval
        super().__init__(
            source=SOURCE_TYPE,
            device_id=device_id,
            collection_interval=config.collection_interval
        )

        self.wikipedia_language = wikipedia_language
        self.api_url = f"https://{wikipedia_language}.wikipedia.org/w/api.php"
        logger.debug("WikipediaCollector initialized for %s", wikipedia_language)

    def _query_recent_changes(self, start_time: datetime, end_time: datetime) -> Optional[int]:
        """Query Wikipedia API for edit count in time range."""
        rc_start = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        rc_end = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.debug("Querying Wikipedia API from %s to %s", rc_start, rc_end)

        params = {
            "action": "query",
            "list": "recentchanges",
            "rcstart": rc_start,
            "rcend": rc_end,
            "rcnamespace": NAMESPACE_ARTICLES,
            "rclimit": "max",
            "format": "json",
            "rctype": "edit|new",
        }

        try:
            user_agent = get_wikipedia_collector_config().user_agent

            response = requests.get(
                self.api_url,
                params=params,
                timeout=API_TIMEOUT,
                headers={"User-Agent": user_agent}
            )
            response.raise_for_status()

            data = response.json()

            if "query" in data and "recentchanges" in data["query"]:
                count = len(data["query"]["recentchanges"])
                logger.info("API returned %s changes", count)
                return count
            else:
                logger.warning("Wikipedia API response missing 'recentchanges'")
                return 0

        except requests.exceptions.RequestException as e:
            logger.warning("Failed to query Wikipedia API: %s", e)
            return None
        except (KeyError, ValueError) as e:
            logger.warning("Failed to parse Wikipedia API response: %s", e)
            return None

    def collect_data(self) -> Dict[str, Any]:
        """Collect Wikipedia edit count for the configured time window."""
        collection_window = get_wikipedia_collector_config().collection_window
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(seconds=collection_window)

        edit_count = self._query_recent_changes(start_time, end_time)

        return {
            "wikipedia_language": self.wikipedia_language,
            "query_timestamp": end_time.isoformat() + ISO_UTC_SUFFIX,
            "edit_count_last_minute": edit_count if edit_count is not None else 0,
            "query_success": edit_count is not None,
        }


if __name__ == "__main__":
    language = sys.argv[1] if len(sys.argv) > 1 else "en"
    collector = WikipediaCollector(
        device_id=f"wikipedia-monitor-{language}",
        wikipedia_language=language
    )

    print(f"Wikipedia Collector - Monitoring {language}.wikipedia.org")
    print("Press Ctrl+C to stop\n")

    try:
        poll_interval = get_collector_config().default_interval
        while True:
            message = collector.generate_message()

            # Extract edit count from metrics
            edit_count = next(
                (m.metric_value for m in message.metrics if m.metric_name == "edit_count_last_minute"),
                0
            )
            query_success = next(
                (m.metric_value for m in message.metrics if m.metric_name == "query_success"),
                0
            )

            status = "✓" if query_success else "✗"
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {status} Edits: {int(edit_count)}")
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("\nStopped")
