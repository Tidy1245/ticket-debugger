#!/bin/bash
# Ticket Debugger - Pull & Restart Script
# Usage: bash deploy.sh

set -e

APP_NAME="ticket-debugger"
APP_PORT=9020
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== $APP_NAME deploy ==="

# 1. Pull latest code
echo "[1/3] Pulling latest code..."
git pull origin main

# 2. Kill existing process on port
echo "[2/3] Stopping old process..."
PID=$(lsof -ti:$APP_PORT 2>/dev/null || true)
if [ -n "$PID" ]; then
  kill $PID 2>/dev/null || true
  sleep 1
  echo "  Killed PID $PID"
else
  echo "  No existing process"
fi

# 3. Start server in background
echo "[3/3] Starting server on port $APP_PORT..."
nohup python server.py > server.log 2>&1 &
NEW_PID=$!
sleep 2

# Verify
if kill -0 $NEW_PID 2>/dev/null; then
  echo "=== Done! PID=$NEW_PID, http://0.0.0.0:$APP_PORT ==="
else
  echo "=== FAILED! Check server.log ==="
  tail -5 server.log
  exit 1
fi
