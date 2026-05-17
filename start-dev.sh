#!/bin/bash
# Mulan BI Platform - Docker development entrypoint
# Usage:
#   ./start-dev.sh             Start/recreate the Docker dev environment
#   ./start-dev.sh stop        Stop the Docker dev environment
#   ./start-dev.sh restart X   Restart a service, e.g. celery
#   ./start-dev.sh logs [X]    Tail logs for all services or one service
#   ./start-dev.sh ps          Show service status

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
DIM='\033[2m'
RESET='\033[0m'

ROOT="$(cd "$(dirname "$0")" && pwd)"
COMPOSE=()

fail() {
  printf "${RED}error:${RESET} %s\n" "$1" >&2
  exit 1
}

preflight() {
  command -v docker >/dev/null 2>&1 || fail "docker is not installed or not in PATH"

  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.dev.yml")
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.dev.yml")
  else
    fail "Docker Compose is not installed; install Docker Compose v2 or docker-compose"
  fi
}

print_ready() {
  echo ""
  printf "${GREEN}ready.${RESET} frontend -> ${DIM}http://localhost:3000${RESET}  backend -> ${DIM}http://localhost:8000${RESET}\n"
  printf "logs -> ${DIM}./start-dev.sh logs [service]${RESET}  stop -> ${DIM}./start-dev.sh stop${RESET}\n"
}

preflight

case "${1:-up}" in
  up|start)
    "${COMPOSE[@]}" up -d --build
    print_ready
    ;;
  stop|down)
    "${COMPOSE[@]}" down
    ;;
  restart)
    shift
    [ "$#" -gt 0 ] || fail "usage: ./start-dev.sh restart <service>"
    "${COMPOSE[@]}" restart "$@"
    ;;
  logs)
    shift
    "${COMPOSE[@]}" logs -f --tail=120 "$@"
    ;;
  ps|status)
    "${COMPOSE[@]}" ps
    ;;
  *)
    fail "unknown command: $1"
    ;;
esac
