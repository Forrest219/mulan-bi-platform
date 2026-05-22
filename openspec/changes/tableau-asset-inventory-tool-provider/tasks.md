# Tasks: Tableau Asset Inventory Built-in Tool Provider

## Phase 0: Approval Gate

- [x] Task 0.1 审批本 OpenSpec change。
- [x] Task 0.2 确认本次不在 `mcp_proxy_main.py` 新增本地 asset SQL 分支。
- [x] Task 0.3 确认所有资产目录查询必须绑定 `connection_id` 和当前 `user_id` 权限。
- [x] Task 0.4 确认 Planner 合约失败不得暴露模型 `reason` 给用户。

## Phase 1: Built-in Tool Provider

- [x] Task 1.1 设计 Mulan built-in tool provider 接口，用于承载本地内置工具。
- [x] Task 1.2 新增 `mulan-list-tableau-assets` 工具定义和 JSON schema。
- [x] Task 1.3 将内置工具注册到现有 MCP Tool Catalog，供 Planner 与 Tableau MCP native tools 一起选择。
- [x] Task 1.4 保证内置工具调用进入 `MCPToolExecutor.execute()`，不得走私有执行通道。
- [x] Task 1.5 Trace 中记录 `tool_provider=mulan_builtin`、`mcp_tool_name`、`execution_source`。

## Phase 2: Permission-scoped Asset Catalog

- [x] Task 2.1 在内置工具执行前强制校验 `connection_id`。
- [x] Task 2.2 `connection_id` 缺失时返回选择连接/站点的 clarification，不查询 catalog。
- [x] Task 2.3 校验当前 `user_id` 对该 `connection_id` 可用。
- [x] Task 2.4 查询 `tableau_assets` 时强制带 `connection_id = ?` 过滤。
- [x] Task 2.5 排除已删除/不可见资产，并限制 `limit` 默认值与最大值。
- [x] Task 2.6 未授权、连接不可用或服务不可用时返回结构化错误/clarification，不 fallback 到全局 asset list。

## Phase 3: Planner Integration

- [x] Task 3.1 更新 Planner tool catalog 输入，让模型看到 `mulan-list-tableau-assets` 的用途与参数。
- [x] Task 3.2 更新 Planner prompt，明确区分 `router_advisory` 与 `compiler_advisory`，且两者均为 hint，不是事实。
- [x] Task 3.3 Prompt 明确资产目录问题使用 asset inventory tool，业务指标问数必须使用 Tableau MCP query tool。
- [x] Task 3.4 确认 asset catalog 结果不能冒充 `query_result`。

## Phase 4: Planner Contract Failure Handling

- [x] Task 4.1 捕获 Planner schema validation error，识别 `needs_clarification=true` 但缺少 `clarification` block 的合约失败。
- [x] Task 4.2 对该类失败执行一次 Planner retry，并向模型注入明确 validation feedback。
- [x] Task 4.3 Retry 成功时按有效 Planner 输出继续。
- [x] Task 4.4 Retry 仍失败时返回标准系统 clarification，不使用模型 `reason` 作为用户回复。
- [x] Task 4.5 记录 `PLANNER_CONTRACT_FAILURE`、`planner_retry_attempted`、`planner_retry_success`、`planner_validation_error`。
- [x] Task 4.6 确保模型内部 `reason` 不出现在前端响应中。

## Phase 5: Response Normalization

- [x] Task 5.1 为 asset inventory 定义 `asset_candidates` / `asset_metadata` / `asset_not_found` / `tool_unavailable` 响应。
- [x] Task 5.2 确认资产目录响应不生成 `fields` / `rows` / `table_display.columns`。
- [x] Task 5.3 保持业务问数 `query_result` contract 不变，必须来自真实 Tableau MCP query tool call。

## Phase 6: Tests

- [x] Task 6.1 Unit test：有连接且有权限时，资产问题生成/执行 `mulan-list-tableau-assets`。
- [x] Task 6.2 Unit test：缺少 connection 时返回 clarification 且不查询 catalog。
- [x] Task 6.3 Unit test：无 connection 权限时不返回资产列表。
- [x] Task 6.4 Unit test：catalog 查询强制带 `connection_id` 约束。
- [x] Task 6.5 Runtime test：`你有哪些看板？` 不返回 Planner 不可执行错误。
- [x] Task 6.6 Runtime test：内置工具通过 `MCPToolExecutor.execute()` 执行。
- [x] Task 6.7 Runtime test：Planner missing clarification block 会 retry 一次。
- [x] Task 6.8 Runtime test：retry 仍失败时返回标准系统 clarification 与 `PLANNER_CONTRACT_FAILURE`。
- [x] Task 6.9 Regression：模型 `reason` 不会进入用户响应。
- [x] Task 6.10 Regression：资产目录响应不会冒充业务 `query_result`。

## Phase 7: Verification

- [x] Task 7.1 `py_compile` 相关后端文件。
- [x] Task 7.2 运行 asset inventory、planner、mcp proxy、agent stream 相关测试。
- [x] Task 7.3 运行 `tests/services/data_agent/ -x -q`。
- [ ] Task 7.4 重建 backend 容器。
- [ ] Task 7.5 人工验证有连接/无连接/无权限三类资产清单问题。
- [ ] Task 7.6 检查 Agent Monitor 中可见 tool call、permission decision、planner retry 与 contract failure 指标。

## Acceptance Checklist

- [x] 本次新增的资产清单能力不在 `mcp_proxy_main.py` 查询本地 `tableau_assets`。
- [x] 不返回未绑定连接权限的全局资产列表。
- [x] `mulan-list-tableau-assets` 进入统一 executor。
- [x] 资产目录查询按 `connection_id` 和 `user_id` 权限收敛。
- [x] Planner clarification 合约失败有 retry 和 Error 级观测。
- [x] 用户响应不暴露模型内部 `reason`。
- [x] 业务问数仍必须来自真实 Tableau MCP query tool call。
