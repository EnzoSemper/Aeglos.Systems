"""
AEGLOS Analytics Pro — Cross-Platform Launcher
Starts API + Web servers, opens browser.
No tkinter/Tk dependency — runs fully headless inside the .app bundle.
"""

import os
import sys
import time
import signal
import threading
import webbrowser
import urllib.request
import subprocess

# ── PyInstaller bundle path resolution ────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS  # type: ignore[attr-defined]
    APP_DIR  = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR  = BASE_DIR

os.environ['AEGLOS_BASE_DIR']   = BASE_DIR
os.environ['AEGLOS_STATIC_DIR'] = os.path.join(BASE_DIR, 'static')
sys.path.insert(0, BASE_DIR)

import logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(name)s  %(message)s',
)
log = logging.getLogger('launcher')

# ── Shutdown event ────────────────────────────────────────────────────────────
_shutdown = threading.Event()

def _handle_signal(signum, frame):
    log.info("Signal %s received — shutting down", signum)
    _shutdown.set()

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT,  _handle_signal)

# ── Native macOS notification (no dependencies) ───────────────────────────────
def _notify(title: str, message: str):
    """Show a macOS notification via osascript — no Tk, no deps."""
    if sys.platform != "darwin":
        return
    try:
        script = (
            f'display notification "{message}" '
            f'with title "{title}" '
            f'sound name "Submarine"'
        )
        subprocess.run(
            ["osascript", "-e", script],
            timeout=5, capture_output=True
        )
    except Exception:
        pass

# ── Server runners ────────────────────────────────────────────────────────────
def _run_api():
    try:
        import uvicorn
        uvicorn.run(
            "main:app",
            host="127.0.0.1",
            port=8000,
            log_level="warning",
            workers=1,
            loop="asyncio",
        )
    except Exception as exc:
        log.error("API server crashed: %s", exc)
    finally:
        _shutdown.set()

def _run_web():
    try:
        import web_server
        web_server.app.run(
            host="127.0.0.1",
            port=5001,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    except Exception as exc:
        log.error("Web server crashed: %s", exc)
    finally:
        _shutdown.set()

# ── Health check ──────────────────────────────────────────────────────────────
def _wait_for_health(timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _shutdown.is_set():
            return False
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2)
            return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

# ── macOS Dock menu via PyObjC (optional, graceful fallback) ──────────────────
def _run_dock_app():
    """
    If PyObjC is available, show a minimal Dock icon with a Quit menu.
    Falls back gracefully — the app keeps running headlessly either way.
    """
    try:
        from AppKit import (
            NSApplication, NSApp, NSMenu, NSMenuItem,
            NSObject, NSApplicationActivationPolicyAccessory,
        )
        from Foundation import NSString

        class AppDelegate(NSObject):
            def applicationDidFinishLaunching_(self, notification):
                pass

            def quit_(self, sender):
                _shutdown.set()
                NSApp.terminate_(None)

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        delegate = AppDelegate.alloc().init()
        app.setDelegate_(delegate)

        # Dock menu
        menu = NSMenu.alloc().init()
        open_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open Intelligence Dashboard", "openDashboard:", ""
        )
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit AEGLOS Analytics Pro", "quit:", "q"
        )
        menu.addItem_(open_item)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(quit_item)
        app.setDockTilesMenu_(menu)

        # Watch for shutdown from other threads
        def _watch():
            _shutdown.wait()
            app.terminate_(None)
        threading.Thread(target=_watch, daemon=True).start()

        app.run()

    except ImportError:
        # PyObjC not available — just block until shutdown signal
        _shutdown.wait()
    except Exception as exc:
        log.debug("Dock app error: %s", exc)
        _shutdown.wait()


def _start_ollama():
    """Start the bundled Ollama process in a background thread (non-fatal if missing)."""
    try:
        from ollama_manager import ollama_manager
        ok = ollama_manager.start()
        if ok:
            log.info("Ollama started successfully")
        else:
            log.info("Ollama not started (binary not found or failed — AI features use API fallback)")
    except Exception as exc:
        log.warning("Ollama startup error: %s", exc)


def _stop_ollama():
    """Gracefully stop the Ollama child process."""
    try:
        from ollama_manager import ollama_manager
        ollama_manager.stop()
    except Exception:
        pass


def _model_status() -> dict:
    """Return the ollama status dict from the local API (best-effort)."""
    try:
        import json
        req = urllib.request.Request("http://127.0.0.1:8000/api/v1/ollama/status")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def _trigger_pull() -> bool:
    """POST /api/v1/ollama/pull to kick off the model download. Returns True on success."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/v1/ollama/pull",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        return True
    except Exception as exc:
        log.warning("Could not trigger model pull: %s", exc)
        return False


def main():
    log.info("AEGLOS Analytics Pro starting…")

    # Start Ollama before the API so convergence engine can find it
    threading.Thread(target=_start_ollama, name="aeglos-ollama", daemon=True).start()

    # Start server threads
    api_t = threading.Thread(target=_run_api, name="aeglos-api", daemon=True)
    web_t = threading.Thread(target=_run_web, name="aeglos-web", daemon=True)
    api_t.start()
    web_t.start()

    # Background: wait for health → check model → open correct page
    def _on_ready():
        if not _wait_for_health(timeout=60):
            log.warning("API did not become healthy within 60s")
            _notify("AEGLOS Analytics Pro", "⚠ Server startup timed out")
            return

        log.info("API healthy — checking model status")
        status = _model_status()

        if status.get("model_present"):
            # Model already downloaded — go straight to dashboard
            _notify("AEGLOS Analytics Pro", "Intelligence platform is live")
            webbrowser.open("http://localhost:5001/geothreat")
        elif status.get("process_running"):
            # First run: trigger auto-pull and open setup screen
            log.info("First run detected — triggering Qwen model download")
            _trigger_pull()
            _notify(
                "AEGLOS Analytics Pro",
                "First run: downloading AI model (~4.7 GB)…",
            )
            webbrowser.open("http://localhost:5001/setup")
        else:
            # Ollama not running (binary missing etc.) — open dashboard anyway,
            # intelligence feeds work without the model
            _notify("AEGLOS Analytics Pro", "Intelligence platform is live (AI engine offline)")
            webbrowser.open("http://localhost:5001/geothreat")

    threading.Thread(target=_on_ready, daemon=True).start()

    # Block main thread (handles Dock / signals on macOS, blocks on other OS)
    _run_dock_app()

    # Clean shutdown
    _stop_ollama()
    log.info("AEGLOS Analytics Pro exiting")


if __name__ == "__main__":
    main()
