#!/usr/bin/env bash
# SSE 契约哨兵：检测到 API 层变更时，注入上下文要求 Claude 派子代理核对协议
set -uo pipefail

f=$(jq -r '.tool_input.file_path // empty' 2>/dev/null)
[[ -z "$f" ]] && exit 0

# 跳过契约文件自身的编辑（避免循环触发）
echo "$f" | grep -q 'ask_data_contract' && exit 0

if echo "$f" | grep -qE 'backend/app/api/|frontend/src/api/'; then
  printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"[SSE契约哨兵] API层文件已变更：%s\\n请立即派一个子代理完成以下任务：\\n1. 读取 frontend/src/api/ask_data_contract.ts\\n2. 读取刚才修改的文件\\n3. 逐项检查字段名、类型、HTTP状态码、SSE事件格式是否与契约一致\\n4. 发现冲突直接列出，不要等待用户发现"}}\n' "$f"
fi
exit 0
