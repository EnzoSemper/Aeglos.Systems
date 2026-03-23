"""
AEGLOS Analytics Pro — Ollama Process Manager

Finds the bundled Ollama binary (./bin/ollama or sys._MEIPASS/bin/ollama),
starts it as a child process with app-local model storage, and manages its
entire lifecycle including first-run model download with progress tracking.
"""

import asyncio
import json
import logging
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import aiohttp

logger = logging.getLogger("ollama_manager")

# ── Constants ──────────────────────────────────────────────────────────────────

OLLAMA_MODEL         = "qwen2.5:7b"
OLLAMA_MODEL_LABEL   = "Qwen 2.5 7B Instruct"
OLLAMA_MODEL_QUANT   = "Q4_K_M"
OLLAMA_MODEL_SIZE_GB = 4.7
OLLAMA_MODEL_SOURCE  = "ollama.com/library/qwen2.5"

OLLAMA_HOST     = "127.0.0.1"
OLLAMA_PORT     = 11435          # offset from 11434 to avoid conflicts with user Ollama
OLLAMA_BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

# App-local model storage (separate from any system Ollama install)
APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "AEGLOS"
OLLAMA_MODEL_DIR = APP_SUPPORT_DIR / "ollama" / "models"
OLLAMA_DATA_DIR  = APP_SUPPORT_DIR / "ollama"

STARTUP_TIMEOUT  = 15   # seconds to wait for Ollama to accept connections
PULL_TIMEOUT     = 600  # 10 min max for a 4.7 GB pull on slow connections


# ── Binary discovery ──────────────────────────────────────────────────────────

def find_ollama_binary() -> Optional[Path]:
    """
    Search order:
      1. Bundled binary next to this file (dev: ./bin/ollama)
      2. PyInstaller MEIPASS bundle (frozen: _MEIPASS/bin/ollama)
      3. System install fallbacks (homebrew, /usr/local)
    """
    if getattr(sys, 'frozen', False):
        bases = [Path(sys._MEIPASS)]  # type: ignore[attr-defined]
    else:
        bases = [Path(__file__).parent]

    for base in bases:
        p = base / "bin" / "ollama"
        if p.is_file():
            return p

    # System fallbacks (user may have Ollama installed separately)
    for system_path in [
        Path("/opt/homebrew/bin/ollama"),       # Apple Silicon homebrew
        Path("/usr/local/bin/ollama"),           # Intel homebrew / manual
        Path("/Applications/Ollama.app/Contents/MacOS/ollama"),
    ]:
        if system_path.is_file():
            logger.info("Using system Ollama at %s", system_path)
            return system_path

    return None


def _ensure_executable(path: Path):
    """Make sure the binary is executable."""
    current = path.stat().st_mode
    if not (current & stat.S_IXUSR):
        path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ── Manager ───────────────────────────────────────────────────────────────────

