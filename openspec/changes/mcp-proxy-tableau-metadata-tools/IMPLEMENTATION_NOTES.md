# Implementation Notes: mcp-proxy-tableau-metadata-tools

## 开工信息

- 开工时间：2026-05-20 12:43:14 CST
- 当前 git commit：`edbfb2bee075d23bc665bac684f9cca88a9f9d13`
- 当前工作区状态：存在既有未跟踪文件 `frontend/batch2-test-run.mjs`、`inbox/20260520-12-mcp-native-homepage-qa-plan.md`、`openspec/changes/mcp-proxy-tableau-metadata-tools/`、`reports/`；本任务只修改本 change 相关文件。

## 已读取文件清单

- `openspec/changes/mcp-proxy-tableau-metadata-tools/proposal.md`
- `openspec/changes/mcp-proxy-tableau-metadata-tools/design.md`
- `openspec/changes/mcp-proxy-tableau-metadata-tools/tasks.md`
- `inbox/20260520-12-mcp-native-homepage-qa-plan.md`
- `backend/services/data_agent/mcp_proxy_main.py`
- `backend/services/data_agent/mcp_args_guardrail.py`
- `backend/services/data_agent/mcp_host/runtime.py`
- `backend/services/tableau/mcp_client.py`
- `backend/services/data_agent/mcp_first_main.py`
- `backend/services/data_agent/runner.py`
- `backend/services/data_agent/tool_base.py`
- `backend/app/api/agent.py`
- `backend/services/tableau/models.py`
- `backend/tests/services/data_agent/test_mcp_proxy_main.py`

## 实施计划

1. 梳理现有 MCP proxy、guardrail、mcp_host runtime、Tableau MCP client、renderer/response contract 代码路径。
2. 在 `mcp_proxy_main.py` 中增加 deterministic datasource resolver 和 metadata/list 控制流，保持其入口 wrapper 定位。
3. 扩展 `mcp_args_guardrail.py` 的 tool matrix，覆盖 `query-datasource`、`list-datasources`、`get-datasource-metadata` 的 scope/args/result 边界。
4. 增加 response normalizer，保证 `done.response_type` / `done.response_data` 扁平结构，并为表格响应补齐 `table_display.columns`。
5. 实现 `catalog_cache` 显式降级，满足 asset + field 完备标准，不把 schema inventory 当作成功 fallback。
6. 补充后端测试，覆盖 1/0/N 候选、cache fallback、query_result display contract。
7. 运行 py_compile 和相关 data_agent 测试；必要时记录环境限制。

## 关键设计取舍

- 复用 `mcp_host/runtime.py` 的 `MCPToolCatalog` 与 `MCPToolExecutor`，不新增独立 MCP Host 平台。
- Resolver 只做 normalize exact / contains，候选上限 5，不做中文同义词或语义推断。
- 1 候选资产介绍类问题由系统确定性调用 `get-datasource-metadata`，不交给 LLM 自由选择工具。
- `catalog_cache` 只在 MCP metadata 调用失败且本地 asset 与字段缓存完备时作为显式降级，`response_data.source` 必须为 `catalog_cache`。
- 架构歧义记录：当前 `app/api/agent.py` 的 deterministic schema_inventory 会在进入 `run_agent` 前拦截资产介绍问题，导致 MCP proxy 无法处理 metadata 工具。选择：仅在 chain selector 指向 MCP proxy 时绕过 schema_inventory，非 MCP proxy 模式保留旧行为。
- 架构歧义记录：`runner.py` 当前只对 `is_data_intent` 启用 controlled path。选择：仅当 MCP proxy 启用且 `is_asset_inventory` 时扩展进入 controlled path，避免影响 mcp-first/legacy 链路。

## Task 状态

