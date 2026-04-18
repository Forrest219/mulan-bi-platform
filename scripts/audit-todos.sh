#!/usr/bin/env bash
# 扫描裸 TODO 注释（未经 ADR 登记的临时代码）
# 通过：无输出，exit 0
# 失败：打印违规位置，exit 1

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Audit: 扫描裸 TODO ==="

# 搜索裸 TODO（不含 EMERGENCY-ADR 前缀）
RESULTS=$(grep -rn "TODO" \
  --include="*.py" \
  --include="*.ts" \
  --include="*.tsx" \
  "$ROOT/backend" "$ROOT/frontend/src" 2>/dev/null \
  | grep -v "EMERGENCY-ADR" \
  | grep -v "node_modules" \
  | grep -v ".pyc" \
  || true)

if [ -z "$RESULTS" ]; then
  echo "✅ 无裸 TODO，通过"
  exit 0
fi

echo "❌ 发现裸 TODO（必须登记 ADR 或移除）："
echo "$RESULTS"
echo ""
echo "修复方式："
echo "  - 登记紧急豁免：docs/adr/ADR-XXXX-emergency-<topic>.md"
echo "  - 替换注释为：# EMERGENCY-ADR-XXXX"
echo "  - 或直接实现，删除 TODO"
exit 1
