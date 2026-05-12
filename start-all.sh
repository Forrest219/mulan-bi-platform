#!/usr/bin/env bash
# Deprecated compatibility wrapper.
# Use ./start-dev.sh as the single local startup entrypoint.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[start-all] deprecated: use ./start-dev.sh. Forwarding arguments..."
exec "$SCRIPT_DIR/start-dev.sh" "$@"
