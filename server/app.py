"""Flask API server for receiving and serving metrics data."""

import os
import sys
import time

from flask import Flask, request, jsonify
from pydantic import ValidationError
from sqlalchemy import asc

# Add parent directory to path so collectors and sharedUtils are importable
# both in local dev and on PythonAnywhere
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from collectors.base_data_collector import DataMessage
from server.database import Base, engine, get_db
from server.models import Message, Metric
from ContextOfTheCode.sharedUtils.logger.logger import get_logger

logger = get_logger(__name__)

app = Flask(__name__)

# Create tables on startup if they don't already exist
Base.metadata.create_all(bind=engine)
logger.info("Database tables verified/created")


@app.route('/api/metrics', methods=['POST'])
def post_metrics():
    """
    Receive metrics data from a collector and persist to the database.

    Expects a JSON body matching the DataMessage schema:
    {
        "message_id": "uuid",
        "timestamp": 1234567890.123,
        "device_id": "device_identifier",
        "source": "local|mobile|wikipedia",
        "metrics": [
            {"metric_name": "cpu_usage_percent", "metric_value": 45.2},
            ...
        ]
    }
    """
    data = request.get_json()

    if not data:
        logger.warning("POST /api/metrics: no JSON body")
        return jsonify({"error": "No JSON data provided"}), 400

    try:
        message = DataMessage(**data)
    except ValidationError as e:
        logger.warning("POST /api/metrics: validation failed: %s", str(e))
        return jsonify({"error": str(e)}), 400

    try:
        with get_db() as db:
            row = Message(
                message_id=message.message_id,
                device_id=message.device_id,
                source=message.source,
                collected_at=message.timestamp,
                received_at=time.time(),
            )
            db.add(row)
            db.flush()  # Get the primary key before adding children

            for entry in message.metrics:
                db.add(Metric(
                    message_id=message.message_id,
                    metric_name=entry.metric_name,
                    metric_value=entry.metric_value,
                ))

        logger.info(
            "Stored message %s from device=%s source=%s (%d metrics)",
            message.message_id, message.device_id, message.source, len(message.metrics)
        )

        return jsonify({
            "status": "success",
            "message_id": message.message_id,
            "metrics_received": len(message.metrics),
        }), 201

    except Exception as e:
        logger.error("POST /api/metrics: database error: %s", str(e))
        return jsonify({"error": "Failed to store metrics"}), 500


@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    """
    Retrieve historical metrics data.

    Query parameters:
        device_id (optional): Filter by device ID
        source    (optional): Filter by source (local, mobile, wikipedia)
        limit     (optional): Max messages to return, default 100
        since     (optional): Unix timestamp — only return data collected after this time

    Results are ordered by collected_at ascending so the dashboard always
    receives data in measurement order regardless of delivery order.
    """
    try:
        device_id = request.args.get('device_id')
        source    = request.args.get('source')
        limit     = request.args.get('limit', 100, type=int)
        since     = request.args.get('since', type=float)
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid query parameter: {e}"}), 400

    try:
        with get_db() as db:
            query = db.query(Message)

            if device_id:
                query = query.filter(Message.device_id == device_id)
            if source:
                query = query.filter(Message.source == source)
            if since is not None:
                query = query.filter(Message.collected_at > since)

            query = query.order_by(asc(Message.collected_at)).limit(limit)
            messages = query.all()

            result = [
                {
                    "message_id":   m.message_id,
                    "device_id":    m.device_id,
                    "source":       m.source,
                    "collected_at": m.collected_at,
                    "received_at":  m.received_at,
                    "metrics": [
                        {"metric_name": metric.metric_name, "metric_value": metric.metric_value}
                        for metric in m.metrics
                    ],
                }
                for m in messages
            ]

        logger.info(
            "GET /api/metrics: returned %d messages (device=%s, source=%s, since=%s)",
            len(result), device_id, source, since
        )

        return jsonify({
            "status": "success",
            "count":   len(result),
            "messages": result,
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
