# AEGLOS Analytics Pro — Installation Guide

This document covers all supported installation methods.

- [Requirements](#requirements)
- [Option 1 — macOS Desktop (DMG)](#option-1--macos-desktop-dmg)
- [Option 2 — Development / Source](#option-2--development--source)
- [Option 3 — Docker Compose](#option-3--docker-compose)
- [Option 4 — Linux Server (systemd + nginx)](#option-4--linux-server-systemd--nginx)
- [Option 5 — Air-Gapped Environments](#option-5--air-gapped-environments)
- [Post-Install Verification](#post-install-verification)
- [Updating](#updating)
- [Uninstalling](#uninstalling)
- [Troubleshooting](#troubleshooting)

---

## Requirements

### All installation methods

| Requirement | Minimum | Recommended |
|---|---|---|
| RAM | 4 GB | 8 GB (16 GB for Qwen model + feeds) |
| Disk | 6 GB free | 12 GB free |
| Network | Required (OSINT feeds are live) | Broadband |

### macOS Desktop

- macOS 12 Monterey or later
- Apple Silicon (arm64) or Intel (x86_64)
- No additional software required — everything is bundled

### Development / Source

- Python 3.10 or later (3.12 recommended)
- macOS, Linux, or Windows (WSL2)
- Git

### Docker

- Docker Engine 24+
- Docker Compose v2 (`docker compose`, not `docker-compose`)
- 8 GB RAM allocated to Docker

### Linux Server

- Ubuntu 22.04 LTS / Debian 12 / RHEL 9 or equivalent
- Python 3.10+
- nginx
- systemd

---

## Option 1 — macOS Desktop (DMG)

The simplest installation. Everything including the Ollama binary is bundled. The Qwen AI model downloads automatically on first launch.

### Install

**1.** Open `AEGLOS-Analytics-Pro-1.0.0-macOS-arm64.dmg`

**2.** Drag **AEGLOS Analytics Pro.app** to the **Applications** folder

**3.** Eject the DMG

### First Launch

Because the app is not notarised, macOS Gatekeeper will block it on the first open.

```
Right-click AEGLOS Analytics Pro.app → Open → Open
```

This is only required once. Subsequent launches work normally from Launchpad or Spotlight.

### First-Run Setup

On the very first launch, the app will:

1. Start the Ollama inference engine (bundled binary, no install required)
2. Start the intelligence API and web server
3. Open your browser to a **First Run Setup** screen
4. Automatically begin downloading the Qwen 2.5 7B model (~4.7 GB)

A progress bar shows download status. When complete, the browser redirects automatically to the intelligence dashboard.

> **Note:** The OSINT intelligence dashboard (feeds, ML analysis, forecasting) is fully operational during the model download — only the AI Convergence Engine requires the model.

### Subsequent Launches

Double-click the app. The browser opens directly to the dashboard. No setup screen.

### Data Location

All persistent data is stored at:

```
~/Library/Application Support/AEGLOS/
├── ollama/
│   ├── models/          Qwen 2.5 7B model files (~4.7 GB)
│   └── ollama.log       Ollama process log
└── state/
    ├── events.json      Cached intelligence events (up to 10,000)
    └── social_config.json  Social source configuration
```

### Stopping the App

Quit from the Dock menu (**Quit AEGLOS Analytics Pro**) or press `Cmd+Q` when the app is focused.

---

## Option 2 — Development / Source

For contributors or operators who need direct access to logs, configuration, and source code.

### Clone and Start

```bash
git clone <repo>
cd aeglos-analytics
./start-dev.sh
```

The script will:
- Create a Python virtual environment (`./venv/`)
- Install all dependencies from `requirements.txt`
- Stop any existing AEGLOS processes
- Start the API server (port 8000) and web server (port 5001)
- Perform an initial intelligence collection

Open **http://localhost:5001/geothreat** for the dashboard.

### Access Points

| Service | URL |
|---|---|
| Intelligence Dashboard | http://localhost:5001/geothreat |
| API (interactive docs) | http://localhost:8000/docs |
| API health check | http://localhost:8000/health |

### Stop

```bash
./stop.sh
```

### Logs

```
logs/api.log    FastAPI server output
logs/web.log    Flask web server output
```

Tail live:

```bash
tail -f logs/api.log
tail -f logs/web.log
```

### AI Engine Setup (optional)

The Ollama binary is not included in the source tree. To enable the local Qwen model:

```bash
# Download the Ollama binary into ./bin/
./tools/fetch_ollama.sh

# Start the API — Ollama will start automatically
./start-dev.sh

# Then trigger the model download from the AI Engine panel in the dashboard,
# or via the API:
curl -X POST http://localhost:8000/api/v1/ollama/pull
```

Alternatively, configure a cloud AI provider:

```bash
# Claude
curl -X POST http://localhost:8000/api/v1/convergence/configure \
  -H "Content-Type: application/json" \
  -d '{"provider":"claude","api_key":"sk-ant-...","preferred":true}'

# OpenAI
curl -X POST http://localhost:8000/api/v1/convergence/configure \
  -H "Content-Type: application/json" \
  -d '{"provider":"openai","api_key":"sk-...","preferred":true}'
```

### Environment Variables

Create a `.env` file in the project root (optional — all have safe defaults):

```bash
# .env
AEGLOS_API_KEY=              # leave empty in dev; auth is disabled
CORS_ORIGINS=                # leave empty in dev; defaults to *
AEGLOS_PERSIST_DIR=          # leave empty; uses ~/Library/Application Support/AEGLOS/state
DEBUG=false
WORKERS=4
```

---

## Option 3 — Docker Compose

The recommended method for production server deployments.

### Prerequisites

```bash
docker --version    # 24.0+
docker compose version  # 2.x
```

### Setup

**1. Clone the repository**

```bash
git clone <repo>
cd aeglos-analytics
```

**2. Create the environment file**

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Required for production
AEGLOS_API_KEY=<generate with: openssl rand -hex 32>

# Set to your actual domain(s) — comma-separated
CORS_ORIGINS=https://aeglos.yourdomain.com

# Optional: adjust if needed
WORKERS=4
```

> **Important:** Keep `.env` out of version control. It is already listed in `.gitignore`.

**3. Start the stack**

```bash
docker compose up -d
```

This starts:

| Container | Port | Role |
|---|---|---|
| `aeglos-api` | 8000 (internal only) | FastAPI intelligence API |
| `aeglos-web` | 5000 | Flask dashboard + API proxy |
| `aeglos-postgres` | 5432 (internal) | PostgreSQL (future persistence layer) |
| `aeglos-redis` | 6379 (internal) | Redis cache |
| `aeglos-nginx` | 80, 443 | Reverse proxy + TLS termination |

> Port 8000 is **not** exposed externally. All traffic routes through the web container proxy at port 5000, which injects the API key server-side.

**4. Check status**

```bash
docker compose ps
docker compose logs -f aeglos-api
```

**5. Verify**

```bash
curl http://localhost:5000/health
```

### TLS / HTTPS

Point your DNS A record to the server, then:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d aeglos.yourdomain.com
```

Certbot will configure nginx and set up automatic renewal.

Self-signed certificate (testing only):

```bash
mkdir -p deployment/certs
openssl req -x509 -nodes -days 365 -newkey rsa:4096 \
  -keyout deployment/certs/key.pem \
  -out deployment/certs/cert.pem \
  -subj "/CN=aeglos-analytics"
```

### Persistent Storage

Events and state persist in the `aeglos_state` Docker volume:

```bash
docker volume inspect aeglos-analytics_aeglos_state
```

### Stopping / Restarting

```bash
docker compose down           # stop containers, keep volumes
docker compose down -v        # stop containers AND delete all data
docker compose restart        # restart all services
docker compose restart aeglos-api   # restart one service
```

---

## Option 4 — Linux Server (systemd + nginx)

For operators who prefer direct system installation without Docker.

### Install System Dependencies

```bash
# Debian / Ubuntu
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip nginx curl git

# RHEL / Rocky
sudo dnf install -y python3.12 python3-pip nginx curl git
```

### Create Application User

```bash
sudo useradd -r -s /bin/false -m -d /opt/aeglos aeglos
```

### Install Application

```bash
sudo git clone <repo> /opt/aeglos/app
sudo chown -R aeglos:aeglos /opt/aeglos

sudo -u aeglos python3.12 -m venv /opt/aeglos/venv
sudo -u aeglos /opt/aeglos/venv/bin/pip install --upgrade pip
sudo -u aeglos /opt/aeglos/venv/bin/pip install -r /opt/aeglos/app/requirements.txt
```

### Configure Environment

```bash
sudo nano /opt/aeglos/app/.env
```

```bash
AEGLOS_API_KEY=<openssl rand -hex 32>
CORS_ORIGINS=https://aeglos.yourdomain.com
AEGLOS_PERSIST_DIR=/opt/aeglos/state
API_HOST=127.0.0.1
WEB_PORT=5001
WORKERS=4
```

```bash
sudo mkdir -p /opt/aeglos/state
sudo chown aeglos:aeglos /opt/aeglos/state
```

### Install systemd Services

```bash
sudo cp /opt/aeglos/app/deployment/aeglos-api.service /etc/systemd/system/
sudo cp /opt/aeglos/app/deployment/aeglos-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aeglos-api aeglos-web
```

### Configure nginx

```bash
sudo cp /opt/aeglos/app/deployment/nginx.conf /etc/nginx/sites-available/aeglos
sudo ln -s /etc/nginx/sites-available/aeglos /etc/nginx/sites-enabled/aeglos
sudo nginx -t
sudo systemctl reload nginx
```

### Verify

```bash
sudo systemctl status aeglos-api
sudo systemctl status aeglos-web
curl http://localhost:5001/health
journalctl -u aeglos-api -f
```

### AI Engine (optional)

```bash
# Download Ollama binary
sudo -u aeglos /opt/aeglos/app/tools/fetch_ollama.sh

# Restart the API to pick it up
sudo systemctl restart aeglos-api

# Trigger model download (runs in background, poll progress)
curl -X POST http://localhost:8000/api/v1/ollama/pull \
  -H "Authorization: Bearer $AEGLOS_API_KEY"

curl http://localhost:8000/api/v1/ollama/pull/progress \
  -H "Authorization: Bearer $AEGLOS_API_KEY"
```

---

## Option 5 — Air-Gapped Environments

For networks with no outbound internet access.

### Constraints

| Component | Requirement |
|---|---|
| OSINT feeds | Internet access required — RSS feeds are the data source |
| Qwen model download | Internet access required for first pull |
| Cloud AI fallback | Internet access required |
| Core intelligence platform | Runs offline once feeds are replaced with local sources |

### Pre-pull the Model (on an internet-connected machine)

```bash
# Pull the model to a local directory
OLLAMA_MODELS=/tmp/aeglos-models ollama pull qwen2.5:7b

# Transfer to air-gapped system
rsync -av /tmp/aeglos-models/ airgapped-host:/opt/aeglos/ollama-models/
```

On the air-gapped system, set:

```bash
# In .env or systemd service EnvironmentFile
OLLAMA_MODELS=/opt/aeglos/ollama-models
```

### Custom Feed Sources

Replace the default internet RSS sources with internal feeds by editing `config.py`:

```python
RSS_SOURCES = [
    {
        "name": "Internal Intel Feed",
        "url": "http://internal.example.com/feed.xml",
        "category": "government",
        "reliability": 0.99,
        "region_hint": None,
    },
    # ...
]
```

---

## Post-Install Verification

Run these checks after any installation method to confirm everything is operational.

### Health Check

```bash
# Via web proxy (use in deployed/Docker environments)
curl http://localhost:5001/health

# Direct API (use in dev/source environments)
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "healthy",
  "service": "AEGLOS Analytics Pro",
  "version": "1.0.0",
  "geothreat_available": true,
  "ml_trained": true
}
```

### Intelligence Pipeline

```bash
# With auth
curl -H "Authorization: Bearer $AEGLOS_API_KEY" \
  http://localhost:8000/api/v1/geothreat/statistics

# Without auth (dev mode / no key set)
curl http://localhost:8000/api/v1/geothreat/statistics
```

A successful response includes `sources_online: 17` and a non-zero `total_events` count (populated after the first ingest cycle, ~30 seconds).

### AI Engine

```bash
curl http://localhost:8000/api/v1/ollama/status \
  -H "Authorization: Bearer $AEGLOS_API_KEY"
```

Look for `"process_running": true` and `"model_present": true`. If the model is absent, trigger a download:

```bash
curl -X POST http://localhost:8000/api/v1/ollama/pull \
  -H "Authorization: Bearer $AEGLOS_API_KEY"

# Poll progress
watch -n 2 'curl -s http://localhost:8000/api/v1/ollama/pull/progress \
  -H "Authorization: Bearer $AEGLOS_API_KEY" | python3 -m json.tool'
```

---

## Updating

### Source / Dev

```bash
git pull
./stop.sh
source venv/bin/activate && pip install -r requirements.txt
./start-dev.sh
```

### Docker

```bash
git pull
docker compose build
docker compose up -d
```

### macOS Desktop

Replace the `.app` in Applications with the new DMG build. Model files and state are preserved in `~/Library/Application Support/AEGLOS/` and are not affected by app updates.

### systemd

```bash
cd /opt/aeglos/app
sudo git pull
sudo -u aeglos /opt/aeglos/venv/bin/pip install -r requirements.txt
sudo systemctl restart aeglos-api aeglos-web
```

---

## Uninstalling

### macOS Desktop

```bash
# Remove the app
rm -rf /Applications/AEGLOS\ Analytics\ Pro.app

# Remove model, state, and logs (optional — ~5 GB)
rm -rf ~/Library/Application\ Support/AEGLOS
```

### Source / Dev

```bash
cd aeglos-analytics
./stop.sh
cd ..
rm -rf aeglos-analytics
```

### Docker

```bash
docker compose down -v           # removes containers and volumes
docker rmi $(docker images | grep aeglos | awk '{print $3}')
```

### systemd

```bash
sudo systemctl disable --now aeglos-api aeglos-web
sudo rm /etc/systemd/system/aeglos-*.service
sudo systemctl daemon-reload
sudo rm -rf /opt/aeglos
```

---

## Troubleshooting

### Dashboard shows OFFLINE

The web server cannot reach the API. Check:

```bash
curl http://localhost:8000/health     # Is the API running?
cat logs/api.log                      # Any startup errors?
```

Common causes:
- API server failed to start (Python import error, port conflict)
- `API_BASE_URL` env var pointing to wrong host in Docker

### 401 Unauthorized on API calls

`AEGLOS_API_KEY` is set in the API environment but not in the web server environment (or vice versa). In Docker, confirm both `aeglos-api` and `aeglos-web` have `AEGLOS_API_KEY` in their `environment` block.

### Port conflict on 5001

Another process is using port 5001. Either kill it or set `WEB_PORT=5002` (or any free port) in your `.env`.

```bash
lsof -i :5001      # identify the conflicting process
```

### Qwen model download stalled

Check Ollama's log:

```bash
# macOS desktop
cat ~/Library/Application\ Support/AEGLOS/ollama/ollama.log

# Dev / source
cat /tmp/ollama.log
```

If the download stalled, restart the app — the pull will resume from the last checkpoint.

### `ssl=False` warning in logs

This is expected for connections to `127.0.0.1:11435` (Ollama, plain HTTP). It is not a security issue — there is no TLS session on a loopback HTTP connection.

### High memory usage

After several days of continuous operation, memory usage may increase. This is expected behaviour from the in-process event buffer (up to 10,000 events × ~1 KB each ≈ 10 MB). The `_seen_ids` set is bounded to the same limit and trimmed after each ingest cycle.

If memory usage exceeds expectations, restart the API server — events are persisted to disk and will reload automatically.

### ML accuracy below target

The ML engine trains on bootstrap data at startup and retrains on real events after each ingest cycle (minimum 50 events required). Accuracy will be low (`~0.25–0.40`) on the first few cycles and improves as the live dataset grows. Target accuracy (`0.997`) reflects performance on the held-out split of real ingested data after several hours of operation.
