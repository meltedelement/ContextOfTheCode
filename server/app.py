"""Flask API server for receiving and serving metrics data."""

from flask import Flask, request, jsonify
from typing import Dict, Any, List
import sys
import os

# Add parent directory to path to import from collectors
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from collectors.base_data_collector import DataMessage, MetricEntry
from sharedUtils.logger.logger import get_logger

logger = get_logger(__name__)

app = Flask(__name__)


@app.route('/api/metrics', methods=['POST'])
def post_metrics():
    """
    Receive metrics data from collectors.

    Expects JSON body matching DataMessage schema:
    {
        "message_id": "uuid",
        "timestamp": 1234567890.123,
        "device_id": "device_identifier",
        "source": "local|mobile|third_party",
        "metrics": [
            {"metric_name": "cpu_percent", "metric_value": 45.2},
            ...
        ]
    }

    Returns:
        JSON response with success status
    """
    try:
        # Get JSON data from request
        data = request.get_json()

        if not data:
            logger.warning("Received POST request with no JSON body")
            return jsonify({"error": "No JSON data provided"}), 400

        # Validate using Pydantic model
        message = DataMessage(**data)

        logger.info(
            "Received metrics from device=%s, source=%s, metrics_count=%d, message_id=%s",
            message.device_id,
            message.source,
            len(message.metrics),
            message.message_id
        )

        # TODO: Store in database using SQLAlchemy
        # For now, just log the data
        for metric in message.metrics:
            logger.debug("  %s: %s", metric.metric_name, metric.metric_value)

        return jsonify({
            "status": "success",
            "message_id": message.message_id,
            "metrics_received": len(message.metrics)
        }), 201

    except Exception as e:
        logger.error("Error processing POST /api/metrics: %s", str(e))
        return jsonify({"error": str(e)}), 400


@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    """
    Retrieve historical metrics data.

    Query parameters:
        device_id (optional): Filter by device ID
        source (optional): Filter by source (local, mobile, third_party)
        limit (optional): Maximum number of records to return (default: 100)
        since (optional): Unix timestamp - only return metrics after this time

    Returns:
        JSON array of stored metrics
    """
    try:
        # Get query parameters
        device_id = request.args.get('device_id')
        source = request.args.get('source')
        limit = int(request.args.get('limit', 100))
        since = request.args.get('since', type=float)

        logger.info(
            "GET /api/metrics - device_id=%s, source=%s, limit=%d, since=%s",
            device_id, source, limit, since
        )

        # TODO: Query database using SQLAlchemy with filters
        # For now, return empty array
        metrics_data = []

        return jsonify({
            "status": "success",
            "count": len(metrics_data),
            "metrics": metrics_data
        }), 200

    except Exception as e:
        logger.error("Error processing GET /api/metrics: %s", str(e))
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy"}), 200


if __name__ == '__main__':
    logger.info("Starting Flask API server...")
    app.run(host='0.0.0.0', port=5000, debug=True)
