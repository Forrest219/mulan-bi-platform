#!/usr/bin/env bash
# =============================================================================
# Eval: 陷阱 4 — Alembic autogenerate 遗漏 server_default
#
# 扫描 backend/alembic/versions/*.py，检测存在 nullable=False 但缺少
# server_default 的列定义。
#
# 背景：
# 向已有非空数据的表添加 NOT NULL 列时，若无 server_default，
# Alembic 迁移在存量数据行上会直接失败（PostgreSQL 不允许为现有行插入 NULL）。
# autogenerate 不会自动补充 server_default，需要人工添加。
#
# 检测逻辑（静态分析，无需连接数据库）：
# 扫描 op.add_column() 调用中，sa.Column() 参数包含 nullable=False 但不含
# server_default= 的情形。
#
# 退出码：
#   0 — 未发现问题（PASS）
#   1 — 发现可疑的列定义（FAIL，需人工复核）
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSIONS_DIR="${PROJECT_ROOT}/backend/alembic/versions"

echo "====================================================="
echo "Eval: 陷阱 4 — Alembic server_default 遗漏检测"
echo "扫描目录: ${VERSIONS_DIR}"
echo "====================================================="

if [ ! -d "${VERSIONS_DIR}" ]; then
  echo "ERROR: 目录不存在 — ${VERSIONS_DIR}"
  exit 1
fi

PY_FILES=$(find "${VERSIONS_DIR}" -name "*.py" ! -name "__pycache__" | sort)

if [ -z "${PY_FILES}" ]; then
  echo "未找到任何迁移文件。"
  exit 0
fi

ISSUES=""

for f in ${PY_FILES}; do
  filename=$(basename "${f}")

  # 使用 Python 进行精确的多行模式分析
  result=$(python3 - "${f}" <<'PYEOF'
import sys
import re

filepath = sys.argv[1]
with open(filepath, encoding='utf-8') as fh:
    content = fh.read()

# 查找 op.add_column 调用块（允许多行）
# 策略：找到 op.add_column( 开始，提取到配对的右括号为止
issues = []
pos = 0
while True:
    idx = content.find('op.add_column(', pos)
    if idx == -1:
        break

    # 找到配对括号
    depth = 0
    start = idx + len('op.add_column(') - 1  # 指向第一个 (
    end = start
    for i in range(start, min(start + 2000, len(content))):
        c = content[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                end = i
                break

    snippet = content[idx:end+1]

    # 条件 1：包含 nullable=False
    has_nullable_false = bool(re.search(r'nullable\s*=\s*False', snippet))
    # 条件 2：不包含 server_default
    has_server_default = bool(re.search(r'server_default\s*=', snippet))

    if has_nullable_false and not has_server_default:
        # 获取行号
        line_no = content[:idx].count('\n') + 1
        # 提取单行摘要（去掉多余空白）
        summary = ' '.join(snippet.split())[:120]
        issues.append(f"  Line {line_no}: {summary}")

    pos = end + 1

for iss in issues:
    print(iss)
PYEOF
  )

  if [ -n "${result}" ]; then
    ISSUES="${ISSUES}\n[${filename}]\n${result}"
  fi
done

if [ -z "${ISSUES}" ]; then
  echo ""
  echo "✅ PASS — 所有 op.add_column(nullable=False) 均已包含 server_default"
  exit 0
else
  echo ""
  echo "❌ FAIL — 发现以下 nullable=False 但缺少 server_default 的列定义："
  echo "-----------------------------------------------------"
  echo -e "${ISSUES}"
  echo "-----------------------------------------------------"
  echo "修复方法：在 sa.Column() 中添加 server_default='<默认值>'，"
  echo "或在迁移的 upgrade() 中先将列设为 nullable=True，填充数据后再 ALTER NOT NULL。"
  exit 1
fi
