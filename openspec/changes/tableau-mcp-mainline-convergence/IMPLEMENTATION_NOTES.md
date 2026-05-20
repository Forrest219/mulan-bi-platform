# Implementation Notes: Tableau MCP Mainline Convergence

## 开工信息

- 开工时间：2026-05-20 16:38:16 CST
- 当前 git commit：`edbfb2bee075d23bc665bac684f9cca88a9f9d13`
- 当前工作区状态：存在多项既有未提交改动；本任务会避免回滚用户或其他 coder 已有改动，只修改本 change 直接相关文件。

## 已读取文件清单

- `openspec/changes/tableau-mcp-mainline-convergence/proposal.md`
- `openspec/changes/tableau-mcp-mainline-convergence/design.md`
- `openspec/changes/tableau-mcp-mainline-convergence/tasks.md`
- `openspec/changes/tableau-mcp-mainline-convergence/CODER_TASKBOOK.md`
- `CLAUDE.md`

## 当前生产可达路径盘点

状态：TMC-01 completed。

生产可达路径：

1. `/api/agent/stream` -> `agent.py` deterministic schema inventory route：在非 MCP proxy 或 defer 条件失败时抢答 schema/asset 问题。
2. `/api/agent/stream` -> `run_agent` -> `mcp_proxy_main.run_mcp_proxy_main_path`：当前目标主干入口。
3. `mcp_proxy_main.run_mcp_proxy_main_path` -> asset/list/metadata controlled flow：已覆盖 list-datasources、candidate resolver、get-datasource-metadata、catalog_cache fallback。
4. `mcp_proxy_main.run_mcp_proxy_main_path` -> deterministic compiler strategy：简单聚合、时间趋势、TopN、单指标过滤不进入 LLM planner。
5. `mcp_proxy_main.run_mcp_proxy_main_path` -> `mcp_first_main._run_mcp_main_route`：Compiler 不适用的普通问数仍委托旧 MCP Host planner。
6. `run_agent` -> `mcp_first_main.run_mcp_first_main_path`：当 chain selector fallback 到 legacy_queryspec 时仍可达。
7. `run_agent` -> legacy ReAct engine / QueryTool path：非 controlled path 或 controlled 不命中时仍可达。
8. `mcp_first_main._run_mcp_main_route` -> `_run_mcp_host_route` -> optional thin MCP fallback：host planner 失败后可能进入 thin passthrough fallback。
9. `mcp_first_main.run_mcp_first_main_path` 内 QuerySpec fallback / QuerySpec MCP fallback：legacy controlled path 中仍有多处生产可达分支。

已删除路径：

- `/api/agent/stream` -> `try_fast_mcp_stream` 快通 MCP 旁路：已删除，避免绕过 `mcp_proxy_main`。

## 删除清单与删除前置条件

初版待代码盘点后细化：

- Tableau MCP 场景下 `schema_inventory` 抢答路径：前置条件是 `mcp_proxy_main` asset flow 覆盖 list/metadata/not_found/candidates；当前已基本满足，需要在 `agent.py` 中进一步删除/收紧该生产可达分支。
- `try_fast_mcp_stream` 快通旁路：已删除。替代方案是 `mcp_proxy_main` 内 deterministic compiler strategy。
- `mcp_first_main.py` 中 QuerySpec fallback 生产可达路径：前置条件是 deterministic compiler + LLM planner + guardrail 覆盖 data question。
- `mcp_first_main._run_mcp_main_route` thin fallback：前置条件是 `mcp_proxy_main` 内 LLM planner fallback 统一结构化失败，不再 hidden fallback。
- 重复 datasource resolver：前置条件是统一 `DatasourceCandidateResolver` 被 asset flow、compiler、planner 共同调用。
- 分散业务级 guardrail：前置条件是 `TableauMcpGuardrailService` 覆盖 connection/datasource/tool/field/limit/timeout。
- 重复 response normalizer：前置条件是 `TableauMcpResponseNormalizer` 覆盖 asset/query/error 契约。

