#!/usr/bin/env bash
#
# RAT — Repo Analysis Tool — one-command launcher.
#
#   ./start.sh              serve on http://127.0.0.1:8000
#   PORT=9000 ./start.sh    serve on another port
#
# Data lives in ./data (SQLite catalog + extracted repositories) unless
# RAT_DATA_DIR points somewhere else. Other knobs: RAT_MAX_UPLOAD_BYTES,
# RAT_MAX_EXTRACTED_BYTES, RAT_CLONE_TIMEOUT, HOST.
#
# The script is idempotent: it creates the Python virtual environment on first
# run, installs backend/frontend dependencies when missing, rebuilds the
# frontend and then serves the whole app (API + dashboard) from one process.

set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
PYTHON="${PYTHON:-python3}"

for tool in git "$PYTHON" node npm; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "error: '$tool' is required but was not found on PATH." >&2
        exit 1
    fi
done

if [ ! -x .venv/bin/python ]; then
    echo "==> Creating Python virtual environment (.venv)"
    "$PYTHON" -m venv .venv
fi

echo "==> Installing backend dependencies"
.venv/bin/pip install --quiet --disable-pip-version-check -r backend/requirements.txt

if [ ! -d frontend/node_modules ]; then
    echo "==> Installing frontend dependencies (npm install)"
    (cd frontend && npm install --no-audit --no-fund)
fi

echo "==> Building the frontend"
(cd frontend && npm run build)

echo
echo "RAT is starting on http://${HOST}:${PORT}  (press Ctrl+C to stop)"
echo
cd backend
exec ../.venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
