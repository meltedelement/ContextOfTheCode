"""Unit tests for TransportCollector per-bus SnapshotMessage generation.

Tests cover:
- generate_message() queues one snapshot per bus
- Metric names in snapshots have no bus prefix or __ separator
- vehicle_id metric value is a float
- Buses without trip updates have 3 metrics (no arrival_delay)
- Empty API response falls back to base class behaviour
- All bus snapshots share the same device_id

All tests mock HTTP and queue — no live infrastructure needed.
"""

from unittest.mock import MagicMock, patch, call

import pytest

from collectors.transport_collector import TransportCollector


# ── Helpers ───────────────────────────────────────────────────────────────────

DEVICE_ID = "transport-test-001"


def _make_vehicle_entity(vehicle_id, lat, lon, trip_id="trip-1"):
    return {
        "id": str(vehicle_id),
        "vehicle": {
            "position": {"latitude": lat, "longitude": lon},
            "trip": {"trip_id": trip_id},
            "vehicle": {"id": vehicle_id},
        },
    }


def _make_trip_entity(trip_id, vehicle_id, delay):
    return {
        "id": f"trip-entity-{trip_id}",
        "trip_update": {
            "trip": {"trip_id": trip_id},
            "vehicle": {"id": vehicle_id},
            "stop_time_update": [
                {"arrival": {"delay": delay}},
            ],
        },
    }


def _make_vehicles_response(*entities):
    return {"entity": list(entities)}


def _make_trips_response(*entities):
    return {"entity": list(entities)}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_queue():
    """Mock upload queue with a put() that always succeeds."""
    q = MagicMock()
    q.put.return_value = True
    return q


@pytest.fixture
def collector():
    """TransportCollector with a dummy config (collection_interval irrelevant)."""
    mock_config = MagicMock()
    mock_config.collection_interval = 30
    mock_config.api_timeout = 10
    with patch("collectors.transport_collector.get_transport_collector_config", return_value=mock_config):
        c = TransportCollector(
            device_id=DEVICE_ID,
            api_url="http://fake-vehicles/",
            tripupdates_url="http://fake-trips/",
        )
    return c


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestGenerateMessagePerBusSnapshot:
    """generate_message() should call export_to_data_model() once per bus."""

    def test_three_buses_queues_three_snapshots(self, collector, mock_queue):
        vehicles = _make_vehicles_response(
            _make_vehicle_entity(1001, 53.34, -6.26, "t1"),
            _make_vehicle_entity(1002, 53.35, -6.27, "t2"),
            _make_vehicle_entity(1003, 53.36, -6.28, "t3"),
        )
        trips = _make_trips_response(
            _make_trip_entity("t1", 1001, 60),
            _make_trip_entity("t2", 1002, 90),
            _make_trip_entity("t3", 1003, 120),
        )

        with patch("collectors.base_data_collector.get_upload_queue", return_value=mock_queue), \
             patch.object(collector, "_query_transport_api", return_value=vehicles), \
             patch.object(collector, "_query_tripupdates_api", return_value=trips):
            collector.generate_message()

        assert mock_queue.put.call_count == 3

    def test_last_bus_count_attribute_set(self, collector, mock_queue):
        vehicles = _make_vehicles_response(
            _make_vehicle_entity(10, 53.0, -6.0),
            _make_vehicle_entity(20, 53.1, -6.1),
        )
        trips = {"entity": []}

        with patch("collectors.base_data_collector.get_upload_queue", return_value=mock_queue), \
             patch.object(collector, "_query_transport_api", return_value=vehicles), \
             patch.object(collector, "_query_tripupdates_api", return_value=trips):
            collector.generate_message()

        assert collector._last_bus_count == 2


class TestMetricNamesAreClean:
    """Snapshots must not contain __ separators or bus_ prefixes in metric names."""

    def test_no_double_underscore_in_metric_names(self, collector, mock_queue):
        vehicles = _make_vehicles_response(
            _make_vehicle_entity(42, 53.0, -6.0),
        )
        trips = {"entity": []}

        captured = []
        mock_queue.put.side_effect = lambda snap: captured.append(snap) or True

        with patch("collectors.base_data_collector.get_upload_queue", return_value=mock_queue), \
             patch.object(collector, "_query_transport_api", return_value=vehicles), \
             patch.object(collector, "_query_tripupdates_api", return_value=trips):
            collector.generate_message()

        for snapshot in captured:
            for metric in snapshot.metrics:
                assert "__" not in metric.metric_name, (
                    f"metric_name {metric.metric_name!r} still contains '__'"
                )

    def test_no_bus_prefix_in_metric_names(self, collector, mock_queue):
        vehicles = _make_vehicles_response(
            _make_vehicle_entity(42, 53.0, -6.0),
        )
        trips = {"entity": []}

        captured = []
        mock_queue.put.side_effect = lambda snap: captured.append(snap) or True

        with patch("collectors.base_data_collector.get_upload_queue", return_value=mock_queue), \
             patch.object(collector, "_query_transport_api", return_value=vehicles), \
             patch.object(collector, "_query_tripupdates_api", return_value=trips):
            collector.generate_message()

        for snapshot in captured:
            for metric in snapshot.metrics:
                assert not metric.metric_name.startswith("bus_"), (
                    f"metric_name {metric.metric_name!r} still has 'bus_' prefix"
                )