- Task 1：已完成（清理 `run_mcp_proxy_main_path` 中 `return` 后不可达 Args 实验链路；metadata/list 新分支通过 `MCPHostRuntime` 执行）
- Task 2：已完成（resolver 使用 normalize exact/contains，候选上限 5；0/1/N 候选策略均有测试）
- Task 3：已完成（`query-datasource` 保持原校验；`list-datasources` / `get-datasource-metadata` 新增只读 scope/permission/limit 校验）
- Task 4：已完成（proxy metadata/list 分支输出扁平 envelope；runner 将 envelope 映射到 `done.response_type` / `done.response_data`，query 表格映射为 `query_result`）
- Task 5：已完成（MCP metadata 失败后仅在 asset+field 缓存完备时返回 `source="catalog_cache"`；不完备返回结构化失败）
- Task 6：已完成（新增/更新后端测试覆盖验收路径，包括 list-datasources connection access 拒绝）
- Debug 补充（2026-05-20 13:35 CST）：`run_id=d7f4e6bc-242e-4f5e-96b1-a7fb1d8b631b` 仍走 `schema_inventory`，根因是容器未启用 `DATA_AGENT_CHAIN_MODE=mcp_proxy` / `DATA_AGENT_MCP_PROXY_ENABLED=true`，且后续只 recreate 未 rebuild，容器未加载本地代码。
- Debug 修复：`docker-compose.yml` 已为 backend/celery 添加 MCP proxy flags；`runner.py` controlled path 条件补充 `route_decision.is_asset_question`，覆盖 intent classifier 返回 `unknown` 但 router guardrail 判定资产问题的场景。

## 修改文件清单

- `openspec/changes/mcp-proxy-tableau-metadata-tools/IMPLEMENTATION_NOTES.md`
- `openspec/changes/mcp-proxy-tableau-metadata-tools/tasks.md`
- `backend/services/data_agent/mcp_proxy_main.py`
- `backend/services/data_agent/mcp_args_guardrail.py`
- `backend/services/data_agent/runner.py`
- `backend/services/data_agent/tool_base.py`
- `backend/app/api/agent.py`
- `backend/tests/services/data_agent/test_mcp_proxy_main.py`
- `docker-compose.yml`

## 验证命令与结果

- `cd backend && python3 -m py_compile $(git diff --name-only | grep '\.py$')`：失败；进入 `backend/` 后 git diff 仍输出 `backend/...` 路径，导致 `FileNotFoundError: backend/app/api/agent.py`。
- `cd backend && .venv/bin/python -m py_compile $(git diff --name-only --relative=backend | grep '\.py$')`：通过。
- `cd backend && .venv/bin/python -m pytest tests/services/data_agent/test_mcp_proxy_main.py -q --no-cov`：通过，16 passed。
- `cd backend && .venv/bin/python -m pytest tests/services/data_agent/ -q --no-cov`：通过，543 passed。
- Docker smoke：`curl -sS -m 5 http://localhost:8000/health` 返回 `{"status":"ok"}`；`docker compose ps backend tableau-mcp-gateway` 显示 backend healthy、gateway running。
- Debug smoke：`docker compose up -d --build --force-recreate backend celery` 后，容器内 `select_data_agent_chain()` 返回 `selected_chain_mode=mcp_proxy`；真实请求 `介绍管理费用数据源` 返回 `response_type=asset_metadata`，`response_data.source=catalog_cache`，不再返回 24 个 datasource list。

## 已知风险/未完成项

- 已确认 `MCPToolExecutor` 可通过 `TableauMCPClient.call_tool` 执行任意 MCP tool；metadata/list 可在 proxy 入口中构造 client + catalog + executor，不需要新增 MCP Host 平台。
- 当前实现已避免 “介绍 X 数据源” 走 schema_inventory 成功 fallback：MCP proxy 模式下资产类问题进入 controlled path，由 resolver 决定 metadata/candidates/not_found。
- 初版未修改前端；Follow-up 已补齐通用结构化展示层，并运行 frontend type-check/lint/test/build。
- 当前真实请求中 `get-datasource-metadata` MCP 调用超时 `[NLQ_007] Request timed out after 29s (tools/call)`，已按设计降级到 `catalog_cache`；如 tester 要求 `source=mcp`，需要继续排查 Gateway metadata tool 性能/可用性。

## Follow-up: 通用结构化展示层

- 开工时间：2026-05-20 14:36:31 CST
- 当前 git commit：`edbfb2bee075d23bc665bac684f9cca88a9f9d13`
- 触发问题：用户提问“你有哪些数据源？”时，后端 `response_data.candidates` 已包含正确清单，但前端只展示 answer 文本，形成一长句。
- 关联 run：`814c0b3f-441a-4953-91b7-eb00d3ab5481` 为旧 run，`candidates=[]`；后续复测 run 已有 24 条 `catalog_cache` candidates，但渲染仍不结构化。
- 已读取文件：
  - `frontend/src/components/chat/MessageBubble.tsx`
  - `frontend/src/pages/home/components/MessageList.tsx`
  - `frontend/src/hooks/useStreamingChat.ts`
  - `frontend/src/api/agent.ts`
  - `frontend/src/components/chat/QueryResultTable.tsx`
  - `frontend/src/components/chat/MessageBubble.test.tsx`
