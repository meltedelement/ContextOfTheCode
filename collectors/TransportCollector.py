

"""
TransportCollector: Data collector for transport APIs using REST endpoints.

This collector fetches transport-related data from a remote API, supporting authentication
with public and private keys. It inherits from BaseDataCollector and is compatible with the
framework's message and queue system. The collector is designed to be easily extended for
different API response formats and authentication schemes.
"""

from ContextOfTheCode.collectors.base_data_collector import BaseDataCollector, DataMessage, MetricEntry
from typing import Dict, Any, Optional, List
import requests
 # No protobuf import needed if using JSON endpoint
import sys
import time
import os
from dotenv import load_dotenv
from ContextOfTheCode.sharedUtils.logger.logger import get_logger
from ContextOfTheCode.sharedUtils.config import get_collector_config


# Logger instance for this module
logger = get_logger(__name__)
# Source identifier for this collector type (used in message metadata)
SOURCE_TYPE = "transport_api"
# Timeout for API requests (in seconds)
API_TIMEOUT = 10


class TransportCollector(BaseDataCollector):
	def _query_tripupdates_api(self) -> Optional[dict]:
		"""
		Query the TripUpdates API and return the response as a Python dictionary (parsed JSON).
		Returns:
			dict: Parsed JSON response from the API, or None if the request fails.
		"""
		tripupdates_url = "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates?format=json"
		try:
			response = requests.get(tripupdates_url, timeout=API_TIMEOUT)
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
	"""
	
	TransportCollector pulls data from a REST API endpoint.

	Supports authentication using primary (primary key is the API key) and secondary keys, which are sent as headers.
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
		# Load collector config for interval and other settings
		config = get_collector_config()
		# Initialize the base collector with source, device_id, and collection interval
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
		Query the transport API and return the response as a Python dictionary (parsed JSON).

		Returns:
			dict: Parsed JSON response from the API, or None if the request fails.
		"""
		headers = {}
		if self.primary_key:
			headers["x-api-key"] = self.primary_key
		if self.secondary_key:
			headers["X-Secondary-Key"] = self.secondary_key
		# Always request JSON format if possible
		params = {"format": "json"}
		try:
			response = requests.get(self.api_url, headers=headers, params=params, timeout=API_TIMEOUT)
			response.raise_for_status()
			data = response.json()  # Parse JSON response
			logger.info("API returned status %s", response.status_code)
			return data
		except requests.exceptions.RequestException as e:
			logger.warning("Failed to query Transport API: %s", e)
			return None
		except Exception as e:
			logger.warning("Failed to parse Transport API response: %s", e)
			return None
		
	def _query_tripupdate_api(self) -> Optional[dict]:
		headers = {}
		if self.primary_key:
			headers["x-api-key"] = self.primary_key
		if self.secondary_key:
			headers["X-Secondary-Key"] = self.secondary_key
		params = {"format": "json"}
		try: 
			response = requests.get(self.api_url, headers=headers, params=params, timeout=API_TIMEOUT)
			response.raise_for_status()
			data = response.json()  # Parse JSON response
			logger.info("API returned status %s", response.status_code)
			return data
		except requests.exceptions.RequestException as e:
			logger.warning("Failed to query Trip Update API: %s", e)
			return None
		except Exception as e:
			logger.warning("Failed to parse Trip Update API response: %s", e)
			return None
		
	def collect_data(self) -> DataMessage:
		"""
		Collect transport data from the configured API endpoint and return a DataMessage.

		This method fetches the JSON feed, extracts all unique route IDs from trip updates,
		and returns a DataMessage (matching the new data model and collector style).
		"""
		# --- BEGIN: Fetch Vehicle API data ---
		# Query the vehicle API for current vehicle positions and trip info
		vehicle_data = self._query_transport_api()
		print("Raw Vehicle API response:", vehicle_data)

		# --- BEGIN: Fetch TripUpdates API data ---
		# Query the TripUpdates API for trip progress, stop times, and delays
		tripupdates_data = self._query_tripupdates_api()
		print("Raw TripUpdates API response:", tripupdates_data)

		# --- BEGIN: Prepare bus metrics as a list of dictionaries ---
		bus_metrics: List[dict] = []

		# --- Build a lookup dictionary for (trip_id, vehicle_id) -> trip_update dict for fast access ---
		# This allows us to quickly find the TripUpdate for a given trip and vehicle.
		trip_update_lookup = {}
		if tripupdates_data and "entity" in tripupdates_data:
			for entity in tripupdates_data["entity"]:
				trip_update = entity.get("trip_update")
				# Only process if both trip and vehicle info are present in the trip_update
				if trip_update and "trip" in trip_update and "vehicle" in trip_update:
					trip_id = trip_update["trip"].get("trip_id")
					# Vehicle ID is always string for consistency
					vehicle_id = str(trip_update["vehicle"].get("id")) if trip_update["vehicle"].get("id") is not None else None
					# Only add to lookup if both IDs are present
					if trip_id and vehicle_id:
						trip_update_lookup[(trip_id, vehicle_id)] = trip_update

		# --- Process each vehicle and join with trip updates ---
		# For each vehicle, extract its position, trip info, and try to find the matching TripUpdate
		if vehicle_data and "entity" in vehicle_data:
			for entity in vehicle_data["entity"]:
				vehicle = entity.get("vehicle")
				# Only process if both position and trip info are present
				if vehicle and "position" in vehicle and "trip" in vehicle:
					position = vehicle["position"]
					lat = position.get("latitude")
					lon = position.get("longitude")
					# Extract trip info from vehicle
					trip = vehicle["trip"]
					trip_id = trip.get("trip_id", "unknown")
					start_time = trip.get("start_time", "unknown")
					start_date = trip.get("start_date", "unknown")
					# Extract vehicle_id (bus id) as string
					vehicle_id = str(vehicle.get("vehicle", {}).get("id", entity.get("id", "unknown")))

					# Try to find the matching trip update for this (trip_id, vehicle_id) pair
					trip_update = trip_update_lookup.get((trip_id, vehicle_id))

					# Only add if lat/lon are present (i.e., valid position)
					if lat is not None and lon is not None:
						# Compose the bus metric dictionary for this vehicle
						bus_metric = {
							"id": vehicle_id,  # Unique bus/vehicle identifier
							"trip_id": trip_id,  # Trip identifier
							"start_time": start_time,  # Scheduled trip start time
							"start_date": start_date,  # Scheduled trip start date
							"latitude": float(lat),  # Current latitude
							"longitude": float(lon)  # Current longitude
						}
						# If a matching TripUpdate is found, try to extract last stop info
						if trip_update and "stop_time_update" in trip_update:
							stop_updates = trip_update["stop_time_update"]
							if stop_updates:
								# The last stop in the list is the end of the trip
								last_stop = stop_updates[-1]
								stop_id = last_stop.get("stop_id")  # Stop ID for the last stop
								arrival = last_stop.get("arrival", {})  # Arrival info dict
								arrival_delay = arrival.get("delay")  # Delay in seconds at last stop
								# Only add these fields if present (avoid nulls)
								if stop_id is not None:
									bus_metric["last_stop_id"] = stop_id
								if arrival_delay is not None:
									bus_metric["last_arrival_delay"] = arrival_delay
						# Add the bus metric to the list
						bus_metrics.append(bus_metric)
		else:
			logger.warning("No data received from Vehicle API or failed to parse feed.")

		# --- Print the bus metrics (as pretty-printed JSON) ---
		import json
		print("\n==== Bus Metrics Extracted from Feed ====")
		print(json.dumps(bus_metrics, indent=2))
		print("==== End of Bus Metrics ====")

		# Optionally, you can still return a DataMessage with empty metrics or adapt downstream usage
		return DataMessage(
			device_id=self.device_id,
			source=SOURCE_TYPE,
			metrics=[]
		)





# Standalone usage example for manual testing.

if __name__ == "__main__":
	# Load environment variables from .env file if present
	load_dotenv()

	# Accept API URL as command-line argument, or use default placeholder
	api_url = sys.argv[1] if len(sys.argv) > 1 else "https://api.nationaltransport.ie/gtfsr/v2/Vehicles?format=json"
	# Optionally accept format param as second argument
	format_param = sys.argv[2] if len(sys.argv) > 2 else None
	# Load keys from environment variables (set in .env or system env)
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
		# Use the default polling interval from config.
		poll_interval = get_collector_config().default_interval
		while True:
			# Generate a new message (fetches and processes API data).
			message = collector.generate_message()
			# Print only the metrics extracted from the feed
			print("--- Metrics Extracted ---")
			import json
			print(json.dumps([m.dict() for m in message.metrics], indent=2))
			print("--- End of Metrics ---")
			time.sleep(poll_interval)
	except KeyboardInterrupt:
		print("\nStopped")
