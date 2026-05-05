#!/bin/bash
#
# start-mcp-servers.sh — 启动 / 停止 Mulan 所有 MCP Server（Streamable-HTTP 模式）
#
# 用法:
#   ./start-mcp-servers.sh start        启动全部
#   ./start-mcp-servers.sh stop         停止全部
#   ./start-mcp-servers.sh restart      重启
#   ./start-mcp-servers.sh status       查看运行状态
#
# 凭证替换方式（两种）：
#   方式 1：直接修改下方 DEFAULT_* 变量（适合本地开发）
#   方式 2：环境变量（适合生产 / Docker 部署）
#
# ──────────────────────────────────────────────────────────
# 可配置的凭证（优先读取环境变量，未设则用默认值）
# ──────────────────────────────────────────────────────────

# ── Tableau MCP ──────────────────────────────────────────
TABLEAU_MCP_PORT="${TABLEAU_MCP_PORT:-3927}"
TABLEAU_SERVER_URL="${TABLEAU_SERVER_URL:-https://online.tableau.com}"
TABLEAU_SITE_NAME="${TABLEAU_SITE_NAME:-}"
TABLEAU_PAT_NAME="${TABLEAU_PAT_NAME:-}"
TABLEAU_PAT_VALUE="${TABLEAU_PAT_VALUE:-}"

# ── StarRocks MCP ────────────────────────────────────────
# 注意：默认 8000 会被 Mulan 后端占用，优先使用 8002
STARROCKS_MCP_PORT="${STARROCKS_MCP_PORT:-8002}"
STARROCKS_HOST="${STARROCKS_HOST:-10.69.65.62}"
STARROCKS_PORT="${STARROCKS_PORT:-8090}"
STARROCKS_USER="${STARROCKS_USER:-admin}"
STARROCKS_PASSWORD="${STARROCKS_PASSWORD:-}"
STARROCKS_DB="${STARROCKS_DB:-}"

# ── MySQL MCP ────────────────────────────────────────────
MYSQL_MCP_PORT="${MYSQL_MCP_PORT:-3000}"
MYSQL_HOST="${MYSQL_HOST:-localhost}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-}"
MYSQL_DATABASE="${MYSQL_DATABASE:-}"

# ──────────────────────────────────────────────────────────
# 路径配置（通常不需要修改）
# ──────────────────────────────────────────────────────────

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_MCP="$ROOT/.venv-mcp"
LOG_DIR="$ROOT/.dev-logs/mcp"
PID_DIR="$ROOT/.dev-pids"

# PID 文件名
TABLEAU_MCP_PID="$PID_DIR/tableau-mcp.pid"
STARROCKS_MCP_PID="$PID_DIR/starrocks-mcp.pid"
MYSQL_MCP_PID="$PID_DIR/mysql-mcp.pid"

# ──────────────────────────────────────────────────────────
# 颜色输出
# ──────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DIM='\033[2m'
RESET='\033[0m'

info()    { echo -e "${GREEN}[INFO]${RESET}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
running() { echo -e "${DIM}[...]${RESET}  $*"; }

# ──────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────

ensure_dirs() {
  mkdir -p "$LOG_DIR" "$PID_DIR"
}

is_running() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    # PID 文件存在但进程已死，清理
    rm -f "$pid_file"
  fi
  return 1
}

get_pid() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && cat "$pid_file"
}

wait_for_port() {
  local port="$1"
  local timeout="${2:-10}"
  local count=0
  while ! nc -z localhost "$port" 2>/dev/null && ((count < timeout)); do
    sleep 1
    ((count++))
  done
  if nc -z localhost "$port" 2>/dev/null; then
    return 0
  fi
  return 1
}

# ──────────────────────────────────────────────────────────
# 启动函数
# ──────────────────────────────────────────────────────────

