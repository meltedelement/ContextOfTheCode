"""Mobile app collector — reads device_stats rows from Supabase."""

from collectors.base_data_collector import BaseDataCollector, MetricEntry
from typing import Optional, List
from supabase import create_client, Client
from sharedUtils.logger.logger import get_logger
from sharedUtils.config import get_mobile_app_collector_config

logger = get_logger(__name__)

# Identifies this collector type in SnapshotMessage.source and logs
SOURCE_TYPE = "mobile_app"


class MobileAppCollector(BaseDataCollector):
	"""Collects device metrics from the device_stats table in Supabase.

	Each row in device_stats represents one mobile device. The collector
	reads all rows on every collection cycle and emits one MetricEntry per
	numeric field per device, named  mobile_<user_id>_<column>.

	Numeric columns collected:
	  - battery_level      → unit "%"
	  - is_charging        → bool coerced to 1.0 / 0.0, unit ""
	  - ram_total_mb       → unit "MB"
	  - ram_available_mb   → unit "MB"
	  - ram_used_mb        → unit "MB"
	  - storage_total_gb   → unit "GB"
	  - storage_free_gb    → unit "GB"
	  - storage_used_gb    → unit "GB"

	String columns (device_model, os_name, network_type, wifi_name) are
	skipped — MetricEntry only accepts float values.
	"""

	def __init__(self, device_id: str, supabase_url: str, supabase_key: str):
		"""
		Initialize the collector with Supabase credentials.

		Args:
			device_id:     Server-issued UUID identifying this aggregator.
			supabase_url:  Full URL of the Supabase project.
			supabase_key:  Supabase anon/service key for authentication.
		"""
		# Load interval from [mobile_app_collector] section of config.toml
		config = get_mobile_app_collector_config()
		super().__init__(
			source=SOURCE_TYPE,
			device_id=device_id,
			collection_interval=config.collection_interval
		)
		# Supabase client — reused across every collection cycle
		self._client: Client = create_client(supabase_url, supabase_key)
		logger.debug("MobileAppCollector initialized for %s", supabase_url)

	def _query_device_stats(self) -> Optional[list]:
		"""
		Fetch all rows from the device_stats table.

		Returns None on any network or query error so that collect_data()
		can fail gracefully without raising an exception to the base class loop.

		Returns:
			List of row dicts, or None if the query fails.
		"""
		try:
			response = self._client.table("device_stats").select("*").execute()
			logger.info("Fetched %d rows from device_stats", len(response.data))
			return response.data
		except Exception as e:
			logger.warning("Failed to query device_stats: %s", e)
			return None

	def collect_data(self) -> List[MetricEntry]:
		"""
		Build a MetricEntry list from all device_stats rows.

		Called automatically by BaseDataCollector.generate_message() on each
		collection cycle. Returns an empty list (not an error) if the table
		is empty or unreachable, so the upload queue still receives a valid
		(zero-metric) snapshot rather than crashing the collection loop.

		Returns:
			List of MetricEntry objects, one per numeric field per device.
		"""
		rows = self._query_device_stats()
		metrics: List[MetricEntry] = []

		if not rows:
			logger.warning("No rows returned from device_stats.")
			return metrics

		for row in rows:
			# Prefer user_id as the stable device identifier; fall back to id or "unknown"
			user_id = row.get("user_id", row.get("id", "unknown"))

			# --- Battery ---
			battery_level = row.get("battery_level")
			if battery_level is not None:
				metrics.append(MetricEntry(
					metric_name=f"mobile_{user_id}_battery_level",
					metric_value=float(battery_level),
					unit="%"
				))

			# --- Charging state (bool → float: True=1.0, False=0.0) ---
			is_charging = row.get("is_charging")
			if is_charging is not None:
				metrics.append(MetricEntry(
					metric_name=f"mobile_{user_id}_is_charging",
					metric_value=1.0 if is_charging else 0.0,
					unit=""
				))

			# --- RAM and storage columns (uniform float conversion) ---
			for col, unit in [
				("ram_total_mb",     "MB"),
				("ram_available_mb", "MB"),
				("ram_used_mb",      "MB"),
				("storage_total_gb", "GB"),
				("storage_free_gb",  "GB"),
				("storage_used_gb",  "GB"),
			]:
				val = row.get(col)
				if val is not None:
					metrics.append(MetricEntry(
						metric_name=f"mobile_{user_id}_{col}",
						metric_value=float(val),
						unit=unit
					))

		return metrics
