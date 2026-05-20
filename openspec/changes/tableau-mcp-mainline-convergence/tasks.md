# Tasks: Tableau MCP Mainline Convergence

## Phase A: 主干收敛

- [x] TMC-01 盘点当前 Tableau MCP 生产可达路径，形成删除清单。`completed 2026-05-20 16:50 CST`
- [ ] TMC-02 将 `mcp_proxy_main.py` 明确为唯一 Tableau MCP controlled chain 入口。
- [ ] TMC-03 将 `mcp_first_main.py` 降级为临时 legacy adapter 或直接删除重复生产路径。
- [ ] TMC-04 禁止 Tableau MCP 场景下 `schema_inventory` 抢答资产清单、资产介绍、字段介绍问题。
- [x] TMC-05 新增 `TableauMcpResponseNormalizer`，统一 `asset_candidates`、`asset_metadata`、`query_result`、`tool_unavailable`。`completed 2026-05-20 16:48 CST`
- [ ] TMC-06 删除或迁移旧 response normalizer / renderer 分支，确保前端只面对一种 Agent response contract。
- [ ] TMC-07 增加主干 telemetry span：route、resolver、catalog、metadata、planner、query、normalize、render。

## Phase B: Resolver 与 Guardrail 收口

- [x] TMC-08 新增 `DatasourceCandidateResolver`，统一 exact / contains / max 5 / clarification 规则。`completed 2026-05-20 16:58 CST`
- [ ] TMC-09 删除重复 datasource resolver，所有 Tableau MCP datasource lookup 必须调用统一 resolver。`in progress 2026-05-20 16:58 CST`
- [x] TMC-10 新增 `TableauMcpGuardrailService`，集中校验 connection、datasource、tool allowlist、schema、limit、timeout。`completed 2026-05-20 16:58 CST`
- [ ] TMC-11 将 `mcp_args_guardrail.py`、`mcp_host/runtime.py`、`mcp_first_main.py` 中业务级重复校验迁移到统一 Guardrail。
- [x] TMC-12 保留 Runtime 基础资源兜底，但禁止 Runtime 承担业务权限判断。`completed 2026-05-20 17:05 CST`
- [x] TMC-13 增加越权、跨 connection datasource、未知 tool、超 limit、字段不存在的后端测试。`completed 2026-05-20 16:58 CST`

## Phase C: Deterministic Plan Compiler

- [x] TMC-14 新增 `DeterministicPlanCompiler`，作为 `mcp_proxy_main` 内部 strategy。`completed 2026-05-20 16:58 CST`
- [x] TMC-15 支持 `metric by dimension`。`completed 2026-05-20 16:58 CST`
- [x] TMC-16 支持 `metric by time/date part`。`completed 2026-05-20 16:58 CST`
- [x] TMC-17 支持 `top N metric by dimension`。`completed 2026-05-20 16:58 CST`
- [x] TMC-18 支持 `single metric with filters`。`completed 2026-05-20 16:58 CST`
- [x] TMC-19 Compiler 输出标准 `query-datasource` args，并强制进入统一 Guardrail。`completed 2026-05-20 16:58 CST`
- [x] TMC-20 字段歧义或置信度不足时返回 clarification，不调用 LLM 猜测。`completed 2026-05-20 16:58 CST`
- [ ] TMC-21 删除针对具体 run_id、具体字段名、具体问法的个性化分支。
- [x] TMC-22 增加简单聚合不进入 LLM Planner 的测试。`completed 2026-05-20 16:58 CST`

## Phase D: LLM Planner 收敛

- [ ] TMC-23 明确 LLM Planner 只处理复杂、多步、Compiler 不适用的问题。
- [ ] TMC-24 Planner 输出不得直接调用 MCP，必须进入统一 Guardrail 与 Runtime。
- [ ] TMC-25 设置 planner latency budget、超时错误、结构化 fallback。
- [ ] TMC-26 删除旧 QuerySpec fallback 的生产可达路径。
- [ ] TMC-27 增加 planner fallback 不伪装成功的测试。

## Phase E: TTL Cache

- [x] TMC-28 增加 tools catalog TTL cache。`completed 2026-05-20 17:05 CST`
- [x] TMC-29 增加 datasource metadata TTL cache。`completed 2026-05-20 17:05 CST`
- [x] TMC-30 cache key 必须包含 connection scope，避免跨用户或跨连接污染。`completed 2026-05-20 16:58 CST`
- [x] TMC-31 cache response 必须携带 source、freshness、cache_hit telemetry。`completed 2026-05-20 17:05 CST`
- [x] TMC-32 增加 cache hit/miss/invalidated 后端测试。`completed 2026-05-20 16:58 CST`

## Phase F: 删除与归档

- [ ] TMC-33 删除 Tableau MCP 场景下不可再走的 legacy route。`in progress 2026-05-20 17:10 CST; removed try_fast_mcp_stream bypass`
- [ ] TMC-34 删除重复 resolver、guardrail、normalizer、fallback 分支。`in progress 2026-05-20 17:10 CST`
- [ ] TMC-35 如必须保留 legacy adapter，标记 removal target 并确保生产不可达。
- [ ] TMC-36 更新开发文档，说明新主干和禁止新增旁路的规则。
- [ ] TMC-37 移除不再适用的测试，补充新主干测试。
- [x] TMC-38 运行全量后端 data_agent 测试和前端结构化响应测试。`completed 2026-05-20 17:13 CST`

## 验证命令

后端：

```bash
cd backend && python3 -m py_compile $(git diff --name-only --relative=backend | grep '\.py$')
cd backend && pytest tests/services/data_agent/ -q --no-cov
cd backend && pytest tests/test_agent_stream_keepalive.py -q --no-cov
```

前端：

```bash
cd frontend && npm run type-check
cd frontend && npm run lint
cd frontend && npm test -- --run
```

Docker smoke：

```bash
docker compose up -d --build --force-recreate backend celery frontend tableau-mcp-gateway
curl -sS -m 5 http://localhost:8000/health
curl -sS -m 5 http://localhost:3000/
```