start_tableau_mcp() {
  if is_running "$TABLEAU_MCP_PID"; then
    warn "Tableau MCP 已运行 (PID=$(get_pid "$TABLEAU_MCP_PID"))，跳过"
    return 0
  fi

  if [[ -z "$TABLEAU_PAT_VALUE" ]]; then
    warn "TABLEAU_PAT_VALUE 未设置，跳过启动 Tableau MCP"
    return 1
  fi

  ensure_dirs
  info "启动 Tableau MCP :$TABLEAU_MCP_PORT ..."

  # Tableau MCP server 通过环境变量注入凭证
  TABLEAU_MCP_LOG="$LOG_DIR/tableau-mcp.log"

  nohup uv run --with tableau-mcp-server tableau_mcp_server \
    --port "$TABLEAU_MCP_PORT" \
    --tableau-server "$TABLEAU_SERVER_URL" \
    --site "$TABLEAU_SITE_NAME" \
    --token-name "$TABLEAU_PAT_NAME" \
    --token-value "$TABLEAU_PAT_VALUE" \
    > "$TABLEAU_MCP_LOG" 2>&1 &

  local pid=$!
  echo "$pid" > "$TABLEAU_MCP_PID"
  echo -e "${DIM}  PID=$pid  log=$TABLEAU_MCP_LOG${RESET}"

  if wait_for_port "$TABLEAU_MCP_PORT" 15; then
    info "Tableau MCP 已就绪 :$TABLEAU_MCP_PORT"
  else
    error "Tableau MCP 启动超时，查看日志：$TABLEAU_MCP_LOG"
    cat "$TABLEAU_MCP_LOG" >&2
    rm -f "$TABLEAU_MCP_PID"
    return 1
  fi
}

start_starrocks_mcp() {
  if is_running "$STARROCKS_MCP_PID"; then
    warn "StarRocks MCP 已运行 (PID=$(get_pid "$STARROCKS_MCP_PID"))，跳过"
    return 0
  fi

  if [[ -z "$STARROCKS_PASSWORD" ]]; then
    warn "STARROCKS_PASSWORD 未设置，跳过启动 StarRocks MCP"
    return 1
  fi

  ensure_dirs
  info "启动 StarRocks MCP :$STARROCKS_MCP_PORT ..."

  local STARROCKS_MCP_LOG="$LOG_DIR/starrocks-mcp.log"

  # 优先用预装的 venv（更快），没有则用 uv run --with
  if [[ -f "$VENV_MCP/bin/mcp-server-starrocks" ]]; then
    nohup STARROCKS_HOST="$STARROCKS_HOST" \
      STARROCKS_PORT="$STARROCKS_PORT" \
      STARROCKS_USER="$STARROCKS_USER" \
      STARROCKS_PASSWORD="$STARROCKS_PASSWORD" \
      STARROCKS_DB="$STARROCKS_DB" \
      "$VENV_MCP/bin/mcp-server-starrocks" \
      --mode streamable-http \
      --port "$STARROCKS_MCP_PORT" \
      > "$STARROCKS_MCP_LOG" 2>&1 &
  else
    nohup uv run --with mcp-server-starrocks mcp-server-starrocks \
      --mode streamable-http \
      --port "$STARROCKS_MCP_PORT" \
      > "$STARROCKS_MCP_LOG" 2>&1 &
  fi

  local pid=$!
  echo "$pid" > "$STARROCKS_MCP_PID"
  echo -e "${DIM}  PID=$pid  log=$STARROCKS_MCP_LOG${RESET}"

  if wait_for_port "$STARROCKS_MCP_PORT" 15; then
    info "StarRocks MCP 已就绪 :$STARROCKS_MCP_PORT"
  else
    error "StarRocks MCP 启动超时，查看日志：$STARROCKS_MCP_LOG"
    cat "$STARROCKS_MCP_LOG" >&2
    rm -f "$STARROCKS_MCP_PID"
    return 1
  fi
}

