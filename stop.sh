#!/usr/bin/env bash
# AEGLOS Analytics Pro — Stop Script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$SCRIPT_DIR/.pids"

echo "Stopping AEGLOS Analytics Pro servers..."

stopped=0
for pidfile in "$PID_DIR"/*.pid; do
  [ -f "$pidfile" ] || continue
  name=$(basename "$pidfile" .pid)
  pid=$(cat "$pidfile")
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null && echo "  ✓ Stopped $name (PID $pid)" || echo "  ✗ Could not stop $name"
    stopped=$((stopped+1))
  else
    echo "  — $name not running"
  fi
  rm -f "$pidfile"
done

# Also kill by port as fallback
for port in 8000 5000; do
  pid=$(lsof -ti ":$port" 2>/dev/null || true)
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null && echo "  ✓ Stopped process on port $port" || true
    stopped=$((stopped+1))
  fi
done

[ $stopped -eq 0 ] && echo "No running servers found." || echo "Done."
