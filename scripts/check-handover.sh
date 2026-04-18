#!/usr/bin/env bash
# PostToolUse 钩子：
#   1. 非法命名拦截器 — 检测到 HANDOVER.md 写入时立即阻塞
#   2. 交接制品完整性检查 — IMPLEMENTATION_NOTES.md 写入后验证必要制品
# 从 stdin 读取 Claude Code 传入的 JSON tool 事件

set -euo pipefail

# 读取 stdin（Claude Code 传入的工具调用信息）
INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    path = data.get('tool_input', {}).get('file_path', '')
    print(path)
except:
    print('')
" 2>/dev/null || true)

# ── 非法命名拦截器 ─────────────────────────────────────────────────────────────
# 交接制品必须使用 IMPLEMENTATION_NOTES.md，禁止使用 HANDOVER.md 等非规范名称
ILLEGAL_NAMES=("HANDOVER.md" "handover.md" "Handover.md")
for illegal in "${ILLEGAL_NAMES[@]}"; do
  if [[ "$FILE_PATH" == *"$illegal" ]]; then
    echo "❌ [非法命名拦截] 检测到写入 $illegal"
    echo ""
    echo "   交接制品命名规范：IMPLEMENTATION_NOTES.md"
    echo "   禁止使用：$illegal"
    echo ""
    echo "   请重命名后重试。规则来源：AGENT_PIPELINE.md 铁规则 #7"
    exit 1
  fi
done

# ── 交接制品完整性检查 ──────────────────────────────────────────────────────────
if [[ "$FILE_PATH" != *"IMPLEMENTATION_NOTES.md" ]]; then
  exit 0
fi

echo "=== 交接制品检查（检测到 IMPLEMENTATION_NOTES.md 写入）==="

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MISSING=()

# 必须存在的制品
REQUIRED=(
  "IMPLEMENTATION_NOTES.md"
)

for artifact in "${REQUIRED[@]}"; do
  if ! find "$ROOT" -maxdepth 2 -name "$artifact" | grep -q .; then
    MISSING+=("$artifact")
  fi
done

if [ ${#MISSING[@]} -eq 0 ]; then
  echo "✅ 交接制品完整"
  exit 0
fi

echo "❌ 缺少以下交接制品，流水线不得推进："
for m in "${MISSING[@]}"; do
  echo "  - $m"
done
echo ""
echo "请补齐后再标记阶段完成。"
exit 1
