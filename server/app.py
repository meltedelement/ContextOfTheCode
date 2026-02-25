"""Flask API server for receiving and serving metrics data."""

import os
import sys
import time
import uuid

from flask import Flask, request, jsonify
from sqlalchemy.exc import IntegrityError
from sqlalchemy import asc

from server.database import Base, engine, get_db
from server.models import Aggregator, Device, Snapshot, Metric
from sharedUtils.logger.logger import get_logger

logger = get_logger(__name__)

DEFAULT_QUERY_LIMIT = 100  # Max snapshots returned by GET /api/metrics when no limit param is given

app = Flask(__name__)

# Create tables on startup if they don't already exist
Base.metadata.create_all(bind=engine)
logger.info("Database tables verified/created")


@app.route('/aggregators', methods=['POST'])
def post_aggregators():
    """
    Register an aggregator by name (idempotent).

    Body: {"name": "SavageLaptop"}
    Returns existing aggregator_id with 200 if name already registered,
    or new aggregator_id with 201 on first registration.
    """
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Missing 'name' field"}), 400

    name = data["name"]

    try:
        with get_db() as db:
            aggregator = db.query(Aggregator).filter_by(name=name).first()
            if aggregator:
                logger.info("Aggregator '%s' already registered: %s", name, aggregator.aggregator_id)
                return jsonify({"aggregator_id": aggregator.aggregator_id}), 200

            new_id = str(uuid.uuid4())
            db.add(Aggregator(aggregator_id=new_id, name=name))

        logger.info("Registered new aggregator '%s': %s", name, new_id)
        return jsonify({"aggregator_id": new_id}), 201

    except IntegrityError:
        # Race condition: another request registered the same name concurrently
        with get_db() as db:
            aggregator = db.query(Aggregator).filter_by(name=name).first()
            if aggregator:
                return jsonify({"aggregator_id": aggregator.aggregator_id}), 200
        return jsonify({"error": "Failed to register aggregator"}), 500

    except Exception as e:
        logger.error("POST /aggregators: database error: %s", str(e))
        return jsonify({"error": "Failed to register aggregator"}), 500


@app.route('/devices', methods=['POST'])
def post_devices():
    """
    Register a device under an aggregator.

    Body: {"aggregator_id": "uuid", "name": "local-system", "source": "local"}
    Returns {"device_id": "server-generated-uuid"} with 201.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400

    aggregator_id = data.get("aggregator_id")
    name          = data.get("name")
    source        = data.get("source")

    if not all([aggregator_id, name, source]):
        return jsonify({"error": "Missing required fields: aggregator_id, name, source"}), 400

    try:
        with get_db() as db:
            aggregator = db.query(Aggregator).filter_by(aggregator_id=aggregator_id).first()
            if not aggregator:
                return jsonify({"error": f"Aggregator '{aggregator_id}' not found"}), 404

            device_id = str(uuid.uuid4())
            db.add(Device(
                device_id=device_id,
                aggregator_id=aggregator_id,
                name=name,
                source=source,
            ))

        logger.info("Registered device '%s' (source=%s) under aggregator %s: %s",
                    name, source, aggregator_id, device_id)
        return jsonify({"device_id": device_id}), 201

    except Exception as e:
        logger.error("POST /devices: database error: %s", str(e))
        return jsonify({"error": "Failed to register device"}), 500


@app.route('/api/metrics', methods=['POST'])
def post_metrics():
    """
    Receive a snapshot of metrics from a collector and persist to the database.

    Expects a JSON body matching the SnapshotMessage schema:
    {
        "snapshot_id": "uuid",
        "timestamp": 1234567890.123,
        "device_id": "server-issued-uuid",
        "metrics": [
            {"metric_name": "cpu_usage_percent", "metric_value": 45.2, "unit": "%"},
            ...
        ]
    }
    """
    data = request.get_json()

    if not data:
        logger.warning("POST /api/metrics: no JSON body")
        return jsonify({"error": "No JSON data provided"}), 400

    snapshot_id = data.get("snapshot_id")
    device_id   = data.get("device_id")
    timestamp   = data.get("timestamp")
    metrics     = data.get("metrics", [])

    if not all([snapshot_id, device_id, timestamp is not None]):
        return jsonify({"error": "Missing required fields: snapshot_id, device_id, timestamp"}), 400

    try:
        with get_db() as db:
            device = db.query(Device).filter_by(device_id=device_id).first()
            if not device:
                logger.warning("POST /api/metrics: unknown device_id=%s", device_id)
                return jsonify({"error": f"Device '{device_id}' not found"}), 404

            snapshot = Snapshot(
                snapshot_id=snapshot_id,
                device_id=device_id,
                collected_at=timestamp,
                received_at=time.time(),
            )
            db.add(snapshot)
            db.flush()

            for entry in metrics:
                db.add(Metric(
                    snapshot_id=snapshot_id,
                    metric_name=entry.get("metric_name", ""),
                    metric_value=float(entry.get("metric_value", 0.0)),
                    unit=entry.get("unit", ""),
                ))

        logger.info(
            "Stored snapshot %s from device=%s (%d metrics)",
            snapshot_id, device_id, len(metrics)
        )

        return jsonify({
            "status": "success",
            "snapshot_id": snapshot_id,
            "metrics_received": len(metrics),
        }), 201

    except Exception as e:
        logger.error("POST /api/metrics: database error: %s", str(e))
        return jsonify({"error": "Failed to store metrics"}), 500


@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    """
    Retrieve historical metrics data.

    Query parameters:
        device_id (optional): Filter by device UUID
        source    (optional): Filter by source (local, wikipedia) — joined through Device
        limit     (optional): Max snapshots to return, default 100
        since     (optional): Unix timestamp — only return data collected after this time

    Results are ordered by collected_at ascending so the dashboard always
    receives data in measurement order regardless of delivery order.
    """
    try:
        device_id = request.args.get('device_id')
        source    = request.args.get('source')
        limit     = request.args.get('limit', DEFAULT_QUERY_LIMIT, type=int)
        since     = request.args.get('since', type=float)
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid query parameter: {e}"}), 400

    try:
        with get_db() as db:
            query = db.query(Snapshot)

            if device_id:
                query = query.filter(Snapshot.device_id == device_id)
            if source:
                query = query.join(Device).filter(Device.source == source)
            if since is not None:
                query = query.filter(Snapshot.collected_at > since)

            query = query.order_by(asc(Snapshot.collected_at)).limit(limit)
            snapshots = query.all()

            result = [
                {
                    "snapshot_id":  s.snapshot_id,
                    "device_id":    s.device_id,
                    "source":       s.device.source,
                    "collected_at": s.collected_at,
                    "received_at":  s.received_at,
                    "metrics": [
                        {
                            "metric_name":  m.metric_name,
                            "metric_value": m.metric_value,
                            "unit":         m.unit,
                        }
                        for m in s.metrics
                    ],
                }
                for s in snapshots
            ]

        logger.info(
            "GET /api/metrics: returned %d snapshots (device=%s, source=%s, since=%s)",
            len(result), device_id, source, since
        )

        return jsonify({
            "status":    "success",
            "count":     len(result),
            "snapshots": result,
        }), 200

    except Exception as e:
        logger.error("GET /api/metrics: database error: %s", str(e))
        return jsonify({"error": "Failed to retrieve metrics"}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy"}), 200


if __name__ == '__main__':
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    logger.info("Starting Flask API server (debug=%s)...", debug)
    app.run(host='0.0.0.0', port=5000, debug=debug)
