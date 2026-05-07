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
BACKEND_PY="$BACKEND/.venv/bin/python"
BACKEND_CELERY="$BACKEND/.venv/bin/celery"
COMPOSE=()

export DATABASE_URL="${DATABASE_URL:-postgresql://mulan:mulan@localhost:5432/mulan_bi}"

mkdir -p "$LOG_DIR" "$PID_DIR"

fail() {
  printf "${RED}error:${RESET} %s\n" "$1" >&2
  exit 1
}

port_in_use() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

wait_port_free() {
  port="$1"
  tries=20
  while [ "$tries" -gt 0 ]; do
    port_in_use "$port" || return 0
    sleep 0.25
    tries=$((tries - 1))
  done
  return 1
}

stop_stale_project_listener() {
  port="$1"
  label="$2"
  filter_project="${3:-false}"
  pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  [ -n "$pids" ] || return 0

  for pid in $pids; do
    # 项目级过滤：检查进程是否属于本项目（命令路径含 ROOT）
    if [ "$filter_project" = "true" ]; then
      cmdline=$(ps -p "$pid" -o args= 2>/dev/null || true)
      if [ -z "$cmdline" ] || ! echo "$cmdline" | grep -q "$ROOT"; then
        printf "${DIM}skipped non-project listener on port %s (pid %s)${RESET}\n" "$port" "$pid"
        continue
      fi
    fi

    printf "${DIM}stopped stale %s listener on port %s (pid %s)${RESET}\n" "$label" "$port" "$pid"
    kill "$pid" 2>/dev/null || true
    sleep 0.2
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
}

require_port_free() {
  port="$1"
  label="$2"
  if port_in_use "$port"; then
    printf "${RED}%s port %s is already in use.${RESET}\n" "$label" "$port" >&2
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true
    fail "stop the process above or run './start-dev.sh stop' if it was started by this project"
  fi
}

wait_http() {
  url="$1"
  label="$2"
  tries=60
  while [ "$tries" -gt 0 ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
    tries=$((tries - 1))
  done
  fail "$label did not become ready: $url"
}

preflight() {
  command -v docker >/dev/null 2>&1 || fail "docker is not installed or not in PATH"
  command -v npm >/dev/null 2>&1 || fail "npm is not installed or not in PATH"
  command -v curl >/dev/null 2>&1 || fail "curl is not installed or not in PATH"
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose -f "$ROOT/docker-compose.yml")
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose -f "$ROOT/docker-compose.yml")
  else
    fail "Docker Compose is not installed; install Docker Compose v2 or docker-compose"
  fi
  if [ -z "$SKIP_BACKEND_CHECK" ]; then
    [ -x "$BACKEND_PY" ] || fail "missing backend virtualenv: $BACKEND_PY; create it and run 'cd backend && python3 -m pip install -r requirements.txt'"
    [ -x "$BACKEND_CELERY" ] || fail "missing celery in backend virtualenv; run 'cd backend && .venv/bin/python -m pip install -r requirements.txt'"
    "$BACKEND_PY" -c "import fastapi, uvicorn, pandas, requests, pgvector, tiktoken, redbeat, openpyxl, croniter" \
      || fail "backend dependencies are incomplete; run 'cd backend && .venv/bin/python -m pip install -r requirements.txt'"
  fi
}

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

  # 清理残留的端口监听进程，确保端口真正释放（仅限本项目进程）
  stop_stale_project_listener 8000 "backend" true
  stop_stale_project_listener 3000 "frontend" true

  printf "${GREEN}all stopped${RESET}\n"
}

if [ "${1:-}" = "stop" ]; then
  stop_all
  exit 0
fi

preflight

# 先停旧进程（仅限本项目进程）
stop_all 2>/dev/null || true
stop_stale_project_listener 8000 "backend" true
stop_stale_project_listener 3000 "frontend" true
wait_port_free 8000 || fail "backend port 8000 is still in use after stopping old processes"
wait_port_free 3000 || fail "frontend port 3000 is still in use after stopping old processes"
require_port_free 8000 "backend"
require_port_free 3000 "frontend"

# Docker 基础设施
printf "docker... "
"${COMPOSE[@]}" up -d --quiet-pull postgres redis
printf "${GREEN}ok${RESET}\n"

# 等 PostgreSQL 就绪
printf "postgres... "
until docker exec mulan-bi-postgres pg_isready -U mulan -d mulan_bi -q 2>/dev/null; do sleep 1; done
printf "${GREEN}ok${RESET}\n"

# 迁移数据库（Load .env for DATABASE_URL）
# 只有在未跳过 backend 检查时才运行 backend 相关操作
if [ -z "$SKIP_BACKEND_CHECK" ]; then
  printf "migrate... "
  cd "$BACKEND"
  if [ -f "$BACKEND/.env" ]; then
    set -a
    source "$BACKEND/.env"
    set +a
  fi
  if ! "$BACKEND_PY" -m alembic upgrade head > "$LOG_DIR/alembic.log" 2>&1; then
    printf "${RED}failed${RESET}\n"
    cat "$LOG_DIR/alembic.log" >&2
    fail "alembic upgrade failed; check .dev-logs/alembic.log"
  fi
  printf "${GREEN}ok${RESET}\n"

  # 后端（.env 已由 migrate 段加载）
  printf "backend... "
  nohup "$BACKEND_PY" -m uvicorn app.main:app --reload --port 8000 > "$LOG_DIR/backend.log" 2>&1 < /dev/null &
  echo $! > "$PID_DIR/backend.pid"
  printf "${GREEN}ok${RESET}  ${DIM}http://localhost:8000${RESET}\n"

  # Celery Beat
  printf "celery-beat... "
  nohup "$BACKEND_CELERY" -A services.tasks beat --loglevel=warning > "$LOG_DIR/celery-beat.log" 2>&1 < /dev/null &
  echo $! > "$PID_DIR/celery-beat.pid"
  printf "${GREEN}ok${RESET}\n"

  # Celery Worker
  printf "celery-worker... "
  nohup "$BACKEND_CELERY" -A services.tasks worker --pool=solo --loglevel=warning > "$LOG_DIR/celery-worker.log" 2>&1 < /dev/null &
  echo $! > "$PID_DIR/celery-worker.pid"
  printf "${GREEN}ok${RESET}\n"
else
  printf "${DIM}backend/celery skipped (SKIP_BACKEND_CHECK=1)${RESET}\n"
fi

# 前端
printf "frontend... "
cd "$FRONTEND"
nohup npm run dev -- --host 0.0.0.0 --port 3000 --strictPort > "$LOG_DIR/frontend.log" 2>&1 < /dev/null &
echo $! > "$PID_DIR/frontend.pid"
printf "${GREEN}ok${RESET}  ${DIM}http://localhost:3000${RESET}\n"

printf "health... "
if [ -z "$SKIP_BACKEND_CHECK" ]; then
  wait_http "http://127.0.0.1:8000/health" "backend"
fi
wait_http "http://127.0.0.1:3000/" "frontend"
printf "${GREEN}ok${RESET}\n"

echo ""
printf "${GREEN}ready.${RESET} logs → ${DIM}.dev-logs/${RESET}  stop → ${DIM}./start-dev.sh stop${RESET}\n"
