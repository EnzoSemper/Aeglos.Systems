# ============================================================
# AEGLOS Analytics Pro — Windows Build Script (PowerShell)
# Produces:  dist\AEGLOS-Analytics-Pro-1.0.0-Windows-x64.exe
# Run from the aeglos-analytics directory:
#   Set-ExecutionPolicy Bypass -Scope Process
#   .\build\build_windows.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$ROOT = Split-Path $PSScriptRoot -Parent
$VERSION = "1.0.0"
$APP_NAME = "AEGLOS Analytics Pro"
$EXE_BASE = "AEGLOS-Analytics-Pro-$VERSION-Windows-x64"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║       AEGLOS Analytics Pro — Windows .exe Build              ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Python check ──────────────────────────────────────────────────────────────
$PYTHON = (Get-Command python -ErrorAction Stop).Source
$PY_VER = & python --version
Write-Host "✓ $PY_VER at $PYTHON" -ForegroundColor Green

# ── Virtual env ───────────────────────────────────────────────────────────────
$VENV = Join-Path $ROOT "venv_build"
if (-not (Test-Path $VENV)) {
    Write-Host "→ Creating build venv..." -ForegroundColor Yellow
    & python -m venv $VENV
}
& "$VENV\Scripts\Activate.ps1"
Write-Host "✓ Build venv active" -ForegroundColor Green

# ── Dependencies ──────────────────────────────────────────────────────────────
Write-Host "→ Installing dependencies (may take several minutes)..." -ForegroundColor Yellow
& pip install -q --upgrade pip
& pip install -q -r (Join-Path $ROOT "requirements.txt")
& pip install -q pyinstaller Pillow pywin32
Write-Host "✓ Dependencies installed" -ForegroundColor Green

# ── Generate icon ─────────────────────────────────────────────────────────────
Write-Host "→ Generating app icon..." -ForegroundColor Yellow
& python (Join-Path $ROOT "build\make_icon.py")
Write-Host "✓ Icon generated" -ForegroundColor Green

# ── Clean ─────────────────────────────────────────────────────────────────────
$DIST_APP = Join-Path $ROOT "dist_app"
if (Test-Path $DIST_APP) { Remove-Item $DIST_APP -Recurse -Force }
$WORK_DIR = Join-Path $ROOT "build\pyinstaller_work"
if (Test-Path $WORK_DIR) { Remove-Item $WORK_DIR -Recurse -Force }

# ── PyInstaller ───────────────────────────────────────────────────────────────
Write-Host "→ Running PyInstaller (3-10 minutes)..." -ForegroundColor Yellow
& pyinstaller `
    --distpath $DIST_APP `
    --workpath $WORK_DIR `
    --noconfirm `
    --log-level WARN `
    (Join-Path $ROOT "build\aeglos.spec")

$APP_DIR = Join-Path $DIST_APP $APP_NAME
if (-not (Test-Path $APP_DIR)) {
    Write-Error "Build failed — $APP_DIR not found"
    exit 1
}
$SIZE = [math]::Round((Get-ChildItem $APP_DIR -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB, 0)
Write-Host "✓ Build complete: $SIZE MB" -ForegroundColor Green

# ── Create distributable ──────────────────────────────────────────────────────
$DIST_DIR = Join-Path $ROOT "dist"
New-Item -ItemType Directory -Force -Path $DIST_DIR | Out-Null

# Check for NSIS
$NSIS = $null
@("C:\Program Files (x86)\NSIS\makensis.exe", "C:\Program Files\NSIS\makensis.exe") | ForEach-Object {
    if (Test-Path $_) { $NSIS = $_ }
}

if ($NSIS) {
    Write-Host "→ NSIS found — creating installer..." -ForegroundColor Yellow
    & python (Join-Path $ROOT "build\make_nsis.py")
    & $NSIS (Join-Path $ROOT "build\aeglos_installer.nsi")
    Write-Host "✓ Installer: $DIST_DIR\$EXE_BASE.exe" -ForegroundColor Green
} else {
    Write-Host "→ NSIS not found — creating portable zip..." -ForegroundColor Yellow
    $ZIP_OUT = Join-Path $DIST_DIR "$EXE_BASE-portable.zip"
    Compress-Archive -Path $APP_DIR -DestinationPath $ZIP_OUT -Force
    Write-Host "✓ Portable zip: $ZIP_OUT" -ForegroundColor Green

    # Create minimal batch launcher in the zip's parent
    $LAUNCHER_BAT = Join-Path $DIST_DIR "Launch-AEGLOS.bat"
    @"
@echo off
echo Starting AEGLOS Analytics Pro...
set DIR=%~dp0AEGLOS Analytics Pro
start "" "%DIR%\AEGLOS Analytics Pro.exe"
"@ | Set-Content $LAUNCHER_BAT
}

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                   BUILD COMPLETE ✅                          ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Output: $DIST_DIR" -ForegroundColor White
Write-Host "  Usage:  Extract zip, run 'AEGLOS Analytics Pro\AEGLOS Analytics Pro.exe'" -ForegroundColor Gray
Write-Host ""
