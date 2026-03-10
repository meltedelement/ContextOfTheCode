"""Flask API server for receiving and serving metrics data."""

import os
import sys
import time
import uuid

from flask import Flask, request, jsonify
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from server.database import Base, engine, get_db
from server.models import Aggregator, Device, Snapshot, Metric
from sharedUtils.logger.logger import get_logger
from flask_cors import CORS

logger = get_logger(__name__)

DEFAULT_QUERY_LIMIT = 100  # Max snapshots returned by GET /api/metrics when no limit param is given

app = Flask(__name__)
CORS(app)

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
    Register a device under an aggregator (idempotent).

    Body: {"aggregator_id": "uuid", "name": "local-system", "source": "local"}
    Returns existing device_id with 200 if (aggregator_id, name) already registered,
    or new device_id with 201 on first registration.
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

            device = db.query(Device).filter_by(
                aggregator_id=aggregator_id, name=name, source=source
            ).first()
            if device:
                logger.info("Device '%s' (source=%s) already registered: %s", name, source, device.device_id)
                return jsonify({"device_id": device.device_id}), 200

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

    except IntegrityError:
        # Race condition: another request registered the same device concurrently
        with get_db() as db:
            device = db.query(Device).filter_by(
                aggregator_id=aggregator_id, name=name, source=source
            ).first()
            if device:
                return jsonify({"device_id": device.device_id}), 200
        return jsonify({"error": "Failed to register device"}), 500

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
    vehicle_id  = data.get("vehicle_id")
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
                vehicle_id=vehicle_id,
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


@app.route('/api/metrics/batch', methods=['POST'])
def post_metrics_batch():
    """
    Receive a batch of snapshots in a single request and persist all in one transaction.

    Expects a JSON array of SnapshotMessage objects (same schema as POST /api/metrics).
    Items with unknown device_ids or missing fields are skipped; the rest are stored.

    Uses bulk_insert_mappings to insert all rows in two bulk operations (snapshots + metrics)
    instead of individual ORM inserts, and caches device lookups to avoid repeated SELECTs.
    """
    data = request.get_json()

    if not isinstance(data, list):
        logger.warning("POST /api/metrics/batch: body is not a JSON array")
        return jsonify({"error": "Expected a JSON array of snapshots"}), 400

    if not data:
        return jsonify({"status": "success", "snapshots_received": 0}), 200

    try:
        with get_db() as db:
            # Cache device lookups — avoids repeated SELECTs for the same device_id
            known_devices: dict[str, bool] = {}
            snapshot_rows = []
            metric_rows = []
            now = time.time()

            for item in data:
                snapshot_id = item.get("snapshot_id")
                device_id   = item.get("device_id")
                vehicle_id  = item.get("vehicle_id")
                timestamp   = item.get("timestamp")
                metrics     = item.get("metrics", [])

                if not all([snapshot_id, device_id, timestamp is not None]):
                    logger.warning("POST /api/metrics/batch: skipping malformed item (missing fields)")
                    continue

                # Check device existence, hitting the DB only once per unique device_id
                if device_id not in known_devices:
                    device = db.query(Device).filter_by(device_id=device_id).first()
                    known_devices[device_id] = device is not None
                    if not device:
                        logger.warning("POST /api/metrics/batch: unknown device_id=%s", device_id)

                if not known_devices[device_id]:
                    continue

                snapshot_rows.append({
                    "snapshot_id": snapshot_id,
                    "device_id":   device_id,
                    "vehicle_id":  vehicle_id,
                    "collected_at": timestamp,
                    "received_at": now,
                })

                for entry in metrics:
                    metric_rows.append({
                        "snapshot_id": snapshot_id,
                        "metric_name": entry.get("metric_name", ""),
                        "metric_value": float(entry.get("metric_value", 0.0)),
                        "unit": entry.get("unit", ""),
                    })

            # INSERT IGNORE skips duplicate snapshot_ids (e.g. retried batches)
            if snapshot_rows:
                db.execute(
                    text("INSERT IGNORE INTO snapshots (snapshot_id, device_id, vehicle_id, collected_at, received_at) VALUES (:snapshot_id, :device_id, :vehicle_id, :collected_at, :received_at)"),
                    snapshot_rows,
                )
                db.execute(
                    text("INSERT IGNORE INTO metrics (snapshot_id, metric_name, metric_value, unit) VALUES (:snapshot_id, :metric_name, :metric_value, :unit)"),
                    metric_rows,
                )

        logger.info("POST /api/metrics/batch: stored %d/%d snapshots (%d metrics)",
                     len(snapshot_rows), len(data), len(metric_rows))
        return jsonify({"status": "success", "snapshots_received": len(snapshot_rows)}), 201

    except Exception as e:
        logger.error("POST /api/metrics/batch: database error: %s", str(e))
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
            # Build WHERE clauses dynamically so MySQL can use indexes.
            # The previous IS NULL OR pattern prevented index usage, causing
            # full table scans that degraded as the snapshots table grew.
            where_clauses = []
            params: dict = {"limit": limit}

            if device_id:
                where_clauses.append("sn.device_id = :device_id")
                params["device_id"] = device_id
            if source:
                where_clauses.append("d.source = :source")
                params["source"] = source
            if since is not None:
                where_clauses.append("sn.collected_at > :since")
                params["since"] = since

            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Raw SQL with a subquery to apply LIMIT on snapshots before joining metrics.
            # Subquery selects the N most recent matching snapshots (ORDER DESC + LIMIT),
            # then the outer query re-joins and orders ASC for chronological output.
            rows = db.execute(text(f"""
                SELECT
                    s.snapshot_id, s.device_id, s.vehicle_id,
                    s.collected_at, s.received_at,
                    d.name        AS device_name,
                    d.source      AS source,
                    d.aggregator_id,
                    a.name        AS aggregator_name,
                    m.metric_name, m.metric_value, m.unit
                FROM (
                    SELECT sn.snapshot_id, sn.device_id, sn.vehicle_id,
                           sn.collected_at, sn.received_at
                    FROM snapshots sn
                    JOIN devices d ON sn.device_id = d.device_id
                    {where_sql}
                    ORDER BY sn.collected_at DESC
                    LIMIT :limit
                ) s
                JOIN devices     d ON s.device_id      = d.device_id
                JOIN aggregators a ON d.aggregator_id  = a.aggregator_id
                LEFT JOIN metrics m ON s.snapshot_id   = m.snapshot_id
                ORDER BY s.collected_at ASC, s.snapshot_id, m.metric_name
            """), params)

            # Collapse flat rows into per-snapshot dicts
            snapshots_map: dict = {}
            order: list = []
            for row in rows:
                sid = row.snapshot_id
                if sid not in snapshots_map:
                    snapshots_map[sid] = {
                        "snapshot_id":     sid,
                        "device_id":       row.device_id,
                        "vehicle_id":      row.vehicle_id,
                        "device_name":     row.device_name,
                        "source":          row.source,
                        "aggregator_id":   row.aggregator_id,
                        "aggregator_name": row.aggregator_name,
                        "collected_at":    row.collected_at,
                        "received_at":     row.received_at,
                        "metrics":         [],
                    }
                    order.append(sid)
                if row.metric_name is not None:
                    snapshots_map[sid]["metrics"].append({
                        "metric_name":  row.metric_name,
                        "metric_value": row.metric_value,
                        "unit":         row.unit,
                    })

            result = [snapshots_map[sid] for sid in order]

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
    app.run(host='0.0.0.0', port=5001, debug=debug)