- 实施计划：
  1. 在聊天消息层新增通用结构化 renderer，入口使用 `response_type + response_data`，不依赖 run_id 或 answer 文本。
  2. `asset_candidates + reason=list_datasources` 渲染为数据源清单；其他 `asset_candidates` 渲染为澄清候选。
  3. 支持 `asset_metadata` / `asset_not_found` 的稳定结构化展示；`query_result` 复用表格解析能力。
  4. 同时覆盖 streaming done 和历史消息恢复路径。
  5. 增加前端单测并运行 type-check / lint / test。
- 关键设计取舍：
  - 不改 MCP 执行、Resolver、权限、Gateway 调用链路；本次只补齐 Agent 结构化响应到 UI 的通用展示层。
  - 以 `response_data` 为权威结构化数据，answer 文本作为摘要/fallback。
  - 对 `asset_candidates` 使用 `reason` 区分“清单展示”和“多候选澄清”，避免语义混淆。
- 执行状态：
  - Follow-up 4.1：已完成。
- 修改文件：
  - `frontend/src/components/chat/AgentStructuredResponse.tsx`
  - `frontend/src/components/chat/AgentStructuredResponse.utils.ts`
  - `frontend/src/components/chat/MessageBubble.tsx`
  - `frontend/src/components/chat/MessageBubble.test.tsx`
  - `frontend/src/hooks/useStreamingChat.ts`
  - `frontend/src/pages/home/components/MessageList.tsx`
  - `openspec/changes/mcp-proxy-tableau-metadata-tools/tasks.md`
  - `openspec/changes/mcp-proxy-tableau-metadata-tools/IMPLEMENTATION_NOTES.md`
- 验证命令与结果：
  - `cd frontend && npm run type-check`：通过。
  - `cd frontend && npm run lint`：通过，0 errors；仍有仓库既有 52 warnings。
  - `cd frontend && npm test -- --run`：通过，7 files / 24 tests。
  - `cd frontend && npm run build`：通过；保留既有 font resolve 与 chunk size warning。
  - `git diff --check`：通过。
- 已知风险/未完成：
  - 未做真实浏览器自动化 smoke；当前会话未暴露 Browser 所需 Node REPL 执行工具，已用组件 DOM 测试覆盖 streaming/historical 结构化渲染的核心分支。

## Debug: run ef721c21-4cce-4120-9531-017c06a12a34 展示未更新

- 时间：2026-05-20 14:46-14:49 CST
- 现象：用户反馈 `run_id=ef721c21-4cce-4120-9531-017c06a12a34` 的输出格式仍是一长句。
- 排查结论：
  - `bi_agent_runs` 中该 run 为 `response_type=asset_candidates`。
  - 对应 conversation message `id=1041` 的 `response_data` 已包含 `reason=list_datasources`、`source=catalog_cache`、`total_count=24` 和 24 条 `candidates`。
  - 后端契约正确，问题在前端运行态仍服务旧 bundle。
  - `localhost:3000` 原先返回旧入口 `/assets/index-CGDd9k_G.js`；Docker frontend 容器创建于约 40 小时前，容器内无新结构化 renderer 代码。
  - 同时存在一个 2026-05-17 启动的本项目 Vite 进程监听 3000，存在端口/API 来源混淆风险。
- 已执行：
  - 停止旧本地 Vite 进程：`kill 82771`。
  - 重建 frontend 镜像：`docker compose build frontend`，通过。
  - 重建并重启 frontend 容器：`docker compose up -d --force-recreate frontend`，通过。
  - 复查 `curl http://localhost:3000/`：入口已变为 `/assets/index-BJe_7ST0.js`。
  - 复查容器静态资源：新 bundle 中存在“数据源清单 / Catalog cache 缓存”渲染代码。
- 需要用户侧动作：
  - 浏览器对当前页面做硬刷新，或重新打开 `/?conv=25f460e6-3d7f-422b-a720-a782e98cbe7f&connection=4`。

