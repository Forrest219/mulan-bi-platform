#!/usr/bin/env bash
# =============================================================================
# PreToolUse 防护脚本
#
# 在每次工具执行前拦截危险操作：
#   - Bash: 只允许白名单命令
#   - Write/Edit: 禁止修改 .claude/settings.json 和迁移文件
#   - 高危参数组合拦截
#
# stdin: Claude Code 传入的 JSON tool 事件
# 退出码：0=允许，1=拒绝
# =============================================================================

set -euo pipefail

INPUT=$(cat)

# 解析 tool_name
TOOL_NAME=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('tool_name', ''))
except:
    print('')
" 2>/dev/null || true)

# 解析 tool_input（主要是 Bash 的 command 参数）
TOOL_INPUT=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    inp = data.get('tool_input', {})
    # Write/Edit/Delete 工具
    if 'file_path' in inp:
        print('PATH:' + inp['file_path'])
    # Bash 工具
    if 'command' in inp:
        print('CMD:' + inp['command'])
except:
    print('')
" 2>/dev/null || true)

# ── 1. Bash 命令白名单 ─────────────────────────────────────────────────────
if [[ "$TOOL_NAME" == "Bash" ]]; then
  CMD=$(echo "$TOOL_INPUT" | sed 's/^CMD://')

  # 精确白名单（禁止通配扩展）
  ALLOWED_CMDS=(
    # 前端
    "cd frontend && npm run lint"
    "cd frontend && npm run type-check"
    "cd frontend && npm run build"
    "cd frontend && npm run test"
    "cd frontend && npx playwright test"
    "cd frontend && npx playwright install"
    "cd frontend && npm ci"
    "cd frontend && npm run dev"
    # 后端
    "cd backend && ruff check ."
    "cd backend && python3 -m py_compile"
    "cd backend && alembic upgrade head"
    "cd backend && alembic downgrade"
    "cd backend && pytest"
    "cd backend && uvicorn"
    "cd backend && pip install"
    # 审计脚本（固定调用）
    "bash scripts/audit-todos.sh"
    "bash scripts/audit-internal-links.sh"
    "bash scripts/audit-alembic-server-defaults.sh"
    "bash scripts/check-handover.sh"
    "bash scripts/pretool-guard.sh"
    "bash scripts/audit-adrs.sh"
    # Alembic（精确调用）
    "alembic upgrade head"
    "alembic downgrade"
    "alembic revision"
    # Git（只读操作）
    "git status"
    "git diff"
    "git log"
    "git show"
    "git branch"
    "git remote"
    # 环境探索
    "python3 -c"
    "node -e"
    "node --version"
    "npm --version"
    "python3 --version"
  )

  ALLOWED=0
  for allowed in "${ALLOWED_CMDS[@]}"; do
    # 精确匹配（不允许参数扩展）
    if [[ "$CMD" == "$allowed" ]]; then
      ALLOWED=1
      break
    fi
    # 前缀匹配：允许 "cd frontend && npm ci --legacy-peer-deps" 这种扩展
    prefix="${allowed} "
    if [[ "$CMD" == "$prefix"* ]]; then
      ALLOWED=1
      break
    fi
  done

  if [[ "$ALLOWED" == "0" ]]; then
    echo "❌ [PreToolUse 拒绝] Bash 命令不在白名单中："
    echo "   命令：$CMD"
    echo ""
    echo "   允许的命令仅限："
    for allowed in "${ALLOWED_CMDS[@]}"; do
      echo "     - $allowed"
    done
    echo ""
    echo "   如需新增命令，请联系维护者添加白名单。"
    exit 1
  fi

  # ── 高危参数组合拦截 ────────────────────────────────────────────────────
  DANGEROUS_PATTERNS=(
    "curl.*--data"          # 外发数据
    "wget.*-O"              # 外发下载写入
    "rm -rf /"
    "rm -rf /home"
    "chmod 777"
    "mkfs"
    "dd of=/dev/"
    "truncate -s 0.*passwd"
    "python3 -c.*import os"
    "node -e.*require('fs')"
  )

  for pattern in "${DANGEROUS_PATTERNS[@]}"; do
    if [[ "$CMD" =~ $pattern ]]; then
      echo "❌ [PreToolUse 拒绝] 检测到高危参数组合："
      echo "   命令：$CMD"
      echo "   模式：$pattern"
      exit 1
    fi
  done

  exit 0
fi

# ── 2. 写工具：禁止修改敏感文件 ─────────────────────────────────────────
FILE_PATH=$(echo "$TOOL_INPUT" | sed 's/^PATH://')

SENSITIVE_PATTERNS=(
  ".claude/settings.json"
  "backend/alembic/versions/"
  "backend/app/models/"
  "backend/app/api/"
)

for pattern in "${SENSITIVE_PATTERNS[@]}"; do
  if [[ "$FILE_PATH" == *"$pattern"* ]]; then
    echo "❌ [PreToolUse 拒绝] 禁止修改受保护文件："
    echo "   路径：$FILE_PATH"
    echo "   模式：$pattern"
    echo ""
    echo "   受保护文件包括："
    echo "     - Claude Code 设置"
    echo "     - Alembic 迁移文件（需走 ADR）"
    echo "     - 核心模型和 API（需走规范流程）"
    exit 1
  fi
done

# ── 3. 写工具：禁止通过管道写入覆盖关键文件 ──────────────────────────────
if [[ "$TOOL_NAME" == "Bash" ]]; then
  CMD=$(echo "$TOOL_INPUT" | sed 's/^CMD://')
  if [[ "$CMD" =~ \>(|.*\/)\.(github|claude|git) ]]; then
    echo "❌ [PreToolUse 拒绝] 禁止通过 Bash 重定向覆盖 Git/Claude 配置："
    echo "   命令：$CMD"
    exit 1
  fi
fi

echo "✅ [PreToolUse 通过]"
exit 0
