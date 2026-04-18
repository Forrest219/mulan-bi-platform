#!/usr/bin/env bash
# =============================================================================
# Eval: 陷阱 3 — <a href> 触发全页刷新（应用内路由应用 Link）
#
# 扫描 frontend/src 中所有以 / 开头（内部路径）、不含 http 的 <a href 用法。
# 这类用法会触发全页刷新，破坏 SPA 路由状态。
# 应替换为 react-router-dom 的 <Link to="..."> 或 <NavLink to="...">。
#
# 退出码：
#   0 — 未发现问题（PASS）
#   1 — 发现可疑的 <a href 内部链接（FAIL，需人工复核）
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SRC_DIR="${PROJECT_ROOT}/frontend/src"

echo "====================================================="
echo "Eval: 陷阱 3 — 内部 <a href> 链接审计"
echo "扫描目录: ${SRC_DIR}"
echo "====================================================="

if [ ! -d "${SRC_DIR}" ]; then
  echo "ERROR: 目录不存在 — ${SRC_DIR}"
  exit 1
fi

# 匹配模式说明：
# - href=["']/     : href 属性值以 / 开头（内部路径）
# - 排除 http/https: 避免误报外部链接（如 href="https://..."）
# - 文件类型：.tsx .ts .jsx .js
# - 排除 node_modules 和 out（构建产物）

FOUND=$(grep -rn \
  --include="*.tsx" --include="*.ts" --include="*.jsx" --include="*.js" \
  --exclude-dir="node_modules" --exclude-dir="out" --exclude-dir=".git" \
  -E 'href=["'"'"'][/][^"'"'"'hH]' \
  "${SRC_DIR}" 2>/dev/null || true)

# 额外过滤：排除已包含 http 或 # 锚点的行（二次保险）
FILTERED=$(echo "${FOUND}" | grep -v 'http' | grep -v 'href="#' | grep -v 'href='"'"'#' || true)

if [ -z "${FILTERED}" ]; then
  echo ""
  echo "✅ PASS — 未发现内部 <a href> 路径链接"
  echo "所有内部导航应已使用 <Link to=\"...\"> 或 <NavLink to=\"...\">。"
  exit 0
else
  echo ""
  echo "❌ FAIL — 发现以下可疑的内部 <a href> 用法（可能触发全页刷新）："
  echo "-----------------------------------------------------"
  echo "${FILTERED}"
  echo "-----------------------------------------------------"
  COUNT=$(echo "${FILTERED}" | grep -c . || true)
  echo "共 ${COUNT} 处，请替换为 react-router-dom 的 <Link to=\"...\">。"
  exit 1
fi