## Follow-up: Metadata 字段与分析建议通用化

- 开工时间：2026-05-20 14:58 CST
- 触发问题：`run_id=41907d53-f223-41ee-a391-f033e8c0a0e6` 的问题“管理费用数据源 有什么字段？能做什么分析？”只返回一句摘要，没有列字段，也没有分析建议。
- 排查结论：
  - 直接调用 Tableau MCP `get-datasource-metadata` 返回完整字段，字段位于 `content[0].text` JSON 的 `fieldGroups[].fields[]`。
  - 现有后端 normalizer 只识别顶层 `fields` / `datasource.fields`，导致 `response_data.fields=[]`，但 `field_count=15` 来自候选资产。
  - 当前 answer renderer 对 `asset_metadata` 只输出摘要，没有问题导向的字段清单和分析建议。
- 并行分工：
  - Backend worker：修复 `mcp_proxy_main.py` metadata normalizer / quality gate / field-driven suggestions，并补后端测试。
  - Frontend worker：增强 `AgentStructuredResponse` 的 `asset_metadata` 展示，并补组件测试。
- 关键设计取舍：
  - 不改变 MCP 执行、Resolver、权限、Gateway 调用链路。
  - 保持 `done.response_type='asset_metadata'` 和扁平 `done.response_data` 契约。
  - `response_data` 作为事实层；answer 文本作为摘要/fallback。
- 执行状态：
  - Follow-up 4.2：已完成。
  - Follow-up 4.3：已完成。
- 修改文件：
  - `backend/services/data_agent/mcp_proxy_main.py`
  - `backend/tests/services/data_agent/test_mcp_proxy_main.py`
  - `frontend/src/components/chat/AgentStructuredResponse.tsx`
  - `frontend/src/components/chat/AgentStructuredResponse.utils.ts`
  - `frontend/src/components/chat/MessageBubble.test.tsx`
  - `openspec/changes/mcp-proxy-tableau-metadata-tools/tasks.md`
  - `openspec/changes/mcp-proxy-tableau-metadata-tools/IMPLEMENTATION_NOTES.md`
- 验证命令与结果：
  - `cd backend && .venv/bin/python -m py_compile services/data_agent/mcp_proxy_main.py`：通过。
  - `cd backend && .venv/bin/python -m py_compile $(git diff --name-only --relative=backend | grep '\.py$')`：通过。
  - `cd backend && .venv/bin/python -m pytest tests/services/data_agent/test_mcp_proxy_main.py -q --no-cov`：通过，20 passed。
  - `cd backend && .venv/bin/python -m pytest tests/services/data_agent/ -q --no-cov`：通过，547 passed。
  - `cd frontend && npm test -- --run src/components/chat/MessageBubble.test.tsx`：通过，7 tests。
  - `cd frontend && npm run type-check`：通过。
  - `cd frontend && npm run lint`：通过，0 errors；仍有仓库既有 52 warnings。
  - `cd frontend && npm test -- --run`：通过，7 files / 26 tests。
  - `cd frontend && npm run build`：通过；保留既有 font resolve 与 chunk size warning。
  - `git diff --check`：通过。
  - `docker compose up -d --build --force-recreate backend celery frontend`：通过，backend/celery/frontend 已重建并重启。
  - `docker compose ps backend celery frontend`：backend healthy，celery/frontend running。
  - `curl -sS -m 5 http://localhost:8000/health`：通过，返回 `{"status":"ok"}`。
  - `curl -sS -m 5 http://localhost:3000/`：通过，新入口 bundle 为 `/assets/index-CJ2l28se.js`。
  - `curl -sS -m 5 http://localhost:3000/assets/index-CJ2l28se.js | grep -o "字段信息\|分析建议\|元数据质量" | sort | uniq -c`：通过，新 bundle 包含字段信息、分析建议、元数据质量渲染文案。
- 已知风险/未完成：
  - 本轮实现的是通用字段/建议展示链路，不按 `run_id` 特判；历史已生成的 answer 文本不会被重写，但前端可基于已保存的结构化 `response_data` 展示新增结构。
  - 并行 worker 启动后未及时返回最终报告，主线程接管完成了 patch review、补丁整合和验证；两个 worker 已关闭，避免悬挂。
  - Docker smoke 中 Celery worker 已 ready，但启动日志仍出现既有 beat/scheduler warning（`PersistentScheduler.lock_key`、`auth_users` FK metadata warning）；本轮未触碰 Celery 调度链路。

