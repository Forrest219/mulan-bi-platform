#!/usr/bin/env bash
# Auto-fix edited files: ruff --fix for .py, eslint --fix for .ts/.tsx
set -uo pipefail

f=$(jq -r '.tool_input.file_path // empty' 2>/dev/null)
[[ -z "$f" ]] && exit 0

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$f" in
  *.py)
    "$PROJ/backend/.venv/bin/ruff" check --fix --quiet "$f" 2>/dev/null || true
    python3 -m py_compile "$f" 2>/dev/null || true
    ;;
  *.ts|*.tsx)
    cd "$PROJ/frontend" && npx eslint --fix --quiet "$f" 2>/dev/null || true
    ;;
esac
exit 0
