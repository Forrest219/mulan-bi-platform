#!/usr/bin/env bash
# start-all.sh — 一键启动 Mulan BI Platform 所有服务
#
# 启动顺序：
#   1. Docker (postgres + redis)   — 等待 postgres healthy
#   2. Backend (uvicorn :8000)     — 等待 /health 就绪
#   3. MCP Gateway (3927+)         — 后台运行
#   4. Frontend (vite :3000)       — 前台运行（Ctrl+C 终止所有）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[start-all]${NC} $*"; }
warn()  { echo -e "${YELLOW}[start-all]${NC} $*"; }
error() { echo -e "${RED}[start-all]${NC} $*" >&2; }

# ── 退出时清理后台进程 ──────────────────────────────────────────────────────
BACKEND_PID=""
GATEWAY_PID=""

cleanup() {
  echo ""
  info "正在停止后台服务..."
  [ -n "$GATEWAY_PID" ] && kill "$GATEWAY_PID" 2>/dev/null && info "  MCP Gateway 已停止 (PID $GATEWAY_PID)"
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null && info "  Backend 已停止 (PID $BACKEND_PID)"
  info "完成。Docker 服务仍在后台运行，如需停止：docker-compose down"
}
trap cleanup EXIT INT TERM

# ── 1. Docker ─────────────────────────────────────────────────────────────────
info "启动 Docker 服务 (postgres + redis)..."
cd "$SCRIPT_DIR"
docker-compose up -d postgres redis 2>&1 | grep -v "^$" || true

info "等待 postgres 就绪..."
MAX_WAIT=60
WAITED=0
until docker-compose exec -T postgres pg_isready -U mulan -d mulan_bi -q 2>/dev/null; do
  if [ $WAITED -ge $MAX_WAIT ]; then
    error "Postgres 在 ${MAX_WAIT}s 内未就绪，请检查 Docker 日志"
    exit 1
  fi
  sleep 2
  WAITED=$((WAITED + 2))
done
info "  postgres 已就绪 (${WAITED}s)"

# ── 2. Alembic 迁移 ────────────────────────────────────────────────────────────
info "运行数据库迁移..."
cd "$BACKEND_DIR"
if [ -f ".env" ]; then
  set -a; source .env; set +a
fi
alembic upgrade head 2>&1 | tail -3
info "  迁移完成"

# ── 3. Backend ────────────────────────────────────────────────────────────────
info "启动 Backend (uvicorn :8000)..."
cd "$BACKEND_DIR"
uvicorn app.main:app --reload --port 8000 > /tmp/mulan-backend.log 2>&1 &
BACKEND_PID=$!
info "  Backend PID=${BACKEND_PID}, log: /tmp/mulan-backend.log"

info "等待 Backend /health 就绪..."
MAX_WAIT=30
WAITED=0
until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
  if [ $WAITED -ge $MAX_WAIT ]; then
    error "Backend 在 ${MAX_WAIT}s 内未响应。最后 10 行日志："
    tail -10 /tmp/mulan-backend.log >&2
    exit 1
  fi
  sleep 2
  WAITED=$((WAITED + 2))
done
info "  Backend 已就绪 (${WAITED}s)"

# ── 4. MCP Gateway ────────────────────────────────────────────────────────────
info "启动 MCP Gateway..."
cd "$SCRIPT_DIR"
bash scripts/start-tableau-mcp-gateway.sh > /tmp/mulan-mcp-gateway.log 2>&1 &
GATEWAY_PID=$!
info "  MCP Gateway PID=${GATEWAY_PID}, log: /tmp/mulan-mcp-gateway.log"

# 给 Gateway 3s 初始化，检查是否立即退出
sleep 3
if ! kill -0 "$GATEWAY_PID" 2>/dev/null; then
  warn "  MCP Gateway 启动失败（可能没有活跃的 Tableau 配置）"
  warn "  查看日志：cat /tmp/mulan-mcp-gateway.log"
  GATEWAY_PID=""
fi

# ── 5. Frontend ───────────────────────────────────────────────────────────────
echo ""
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "  所有后台服务已启动"
info "  后端    http://localhost:8000"
info "  前端    http://localhost:3000  (启动中...)"
info "  按 Ctrl+C 停止所有服务"
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd "$FRONTEND_DIR"
npm run dev
