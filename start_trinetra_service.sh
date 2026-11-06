#!/bin/bash
echo "[TRINETRA] Starting TRINETRA Full-Stack Server & Cloudflare Tunnel..."

cleanup() {
  echo "[TRINETRA] Stopping services..."
  kill $(jobs -p) 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Start Uvicorn in background with reload
PYTHONPATH=backend backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload >> /tmp/uvicorn.log 2>&1 &
UVICORN_PID=$!
echo "[TRINETRA] Uvicorn started with PID: $UVICORN_PID"

# Wait for local server to be ready
sleep 2
if curl -s http://127.0.0.1:8000/health > /dev/null; then
  echo "[TRINETRA] Local server is healthy on http://0.0.0.0:8000"
else
  echo "[TRINETRA WARNING] Local health check failed, will keep checking..."
fi

# Auto-reconnecting Tunnel Loop (Cloudflare Tunnel)
while true; do
  echo "[TRINETRA] Launching live public tunnel via Cloudflare..."
  .bin/cloudflared tunnel --url http://127.0.0.1:8000 2>&1 | tee /tmp/cloudflared.log

  echo "[TRINETRA] Tunnel disconnected. Retrying in 3s..."
  sleep 3
done
