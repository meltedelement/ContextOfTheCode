# Metrics Collection API for PythonAnywhere

Simple Flask API to receive and store metrics data from data collectors.

## Features

- REST API endpoint for receiving metrics
- API key authentication
- SQLite database storage
- Pydantic validation
- Normalized database schema for efficient querying

## Files

- `app.py` - Flask application with API endpoints
- `db.py` - SQLite database management
- `requirements.txt` - Python dependencies
- `README.md` - This file

## Deployment on PythonAnywhere

### 1. Create Account

1. Sign up at [pythonanywhere.com](https://www.pythonanywhere.com)
2. Free tier is sufficient for testing

### 2. Upload Files

Option A - Via Web Interface:
1. Go to "Files" tab
2. Create a new directory (e.g., `metrics_api`)
3. Upload `app.py`, `db.py`, and `requirements.txt`

Option B - Via Git:
1. Go to "Consoles" tab → "Bash"
2. Clone your repository:
   ```bash
   git clone <your-repo-url>
   cd Context-of-the-code-project/pythonanywhere_api
   ```

### 3. Install Dependencies

In the PythonAnywhere Bash console:
```bash
cd ~/metrics_api  # or your directory
pip3.10 install --user -r requirements.txt
```

### 4. Configure API Key

**IMPORTANT**: Change the API key in `app.py`:
```python
API_KEY = "your-secret-key-here"  # Change to a secure random string
```

Generate a secure key:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 5. Set Up Web App

1. Go to "Web" tab → "Add a new web app"
2. Choose "Flask" framework
3. Select Python version (3.10 recommended)
4. Set path to your Flask app: `/home/yourusername/metrics_api/app.py`
5. In "Code" section:
   - Source code: `/home/yourusername/metrics_api`
   - Working directory: `/home/yourusername/metrics_api`

### 6. Configure WSGI File

Edit the WSGI configuration file (linked in Web tab):
```python
import sys
path = '/home/yourusername/metrics_api'
if path not in sys.path:
    sys.path.append(path)

from app import app as application
```

### 7. Reload and Test

1. Click "Reload" button in Web tab
2. Your API will be available at: `https://yourusername.pythonanywhere.com`

Test health endpoint:
```bash
curl https://yourusername.pythonanywhere.com/api/health
```

## Local Testing

Before deploying, test locally:

```bash
# Install dependencies
pip install -r requirements.txt

# Run Flask app
python app.py

# Test in another terminal
curl http://localhost:5000/api/health
```

Test the metrics endpoint:
```bash
curl -X POST http://localhost:5000/api/metrics \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key-here" \
  -d '{
    "message_id": "test-001",
    "timestamp": 1642534800.123,
    "device_id": "local-system-001",
    "source": "local",
    "metrics": [
      {"metric_name": "cpu_usage", "metric_value": 45.2},
      {"metric_name": "ram_usage", "metric_value": 7234.5}
    ]
  }'
```

## API Endpoints

### POST /api/metrics
Submit metrics data (requires API key in `X-API-Key` header)

**Request:**
```json
{
  "message_id": "uuid-string",
  "timestamp": 1642534800.123,
  "device_id": "device-001",
  "source": "local",
  "metrics": [
    {"metric_name": "cpu_usage", "metric_value": 45.2}
  ]
}
```

**Response (200):**
```json
{
  "status": "success",
  "message_id": "uuid-string",
  "metrics_count": 1
}
```

### GET /api/health
Health check (no authentication required)

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "total_messages": 150
}
```

### GET /api/recent?limit=10
Get recent messages (requires API key)

**Response:**
```json
{
  "count": 10,
  "messages": [...]
}
```

## Updating Your Local Collector Config

After deploying, update `sharedUtils/config/config.toml`:

```toml
[upload_queue]
type = "simple"
api_endpoint = "https://yourusername.pythonanywhere.com/api/metrics"
api_key = "your-secret-key-here"  # Same as in app.py
timeout = 10
retry_attempts = 3
```

## Database

SQLite database (`metrics.db`) with two tables:

**messages** - Message metadata
- message_id (PRIMARY KEY)
- timestamp
- device_id
- source
- created_at

**metrics** - Individual metrics
- id (PRIMARY KEY)
- message_id (FOREIGN KEY)
- metric_name
- metric_value

Indexes on timestamp, device_id, message_id, and metric_name for efficient queries.

## Monitoring

View logs on PythonAnywhere:
1. Go to "Web" tab
2. Click "Log files" section
3. Check error log and server log

## Troubleshooting

**500 errors after deployment:**
- Check error logs in Web tab
- Ensure working directory is set correctly
- Verify all dependencies installed

**401 Unauthorized:**
- Check API key matches in both `app.py` and `config.toml`
- Ensure `X-API-Key` header is being sent

**Database errors:**
- Check file permissions in PythonAnywhere
- Ensure working directory has write access
- Run `db.init_db()` manually if needed

## Security Notes

- Keep your API key secret
- Don't commit API keys to version control
- Use environment variables for production
- Consider rate limiting for production use
- PythonAnywhere free tier has limited bandwidth