class TestVehicleIdMetricIsFloat:
    """vehicle_id metric value must be a float."""

    def test_vehicle_id_value_is_float(self, collector, mock_queue):
        vehicles = _make_vehicles_response(
            _make_vehicle_entity(4219, 53.0, -6.0),
        )
        trips = {"entity": []}

        captured = []
        mock_queue.put.side_effect = lambda snap: captured.append(snap) or True

        with patch("collectors.base_data_collector.get_upload_queue", return_value=mock_queue), \
             patch.object(collector, "_query_transport_api", return_value=vehicles), \
             patch.object(collector, "_query_tripupdates_api", return_value=trips):
            collector.generate_message()

        assert len(captured) == 1
        vid_metrics = [m for m in captured[0].metrics if m.metric_name == "vehicle_id"]
        assert len(vid_metrics) == 1
        assert isinstance(vid_metrics[0].metric_value, float)
        assert vid_metrics[0].metric_value == 4219.0


class TestArrivalDelayOptional:
    """Buses without trip updates should have 3 metrics, not 4."""

    def test_bus_without_trip_update_has_three_metrics(self, collector, mock_queue):
        vehicles = _make_vehicles_response(
            _make_vehicle_entity(99, 53.0, -6.0, trip_id="no-match"),
        )
        trips = {"entity": []}  # no matching trip update

        captured = []
        mock_queue.put.side_effect = lambda snap: captured.append(snap) or True

        with patch("collectors.base_data_collector.get_upload_queue", return_value=mock_queue), \
             patch.object(collector, "_query_transport_api", return_value=vehicles), \
             patch.object(collector, "_query_tripupdates_api", return_value=trips):
            collector.generate_message()

        assert len(captured) == 1
        metric_names = [m.metric_name for m in captured[0].metrics]
        assert "latitude" in metric_names
        assert "longitude" in metric_names
        assert "vehicle_id" in metric_names
        assert "arrival_delay" not in metric_names
        assert len(captured[0].metrics) == 3

    def test_bus_with_trip_update_has_four_metrics(self, collector, mock_queue):
        vehicles = _make_vehicles_response(
            _make_vehicle_entity(99, 53.0, -6.0, trip_id="t-99"),
        )
        trips = _make_trips_response(
            _make_trip_entity("t-99", 99, 180),
        )

        captured = []
        mock_queue.put.side_effect = lambda snap: captured.append(snap) or True

        with patch("collectors.base_data_collector.get_upload_queue", return_value=mock_queue), \
             patch.object(collector, "_query_transport_api", return_value=vehicles), \
             patch.object(collector, "_query_tripupdates_api", return_value=trips):
            collector.generate_message()

        assert len(captured) == 1
        assert len(captured[0].metrics) == 4


class TestEmptyApiResponseFallsBack:
    """None or empty API response should fall back to base class (1 empty snapshot)."""

    def test_none_vehicle_response_queues_one_empty_snapshot(self, collector, mock_queue):
        with patch("collectors.base_data_collector.get_upload_queue", return_value=mock_queue), \
             patch.object(collector, "_query_transport_api", return_value=None), \
             patch.object(collector, "_query_tripupdates_api", return_value=None):
            collector.generate_message()

        assert mock_queue.put.call_count == 1
        snapshot = mock_queue.put.call_args[0][0]
        assert snapshot.metrics == []

    def test_empty_entity_list_queues_one_empty_snapshot(self, collector, mock_queue):
        vehicles = {"entity": []}
        trips = {"entity": []}

        with patch("collectors.base_data_collector.get_upload_queue", return_value=mock_queue), \
             patch.object(collector, "_query_transport_api", return_value=vehicles), \
             patch.object(collector, "_query_tripupdates_api", return_value=trips):
            collector.generate_message()

        assert mock_queue.put.call_count == 1
        snapshot = mock_queue.put.call_args[0][0]
        assert snapshot.metrics == []


class TestDeviceIdReusedAcrossSnapshots:
    """All bus snapshots must share the same device_id."""

    def test_all_snapshots_share_device_id(self, collector, mock_queue):
        vehicles = _make_vehicles_response(
            _make_vehicle_entity(1, 53.0, -6.0),
            _make_vehicle_entity(2, 53.1, -6.1),
            _make_vehicle_entity(3, 53.2, -6.2),
        )
        trips = {"entity": []}

        captured = []
        mock_queue.put.side_effect = lambda snap: captured.append(snap) or True

        with patch("collectors.base_data_collector.get_upload_queue", return_value=mock_queue), \
             patch.object(collector, "_query_transport_api", return_value=vehicles), \
             patch.object(collector, "_query_tripupdates_api", return_value=trips):
            collector.generate_message()

        assert len(captured) == 3
        for snapshot in captured:
            assert snapshot.device_id == DEVICE_ID
