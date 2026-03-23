"""
AEGLOS Analytics Pro - FastAPI Server
HUMINT/OSINT/GEOINT Intelligence Fusion API
Port: 8000
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse

from config import settings
from data_pipeline import pipeline as data_pipeline
from encryption import decrypt as _decrypt
from encryption import encrypt as _encrypt
from encryption import benchmark_encryption, generate_token
from ml_engine import ml_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger("main")

# Try to import GeoThreat pipeline
try:
    from geothreat_pipeline import pipeline as geothreat
    GEOTHREAT_AVAILABLE = True
    logger.info("GeoThreat OSINT pipeline loaded")
except ImportError as exc:
    GEOTHREAT_AVAILABLE = False
    geothreat = None  # type: ignore
    logger.warning("GeoThreat pipeline unavailable: %s", exc)


# ─── Startup / Shutdown ────────────────────────────────────────────────────────

async def _geothreat_loop():
    """Background task: ingest immediately, then every GEOTHREAT_POLL_INTERVAL seconds."""
    await asyncio.sleep(2)  # brief pause to let startup settle
    while True:
        try:
            result = await geothreat.ingest_all_sources()
            logger.info("GeoThreat ingest: %d new events (total %d)",
                        result.get("new_events", 0), result.get("total_events", 0))
        except Exception as exc:
            logger.warning("GeoThreat ingest error: %s", exc)
        await asyncio.sleep(settings.GEOTHREAT_POLL_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s", settings.APP_NAME, settings.VERSION)
    _social_config.update(_load_social_config())
    ml_engine.train()
    logger.info("ML models ready")
    bg_task = None
    if GEOTHREAT_AVAILABLE:
        bg_task = asyncio.create_task(_geothreat_loop())
        logger.info("GeoThreat background ingest started (interval=%ds)",
                    settings.GEOTHREAT_POLL_INTERVAL)
    # Update convergence engine Ollama URL to match manager's port
    if CONVERGENCE_AVAILABLE:
        import convergence_engine as _ce
        from ollama_manager import OLLAMA_HOST, OLLAMA_PORT
        _ce.OLLAMA_BASE = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
    yield
    if bg_task:
        bg_task.cancel()
    logger.info("Shutting down")


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Multi-Domain HUMINT/OSINT/GEOINT Intelligence Fusion Platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Auth middleware ──────────────────────────────────────────────────────────

_UNPROTECTED = {"/health", "/docs", "/openapi.json", "/redoc"}

class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        if not settings.AEGLOS_API_KEY or request.url.path in _UNPROTECTED:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {settings.AEGLOS_API_KEY}":
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)


app.add_middleware(_AuthMiddleware)


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    data: list[dict] = Field(..., min_length=1, max_length=100_000)

class AnalyzeRequest(BaseModel):
    data: list[dict] = Field(..., min_length=1, max_length=10_000)

class EncryptRequest(BaseModel):
    plaintext: str = Field(..., max_length=1_000_000)
    password: str = Field(..., min_length=8)

class DecryptRequest(BaseModel):
    payload: dict
    password: str = Field(..., min_length=8)


# ─── Standard Endpoints ───────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "geothreat_available": GEOTHREAT_AVAILABLE,
        "ml_trained": ml_engine._trained,
    }


@app.post("/ingest")
async def ingest(req: IngestRequest):
    result = await data_pipeline.ingest_batch(req.data)
    return result


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    result = ml_engine.analyze(req.data)
    return result



@app.post("/encrypt")
async def encrypt_endpoint(req: EncryptRequest):
    try:
        payload = _encrypt(req.plaintext, req.password)
        return {
            "status": "encrypted",
            "payload": payload,
            "token": generate_token(),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/decrypt")
async def decrypt_endpoint(req: DecryptRequest):
    try:
        plaintext = _decrypt(req.payload, req.password)
        return {"status": "decrypted", "plaintext": plaintext}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Decryption failed: {exc}") from exc


@app.get("/metrics")
async def metrics():
    return {
        "pipeline": data_pipeline.get_metrics(),
        "ml": ml_engine.get_model_info(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/benchmark")
async def benchmark(points: int = Query(100_000, ge=1000, le=10_000_000)):
    result = await data_pipeline.benchmark(num_points=points)
    enc_bench = benchmark_encryption(iterations=10)
    return {
        "ingestion": result,
        "encryption": enc_bench,
        "system": settings.APP_NAME,
    }


# ─── GeoThreat Endpoints ──────────────────────────────────────────────────────

def _require_geothreat():
    if not GEOTHREAT_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="GeoThreat pipeline not available (missing dependencies: aiohttp, feedparser)",
        )


@app.post(f"{settings.API_PREFIX}/geothreat/ingest")
async def geothreat_ingest():
    _require_geothreat()
    result = await geothreat.ingest_all_sources()
    # Retrain ML engine on real events after each ingest cycle (guarded against concurrency)
    global _ml_training
    events = geothreat.get_recent_events(limit=2000)
    if len(events) >= 50 and not _ml_training:
        _ml_training = True
        def _train_and_reset():
            global _ml_training
            try:
                ml_engine.train(events)
            finally:
                _ml_training = False
        asyncio.get_running_loop().run_in_executor(None, _train_and_reset)
    return result


@app.get(f"{settings.API_PREFIX}/geothreat/events")
async def geothreat_events(
    limit: int = Query(50, ge=1, le=500),
    region: str = Query("", description="Filter by region name"),
    severity: str = Query("", description="Filter by severity: low/moderate/high/critical"),
):
    _require_geothreat()
    events = geothreat.get_recent_events(limit=limit, region=region, severity=severity)
    return {
        "count": len(events),
        "events": events,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get(f"{settings.API_PREFIX}/geothreat/statistics")
async def geothreat_statistics():
    _require_geothreat()
    return geothreat.get_statistics()


@app.get(f"{settings.API_PREFIX}/geothreat/sources")
async def geothreat_sources():
    _require_geothreat()
    return {
        "sources": geothreat.get_sources_status(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get(f"{settings.API_PREFIX}/geothreat/regions")
async def geothreat_regions():
    _require_geothreat()
    return {
        "regions": geothreat.get_regional_analysis(),
        "by_region": geothreat.get_events_by_region(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get(f"{settings.API_PREFIX}/geothreat/severity")
async def geothreat_severity():
    _require_geothreat()
    return {
        "by_severity": geothreat.get_events_by_severity(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get(f"{settings.API_PREFIX}/geothreat/forecast")
async def geothreat_forecast():
    _require_geothreat()
    return geothreat.get_forecast()


@app.get(f"{settings.API_PREFIX}/geothreat/patterns")
async def geothreat_patterns():
    _require_geothreat()
    return geothreat.get_patterns()


@app.get(f"{settings.API_PREFIX}/geothreat/correlation")
async def geothreat_correlation():
    _require_geothreat()
    return geothreat.get_correlation()


@app.get(f"{settings.API_PREFIX}/geothreat/stories")
async def geothreat_stories(
    limit: int = Query(100, ge=1, le=500),
    region: str = Query("", description="Filter by region name"),
    severity: str = Query("", description="Filter by severity"),
    translate: bool = Query(True, description="Translate non-English headlines to English"),
):
    """
    Deduplicated story feed. Events reporting the same story are merged into
    a single entry with multiple source attributions. Non-English headlines
    are translated to English automatically.
    """
    _require_geothreat()
    stories = geothreat.get_stories(limit=limit, region=region, severity=severity, translate=translate)
    return {
        "count": len(stories),
        "stories": stories,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Social Media Config Endpoint ────────────────────────────────────────────

class SocialConfigRequest(BaseModel):
    platform: str
    enabled: bool = True
    # Twitter
    bearer_token: str = ""
    accounts: list[str] = []
    # BlueSky
    app_password: str = ""
    extra_handles: list[str] = []
    identifier: str = ""
    # Telegram
    bot_token: str = ""
    channels: list[str] = []
    # Custom RSS
    feeds: list[dict] = []

_ml_training: bool = False  # guard against concurrent retraining


def _load_social_config() -> dict:
    import json
    try:
        with open(settings.PERSIST_SOCIAL_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_social_config() -> None:
    import json, os
    os.makedirs(os.path.dirname(settings.PERSIST_SOCIAL_FILE), exist_ok=True)
    try:
        with open(settings.PERSIST_SOCIAL_FILE, "w") as f:
            json.dump(_social_config, f)
    except Exception as exc:
        logger.warning("Failed to save social config: %s", exc)


# Social config — persisted across restarts
_social_config: dict[str, Any] = {}


@app.post("/api/v1/social/configure")
async def social_configure(req: SocialConfigRequest):
    _social_config[req.platform] = req.dict()
    _save_social_config()
    # Apply BlueSky extra_handles immediately if provided
    if req.platform == 'bluesky' and GEOTHREAT_AVAILABLE and req.extra_handles:
        try:
            from bluesky_source import MONITORED_ACCOUNTS
            existing_handles = {a['handle'] for a in MONITORED_ACCOUNTS}
            for handle in req.extra_handles:
                if handle and handle not in existing_handles:
                    MONITORED_ACCOUNTS.append({
                        "handle": handle,
                        "category": "osint",
                        "reliability": 0.75,
                    })
        except Exception as exc:
            logger.warning("Failed to add BlueSky handles: %s", exc)
    return {"status": "configured", "platform": req.platform}


@app.get("/api/v1/social/status")
async def social_status():
    return {"platforms": _social_config}


# ─── Convergence Intelligence Engine ─────────────────────────────────────────

try:
    from convergence_engine import convergence_engine
    CONVERGENCE_AVAILABLE = True
    logger.info("Convergence Intelligence Engine loaded")
except ImportError as exc:
    convergence_engine = None  # type: ignore
    CONVERGENCE_AVAILABLE = False
    logger.warning("Convergence engine unavailable: %s", exc)


class ConvergenceQueryRequest(BaseModel):
    question: str = Field(..., min_length=4, max_length=2000)
    window_hours: int = Field(12, ge=1, le=72)
    regions: list[str] = []


class ConvergenceConfigRequest(BaseModel):
    provider: str           # claude | openai | gemini
    api_key: str = ""
    preferred: bool = False


def _require_convergence():
    if not CONVERGENCE_AVAILABLE or not GEOTHREAT_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Convergence engine or GeoThreat pipeline unavailable",
        )


@app.post("/api/v1/convergence/query")
async def convergence_query(req: ConvergenceQueryRequest):
    _require_convergence()
    events = geothreat.get_recent_events(limit=500)
    # Filter by requested regions if supplied
    if req.regions:
        events = [e for e in events if e.get("region") in req.regions]
    correlation_data = geothreat.get_correlation()
    result = await convergence_engine.query(
        question=req.question,
        events=events,
        correlation_data=correlation_data,
        window_hours=req.window_hours,
    )
    return result


@app.get("/api/v1/convergence/status")
async def convergence_status():
    if not CONVERGENCE_AVAILABLE:
        return {"available": False}
    status = await convergence_engine.status()
    status["available"] = True
    return status


@app.post("/api/v1/convergence/configure")
async def convergence_configure(req: ConvergenceConfigRequest):
    _require_convergence()
    convergence_engine.configure(
        provider=req.provider,
        api_key=req.api_key,
        preferred=req.preferred,
    )
    return {"status": "configured", "provider": req.provider}


# ─── Ollama Management ────────────────────────────────────────────────────────

try:
    from ollama_manager import ollama_manager
    OLLAMA_MGR_AVAILABLE = True
    logger.info("Ollama manager loaded")
except ImportError as exc:
    ollama_manager = None  # type: ignore
    OLLAMA_MGR_AVAILABLE = False
    logger.warning("Ollama manager unavailable: %s", exc)


@app.get("/api/v1/ollama/status")
async def ollama_status():
    if not OLLAMA_MGR_AVAILABLE:
        return {"binary_found": False, "process_running": False, "model_present": False}
    return await ollama_manager.status()


@app.post("/api/v1/ollama/pull")
async def ollama_pull():
    if not OLLAMA_MGR_AVAILABLE:
        raise HTTPException(status_code=503, detail="Ollama manager not available")
    started = await ollama_manager.pull_model()
    return {"started": started, "model": ollama_manager.OLLAMA_MODEL if hasattr(ollama_manager, 'OLLAMA_MODEL') else "qwen2.5:7b"}


@app.get("/api/v1/ollama/pull/progress")
async def ollama_pull_progress():
    if not OLLAMA_MGR_AVAILABLE:
        return {"pull_active": False, "pull_done": False, "pull_pct": 0}
    s = await ollama_manager.status()
    return {
        "pull_active":    s["pull_active"],
        "pull_done":      s["pull_done"],
        "pull_status":    s["pull_status"],
        "pull_pct":       s["pull_pct"],
        "pull_completed": s["pull_completed"],
        "pull_total":     s["pull_total"],
        "pull_error":     s["pull_error"],
        "model_present":  s["model_present"],
    }


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