## Debug: run 760152a1-7c41-4839-a547-a58779153140 流式连接中断

- 时间：2026-05-20 15:17-15:31 CST
- 现象：用户问题“每年的费用金额是多少？”前端显示“连接中断，请重试”。
- 排查结论：
  - `bi_agent_runs.status='running'`，只有 user message，没有 assistant message。
  - backend 日志显示 MCP Host planner 等待 LLM 时发生 provider timeout：`LLM_PROVIDER_TIMEOUT` / `MCP Host planner failed`。
  - frontend Nginx 日志显示 `/api/agent/stream` upstream read timeout，约 60 秒无上游字节后切断连接。
  - 根因是通用流式链路稳定性问题：长耗时 planner/tool 调用期间没有 SSE heartbeat，代理静默超时后后端 run 未收敛。
- 明确撤回的方案：
  - 不做“每年费用金额”或特定字段/数据源正则分流。
  - 不针对该 run_id 做业务特判。
- 通用修复：
  - `backend/app/api/agent.py` 新增 `_stream_with_keepalive()`，在上游异步生成器长时间无事件时发送 SSE comment heartbeat：`: ping ...`。
  - `/api/agent/stream` 响应头补充 `Cache-Control: no-cache, no-transform`、`Connection: keep-alive`、`X-Accel-Buffering: no`。
  - `backend/services/data_agent/runner.py` 捕获 `asyncio.CancelledError`，将 run 标记为 `failed`，`error_code='AGENT_CANCELLED'`，并持久化 assistant 错误消息，避免长期 `running`。
  - `frontend/nginx.conf` 为 `location = /api/agent/stream` 单独配置流式代理：`proxy_buffering off`、`proxy_cache off`、`proxy_read_timeout 300s`、`proxy_send_timeout 300s`，不放宽全部 `/api/`。
  - 运维收敛历史 run：`760152a1-7c41-4839-a547-a58779153140` 已更新为 `failed / AGENT_TIMEOUT / error`，并补充 assistant error message。
- 修改文件：
  - `backend/app/api/agent.py`
  - `backend/services/data_agent/runner.py`
  - `backend/tests/test_agent_stream_keepalive.py`
  - `backend/tests/services/data_agent/test_runner.py`
  - `frontend/nginx.conf`
  - `openspec/changes/mcp-proxy-tableau-metadata-tools/IMPLEMENTATION_NOTES.md`
- 验证命令与结果：
  - `cd backend && .venv/bin/python -m py_compile app/api/agent.py services/data_agent/runner.py`：通过。
  - `cd backend && .venv/bin/python -m py_compile $(git diff --name-only --relative=backend | grep '\.py$')`：通过。
  - `cd backend && .venv/bin/python -m pytest tests/test_agent_stream_keepalive.py tests/services/data_agent/test_runner.py -q --no-cov`：通过，7 passed。
  - `cd backend && .venv/bin/python -m pytest tests/services/data_agent/ -q --no-cov`：通过，548 passed。
  - `git diff --check`：通过。
  - `docker compose up -d --build --force-recreate backend frontend`：通过，backend/frontend 已重建并重启。
  - `docker compose ps backend frontend`：backend healthy，frontend running。
  - `curl -sS -m 5 http://localhost:8000/health`：通过，返回 `{"status":"ok"}`。
  - `docker compose exec -T frontend nginx -T`：确认 `/api/agent/stream` 已加载 300s timeout 和 buffering off 配置。
  - DB smoke：确认 run `760152a1-7c41-4839-a547-a58779153140` 已为 `failed / AGENT_TIMEOUT / error`，消息表已补 assistant error。
- 已知风险/未完成：
  - 本轮不解决 LLM provider 本身的 timeout，只保证长等待不再被静默代理超时切断，并保证 run 状态可收敛。
  - 若 planner 连续超过 300 秒仍无业务结果，Nginx 仍会按生产超时上限中断；heartbeat 理论上会刷新 read timeout，但底层 provider 若长期阻塞仍需要上游超时治理。

## Debug: run 0920503a-72b7-47b7-8fc8-374fd85dc8fe 表格变换误入 planner

