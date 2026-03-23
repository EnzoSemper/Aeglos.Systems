# AEGLOS Analytics Pro

**Multi-Domain HUMINT / OSINT / GEOINT Intelligence Fusion Platform**

Real-time open-source intelligence ingestion, ML-based threat classification, 72-hour forecasting, and AI-powered convergence analysis — packaged as a single macOS application or Docker stack.

```
UNCLASSIFIED // FOR OFFICIAL USE ONLY
Uses publicly available open-source data only. No classified systems accessed.
```

---

## Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Intelligence Coverage](#intelligence-coverage)
- [AI Engine](#ai-engine)
- [Deployment](#deployment)
- [Security](#security)
- [Development](#development)

---

## Overview

AEGLOS ingests from 17 verified open-source feeds (RSS, government releases, think tanks, social media) and runs a six-stage pipeline:

1. **Collection** — async concurrent fetch across all sources every 5 minutes
2. **Normalisation** — Unicode normalisation, timestamp standardisation, translation
3. **Classification** — keyword-based region and severity scoring, SHA-1 deduplication
4. **Analysis** — IsolationForest anomaly detection + RandomForest threat classification
5. **Fusion** — story clustering, cross-region correlation, 72-hour Prophet-style forecasting
6. **Dissemination** — REST API, interactive web dashboard, Python SDK

The intelligence dashboard goes live immediately on launch. The AI convergence engine (Qwen 2.5 7B via Ollama) downloads automatically on first run.

---

## Features

| Capability | Detail |
|---|---|
| **OSINT ingestion** | 17 sources — news, government, analysis, social media. Zero API keys required for core feeds. |
| **Region coverage** | 9 regions: Middle East, Eastern Europe, East Asia, Southeast Asia, South Asia, Africa, Americas, Australia & Pacific, Global |
| **Severity classification** | 4 levels (critical / high / moderate / low) via keyword scoring with per-source confidence bands |
| **Story deduplication** | Trigram Jaccard similarity clustering (threshold 0.30) + SHA-1 event dedup |
| **Translation** | Non-English headlines auto-translated before classification |
| **ML analysis** | IsolationForest (anomaly) + RandomForest (5-class threat) — retrained on live data after each ingest cycle |
| **Forecasting** | 72-hour piecewise-linear + Fourier seasonality forecast with confidence intervals |
| **Convergence analysis** | Qwen 2.5 7B (local, offline) identifies cross-regional correlations and strategic implications |
| **AI fallback chain** | Ollama → Claude → OpenAI → Gemini (whichever is configured) |
| **Encryption** | AES-256-GCM, PBKDF2HMAC (100,000 iterations), unique nonce per message |
| **Persistence** | Events and social config survive restarts via JSON state files |
| **Desktop app** | macOS .app bundle — one-click install, one-click launch |
| **Server deployment** | Docker Compose stack with nginx, Postgres, Redis |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Browser / Client                   │
└──────────────────────┬──────────────────────────────┘
                       │  HTTP (same-origin)
┌──────────────────────▼──────────────────────────────┐
│           Flask Web Server  :5001                    │
│   • Serves HTML dashboards                           │
│   • Proxies /api/v1/* to FastAPI (auth injected)     │
└──────────────────────┬──────────────────────────────┘
                       │  HTTP + Bearer token
┌──────────────────────▼──────────────────────────────┐
│           FastAPI API Server  :8000                  │
│   • Auth middleware (AEGLOS_API_KEY)                 │
│   • GeoThreat ingest loop (300s interval)            │
│   • ML engine, encryption, benchmark endpoints      │
└────┬───────────────┬───────────────┬────────────────┘
     │               │               │
┌────▼────┐   ┌──────▼──────┐  ┌────▼───────────┐
│ Ollama  │   │  OSINT      │  │  ML Engine     │
│ :11435  │   │  Pipeline   │  │  IsolationForest│
│ Qwen2.5 │   │  17 sources │  │  RandomForest  │
│ 7B      │   │  + BlueSky  │  │  Prophet       │
└─────────┘   └─────────────┘  └────────────────┘
```

**Key design decisions:**

- The browser never receives the API key — Flask proxies all API calls server-side
- Ollama runs on port 11435 (offset from 11434 to avoid conflicts with system Ollama installs)
- All state persists to `~/Library/Application Support/AEGLOS/state/` (macOS) or `AEGLOS_PERSIST_DIR`
- Auth is disabled when `AEGLOS_API_KEY` is unset — zero-friction for local/desktop use

---

## Quick Start

### macOS Desktop (recommended)

```
1. Open  dist/AEGLOS-Analytics-Pro-1.0.0-macOS-arm64.dmg
2. Drag  AEGLOS Analytics Pro.app  →  Applications
3. Right-click → Open  (required once for unsigned app)
```

**First launch:** A setup screen appears while the Qwen 2.5 7B model downloads (~4.7 GB, one-time). The full intelligence dashboard opens automatically when ready.

**Subsequent launches:** Opens directly to the dashboard. Model is cached locally.

### Development / Source

```bash
git clone <repo> && cd aeglos-analytics
./start-dev.sh
# Dashboard: http://localhost:5001/geothreat
# API:       http://localhost:8000
# Stop:      ./stop.sh
```

### Docker

```bash
cp .env.example .env          # set AEGLOS_API_KEY
docker compose up -d
# Dashboard: http://localhost:5000/geothreat
```

---

## Configuration

All settings are environment variables. Defaults are safe for local development — no configuration required to run.

| Variable | Default | Description |
|---|---|---|
| `AEGLOS_API_KEY` | *(empty)* | Bearer token for API auth. **Empty = auth disabled.** Set for any networked deployment. Generate with `openssl rand -hex 32`. |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins. Example: `https://aeglos.example.com,http://localhost:5001` |
| `AEGLOS_PERSIST_DIR` | `~/Library/Application Support/AEGLOS/state` | Directory for `events.json` and `social_config.json` |
| `API_HOST` | `0.0.0.0` | FastAPI bind address |
| `API_PORT` | `8000` | FastAPI port |
| `WEB_PORT` | `5001` | Flask port |
| `API_BASE_URL` | `http://localhost:8000` | Flask → FastAPI backend URL (set to `http://aeglos-api:8000` in Docker) |
| `WORKERS` | `4` | Uvicorn worker count |
| `DEBUG` | `false` | Enable FastAPI debug/reload mode |

**Generating an API key:**
```bash
openssl rand -hex 32
# → paste into .env as AEGLOS_API_KEY=<value>
```

**Configuring AI fallback providers** (optional — Ollama is primary):
```bash
curl -X POST http://localhost:8000/api/v1/convergence/configure \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AEGLOS_API_KEY" \
  -d '{"provider":"claude","api_key":"sk-ant-...","preferred":true}'
```

---

## API Reference

Base URL: `http://localhost:8000`

Authentication: `Authorization: Bearer <AEGLOS_API_KEY>` (omit if key not set)

Interactive docs: `http://localhost:8000/docs`

### Core

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check — no auth required |
| `GET` | `/metrics` | Pipeline and ML metrics |
| `GET` | `/benchmark` | Throughput and encryption benchmark |
| `POST` | `/ingest` | Batch data ingest |
| `POST` | `/analyze` | ML analysis on data points |
| `POST` | `/encrypt` | AES-256-GCM encrypt |
| `POST` | `/decrypt` | AES-256-GCM decrypt |

### GeoThreat Intelligence

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/geothreat/ingest` | Trigger immediate feed collection |
| `GET` | `/api/v1/geothreat/events` | Recent events (params: `limit`, `region`, `severity`) |
| `GET` | `/api/v1/geothreat/stories` | Deduplicated story clusters (params: `limit`, `region`, `severity`, `translate`) |
| `GET` | `/api/v1/geothreat/statistics` | Event counts, source status, distributions |
| `GET` | `/api/v1/geothreat/sources` | Per-source online/error status |
| `GET` | `/api/v1/geothreat/regions` | Regional analysis and breakdowns |
| `GET` | `/api/v1/geothreat/severity` | Events grouped by severity |
| `GET` | `/api/v1/geothreat/forecast` | 72-hour threat forecast with confidence intervals |
| `GET` | `/api/v1/geothreat/patterns` | Hourly/daily activity patterns |
| `GET` | `/api/v1/geothreat/correlation` | Cross-region Pearson correlation matrix |

### AI / Convergence Engine

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/convergence/query` | Submit analyst query (body: `question`, `window_hours`, `regions`) |
| `GET` | `/api/v1/convergence/status` | Engine status, last engine used, query count |
| `POST` | `/api/v1/convergence/configure` | Set API key for cloud fallback provider |

### Ollama Management

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/ollama/status` | Binary, process, and model status |
| `POST` | `/api/v1/ollama/pull` | Trigger model download |
| `GET` | `/api/v1/ollama/pull/progress` | Poll download progress (pct, bytes, status) |

### Social / Custom Sources

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/social/configure` | Configure BlueSky, Telegram, custom RSS |
| `GET` | `/api/v1/social/status` | Current social source configuration |

---

## Intelligence Coverage

### Sources (17 active)

| Source | Category | Region Bias | Reliability |
|---|---|---|---|
| BBC News — World | News | Global | 0.96 |
| The Guardian — World | News | Global | 0.95 |
| NHK World | News | East Asia | 0.95 |
| Sky News — World | News | Global | 0.94 |
| ABC Australia | News | Australia & Pacific | 0.94 |
| Sydney Morning Herald | News | Australia & Pacific | 0.93 |
| Straits Times | News | Southeast Asia | 0.93 |
| Channel NewsAsia | News | Southeast Asia | 0.92 |
| Foreign Policy | Analysis | Global | 0.92 |
| Al Jazeera | News | Middle East | 0.88 |
| DoD News | Government | Global | 0.99 |
| FBI Press Releases | Government | Americas | 0.99 |
| UN News | Government | Global | 0.96 |
| OCHA | Government | Global | 0.96 |
| Crisis Group (ICG) | Analysis | Global | 0.95 |
| TASS | News | Eastern Europe | 0.72 |
| Xinhua — World | News | East Asia | 0.70 |

Plus: 12 BlueSky OSINT accounts (Reuters, AP, Bellingcat, and others) — optional keyword search with free account.

### Severity Classification

| Level | Triggers |
|---|---|
| **Critical** | Confirmed armed actions, casualties, strikes, WMD, terrorist attacks, assassinations |
| **High** | Troop movements, military operations, state of emergency, sanctions, escalation |
| **Moderate** | Diplomatic tensions, cyber attacks, protests, economic crisis, espionage |
| **Low** | Drug trafficking, minor incidents, arrests, border activity |

---

## AI Engine

The convergence engine runs **Qwen 2.5 7B Instruct (Q4_K_M)** locally via Ollama. It receives a context window of up to 40 recent events (severity-ranked, filtered to a configurable time window) plus the active regional correlation matrix, and produces structured JSON analysis:

```json
{
  "summary": "Executive summary of key convergence",
  "confidence": "high|medium|low",
  "key_connections": [
    {"events": ["...", "..."], "connection": "...", "strength": "strong|moderate|weak"}
  ],
  "strategic_implications": "...",
  "recommended_monitoring": ["indicator 1", "indicator 2"],
  "analyst_note": "caveats, gaps, alternative interpretations"
}
```

**Fallback chain:** If Ollama is unavailable, the engine tries configured API providers in order: preferred provider → Claude (Haiku) → OpenAI (GPT-4o mini) → Gemini (1.5 Flash).

---

## Deployment

See [INSTALL.md](INSTALL.md) for full installation instructions covering:
- macOS desktop (DMG)
- Development / source
- Docker Compose (production)
- Linux server (systemd + nginx)
- Air-gapped environments

---

## Security

| Control | Implementation |
|---|---|
| **API authentication** | Bearer token middleware on all routes except `/health`. Disabled when `AEGLOS_API_KEY` unset. |
| **Key isolation** | Flask proxies all API calls server-side — key never transmitted to browser |
| **Encryption at rest** | AES-256-GCM with PBKDF2HMAC (100K iterations, unique salt + nonce per message) |
| **TLS verification** | All outbound RSS/feed connections verify certificates |
| **CORS** | Configurable per-origin allowlist via `CORS_ORIGINS` |
| **No classified systems** | All data sources are publicly available and unclassified |

**Reporting issues:** Open a GitHub issue tagged `security`. Do not include sensitive operational data in bug reports.

---

## Development

### Prerequisites

- Python 3.10+ (3.12 recommended)
- macOS 12+ or Linux (Windows via WSL2)

### Setup

```bash
git clone <repo> && cd aeglos-analytics
./start-dev.sh          # creates venv, installs deps, starts API + web
./stop.sh               # graceful shutdown
```

### Tests

```bash
source venv/bin/activate
python -m pytest test_suite.py -v
```

### Build macOS DMG

```bash
# Fetch Ollama binary (required once)
./tools/fetch_ollama.sh

# Build
./build/build_macos.sh
# → dist/AEGLOS-Analytics-Pro-1.0.0-macOS-arm64.dmg
```

### Project Structure

```
aeglos-analytics/
├── main.py                 FastAPI server (port 8000)
├── web_server.py           Flask web server + API proxy (port 5001)
├── launcher.py             macOS .app launcher (starts servers, manages first run)
├── config.py               All settings and env var bindings
├── geothreat_pipeline.py   OSINT ingestion, classification, persistence
├── ml_engine.py            IsolationForest + RandomForest
├── prophet_engine.py       72-hour forecasting engine
├── convergence_engine.py   LLM-based correlation analysis
├── bluesky_source.py       BlueSky / AT Protocol collector
├── dedup_translate.py      Story clustering + translation
├── encryption.py           AES-256-GCM module
├── data_pipeline.py        High-performance batch processor
├── ollama_manager.py       Ollama process lifecycle + model pull
├── aeglos_client.py        Python SDK
├── static/
│   ├── geothreat-dashboard.html   Main intelligence dashboard
│   ├── geothreat-live.js          Real-time data connector
│   └── setup.html                 First-run model download screen
├── build/
│   ├── aeglos.spec         PyInstaller spec
│   └── build_macos.sh      DMG build script
└── deployment/             systemd units, nginx config
```

---

*AEGLOS Analytics Pro v1.0 — 5 Eyes / NATO / DoD compatible classification framework*