## 实施计划

1. TMC-01：完成生产可达路径盘点并更新删除清单。
2. Phase B 基础：抽出统一 Resolver 与 Guardrail，先让现有 proxy flow 复用，减少重复逻辑。
3. Phase A 基础：抽出 Response Normalizer，保持现有 response contract 不变。
4. Phase C 基础：新增 Deterministic Plan Compiler，先覆盖 `metric by dimension`、`metric by time`、`TopN` 的通用模式。
5. Phase E 基础：为 tools catalog 和 datasource metadata 增加 scoped TTL cache。
6. 删除旧路径：在测试覆盖后删除或标记生产不可达。
7. 验证：运行后端 data_agent 测试、前端结构化测试和 Docker smoke。

## 关键设计取舍

- Fast Path 不新增 API 或旁路，只作为 `mcp_proxy_main` 内部 strategy。
- Resolver / Guardrail / Normalizer 先以新模块抽出，再逐步迁移调用点，降低一次性删除风险。
- 删除优先，但只在新主干测试覆盖后执行；临时保留的 legacy 必须标记 removal target 和生产不可达条件。

## 并行分工

- 主线程：TMC-01、主干集成、tasks/notes 增量维护、最终验证。
- Worker A：`DatasourceCandidateResolver` 与 `TableauMcpGuardrailService`，负责后端服务模块和相关测试。
- Worker B：`DeterministicPlanCompiler` 与 TTL cache，负责后端服务模块和相关测试。
- Worker C：前端结构化响应验收检查与测试补齐，避免后端 contract 改动破坏 UI。

## 并行 agent 状态

- Worker A `019e448a-8210-7981-87c7-116764467e33`：已完成 TMC-08 / TMC-10 / TMC-13 基础模块与测试。
- Worker B `019e448a-8297-7fe1-89fb-eb73849187f5`：已完成 TMC-14 至 TMC-18、TMC-28 至 TMC-32 的基础模块、runtime 集成与测试。
- Worker C `019e448a-82cf-70e3-a785-a3c080a8178b`：已完成前端结构化响应测试检查。

## Task 状态

- TMC-01：completed。
- TMC-08：completed。新增 `DatasourceCandidateResolver`，并将 `mcp_proxy_main._resolve_datasource_candidates()` 委托到统一 resolver。
- TMC-09：in progress。Asset metadata resolver 已委托统一 resolver；普通问数显式 datasource resolver 仍在 `mcp_first_main._resolve_explicit_datasource`。
- TMC-10：completed。新增 `TableauMcpGuardrailService`，并在 list/metadata/compiler query 路径中通过统一 service 校验。
- TMC-12：completed。`MCPHostRuntime` 保留 schema/resource cap，并新增 catalog cache；业务级校验集中在 `TableauMcpGuardrailService`。
- TMC-13：completed。新增 resolver/guardrail 单测，覆盖 inaccessible connection、cross-connection datasource、unknown tool、unknown field、limit/timeout repair、too-wide result rejection。
- TMC-14：completed。新增 `DeterministicPlanCompiler`，并作为 `mcp_proxy_main` 内部 strategy 接入。
- TMC-15 / TMC-16 / TMC-17 / TMC-18：completed。Compiler 覆盖 metric by dimension、metric by time/date part、TopN、single metric with filters。
- TMC-19：completed。Compiler 输出 `query-datasource` args 后强制进入 `TableauMcpGuardrailService`。
- TMC-20：completed。Compiler 字段缺失/歧义返回 `clarification`，不进入 LLM planner 猜测。
- TMC-22：completed。新增简单聚合不进入 MCP Host Planner 的集成测试。
- TMC-28：completed。`MCPHostRuntime.load_catalog()` 接入 connection-scoped tools catalog TTL cache。
- TMC-29：completed。`mcp_proxy_main._execute_mcp_host_tool()` 对 `get-datasource-metadata` 接入 connection/datasource-scoped TTL cache。
- TMC-30：completed。Cache key 包含 connection scope。
- TMC-31：completed。Cache lookup result/trace 包含 source、freshness、cache_hit/cache_key telemetry。
- TMC-32：completed。新增 cache hit/miss/expired/invalidated 测试。
- TMC-33：in progress。已从 `agent.py` 删除 `try_fast_mcp_stream` 快通旁路及配套 answer formatter，简单问数不再绕过 `mcp_proxy_main`。
- TMC-34：in progress。已删除 `mcp_proxy_main.py` 内重复 resolver 规则，asset resolver 委托 `DatasourceCandidateResolver`；旧 QuerySpec/LLM planner fallback 分支仍待收敛。
- 前端结构化响应验收：completed by Worker C。
- TMC-05：completed。新增 `TableauMcpResponseNormalizer` 并接入 `mcp_proxy_main.py` 现有 asset/query/tool_unavailable envelope 构造。
- TMC-38：completed。已运行后端 data_agent/keepalive、前端 type-check/lint/test/build，以及 Docker backend/celery/frontend/tableau-mcp-gateway smoke。
- 其他 TMC：pending 或部分完成，详见 `tasks.md`。