- 开工时间：2026-05-20 15:40 CST
- 现象：用户在上一条成功 `query_result` 后追问“增加一列环比金额、环比金额变化率”，run 失败为 `MCP_HOST_PLANNER`。
- 排查结论：
  - 上一条成功 run `fbebc2f6-ab87-4bed-91b7-ad69c1d885a7` 已返回结构化表格：`fields=["财务期间(日期)", "SUM(总金额)"]`、9 行 rows、`table_display` 含 period + metric。
  - 当前问题是对已有结果表追加派生列的 result transformation，不应重新进入 MCP Host planner。
  - 失败直接原因：planner LLM `MiniMax-M2.7` 超时约 56s，repair 后 planner 输出非法 action，最终 fallback。
- 修复边界：
  - 不做针对 run_id、数据源名、字段名“费用金额/总金额/管理费用数据源”的个性化规则。
  - 新增通用 previous-result table transformation 链路：基于上一条 `query_result` 的 `fields/rows/table_display` 执行确定性表格变换。
- 并行分工：
  - Backend worker：新增纯 result transformation engine 和单测。
  - Frontend worker：检查/补齐 query_result 派生列展示测试。
  - 主线程：负责主链路集成、OpenSpec 记录、最终验证和 Docker smoke。
- 执行状态：
  - Result transformation engine：已完成。
  - Agent 主链路集成：已完成。
  - Frontend query_result 展示检查：已完成。
- 修改文件：
  - `backend/services/data_agent/result_transform.py`
  - `backend/services/data_agent/runner.py`
  - `backend/tests/services/data_agent/test_result_transform.py`
  - `backend/tests/services/data_agent/test_runner.py`
  - `frontend/src/components/chat/MessageBubble.test.tsx`
  - `openspec/changes/mcp-proxy-tableau-metadata-tools/IMPLEMENTATION_NOTES.md`
- 实现摘要：
  - 新增 deterministic previous-result transform engine，基于上一条 `query_result` 的 `fields/rows/table_display` 推断 period + metric 列。
  - 支持追加环比差值列和环比变化率列，首行派生值为 `null`，除以前值为 0/null 时变化率为 `null`。
  - `runner.run_agent` 在进入 MCP Host planner 前优先检查 previous-result transform；命中后直接返回 `response_type='query_result'`，不调用 LLM/MCP。
  - 前端确认现有 `query_result` 表格渲染可展示派生列，仅补充 `previous_result_transform` 用例。
- 验证命令与结果：
  - `cd backend && .venv/bin/python -m py_compile services/data_agent/result_transform.py services/data_agent/runner.py`：通过。
  - `cd backend && .venv/bin/python -m py_compile $(git diff --name-only --relative=backend | grep '\.py$')`：通过。
  - `cd backend && .venv/bin/python -m pytest tests/services/data_agent/test_result_transform.py tests/services/data_agent/test_runner.py -q --no-cov`：通过，11 passed。
  - `cd backend && .venv/bin/python -m pytest tests/services/data_agent/ -q --no-cov`：通过，553 passed。
  - `cd frontend && npm test -- --run src/components/chat/MessageBubble.test.tsx`：通过，8 tests。
  - `cd frontend && npm run type-check`：通过。
  - `cd frontend && npm run lint`：通过，0 errors；仍有仓库既有 52 warnings。
  - `cd frontend && npm test -- --run`：通过，7 files / 27 tests。
  - `cd frontend && npm run build`：通过；保留既有 font resolve 与 chunk size warning。
  - `git diff --check`：通过。
  - `docker compose up -d --build --force-recreate backend frontend`：通过，backend/frontend 已重建并重启。
  - `docker compose ps backend frontend`：backend healthy，frontend running。
  - `curl -sS -m 5 http://localhost:8000/health`：通过，返回 `{"status":"ok"}`。
  - 容器内 transform smoke：`transform_previous_result('增加一列环比金额、环比金额变化率', previous)` 返回 `source='previous_result_transform'`，字段包含 `环比金额` 和 `环比金额变化率`，第二行派生值为 `25.0` 和 `0.25`。
- 已知风险/未完成：
  - 当前 transform MVP 只覆盖上一条结果表的 period-over-period delta/rate，不覆盖排序、过滤、移动平均、累计、同比等更多表格算子。
  - 对不可变换场景保持不拦截，仍交给既有 planner/MCP 链路处理。
