"""
AEGLOS Analytics Pro — Convergence Intelligence Engine
Local Qwen2.5:7b via Ollama → Claude / OpenAI / Gemini API fallback
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import aiohttp

logger = logging.getLogger("convergence")

OLLAMA_BASE  = "http://localhost:11435"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT = 120

SYSTEM_PROMPT = """You are AEGLOS, an expert geopolitical intelligence analyst specialising in open-source intelligence (OSINT). You identify correlations, causal chains, and strategic patterns across concurrent global events.

Guidelines:
- Distinguish likely connections from coincidences
- Apply strategic frameworks: escalation ladders, diversionary operations, coordinated campaigns, economic coercion
- Note second and third-order effects
- Flag confidence honestly — "unknown" is a valid answer

Always respond in this exact JSON format (no markdown, no code fences):
{
  "summary": "2-3 sentence executive summary of key convergence",
  "confidence": "high|medium|low",
  "key_connections": [
    {"events": ["headline A", "headline B"], "connection": "explanation of link", "strength": "strong|moderate|weak"}
  ],
  "strategic_implications": "what this convergence means at a strategic level",
  "recommended_monitoring": ["specific indicator 1", "indicator 2"],
  "analyst_note": "caveats, data gaps, or alternative interpretations"
}"""


# ── Context builder ────────────────────────────────────────────────────────────

SEV_WEIGHT = {"critical": 4, "high": 3, "moderate": 2, "low": 1}

def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def build_context(events: list[dict], correlation_data: dict, question: str, window_hours: int = 12) -> str:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)

    recent = [e for e in events if _parse_ts(e.get("timestamp", "")) >= cutoff]
    recent.sort(key=lambda e: (SEV_WEIGHT.get(e.get("severity", "low"), 1),
                                _parse_ts(e.get("timestamp", "")).timestamp()), reverse=True)
    recent = recent[:40]

    event_lines = []
    for e in recent:
        ts      = e.get("timestamp", "")[:16].replace("T", " ")
        sev     = e.get("severity", "low").upper()
        region  = e.get("region", "Global")
        headline = (e.get("headline") or e.get("title", ""))[:120]
        n_src   = e.get("event_count", 1)
        src_tag = f" [{n_src}src]" if n_src > 1 else ""
        event_lines.append(f"  [{ts}][{sev}][{region}]{src_tag} {headline}")

    events_block = "\n".join(event_lines) or "  (no events in window)"

    # Correlation highlights (|r| ≥ 0.5)
    corr_lines = []
    matrix  = correlation_data.get("correlation_matrix", [])
    regions = correlation_data.get("regions", [])
    for row in matrix:
        r1 = row.get("region", "")
        for i, val in enumerate(row.get("values", [])):
            if i < len(regions):
                r2 = regions[i]
                if r1 < r2 and abs(val) >= 0.5:   # dedupe A↔B vs B↔A
                    direction = "co-moves" if val > 0 else "inversely moves"
                    corr_lines.append(f"  {r1} ↔ {r2}: {direction} (r={val:.2f})")

    corr_block = "\n".join(corr_lines[:8]) or "  (insufficient data)"

    return (
        f"INTELLIGENCE CONTEXT — {window_hours}h window ending {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"RECENT INTELLIGENCE ({len(recent)} stories, severity-ranked):\n{events_block}\n\n"
        f"ACTIVE REGIONAL CORRELATIONS (|r| ≥ 0.50):\n{corr_block}\n\n"
        f"ANALYST QUERY: {question}"
    )


# ── LLM backends ──────────────────────────────────────────────────────────────

async def _ollama_available(session: aiohttp.ClientSession) -> bool:
    try:
        async with session.get(
            f"{OLLAMA_BASE}/api/tags",
            timeout=aiohttp.ClientTimeout(total=3),
        ) as resp:
            if resp.status != 200:
                return False
            data  = await resp.json()
            names = [m.get("name", "") for m in data.get("models", [])]
            return any(OLLAMA_MODEL in n for n in names)
    except Exception:
        return False


async def _query_ollama(prompt: str, session: aiohttp.ClientSession) -> Optional[str]:
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system",  "content": SYSTEM_PROMPT},
                {"role": "user",    "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1024},
        }
        async with session.post(
            f"{OLLAMA_BASE}/api/chat",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=OLLAMA_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                logger.warning("Ollama HTTP %s", resp.status)
                return None
            data = await resp.json()
            return data.get("message", {}).get("content", "") or None
    except Exception as exc:
        logger.warning("Ollama query failed: %s", exc)
        return None


async def _query_claude(prompt: str, api_key: str) -> Optional[str]:
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as exc:
        logger.warning("Claude API: %s", exc)
        return None


async def _query_openai(prompt: str, api_key: str) -> Optional[str]:
    try:
        import openai
        client = openai.AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=1024,
            temperature=0.3,
        )
        return resp.choices[0].message.content
    except Exception as exc:
        logger.warning("OpenAI API: %s", exc)
        return None


async def _query_gemini(prompt: str, api_key: str) -> Optional[str]:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            "gemini-1.5-flash",
            system_instruction=SYSTEM_PROMPT,
        )
        resp = await model.generate_content_async(
            prompt,
            generation_config={"temperature": 0.3, "max_output_tokens": 1024},
        )
        return resp.text
    except Exception as exc:
        logger.warning("Gemini API: %s", exc)
        return None


# ── Response parser ────────────────────────────────────────────────────────────

def _parse_response(raw: str) -> dict[str, Any]:
    if not raw:
        return {"error": "Empty response from LLM"}
    text = raw.strip()
    # Strip markdown fences if present
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            candidate = part.lstrip("json").strip()
            if candidate.startswith("{"):
                text = candidate
                break
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Return as free-form summary
        return {
            "summary": text[:600],
            "confidence": "unknown",
            "key_connections": [],
            "strategic_implications": "",
            "recommended_monitoring": [],
            "analyst_note": "Raw response (non-JSON) — model did not follow output format.",
            "_raw": True,
        }


# ── Engine class ───────────────────────────────────────────────────────────────

class ConvergenceEngine:
    def __init__(self):
        self._api_keys: dict[str, str] = {}
        self._preferred_fallback: str  = "claude"
        self._query_count: int         = 0
        self._last_engine: str         = ""

    def configure(self, provider: str, api_key: str = "", preferred: bool = False):
        if api_key:
            self._api_keys[provider] = api_key
        if preferred:
            self._preferred_fallback = provider

    async def status(self) -> dict[str, Any]:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            ollama_ok = await _ollama_available(session)

        # Merge richer status from ollama_manager if available
        ollama_detail: dict[str, Any] = {
            "available":  ollama_ok,
            "model":      OLLAMA_MODEL,
            "url":        OLLAMA_BASE,
        }
        try:
            from ollama_manager import ollama_manager as _omgr
            mgr_status = await _omgr.status()
            ollama_detail.update(mgr_status)
            ollama_detail["available"] = ollama_ok  # keep the live HTTP check authoritative
        except Exception:
            pass

        return {
            "ollama": ollama_detail,
            "apis_configured": {k: bool(v) for k, v in self._api_keys.items()},
            "preferred_fallback": self._preferred_fallback,
            "query_count":   self._query_count,
            "last_engine":   self._last_engine,
        }

    async def query(
        self,
        question: str,
        events: list[dict],
        correlation_data: dict,
        window_hours: int = 12,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        prompt = build_context(events, correlation_data, question, window_hours)

        raw: Optional[str] = None
        engine_used = "none"

        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            if await _ollama_available(session):
                raw = await _query_ollama(prompt, session)
                if raw:
                    engine_used = f"ollama/{OLLAMA_MODEL}"

        # API fallback — try preferred first, then others
        if not raw:
            order = [self._preferred_fallback] + [
                p for p in ["claude", "openai", "gemini"] if p != self._preferred_fallback
            ]
            for provider in order:
                key = self._api_keys.get(provider, "")
                if not key:
                    continue
                if provider == "claude":
                    raw = await _query_claude(prompt, key)
                    engine_used = "claude/haiku"
                elif provider == "openai":
                    raw = await _query_openai(prompt, key)
                    engine_used = "openai/gpt-4o-mini"
                elif provider == "gemini":
                    raw = await _query_gemini(prompt, key)
                    engine_used = "gemini/flash"
                if raw:
                    break

        if not raw:
            return {
                "error": (
                    "No LLM available. Either run Ollama locally "
                    "(ollama run qwen2.5:7b) or add an API key in "
                    "User Settings → AI Engine."
                ),
                "engine": "none",
                "elapsed_ms": round((time.perf_counter() - t0) * 1000),
            }

        self._query_count += 1
        self._last_engine  = engine_used
        result = _parse_response(raw)
        result["engine"]          = engine_used
        result["elapsed_ms"]      = round((time.perf_counter() - t0) * 1000)
        result["timestamp"]       = datetime.now(timezone.utc).isoformat()
        result["context_events"]  = len(events)
        result["window_hours"]    = window_hours
        return result


convergence_engine = ConvergenceEngine()
