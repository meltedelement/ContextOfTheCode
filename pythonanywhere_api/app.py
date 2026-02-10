"""
Flask API for receiving collector data.

Provides a POST endpoint for collectors to send metrics data.
Validates incoming data and stores it in SQLite database.
"""

from flask import Flask, request, jsonify
from functools import wraps
import logging
from typing import Dict, Any
from pydantic import BaseModel, Field, ValidationError
from typing import List
import db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

# Configuration - CHANGE THESE BEFORE DEPLOYING
API_KEY = "your-secret-key-here"  # IMPORTANT: Change this to a secure random string


# Pydantic models for validation (matching the collector data model)
class MetricEntry(BaseModel):
    """Single metric entry."""
    metric_name: str
    metric_value: float


class DataMessage(BaseModel):
    """Data message from collectors."""
    message_id: str
    timestamp: float
    device_id: str
    source: str
    metrics: List[MetricEntry]


def require_api_key(f):
    """
    Decorator to require API key authentication.

    Checks for 'X-API-Key' header and validates it against the configured API_KEY.
    Returns 401 if key is missing or invalid.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')

        if not api_key:
            logger.warning("Request rejected: Missing API key from %s", request.remote_addr)
            return jsonify({'error': 'Missing API key'}), 401

        if api_key != API_KEY:
            logger.warning("Request rejected: Invalid API key from %s", request.remote_addr)
            return jsonify({'error': 'Invalid API key'}), 401

        return f(*args, **kwargs)

    return decorated_function


@app.route('/api/metrics', methods=['POST'])
@require_api_key
def receive_metrics():
    """
    Receive and store metrics data from collectors.

    Expected JSON payload matching DataMessage schema:
    {
        "message_id": "uuid-string",
        "timestamp": 1642534800.123,
        "device_id": "device-001",
        "source": "local",
        "metrics": [
            {"metric_name": "cpu_usage", "metric_value": 45.2},
            {"metric_name": "ram_usage", "metric_value": 7234.5}
        ]
    }

    Returns:
        JSON response with success/error status
        200: Successfully stored
        400: Invalid data format
        500: Database error
    """
    try:
        # Get JSON data from request
        data = request.get_json()

        if not data:
            logger.warning("Request rejected: No JSON data")
            return jsonify({'error': 'No JSON data provided'}), 400

        # Validate with Pydantic
        try:
            message = DataMessage(**data)
        except ValidationError as e:
            logger.warning("Request rejected: Invalid data format - %s", str(e))
            return jsonify({
                'error': 'Invalid data format',
                'details': e.errors()
            }), 400

        # Convert to dict for database insertion
        message_dict = message.model_dump()

        # Insert into database
        success = db.insert_message(message_dict)

        if success:
            logger.info("Successfully stored message %s from %s",
                       message.message_id, message.device_id)
            return jsonify({
                'status': 'success',
                'message_id': message.message_id,
                'metrics_count': len(message.metrics)
            }), 200
        else:
            logger.error("Failed to store message %s", message.message_id)
            return jsonify({
                'error': 'Failed to store message',
                'message_id': message.message_id
            }), 500

    except Exception as e:
        logger.error("Unexpected error processing request: %s", str(e))
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.

    Returns:
        JSON response with service status and database info
    """
    try:
        message_count = db.get_message_count()
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'total_messages': message_count
        }), 200
    except Exception as e:
        logger.error("Health check failed: %s", str(e))
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500


@app.route('/api/recent', methods=['GET'])
@require_api_key
def get_recent():
    """
    Get recent messages (for debugging/monitoring).

    Query parameters:
        limit: Number of messages to return (default: 10, max: 100)

    Returns:
        JSON array of recent messages with their metrics
    """
    try:
        limit = min(int(request.args.get('limit', 10)), 100)
        messages = db.get_recent_messages(limit)

        return jsonify({
            'count': len(messages),
            'messages': messages
        }), 200

    except Exception as e:
        logger.error("Error fetching recent messages: %s", str(e))
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/', methods=['GET'])
def index():
    """Root endpoint - shows API info."""
    return jsonify({
        'name': 'Metrics Collection API',
        'version': '1.0.0',
        'endpoints': {
            'POST /api/metrics': 'Submit metrics data (requires API key)',
            'GET /api/health': 'Health check',
            'GET /api/recent': 'Get recent messages (requires API key)'
        }
    }), 200


# Initialize database on startup
with app.app_context():
    db.init_db()
    logger.info("Flask app initialized, database ready")


if __name__ == '__main__':
    # For local testing only - PythonAnywhere uses WSGI
    app.run(debug=True, host='0.0.0.0', port=5000)