start_mysql_mcp() {
  if is_running "$MYSQL_MCP_PID"; then
    warn "MySQL MCP 已运行 (PID=$(get_pid "$MYSQL_MCP_PID"))，跳过"
    return 0
  fi

  if [[ -z "$MYSQL_PASSWORD" ]]; then
    warn "MYSQL_PASSWORD 未设置，跳过启动 MySQL MCP"
    return 1
  fi

  ensure_dirs
  info "启动 MySQL MCP :$MYSQL_MCP_PORT ..."

  local MYSQL_MCP_LOG="$LOG_DIR/mysql-mcp.log"

  nohup uv run --with mcp-server-mysql mcp-server-mysql \
    --host localhost \
    --port "$MYSQL_MCP_PORT" \
    > "$MYSQL_MCP_LOG" 2>&1 &

  local pid=$!
  echo "$pid" > "$MYSQL_MCP_PID"
  echo -e "${DIM}  PID=$pid  log=$MYSQL_MCP_LOG${RESET}"

  if wait_for_port "$MYSQL_MCP_PORT" 15; then
    info "MySQL MCP 已就绪 :$MYSQL_MCP_PORT"
  else
    error "MySQL MCP 启动超时，查看日志：$MYSQL_MCP_LOG"
    cat "$MYSQL_MCP_LOG" >&2
    rm -f "$MYSQL_MCP_PID"
    return 1
  fi
}

stop_mcp() {
  local name="$1"
  local pid_file="$2"

  if ! is_running "$pid_file"; then
    warn "$name 未运行，跳过"
    return 0
  fi

  local pid="$(get_pid "$pid_file")"
  info "停止 $name (PID=$pid) ..."
  kill "$pid" 2>/dev/null || true

  # 等待最多 5 秒
  for i in {1..5}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pid_file"
      info "$name 已停止"
      return 0
    fi
    sleep 1
  done

  # 强制 kill
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$pid_file"
  warn "$name 强制终止"
}

status_mcp() {
  local name="$1"
  local pid_file="$2"
  local port="$3"

  if is_running "$pid_file"; then
    echo -e "${GREEN}●${RESET} $name  运行中 (PID=$(get_pid "$pid_file"))  :$port"
  else
    echo -e "${RED}○${RESET} $name  已停止"
  fi
}

# ──────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────

main() {
  local action="${1:-start}"

  case "$action" in
    start)
      info "=== 启动 MCP Servers ==="
      start_tableau_mcp  || true
      start_starrocks_mcp || true
      start_mysql_mcp    || true
      echo ""
      info "=== 状态 ==="
      status_mcp "Tableau MCP"   "$TABLEAU_MCP_PID"   "$TABLEAU_MCP_PORT"
      status_mcp "StarRocks MCP" "$STARROCKS_MCP_PID" "$STARROCKS_MCP_PORT"
      status_mcp "MySQL MCP"     "$MYSQL_MCP_PID"     "$MYSQL_MCP_PORT"
      ;;

    stop)
      info "=== 停止 MCP Servers ==="
      stop_mcp "Tableau MCP"   "$TABLEAU_MCP_PID"
      stop_mcp "StarRocks MCP" "$STARROCKS_MCP_PID"
      stop_mcp "MySQL MCP"     "$MYSQL_MCP_PID"
      ;;

    restart)
      "$0" stop
      sleep 2
      "$0" start
      ;;

    status)
      status_mcp "Tableau MCP"   "$TABLEAU_MCP_PID"   "$TABLEAU_MCP_PORT"
      status_mcp "StarRocks MCP" "$STARROCKS_MCP_PID" "$STARROCKS_MCP_PORT"
      status_mcp "MySQL MCP"     "$MYSQL_MCP_PID"     "$MYSQL_MCP_PORT"
      ;;

    *)
      echo "用法: $0 {start|stop|restart|status}"
      exit 1
      ;;
  esac
}

main "$@"
