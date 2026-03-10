#!/bin/bash
# Restart the gunicorn server for ContextOfTheCode
# Run from: /home/student/Project/ContextOfTheCode

PROJECT_DIR="/home/student/Project/ContextOfTheCode"
VENV="/home/student/Project/venv"
GUNICORN="$VENV/bin/gunicorn"
LOG_FILE="$PROJECT_DIR/logs/gunicorn.log"

cd "$PROJECT_DIR" || { echo "Project directory not found: $PROJECT_DIR"; exit 1; }

# Kill existing gunicorn workers
echo "Stopping gunicorn..."
pkill -f "gunicorn.*server.app:app"
sleep 2

# Confirm stopped
if pgrep -f "gunicorn.*server.app:app" > /dev/null; then
    echo "Warning: gunicorn still running, sending SIGKILL..."
    pkill -9 -f "gunicorn.*server.app:app"
    sleep 1
fi

echo "Starting gunicorn..."
mkdir -p "$PROJECT_DIR/logs"
nohup "$GUNICORN" -w 4 -b 0.0.0.0:5000 server.app:app \
    --access-logfile "$LOG_FILE" \
    --error-logfile "$LOG_FILE" \
    >> "$LOG_FILE" 2>&1 &

sleep 2

if pgrep -f "gunicorn.*server.app:app" > /dev/null; then
    echo "Gunicorn started successfully (PID: $(pgrep -f 'gunicorn.*server.app:app' | head -1))"
else
    echo "Error: gunicorn failed to start. Check $LOG_FILE"
    exit 1
fi
