#!/usr/bin/env bash
# Inject context when backend API/service or frontend API layer files change,
# to prevent frontend/backend logic drift.
set -uo pipefail

f=$(jq -r '.tool_input.file_path // empty' 2>/dev/null)
[[ -z "$f" ]] && exit 0

if echo "$f" | grep -qE 'backend/app/api/|backend/services/'; then
  printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"[契约警告] 修改了后端 API/Service 文件。确认前端 frontend/src/ 的 API 调用和 TypeScript 类型是否需要同步，防止前后端接口断层。"}}\n'
elif echo "$f" | grep -qE 'frontend/src/(api|services|hooks)/'; then
  printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"[契约警告] 修改了前端 API 层文件。确认后端接口定义是否仍一致，防止前后端接口断层。"}}\n'
fi
exit 0
