#!/usr/bin/env bash
# PostToolUse 钩子：
#   1. 非法命名拦截器 — 检测到 HANDOVER.md 写入时立即阻塞
#   2. 交接制品完整性检查 — IMPLEMENTATION_NOTES.md 写入后验证必要制品
#   3. 禁止删除交接制品 — 检测到删除 IMPLEMENTATION_NOTES.md 时立即阻塞
# 从 stdin 读取 Claude Code 传入的 JSON tool 事件

set -euo pipefail

# 读取 stdin（Claude Code 传入的工具调用信息）
INPUT=$(cat)

# 解析 tool_name 和 file_path
TOOL_NAME=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('tool_name', ''))
except:
    print('')
" 2>/dev/null || true)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    path = data.get('tool_input', {}).get('file_path', '')
    print(path)
except:
    print('')
" 2>/dev/null || true)

# ── 非法命名拦截器（Write / Edit / MultiEdit）─────────────────────────────────
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

# ── 禁止删除交接制品（Delete 工具）────────────────────────────────────────────
if [[ "$TOOL_NAME" == "Delete" ]]; then
  for required in "IMPLEMENTATION_NOTES.md"; do
    if [[ "$FILE_PATH" == *"$required" ]]; then
      echo "❌ [禁止删除交接制品] 检测到删除 $required"
      echo ""
      echo "   交接制品不得删除，流水线不得逆向推进。"
      echo "   如需废弃，请走 ADR 登记后重新生成。"
      echo "   规则来源：AGENT_PIPELINE.md 铁规则 #7"
      exit 1
    fi
  done
  # Delete 其他文件直接放行
  exit 0
fi

# ── 交接制品完整性检查（仅 Write / Edit / MultiEdit 触发）──────────────────────
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
