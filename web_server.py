"""
AEGLOS Analytics Pro - Flask Web Interface
Serves HTML dashboards on port 5001.
All /api/v1/* and /health requests are proxied to FastAPI with server-side auth injection.
"""

import os
import logging

import requests
from flask import Flask, Response, jsonify, redirect, request, send_from_directory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web_server")

try:
    from flask_cors import CORS
    _cors_available = True
except ImportError:
    _cors_available = False

app = Flask(__name__, static_folder="static", template_folder="static")

_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()] or ["*"]
if _cors_available:
    from flask_cors import CORS
    CORS(app, origins=_cors_origins)

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
API_KEY  = os.getenv("AEGLOS_API_KEY", "")

# Support PyInstaller bundle path override
STATIC_DIR = (
    os.environ.get("AEGLOS_STATIC_DIR")
    or os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
)


def _read_html(filename: str) -> str:
    path = os.path.join(STATIC_DIR, filename)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"<h1>File not found: {filename}</h1>"


def _proxy(path: str) -> Response:
    """Forward a request to FastAPI, injecting the API key server-side."""
    url = f"{API_BASE}{path}"
    headers: dict[str, str] = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    qs = request.query_string.decode()
    if qs:
        url += "?" + qs

    try:
        if request.method in ("POST", "PUT", "PATCH"):
            headers["Content-Type"] = request.content_type or "application/json"
            resp = requests.request(
                request.method,
                url,
                headers=headers,
                data=request.get_data(),
                timeout=60,
            )
        else:
            resp = requests.get(url, headers=headers, timeout=30)

        return Response(
            resp.content,
            status=resp.status_code,
            content_type=resp.headers.get("Content-Type", "application/json"),
        )
    except requests.exceptions.ConnectionError:
        return Response(b'{"error":"API unavailable"}', status=503,
                        content_type="application/json")
    except requests.exceptions.Timeout:
        return Response(b'{"error":"API timeout"}', status=504,
                        content_type="application/json")


# ─── Proxy routes ──────────────────────────────────────────────────────────────

@app.route("/api/v1/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def api_proxy(subpath):
    return _proxy(f"/api/v1/{subpath}")


@app.route("/health")
def health_proxy():
    return _proxy("/health")


# ─── Dashboard routes ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect("/geothreat", code=302)


@app.route("/setup")
def setup():
    return _read_html("setup.html"), 200, {"Content-Type": "text/html"}


@app.route("/geothreat")
def geothreat():
    return _read_html("geothreat-dashboard.html"), 200, {"Content-Type": "text/html"}


# Legacy routes redirected to the live dashboard
@app.route("/dashboard")
@app.route("/demo")
def legacy_redirect():
    return redirect("/geothreat", code=302)


@app.route("/docs")
def docs():
    return _read_html("docs.html"), 200, {"Content-Type": "text/html"}


@app.route("/api/status")
def api_status():
    """Legacy health check endpoint."""
    return health_proxy()


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
