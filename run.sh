#!/usr/bin/env bash
# One-click local setup + start for the Agentic Website Builder.
set -euo pipefail

cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

echo "── Luma Website Builder · local setup ──"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Error: Python 3 not found. Install Python 3.10+ and retry." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "→ Creating virtualenv (.venv)"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ Installing dependencies"
pip install -q -r requirements.txt

if ! python -c "import playwright" 2>/dev/null; then
  echo "→ Installing Playwright Chromium (screenshots)"
  python -m playwright install chromium
else
  if [[ ! -d "$HOME/.cache/ms-playwright" ]] && [[ ! -d "$HOME/Library/Caches/ms-playwright" ]]; then
    echo "→ Installing Playwright Chromium (screenshots)"
    python -m playwright install chromium
  fi
fi

if [[ ! -f .env ]]; then
  echo "→ Creating .env from .env.example"
  cp .env.example .env
  echo "  Add your Anthropic API key to .env, or use: claude login"
fi

PORT="${PORT:-8000}"
echo ""
echo "✓ Ready. Starting server on http://localhost:${PORT}"
echo "  Paste a URL in the browser to build a template."
echo "  Press Ctrl+C to stop."
echo ""
exec python server.py --port "$PORT"