class OllamaManager:
    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._binary: Optional[Path]           = None
        self._running: bool                    = False

        # Pull progress (shared state for polling)
        self._pull_status:    str   = ""        # e.g. "pulling manifest"
        self._pull_completed: int   = 0         # bytes completed
        self._pull_total:     int   = 0         # bytes total
        self._pull_active:    bool  = False
        self._pull_error:     str   = ""
        self._pull_done:      bool  = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """
        Start the Ollama serve process.
        Returns True if Ollama is ready to accept requests.
        """
        self._binary = find_ollama_binary()
        if not self._binary:
            logger.warning(
                "Ollama binary not found. "
                "Run tools/fetch_ollama.sh to download it, "
                "or install Ollama from https://ollama.com"
            )
            return False

        _ensure_executable(self._binary)
        OLLAMA_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        OLLAMA_DATA_DIR.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["OLLAMA_HOST"]   = f"{OLLAMA_HOST}:{OLLAMA_PORT}"
        env["OLLAMA_MODELS"] = str(OLLAMA_MODEL_DIR)
        env["OLLAMA_NOPRUNE"] = "1"   # don't auto-prune unused layers
        # Suppress Ollama's verbose startup output
        env.pop("OLLAMA_DEBUG", None)

        try:
            log_path = OLLAMA_DATA_DIR / "ollama.log"
            log_fh   = open(log_path, "a")
            try:
                self._proc = subprocess.Popen(
                    [str(self._binary), "serve"],
                    env=env,
                    stdout=log_fh,
                    stderr=log_fh,
                    close_fds=True,
                )
                logger.info("Ollama process started (PID %s)", self._proc.pid)
            finally:
                log_fh.close()  # child inherited the fd; parent no longer needs it
        except Exception as exc:
            logger.error("Failed to start Ollama: %s", exc)
            return False

        # Wait for the HTTP server to be ready
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                logger.error("Ollama process exited early (rc=%s)", self._proc.returncode)
                return False
            try:
                import urllib.request
                urllib.request.urlopen(
                    f"{OLLAMA_BASE_URL}/api/tags", timeout=1
                )
                self._running = True
                logger.info("Ollama ready at %s", OLLAMA_BASE_URL)
                return True
            except Exception:
                time.sleep(0.5)

        logger.error("Ollama did not become ready within %ds", STARTUP_TIMEOUT)
        return False

    def stop(self):
        """Gracefully terminate the Ollama child process."""
        if self._proc and self._proc.poll() is None:
            logger.info("Stopping Ollama (PID %s)", self._proc.pid)
            self._proc.terminate()
            try:
                self._proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._running = False
        self._proc = None

    # ── Status ────────────────────────────────────────────────────────────────

    async def status(self) -> dict[str, Any]:
        binary_path = find_ollama_binary()
        binary_ok   = binary_path is not None

        model_present = False
        process_alive = self._running and (
            self._proc is None or self._proc.poll() is None
        )

        if process_alive:
            try:
                connector = aiohttp.TCPConnector(ssl=False)
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(
                        f"{OLLAMA_BASE_URL}/api/tags",
                        timeout=aiohttp.ClientTimeout(total=3),
                    ) as resp:
                        if resp.status == 200:
                            data   = await resp.json()
                            models = [m.get("name", "") for m in data.get("models", [])]
                            model_present = any(OLLAMA_MODEL in m for m in models)
            except Exception:
                process_alive = False

        return {
            "binary_found":   binary_ok,
            "binary_path":    str(binary_path) if binary_ok else None,
            "process_running": process_alive,
            "model_present":  model_present,
            "model_name":     OLLAMA_MODEL,
            "model_label":    OLLAMA_MODEL_LABEL,
            "model_quant":    OLLAMA_MODEL_QUANT,
            "model_size_gb":  OLLAMA_MODEL_SIZE_GB,
            "model_source":   OLLAMA_MODEL_SOURCE,
            "model_dir":      str(OLLAMA_MODEL_DIR),
            "ollama_url":     OLLAMA_BASE_URL,
            "pull_active":    self._pull_active,
            "pull_done":      self._pull_done,
            "pull_status":    self._pull_status,
            "pull_completed": self._pull_completed,
            "pull_total":     self._pull_total,
            "pull_error":     self._pull_error,
            "pull_pct":       (
                round(self._pull_completed / self._pull_total * 100, 1)
                if self._pull_total > 0 else 0
            ),
        }

    # ── Model pull ────────────────────────────────────────────────────────────

    async def pull_model(self) -> bool:
        """
        Trigger an async pull of OLLAMA_MODEL.
        Progress is tracked in self._pull_* and polled via /api/v1/ollama/pull/progress.
        Returns True if the pull was started successfully.
        """
        if not self._running:
            self._pull_error = "Ollama process is not running"
            return False
        if self._pull_active:
            return True   # already in progress

        self._pull_active    = True
        self._pull_done      = False
        self._pull_error     = ""
        self._pull_status    = "Connecting to model registry…"
        self._pull_completed = 0
        self._pull_total     = 0

        asyncio.create_task(self._pull_task())
        return True

    async def _pull_task(self):
        """Background task: stream pull progress from Ollama."""
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    f"{OLLAMA_BASE_URL}/api/pull",
                    json={"name": OLLAMA_MODEL, "stream": True},
                    timeout=aiohttp.ClientTimeout(total=PULL_TIMEOUT),
                ) as resp:
                    if resp.status != 200:
                        self._pull_error  = f"Pull request failed: HTTP {resp.status}"
                        self._pull_active = False
                        return

                    async for raw_line in resp.content:
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        status = obj.get("status", "")
                        self._pull_status = status

                        # Track byte-level progress for the main layer download
                        if "total" in obj and "completed" in obj:
                            t = obj["total"]
                            c = obj["completed"]
                            if t > self._pull_total:   # keep the largest total
                                self._pull_total = t
                            if c > self._pull_completed:
                                self._pull_completed = c

                        if status == "success":
                            self._pull_done      = True
                            self._pull_active    = False
                            self._pull_status    = "Model ready"
                            self._pull_completed = self._pull_total or self._pull_completed
                            logger.info("Ollama model pull complete: %s", OLLAMA_MODEL)
                            return

                        error = obj.get("error", "")
                        if error:
                            self._pull_error  = error
                            self._pull_active = False
                            logger.error("Ollama pull error: %s", error)
                            return

        except asyncio.CancelledError:
            self._pull_error  = "Download cancelled"
            self._pull_active = False
        except Exception as exc:
            self._pull_error  = str(exc)
            self._pull_active = False
            logger.error("Pull task exception: %s", exc)


# ── Module singleton ──────────────────────────────────────────────────────────
ollama_manager = OllamaManager()
