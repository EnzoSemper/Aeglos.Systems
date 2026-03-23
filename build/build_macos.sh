#!/usr/bin/env bash
# ============================================================
# AEGLOS Analytics Pro — macOS .dmg Builder
# Produces:  dist/AEGLOS-Analytics-Pro-1.0.0-macOS-arm64.dmg
# Requires:  macOS 12+, Python 3.10+, Xcode CLI tools
# Usage:     cd aeglos-analytics && ./build/build_macos.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

VERSION="1.0.0"
APP_NAME="AEGLOS Analytics Pro"
DMG_NAME="AEGLOS-Analytics-Pro-${VERSION}-macOS-arm64"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"
PYINSTALLER_DIST="$ROOT_DIR/dist_app"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║        AEGLOS Analytics Pro — macOS .dmg Build               ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Verify macOS ───────────────────────────────────────────────────────────────
[[ "$(uname)" == "Darwin" ]] || { echo -e "${RED}ERROR: Must run on macOS${NC}"; exit 1; }
echo -e "${GREEN}✓${NC} Platform: macOS $(sw_vers -productVersion) $(uname -m)"

# ── Python ──────────────────────────────────────────────────────────────────────
PYTHON=$(command -v python3.12 || command -v python3)
PYVER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "${GREEN}✓${NC} Python $PYVER at $PYTHON"

# ── Virtual env ────────────────────────────────────────────────────────────────
VENV="$ROOT_DIR/venv_build"
if [ ! -d "$VENV" ]; then
  echo -e "${YELLOW}→${NC} Creating build venv…"
  $PYTHON -m venv "$VENV"
fi
source "$VENV/bin/activate"
echo -e "${GREEN}✓${NC} Build venv active"

# ── Install deps + PyInstaller ──────────────────────────────────────────────────
echo -e "${YELLOW}→${NC} Installing dependencies (may take a few minutes)…"
pip install -q --upgrade pip
pip install -q -r "$ROOT_DIR/requirements.txt"
pip install -q pyinstaller Pillow
echo -e "${GREEN}✓${NC} Dependencies installed"

# ── Generate icon ──────────────────────────────────────────────────────────────
echo -e "${YELLOW}→${NC} Generating app icon…"
python "$BUILD_DIR/make_icon.py"
echo -e "${GREEN}✓${NC} Icon generated"

# ── Clean previous build ────────────────────────────────────────────────────────
rm -rf "$PYINSTALLER_DIST" "$ROOT_DIR/build/AEGLOS Analytics Pro" 2>/dev/null || true

# ── PyInstaller build ──────────────────────────────────────────────────────────
echo -e "${YELLOW}→${NC} Running PyInstaller (this takes 3–10 minutes)…"
pyinstaller \
  --distpath "$PYINSTALLER_DIST" \
  --workpath "$ROOT_DIR/build/pyinstaller_work" \
  --noconfirm \
  --log-level WARN \
  "$BUILD_DIR/aeglos.spec"

APP_BUNDLE="$PYINSTALLER_DIST/${APP_NAME}.app"
if [ ! -d "$APP_BUNDLE" ]; then
  echo -e "${RED}ERROR: .app bundle not found at $APP_BUNDLE${NC}"
  exit 1
fi
echo -e "${GREEN}✓${NC} .app bundle created: $(du -sh "$APP_BUNDLE" | cut -f1)"

# ── Purge tkinter/tcl/tk from bundle (prevents TkpInit SIGABRT) ────────────────
echo -e "${YELLOW}→${NC} Purging tkinter/tcl/tk from bundle…"
find "$APP_BUNDLE" \( \
  -name "_tkinter*.so" -o \
  -name "tkinter" -type d -o \
  -name "Tk.framework" -type d -o \
  -name "Tcl.framework" -type d \
\) -exec rm -rf {} + 2>/dev/null || true
echo -e "${GREEN}✓${NC} tkinter purged"

# ── Create .dmg ────────────────────────────────────────────────────────────────
mkdir -p "$DIST_DIR"
DMG_STAGING="/tmp/aeglos_dmg_staging_$$"
mkdir -p "$DMG_STAGING"

# Copy .app into staging dir
cp -R "$APP_BUNDLE" "$DMG_STAGING/"

# Create /Applications symlink
ln -s /Applications "$DMG_STAGING/Applications"

# Write a simple .DS_Store-style README
cat > "$DMG_STAGING/README.txt" <<'README'
AEGLOS Analytics Pro v1.0.0
Multi-Domain HUMINT/OSINT/GEOINT Intelligence Fusion Platform

Install: Drag "AEGLOS Analytics Pro.app" to the Applications folder.
Launch:  Double-click from Applications or Launchpad.

On first launch: right-click → Open (required for unsigned apps on macOS).

The app will:
  1. Start the intelligence API server on port 8000
  2. Start the web interface on port 5001
  3. Open http://localhost:5001/geothreat in your browser

UNCLASSIFIED // FOR OFFICIAL USE ONLY
README

# Create writable DMG from staging dir
echo -e "${YELLOW}→${NC} Creating DMG (writable stage)…"
TMP_DMG="/tmp/aeglos_tmp_$$.dmg"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$DMG_STAGING" \
  -ov -format UDRW \
  -size 800m \
  "$TMP_DMG"

# Mount it to set window properties
MOUNT_POINT=$(hdiutil attach "$TMP_DMG" -readwrite -noverify -noautoopen | \
  grep '/Volumes' | sed 's|.*\(/Volumes/.*\)|\1|')
echo -e "${YELLOW}→${NC} Mounted at $MOUNT_POINT"

# Set icon and window layout via AppleScript
osascript <<APPLESCRIPT || true
tell application "Finder"
  tell disk "${APP_NAME}"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {400, 100, 950, 480}
    set theViewOptions to the icon view options of container window
    set arrangement of theViewOptions to not arranged
    set icon size of theViewOptions to 128
    set position of item "${APP_NAME}.app" of container window to {170, 195}
    set position of item "Applications" of container window to {380, 195}
    set position of item "README.txt" of container window to {275, 340}
    close
    open
    update without registering applications
    delay 3
  end tell
end tell
APPLESCRIPT

sync
hdiutil detach "$MOUNT_POINT"

# Convert to compressed read-only DMG
FINAL_DMG="$DIST_DIR/${DMG_NAME}.dmg"
echo -e "${YELLOW}→${NC} Compressing to final DMG…"
hdiutil convert "$TMP_DMG" \
  -format UDZO \
  -imagekey zlib-level=9 \
  -o "$FINAL_DMG"

# Cleanup
rm -f "$TMP_DMG"
rm -rf "$DMG_STAGING"

DMG_SIZE=$(du -sh "$FINAL_DMG" | cut -f1)
echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║                   BUILD COMPLETE ✅                          ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}DMG:${NC}  $FINAL_DMG"
echo -e "  ${BOLD}Size:${NC} $DMG_SIZE"
echo ""
echo -e "  ${BOLD}To install:${NC} Open the .dmg and drag to Applications"
echo -e "  ${BOLD}First run:${NC}  Right-click → Open (required for unsigned app)"
echo ""