## 修改文件清单

- `openspec/changes/tableau-mcp-mainline-convergence/IMPLEMENTATION_NOTES.md`
- `openspec/changes/tableau-mcp-mainline-convergence/tasks.md`
- `backend/services/data_agent/tableau_mcp_response.py`
- `backend/services/data_agent/mcp_proxy_main.py`
- `backend/services/data_agent/tableau_mcp_resolver.py`
- `backend/services/data_agent/tableau_mcp_guardrail.py`
- `backend/services/data_agent/tableau_mcp_plan_compiler.py`
- `backend/services/data_agent/tableau_mcp_cache.py`
- `backend/services/data_agent/mcp_host/runtime.py`
- `backend/app/api/agent.py`
- `backend/tests/services/data_agent/test_tableau_mcp_resolver.py`
- `backend/tests/services/data_agent/test_tableau_mcp_guardrail.py`
- `backend/tests/services/data_agent/test_tableau_mcp_plan_compiler.py`
- `backend/tests/services/data_agent/test_tableau_mcp_cache.py`
- `backend/tests/services/data_agent/test_mcp_proxy_main.py`
- `backend/tests/services/data_agent/test_mcp_host_runtime.py`
- `frontend/src/components/chat/AgentStructuredResponse.tsx`
- `frontend/src/components/chat/AgentStructuredResponse.utils.ts`
- `frontend/src/components/chat/MessageBubble.test.tsx`

## 验证命令与结果

