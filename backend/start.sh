#!/usr/bin/env bash
# Backend-only compatibility wrapper.
# Prefer ../start-dev.sh for local development.

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PY="$BACKEND_DIR/.venv/bin/python"

if [ ! -x "$BACKEND_PY" ]; then
  echo "error: missing backend virtualenv: $BACKEND_PY" >&2
  echo "create it with Python 3.10+ and run: cd backend && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

if ! "$BACKEND_PY" -c "import sys; raise SystemExit(sys.version_info < (3, 10))"; then
  echo "error: backend requires Python 3.10+; $BACKEND_PY is $("$BACKEND_PY" --version 2>&1)" >&2
  exit 1
fi

cd "$BACKEND_DIR"
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

exec "$BACKEND_PY" -m uvicorn app.main:app --reload --port 8000
