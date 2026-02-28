"""
TransportCollector: Data collector for transport APIs using REST endpoints.

This collector fetches transport-related data from a remote API, supporting authentication
with public and private keys. It inherits from BaseDataCollector and is compatible with the
framework's message and queue system. The collector is designed to be easily extended for
different API response formats and authentication schemes.
"""

from collectors.base_data_collector import BaseDataCollector, MetricEntry
from typing import Optional, List
import requests
import sys
import time
import os
from dotenv import load_dotenv
from sharedUtils.logger.logger import get_logger
from sharedUtils.config import get_collector_config


# Logger instance for this module
logger = get_logger(__name__)
# Source identifier for this collector type (used in message metadata)
SOURCE_TYPE = "transport_api"
# Timeout for API requests (in seconds)
API_TIMEOUT = 10


class TransportCollector(BaseDataCollector):
	"""
	TransportCollector pulls data from a REST API endpoint.

	Supports authentication using primary and secondary keys, which are sent as headers.
	The collector can be extended to handle custom API response formats and authentication.
	"""

	def __init__(self, device_id: str, api_url: str, primary_key: Optional[str] = None, secondary_key: Optional[str] = None, format_param: Optional[str] = None):
		"""
		Initialize the TransportCollector.

		Args:
			device_id (str): Unique identifier for the device or data source.
			api_url (str): The full URL of the transport API endpoint.
			primary_key (Optional[str]): Primary key for authentication (sent as header).
			secondary_key (Optional[str]): Secondary key for authentication (sent as header).
			format_param (Optional[str]): Optional format parameter for the API.
		"""
		config = get_collector_config()
		super().__init__(
			source=SOURCE_TYPE,
			device_id=device_id,
			collection_interval=config.default_interval
		)
		self.api_url = api_url
		self.primary_key = primary_key
		self.secondary_key = secondary_key
		self.format_param = format_param
		logger.debug("TransportCollector initialized for %s", api_url)

	def _query_transport_api(self) -> Optional[dict]:
		"""
		Query the vehicle positions API and return the response as a Python dictionary.

		Returns:
			dict: Parsed JSON response from the API, or None if the request fails.
		"""
		headers = {}
		if self.primary_key:
			headers["x-api-key"] = self.primary_key
		if self.secondary_key:
			headers["X-Secondary-Key"] = self.secondary_key
		params = {"format": "json"}
		try:
			response = requests.get(self.api_url, headers=headers, params=params, timeout=API_TIMEOUT)
			response.raise_for_status()
			data = response.json()
			logger.info("API returned status %s", response.status_code)
			return data
		except requests.exceptions.RequestException as e:
			logger.warning("Failed to query Transport API: %s", e)
			return None
		except Exception as e:
			logger.warning("Failed to parse Transport API response: %s", e)
			return None

	def _query_tripupdates_api(self) -> Optional[dict]:
		"""
		Query the TripUpdates API and return the response as a Python dictionary.

		Returns:
			dict: Parsed JSON response from the API, or None if the request fails.
		"""
		tripupdates_url = "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates?format=json"
		headers = {}
		if self.primary_key:
			headers["x-api-key"] = self.primary_key
		if self.secondary_key:
			headers["X-Secondary-Key"] = self.secondary_key
		try:
			response = requests.get(tripupdates_url, headers=headers, timeout=API_TIMEOUT)
			response.raise_for_status()
			data = response.json()
			logger.info("TripUpdates API returned status %s", response.status_code)
			return data
		except requests.exceptions.RequestException as e:
			logger.warning("Failed to query TripUpdates API: %s", e)
			return None
		except Exception as e:
			logger.warning("Failed to parse TripUpdates API response: %s", e)
			return None

	def collect_data(self) -> List[MetricEntry]:
		"""
		Collect transport data from the configured API endpoint.

		Returns a list of MetricEntry objects (latitude, longitude, last_arrival_delay)
		for each vehicle with a valid position. This is the format expected by the base
		class generate_message().
		"""
		vehicle_data = self._query_transport_api()
		tripupdates_data = self._query_tripupdates_api()

		# Build a lookup for (trip_id, vehicle_id) -> trip_update for fast join
		trip_update_lookup = {}
		if tripupdates_data and "entity" in tripupdates_data:
			for entity in tripupdates_data["entity"]:
				trip_update = entity.get("trip_update")
				if trip_update and "trip" in trip_update and "vehicle" in trip_update:
					trip_id = trip_update["trip"].get("trip_id")
					vehicle_id = str(trip_update["vehicle"].get("id")) if trip_update["vehicle"].get("id") is not None else None
					if trip_id and vehicle_id:
						trip_update_lookup[(trip_id, vehicle_id)] = trip_update

		metrics: List[MetricEntry] = []

		if vehicle_data and "entity" in vehicle_data:
			for entity in vehicle_data["entity"]:
				vehicle = entity.get("vehicle")
				if vehicle and "position" in vehicle and "trip" in vehicle:
					position = vehicle["position"]
					lat = position.get("latitude")
					lon = position.get("longitude")
					trip = vehicle["trip"]
					trip_id = trip.get("trip_id", "unknown")
					vehicle_id = str(vehicle.get("vehicle", {}).get("id", entity.get("id", "unknown")))

					if lat is None or lon is None:
						continue

					metrics.append(MetricEntry(
						metric_name=f"bus_{vehicle_id}_latitude",
						metric_value=float(lat),
						unit="deg"
					))
					metrics.append(MetricEntry(
						metric_name=f"bus_{vehicle_id}_longitude",
						metric_value=float(lon),
						unit="deg"
					))

					trip_update = trip_update_lookup.get((trip_id, vehicle_id))
					if trip_update and "stop_time_update" in trip_update:
						stop_updates = trip_update["stop_time_update"]
						if stop_updates:
							last_stop = stop_updates[-1]
							arrival_delay = last_stop.get("arrival", {}).get("delay")
							if arrival_delay is not None:
								metrics.append(MetricEntry(
									metric_name=f"bus_{vehicle_id}_last_arrival_delay",
									metric_value=float(arrival_delay),
									unit="s"
								))
		else:
			logger.warning("No data received from Vehicle API or failed to parse feed.")

		return metrics


if __name__ == "__main__":
	load_dotenv()

	api_url = sys.argv[1] if len(sys.argv) > 1 else "https://api.nationaltransport.ie/gtfsr/v2/Vehicles?format=json"
	format_param = sys.argv[2] if len(sys.argv) > 2 else None
	primary_key = os.environ.get("PRIMARY_KEY")
	secondary_key = os.environ.get("SECONDARY_KEY")
	collector = TransportCollector(
		device_id="transport-001",
		api_url=api_url,
		primary_key=primary_key,
		secondary_key=secondary_key,
		format_param=format_param
	)

	print(f"Transport Collector - Monitoring {api_url}")
	print("Press Ctrl+C to stop\n")

	try:
		poll_interval = get_collector_config().default_interval
		while True:
			message = collector.generate_message()
			print("--- Metrics Extracted ---")
			import json
			print(json.dumps([m.dict() for m in message.metrics], indent=2))
			print("--- End of Metrics ---")
			time.sleep(poll_interval)
	except KeyboardInterrupt:
		print("\nStopped")