- Worker C：`cd frontend && npm test -- --run src/components/chat/MessageBubble.test.tsx`：通过，1 file / 11 tests。
- `cd backend && .venv/bin/python -m pytest tests/services/data_agent/test_mcp_proxy_main.py -q --no-cov`：通过，20 passed。
- Worker A：`cd backend && ./.venv/bin/python -m py_compile services/data_agent/tableau_mcp_resolver.py services/data_agent/tableau_mcp_guardrail.py tests/services/data_agent/test_tableau_mcp_resolver.py tests/services/data_agent/test_tableau_mcp_guardrail.py`：通过。
- Worker A：`cd backend && ./.venv/bin/python -m pytest tests/services/data_agent/test_tableau_mcp_resolver.py tests/services/data_agent/test_tableau_mcp_guardrail.py tests/services/data_agent/test_mcp_args_guardrail.py -q --no-cov`：通过，40 passed。
- Worker B：`cd backend && python3 -m py_compile services/data_agent/tableau_mcp_plan_compiler.py services/data_agent/tableau_mcp_cache.py tests/services/data_agent/test_tableau_mcp_plan_compiler.py tests/services/data_agent/test_tableau_mcp_cache.py`：通过。
- Worker B：`cd backend && python3 -m pytest tests/services/data_agent/test_tableau_mcp_plan_compiler.py tests/services/data_agent/test_tableau_mcp_cache.py -q --no-cov`：通过，12 passed。
- `cd backend && .venv/bin/python -m pytest tests/services/data_agent/test_mcp_proxy_main.py tests/services/data_agent/test_tableau_mcp_plan_compiler.py tests/services/data_agent/test_tableau_mcp_cache.py tests/services/data_agent/test_tableau_mcp_resolver.py tests/services/data_agent/test_tableau_mcp_guardrail.py -q --no-cov`：通过，48 passed。
- `cd backend && .venv/bin/python -m pytest tests/services/data_agent/test_mcp_host_runtime.py tests/services/data_agent/test_mcp_proxy_main.py tests/services/data_agent/test_tableau_mcp_cache.py -q --no-cov`：通过，32 passed。
- `cd backend && .venv/bin/python -m py_compile app/api/agent.py`：通过。
- `cd backend && .venv/bin/python -m pytest tests/services/data_agent/ -q --no-cov tests/test_agent_stream_keepalive.py -q --no-cov`：通过，584 passed。
- `cd backend && .venv/bin/python -m py_compile app/api/agent.py services/data_agent/mcp_proxy_main.py services/data_agent/mcp_host/runtime.py services/data_agent/tableau_mcp_response.py services/data_agent/tableau_mcp_resolver.py services/data_agent/tableau_mcp_guardrail.py services/data_agent/tableau_mcp_plan_compiler.py services/data_agent/tableau_mcp_cache.py`：通过。
- `cd backend && .venv/bin/python -m py_compile $(git diff --name-only --relative=backend | grep '\.py$')`：通过。
- `cd frontend && npm run type-check`：通过。
- `cd frontend && npm run lint`：通过，0 errors / 52 warnings（现有 warnings）。
- `cd frontend && npm test -- --run`：通过，7 files / 30 tests。
- `cd frontend && npm run build`：通过；存在字体解析与 chunk size warning。
- `docker compose up -d --build --force-recreate backend celery frontend tableau-mcp-gateway`：通过，四个服务已重建并启动。
- `docker compose ps backend celery frontend tableau-mcp-gateway`：backend healthy，celery/frontend/tableau-mcp-gateway running。
- `curl -sS -m 5 http://localhost:8000/health`：通过，`{"status":"ok"}`。
- `curl -sS -m 5 -o /dev/null -w '%{http_code}\n' http://localhost:3000/`：通过，`200`。
- `docker compose exec -T backend python -c '...'` 检查 `TABLEAU_MCP_GATEWAY_URL`：通过，容器内值为 `http://tableau-mcp-gateway:3928/tableau-mcp`。
- `docker compose logs --tail=80 tableau-mcp-gateway`：通过，gateway 已加载 Tableau config、MCP proxy ready；未复现 `ModuleNotFoundError: No module named 'app'`。备注：`/health` 路由返回 404，当前 gateway 未提供该 health endpoint。

## 已知风险/未完成项

- 当前工作区已有大量未提交改动，后续合并 patch 时必须避免覆盖既有实现。
- `mcp_first_main.py` 体量较大，直接删除风险高；需要先用新主干覆盖关键行为并用测试锁住。
- Compiler 字段匹配必须基于 metadata/queryable fields，不允许退化为个性化正则。
- TMC-02/TMC-03/TMC-04/TMC-06/TMC-07、TMC-11、TMC-21、TMC-23 至 TMC-27、TMC-35 至 TMC-37 未完成；当前不建议作为完整 OpenSpec 进入最终 UAT。
- TTL cache 为进程内 MVP；如部署多副本，需要后续升级为 Redis 或带版本广播的共享 cache。
- `mcp_first_main.py` / QuerySpec fallback 仍在部分 compiler unsupported 或 chain selector fallback 场景生产可达。
