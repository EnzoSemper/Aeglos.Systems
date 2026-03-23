#!/usr/bin/env bash
# AEGLOS Analytics Pro — Development Startup Script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_DIR="$SCRIPT_DIR/.pids"
mkdir -p "$PID_DIR"

LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
BOLD='\033[1m'

echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║          AEGLOS ANALYTICS PRO — Starting Up              ║${NC}"
echo -e "${CYAN}${BOLD}║     Multi-Domain HUMINT/OSINT/GEOINT Fusion Platform     ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Check Python ──────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo -e "${RED}ERROR: python3 not found. Install Python 3.10+${NC}"
  exit 1
fi
PYTHON=$(command -v python3)
echo -e "${GREEN}✓${NC} Python: $($PYTHON --version)"

# ── Virtual environment ───────────────────────────────────────────────────────
VENV="$SCRIPT_DIR/venv"
if [ ! -d "$VENV" ]; then
  echo -e "${YELLOW}→${NC} Creating virtual environment..."
  $PYTHON -m venv "$VENV"
fi
source "$VENV/bin/activate"
echo -e "${GREEN}✓${NC} Virtual environment active"

# ── Install dependencies ──────────────────────────────────────────────────────
echo -e "${YELLOW}→${NC} Installing dependencies (this may take a minute on first run)..."
pip install -q -r requirements.txt
echo -e "${GREEN}✓${NC} Dependencies installed"

# ── Stop existing servers ─────────────────────────────────────────────────────
for pidfile in "$PID_DIR"/*.pid; do
  [ -f "$pidfile" ] || continue
  pid=$(cat "$pidfile")
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo -e "${YELLOW}→${NC} Stopped existing process $pid"
  fi
  rm -f "$pidfile"
done

# ── Start API server ──────────────────────────────────────────────────────────
echo -e "${YELLOW}→${NC} Starting API server on port 8000..."
nohup python main.py >"$LOG_DIR/api.log" 2>&1 &
API_PID=$!
echo "$API_PID" > "$PID_DIR/api.pid"
sleep 2

if kill -0 "$API_PID" 2>/dev/null; then
  echo -e "${GREEN}✓${NC} API server started (PID: $API_PID)"
else
  echo -e "${RED}✗${NC} API server failed to start. Check logs/api.log"
  echo "--- Last 20 lines of api.log ---"
  tail -20 "$LOG_DIR/api.log" || true
  exit 1
fi

# ── Start Web server ──────────────────────────────────────────────────────────
echo -e "${YELLOW}→${NC} Starting Web server on port 5000..."
nohup python web_server.py >"$LOG_DIR/web.log" 2>&1 &
WEB_PID=$!
echo "$WEB_PID" > "$PID_DIR/web.pid"
sleep 1

if kill -0 "$WEB_PID" 2>/dev/null; then
  echo -e "${GREEN}✓${NC} Web server started (PID: $WEB_PID)"
else
  echo -e "${RED}✗${NC} Web server failed to start. Check logs/web.log"
  tail -20 "$LOG_DIR/web.log" || true
  exit 1
fi

# ── Wait for API to be healthy ─────────────────────────────────────────────────
echo -e "${YELLOW}→${NC} Waiting for API to become healthy..."
for i in {1..20}; do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} API is healthy"
    break
  fi
  if [ $i -eq 20 ]; then
    echo -e "${YELLOW}⚠${NC} API health check timed out (still starting...)"
  fi
  sleep 1
done

# ── Trigger initial GeoThreat ingest ─────────────────────────────────────────
echo -e "${YELLOW}→${NC} Triggering initial intelligence collection..."
curl -sf -X POST http://localhost:8000/api/v1/geothreat/ingest >/dev/null 2>&1 && \
  echo -e "${GREEN}✓${NC} Initial OSINT collection started" || \
  echo -e "${YELLOW}⚠${NC} Initial collection queued (API still warming up)"

echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║               AEGLOS ANALYTICS PRO — LIVE               ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Web Interface:${NC}   ${CYAN}http://localhost:5000${NC}"
echo -e "  ${BOLD}GeoThreat:${NC}       ${CYAN}http://localhost:5000/geothreat${NC}"
echo -e "  ${BOLD}Analytics:${NC}       ${CYAN}http://localhost:5000/dashboard${NC}"
echo -e "  ${BOLD}Demo Mode:${NC}       ${CYAN}http://localhost:5000/demo${NC}"
echo -e "  ${BOLD}API:${NC}             ${CYAN}http://localhost:8000${NC}"
echo -e "  ${BOLD}API Docs:${NC}        ${CYAN}http://localhost:8000/docs${NC}"
echo ""
echo -e "  ${BOLD}Logs:${NC}  logs/api.log  |  logs/web.log"
echo -e "  ${BOLD}Stop:${NC}  ./stop.sh"
echo ""
echo -e "${GREEN}Intelligence feeds will update every 30 seconds in LIVE MODE.${NC}"
echo ""
