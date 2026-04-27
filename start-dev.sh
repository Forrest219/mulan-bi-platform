#!/bin/bash
# Mulan BI Platform — 一键启动
# 用法: ./start-dev.sh        启动全部
#       ./start-dev.sh stop   停止全部

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
DIM='\033[2m'
RESET='\033[0m'

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
LOG_DIR="$ROOT/.dev-logs"
PID_DIR="$ROOT/.dev-pids"

export DATABASE_URL="${DATABASE_URL:-postgresql://mulan:***@localhost:5432/mulan_bi}"
source "$ROOT/.env" 2>/dev/null || true
export SESSION_SECRET="${SESSION_SECRET:-}"

mkdir -p "$LOG_DIR" "$PID_DIR"

stop_all() {
  for pidfile in "$PID_DIR"/*.pid; do
    [ -f "$pidfile" ] || continue
    pid=$(cat "$pidfile")
    name=$(basename "$pidfile" .pid)
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      printf "${DIM}stopped %s (pid %s)${RESET}\n" "$name" "$pid"
    fi
    rm -f "$pidfile"
  done
  printf "${GREEN}all stopped${RESET}\n"
}

if [ "${1:-}" = "stop" ]; then
  stop_all
  exit 0
fi

# 先停旧进程
stop_all 2>/dev/null || true

# Docker 基础设施
printf "docker... "
docker-compose -f "$ROOT/docker-compose.yml" up -d --quiet-pull 2>/dev/null
printf "${GREEN}ok${RESET}\n"

# 等 PostgreSQL 就绪
printf "postgres... "
until docker exec mulan-bi-postgres pg_isready -U mulan -d mulan_bi -q 2>/dev/null; do sleep 1; done
printf "${GREEN}ok${RESET}\n"

# 后端
printf "backend... "
cd "$BACKEND"
python3 -m uvicorn app.main:app --reload --port 8000 > "$LOG_DIR/backend.log" 2>&1 &
echo $! > "$PID_DIR/backend.pid"
printf "${GREEN}ok${RESET}  ${DIM}http://localhost:8000${RESET}\n"

# Celery Beat
printf "celery-beat... "
python3 -m celery -A services.tasks beat --loglevel=warning > "$LOG_DIR/celery-beat.log" 2>&1 &
echo $! > "$PID_DIR/celery-beat.pid"
printf "${GREEN}ok${RESET}\n"

# Celery Worker
printf "celery-worker... "
python3 -m celery -A services.tasks worker --pool=solo --loglevel=warning > "$LOG_DIR/celery-worker.log" 2>&1 &
echo $! > "$PID_DIR/celery-worker.pid"
printf "${GREEN}ok${RESET}\n"

# 前端
printf "frontend... "
cd "$FRONTEND"
npm run dev -- --port 3000 > "$LOG_DIR/frontend.log" 2>&1 &
echo $! > "$PID_DIR/frontend.pid"
printf "${GREEN}ok${RESET}  ${DIM}http://localhost:3000${RESET}\n"

echo ""
printf "${GREEN}ready.${RESET} logs → ${DIM}.dev-logs/${RESET}  stop → ${DIM}./start-dev.sh stop${RESET}\n"
