#!/bin/bash
# Mulan BI Platform — 部署测试脚本
# 用法:
#   ./deploy-test.sh              启动全部
#   ./deploy-test.sh stop         停止全部
#   ./deploy-test.sh --clean      停止并清除日志/PID
#   ./deploy-test.sh --env <file> 指定 .env 文件（默认 .env）

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DIM='\033[2m'
RESET='\033[0m'

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
LOG_DIR="$ROOT/.dev-logs"
PID_DIR="$ROOT/.dev-pids"

# 默认 .env 文件
ENV_FILE="$ROOT/.env"

# ============ 参数解析 ============
CLEAN_MODE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    stop)
      STOP_MODE=true
      shift
      ;;
    --clean)
      CLEAN_MODE=true
      STOP_MODE=true
      shift
      ;;
    --env)
      ENV_FILE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [stop|--clean|--env <file>]"
      exit 1
      ;;
  esac
done

# ============ 加载环境变量 ============
load_env() {
  if [ -f "$ENV_FILE" ]; then
    echo "Loading env from: $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
  else
    echo "Warning: $ENV_FILE not found, using defaults"
  fi
}

# ============ 环境检查 ============
check_deps() {
  local missing=0
  for cmd in docker node python3 npm; do
    if ! command -v $cmd &> /dev/null; then
      echo "${RED}Error: $cmd not found${RESET}"
      missing=1
    fi
  done
  if [ $missing -eq 1 ]; then
    echo "${RED}Please install missing dependencies${RESET}"
    exit 1
  fi
}

# ============ 验证必需变量 ============
validate_env() {
  local missing=0
  for var in DATABASE_URL SESSION_SECRET DATASOURCE_ENCRYPTION_KEY; do
    if [ -z "${!var}" ]; then
      echo "${RED}Error: $var is not set${RESET}"
      missing=1
    fi
  done
  if [ $missing -eq 1 ]; then
    echo "${RED}Please set required environment variables in $ENV_FILE${RESET}"
    exit 1
  fi
}

