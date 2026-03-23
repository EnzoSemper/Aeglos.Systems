# -*- mode: python ; coding: utf-8 -*-
"""
AEGLOS Analytics Pro — PyInstaller Spec
Builds a one-directory bundle (.app on macOS, .exe dir on Windows).
Run from the aeglos-analytics project root:
    pyinstaller build/aeglos.spec
"""

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path(SPECPATH).parent  # aeglos-analytics/

# ── Application metadata ──────────────────────────────────────────────────────
APP_NAME    = "AEGLOS Analytics Pro"
APP_VERSION = "1.0.0"
BUNDLE_ID   = "pro.aeglos.analytics"

# ── Collect data files ────────────────────────────────────────────────────────
datas = [
    # HTML / JS / CSS dashboards
    (str(project_root / "static"), "static"),
]

# scikit-learn needs its compiled extensions
datas += collect_data_files("sklearn")
datas += collect_data_files("sklearn.utils")
datas += collect_data_files("numpy")
datas += collect_data_files("cryptography")
datas += collect_data_files("aiohttp")
datas += collect_data_files("feedparser")
datas += collect_data_files("charset_normalizer")
datas += collect_data_files("certifi")

# ── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = [
    # FastAPI / Starlette
    "fastapi", "starlette", "starlette.middleware", "starlette.middleware.cors",
    "starlette.routing", "starlette.responses", "starlette.requests",
    "starlette.background", "starlette.concurrency",
    "uvicorn", "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.asyncio",
    "uvicorn.protocols", "uvicorn.protocols.http",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "h11",
    # Pydantic
    "pydantic", "pydantic.v1", "pydantic_core",
    # Flask / CORS
    "flask", "flask_cors", "werkzeug", "jinja2",
    # ML
    "sklearn", "sklearn.ensemble", "sklearn.ensemble._forest",
    "sklearn.ensemble._iforest", "sklearn.tree", "sklearn.tree._classes",
    "sklearn.preprocessing", "sklearn.utils", "sklearn.utils._bunch",
    "sklearn.utils.multiclass", "sklearn.utils.validation",
    "sklearn.metrics", "joblib",
    "numpy", "numpy.core", "numpy.core._methods",
    "scipy", "scipy.special", "scipy.linalg",
    # Crypto
    "cryptography", "cryptography.hazmat", "cryptography.hazmat.primitives",
    "cryptography.hazmat.primitives.ciphers",
    "cryptography.hazmat.primitives.ciphers.aead",
    "cryptography.hazmat.primitives.kdf.pbkdf2",
    "cryptography.hazmat.backends",
    "cryptography.hazmat.backends.openssl",
    # HTTP / async
    "aiohttp", "aiohttp.client", "aiohttp.connector",
    "feedparser",
    "requests", "urllib3", "charset_normalizer",
    # Standard extras
    "multiprocessing.pool", "email", "html.parser",
    # Our modules
    "config", "main", "geothreat_pipeline", "ml_engine",
    "data_pipeline", "encryption", "web_server",
    "prophet_engine", "bluesky_source", "dedup_translate",
]

hiddenimports += collect_submodules("sklearn")
hiddenimports += collect_submodules("scipy")
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("starlette")

# ── Bundled binaries (Ollama + GGML dylibs for local inference) ───────────────
import glob as _glob
_bin_dir = project_root / "bin"
binaries = []
if (_bin_dir / "ollama").exists():
    binaries.append((str(_bin_dir / "ollama"), "bin"))
for _dylib in _glob.glob(str(_bin_dir / "*.dylib")) + _glob.glob(str(_bin_dir / "*.so")) + _glob.glob(str(_bin_dir / "*.metallib")):
    binaries.append((_dylib, "bin"))

# ── Hidden imports (convergence engine + ollama manager) ──────────────────────
hiddenimports += ["convergence_engine", "ollama_manager"]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(project_root / "launcher.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_root / "build" / "hook-block-tkinter.py")],
    excludes=["pytest", "IPython", "jupyter", "notebook", "matplotlib",
              "PIL", "cv2", "torch", "tensorflow",
              "tkinter", "_tkinter", "tk", "tcl",
              "psycopg2", "psycopg2-binary", "redis", "sqlalchemy",
              "pandas", "gunicorn"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

# ── Executable ────────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,        # No terminal window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "build" / "icon.icns") if sys.platform == "darwin" else
         str(project_root / "build" / "icon.ico"),
)

# ── One-dir bundle ─────────────────────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)

# ── macOS .app bundle ─────────────────────────────────────────────────────────
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(project_root / "build" / "icon.icns"),
        bundle_identifier=BUNDLE_ID,
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleName": APP_NAME,
            "CFBundleVersion": APP_VERSION,
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleIdentifier": BUNDLE_ID,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "12.0",
            "NSHumanReadableCopyright": f"© 2025 AEGLOS Analytics Pro",
            "LSUIElement": False,
            "CFBundleDocumentTypes": [],
        },
    )
