#!/usr/bin/env bash
# ── AEGLOS Analytics Pro — Ollama binary fetcher ──────────────────────────────
# Downloads the Ollama CLI binary for macOS into ./bin/ollama so it can be
# bundled in the PyInstaller DMG or used directly from the source tree.
#
# Usage:  ./tools/fetch_ollama.sh [version]
# Example: ./tools/fetch_ollama.sh 0.9.0
#
# If no version is given, the latest stable release is fetched automatically.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BIN_DIR="${REPO_ROOT}/bin"
TARGET="${BIN_DIR}/ollama"

# ── Version resolution ────────────────────────────────────────────────────────
if [[ $# -ge 1 ]]; then
  VERSION="$1"
else
  echo "Fetching latest Ollama release tag…"
  VERSION=$(curl -fsSL \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/ollama/ollama/releases/latest" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))")
fi

echo "Ollama version : ${VERSION}"

# ── Architecture detection ────────────────────────────────────────────────────
ARCH=$(uname -m)
case "${ARCH}" in
  arm64)  ASSET="ollama-darwin-arm64" ;;
  x86_64) ASSET="ollama-darwin-amd64" ;;
  *)      echo "Unsupported architecture: ${ARCH}"; exit 1 ;;
esac

URL="https://github.com/ollama/ollama/releases/download/v${VERSION}/${ASSET}"
echo "Downloading     : ${URL}"

# ── Download ──────────────────────────────────────────────────────────────────
mkdir -p "${BIN_DIR}"
TMP="${BIN_DIR}/ollama.tmp"

curl -fL --progress-bar -o "${TMP}" "${URL}"
mv "${TMP}" "${TARGET}"
chmod +x "${TARGET}"

echo ""
echo "✓  Ollama ${VERSION} (${ARCH}) saved to: ${TARGET}"
echo ""
echo "Next steps:"
echo "  • Run 'ollama run qwen2.5:7b' once to verify (optional — the app downloads it automatically)"
echo "  • The model (~4.7 GB) downloads on first use via the AI Engine panel in the app"