# ============ 停止所有进程 ============
stop_all() {
  echo ""
  echo "Stopping all services..."
  for pidfile in "$PID_DIR"/*.pid; do
    [ -f "$pidfile" ] || continue
    pid=$(cat "$pidfile")
    name=$(basename "$pidfile" .pid)
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      printf "  ${DIM}stopped %s (pid %s)${RESET}\n" "$name" "$pid"
    fi
    rm -f "$pidfile"
  done

  # 停止 docker-compose
  docker-compose -f "$ROOT/docker-compose.yml" down --volumes 2>/dev/null || true
  docker-compose -f "$ROOT/docker-compose.yml" down 2>/dev/null || true

  if [ "$CLEAN_MODE" = true ]; then
    echo "Cleaning logs and PID files..."
    rm -rf "$LOG_DIR"/*.log
    rm -rf "$PID_DIR"/*.pid
  fi

  printf "${GREEN}All stopped${RESET}\n"
}

# ============ 等待 PostgreSQL 就绪 ============
wait_postgres() {
  printf "postgres... "
  local max_wait=30
  local count=0
  until docker exec mulan-bi-postgres pg_isready -U mulan -d mulan_bi -q 2>/dev/null; do
    sleep 1
    count=$((count + 1))
    if [ $count -ge $max_wait ]; then
      echo "${RED}failed (timeout after ${max_wait}s)${RESET}"
      exit 1
    fi
  done
  printf "${GREEN}ok${RESET}\n"
}

# ============ 等待后端健康 ============
wait_backend_healthy() {
  printf "backend health... "
  local max_wait=30
  local count=0
  until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
    sleep 2
    count=$((count + 2))
    if [ $count -ge $max_wait ]; then
      echo "${RED}failed (timeout after ${max_wait}s)${RESET}"
      return 1
    fi
  done
  printf "${GREEN}ok${RESET}\n"
}

# ============ 主流程 ============
main() {
  echo "============================================"
  echo "Mulan BI Platform — Deploy Test Environment"
  echo "============================================"
  echo ""

  mkdir -p "$LOG_DIR" "$PID_DIR"

  # 停止旧进程
  stop_all 2>/dev/null || true

  # 加载环境变量
  load_env

  # 环境检查
  check_deps

  # 验证必需变量
  validate_env

  echo ""
  echo ">>> Step 1: Starting Docker infrastructure..."
  docker-compose -f "$ROOT/docker-compose.yml" up -d --quiet-pull
  printf "docker-compose... ${GREEN}ok${RESET}\n"

  echo ""
  echo ">>> Step 2: Waiting for PostgreSQL..."
  wait_postgres

  echo ""
  echo ">>> Step 3: Running database migrations..."
  printf "alembic upgrade... "
  cd "$BACKEND"
  alembic upgrade head > "$LOG_DIR/alembic.log" 2>&1
  printf "${GREEN}ok${RESET}\n"

  echo ""
  echo ">>> Step 4: Starting backend (uvicorn)..."
  printf "backend... "
  uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$LOG_DIR/backend.log" 2>&1 &
  echo $! > "$PID_DIR/backend.pid"
  printf "${GREEN}ok${RESET}\n"

  echo ""
  echo ">>> Step 5: Waiting for backend to be healthy..."
  wait_backend_healthy

  echo ""
  echo ">>> Step 6: Running seed data script..."
  printf "seed data... "
  python3 "$ROOT/scripts/seed_demo.py" > "$LOG_DIR/seed.log" 2>&1 || {
    echo "${YELLOW}Warning: seed script failed, continuing...${RESET}"
  }
  printf "${GREEN}ok${RESET}\n"

  echo ""
  echo ">>> Step 7: Starting Celery Beat..."
  printf "celery-beat... "
  cd "$BACKEND"
  celery -A services.tasks beat --loglevel=warning > "$LOG_DIR/celery-beat.log" 2>&1 &
  echo $! > "$PID_DIR/celery-beat.pid"
  printf "${GREEN}ok${RESET}\n"

  echo ""
  echo ">>> Step 8: Starting Celery Worker..."
  printf "celery-worker... "
  celery -A services.tasks worker --pool=solo --loglevel=warning > "$LOG_DIR/celery-worker.log" 2>&1 &
  echo $! > "$PID_DIR/celery-worker.pid"
  printf "${GREEN}ok${RESET}\n"

  echo ""
  echo ">>> Step 9: Building frontend..."
  printf "frontend build... "
  cd "$FRONTEND"
  npm ci > "$LOG_DIR/npm-ci.log" 2>&1
  npm run build > "$LOG_DIR/npm-build.log" 2>&1
  printf "${GREEN}ok${RESET}\n"

  echo ""
  echo ">>> Step 10: Starting frontend server..."
  printf "frontend serve... "
  npx serve out -l 3000 -s > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$PID_DIR/frontend.pid"
  printf "${GREEN}ok${RESET}\n"

  echo ""
  echo "============================================"
  printf "${GREEN}ready!${RESET}\n"
  echo "============================================"
  echo ""
  echo "  Frontend:  ${DIM}http://localhost:3000${RESET}"
  echo "  Backend:   ${DIM}http://localhost:8000${RESET}"
  echo "  API Docs:  ${DIM}http://localhost:8000/docs${RESET}"
  echo ""
  echo "  Test accounts:"
  echo "    admin     / admin123     (admin role)"
  echo "    data_admin1 / test123    (data_admin role)"
  echo "    analyst1  / test123      (analyst role)"
  echo "    user1     / test123      (user role)"
  echo ""
  echo "  Logs:     ${DIM}$LOG_DIR/${RESET}"
  echo "  PIDs:     ${DIM}$PID_DIR/${RESET}"
  echo ""
  echo "  Stop:     ${DIM}$0 stop${RESET}"
  echo "  Clean:    ${DIM}$0 --clean${RESET}"
  echo "============================================"
}

# ============ 执行 ============
if [ "${STOP_MODE:-false}" = true ]; then
  stop_all
  exit 0
fi

main