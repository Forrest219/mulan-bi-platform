#!/usr/bin/env bash
# 扫描过期的 Emergency ADR（失效日期 ≤ 今天）
# 通过：无过期 ADR，exit 0
# 失败：打印过期 ADR 列表，exit 1

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADR_DIR="$ROOT/docs/adr"
TODAY=$(date +%Y-%m-%d)

echo "=== Audit: 扫描过期 Emergency ADR（今天：$TODAY）==="

if [ ! -d "$ADR_DIR" ]; then
  echo "✅ docs/adr/ 目录不存在，无 ADR，通过"
  exit 0
fi

EXPIRED=()

for file in "$ADR_DIR"/ADR-*-emergency-*.md; do
  [ -f "$file" ] || continue

  # 从文件中提取"失效日期"字段（格式：失效日期: YYYY-MM-DD）
  EXPIRY=$(grep -i "失效日期\|expiry\|expires" "$file" | grep -oE "[0-9]{4}-[0-9]{2}-[0-9]{2}" | head -1 || true)

  if [ -z "$EXPIRY" ]; then
    echo "⚠️  $(basename "$file")：未找到失效日期字段，视为不合规"
    EXPIRED+=("$file")
    continue
  fi

  if [[ "$EXPIRY" < "$TODAY" || "$EXPIRY" == "$TODAY" ]]; then
    echo "❌ $(basename "$file")：失效日期 $EXPIRY 已过期"
    EXPIRED+=("$file")
  fi
done

if [ ${#EXPIRED[@]} -eq 0 ]; then
  echo "✅ 无过期 ADR，通过"
  exit 0
fi

echo ""
echo "发布被阻塞：${#EXPIRED[@]} 个 Emergency ADR 已过期未清理"
echo "处理方式："
echo "  1. 实现长期方案，删除 ADR 文件及代码中对应的 EMERGENCY-ADR 注释"
echo "  2. 若需要延期，更新 ADR 失效日期并说明原因（需 Human 确认）"
exit 1
