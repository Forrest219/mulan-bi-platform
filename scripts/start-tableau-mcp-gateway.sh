#!/usr/bin/env bash
# start-tableau-mcp-gateway.sh
# 为每个 type='tableau' 且 is_active=true 的 mcp_servers 记录启动一个独立 Gateway 进程。
# 端口从 BASE_PORT (3927) 开始依次分配，并自动回写 server_url 到 mcp_servers 表。
#
# 依赖：node + npm（安装 @tableau/mcp-server）、python3（运行 FastAPI）
# 凭据：从 mulan 数据库 mcp_servers 表自动读取（无明文写入 git）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_DIR="$SCRIPT_DIR/../tableau-mcp-gateway"
BACKEND_ENV="$SCRIPT_DIR/../backend/.env"
BASE_PORT="${GATEWAY_BASE_PORT:-3927}"

cd "$GATEWAY_DIR"

# ── 1. 加载后端 .env ──────────────────────────────────────────────────────────
if [ -f "$BACKEND_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$BACKEND_ENV"
  set +a
  echo "[gateway] Loaded env from $BACKEND_ENV"
else
  echo "[gateway] WARNING: $BACKEND_ENV not found — DB credentials may be missing"
fi

# ── 2. 安装 npm 依赖 ──────────────────────────────────────────────────────────
if [ ! -d "node_modules/@tableau/mcp-server" ]; then
  echo "[gateway] Installing @tableau/mcp-server via npm..."
  npm install --prefer-offline 2>&1 | tail -5
  echo "[gateway] npm install done"
fi

# ── 3. 安装 Python 依赖 ───────────────────────────────────────────────────────
pip3 install -q -r requirements.txt

# ── 4. 枚举活跃 Tableau 配置，按 id 排序 ─────────────────────────────────────
CONFIGS=$(python3 - <<'PYEOF'
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../backend") if False else
               os.path.abspath("../backend"))
from dotenv import load_dotenv
load_dotenv("../backend/.env")
from app.core.database import SessionLocal
from services.mcp.models import McpServer
db = SessionLocal()
try:
    rows = (db.query(McpServer)
            .filter(McpServer.type == "tableau", McpServer.is_active.is_(True))
            .order_by(McpServer.id).all())
    for row in rows:
        print(row.id)
finally:
    db.close()
PYEOF
)

if [ -z "$CONFIGS" ]; then
  echo "[gateway] No active Tableau configs in DB — exiting"
  exit 1
fi

# ── 5. 为每个配置分配端口，回写 server_url，启动进程 ─────────────────────────
PORT=$BASE_PORT
PIDS=()

for CONFIG_ID in $CONFIGS; do
  SERVER_URL="http://localhost:$PORT/tableau-mcp"

  echo "[gateway] config_id=$CONFIG_ID → $SERVER_URL"

  # 回写 server_url（让 mcp-configs/test 能用正确的 endpoint 测试）
  python3 - <<PYEOF
import sys, os
sys.path.insert(0, os.path.abspath("../backend"))
from dotenv import load_dotenv
load_dotenv("../backend/.env")
from app.core.database import SessionLocal
from services.mcp.models import McpServer
db = SessionLocal()
try:
    row = db.query(McpServer).filter(McpServer.id == $CONFIG_ID).first()
    if row and row.server_url != "$SERVER_URL":
        row.server_url = "$SERVER_URL"
        db.commit()
        print(f"[gateway]   updated server_url → $SERVER_URL")
finally:
    db.close()
PYEOF

  GATEWAY_PORT=$PORT GATEWAY_CONFIG_ID=$CONFIG_ID python3 main.py &
  LAST_PID=$!
  PIDS+=($LAST_PID)
  echo "[gateway]   PID=$LAST_PID listening on :$PORT"

  PORT=$((PORT + 1))
done

echo "[gateway] All ${#PIDS[@]} gateway(s) started. Waiting..."
wait "${PIDS[@]}"
