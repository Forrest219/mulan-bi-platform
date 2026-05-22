# Tasks: Homepage Router Guardrail Advisory Mode

## Phase 0: Approval Gate

- [ ] Task 0.1 审批本 OpenSpec change。
- [ ] Task 0.2 确认本次修复不删除 Router Guardrail，只收缩低置信硬拦截。
- [ ] Task 0.3 确认不引入题号、字段名、数据源名或 run_id 硬编码。

## Phase 1: Router Semantics

- [x] Task 1.1 为 Router Guardrail 定义 `allow|advisory|clarify` 行为层。
- [x] Task 1.2 区分 low-confidence ambiguous 与 hard ambiguity。
- [x] Task 1.3 保留空问题、纯标点、极短噪声、危险请求、强冲突问题的 clarification；不得把自然语言短问的语义价值判断硬编码在 Router。
- [x] Task 1.4 为 `你有哪些看板？` 所代表的低风险资产短问建立通用规则，不做单句硬编码。

## Phase 2: Runtime Handoff

- [x] Task 2.1 修改 `/api/agent/stream`：low-confidence ambiguous 不再直接 fallback clarification。
- [x] Task 2.2 扩展 `RouteDecision` 以承载 `route_advisory`，并确保其在 Runtime 合并到 `ToolContext.analysis_context["router_advisory"]`。
- [x] Task 2.3 Planner prompt 必须在概念上明确区分全局的 `router_advisory` 和具体工具编译的 `compiler_advisory`，且明确两者均为 hint，不是事实。
- [x] Task 2.4 保证最终工具调用仍进入 `MCPToolExecutor.execute()`。
- [x] Task 2.5 编写测试验证 advisory 上下文在层层调用中不丢失、不混淆。

## Phase 3: Homepage Suggestions Contract

- [x] Task 3.1 为 `/api/chat/suggestions` 的所有推荐问题增加 route regression。
- [x] Task 3.2 验证推荐问题不会稳定触发 router clarification。
- [x] Task 3.3 如推荐语使用产品同义词，后端必须支持对应 route 或 advisory handoff。

## Phase 4: Tests

- [x] Task 4.1 Router unit test：高置信资产/数据仍为 allow。
- [x] Task 4.2 Router unit test：低置信短问进入 advisory。
- [x] Task 4.3 Router unit test：强歧义仍 clarification。
- [x] Task 4.4 Runtime test：low-confidence advisory 会传给 MCP Host / Planner。
- [x] Task 4.5 Runtime test：hard clarification 不调用 MCP。
- [x] Task 4.6 Regression：`你有哪些看板？` 不返回 router clarification。

## Phase 5: Verification

- [x] Task 5.1 `py_compile` 相关后端文件。
- [x] Task 5.2 targeted pytest：router、agent stream、mcp proxy、chat suggestions。
- [x] Task 5.3 容器重建 backend。
- [ ] Task 5.4 人工验证首页推荐问题。
- [ ] Task 5.5 检查 Agent Monitor / trace 中可见 `route_advisory` 与 MCP tool call。

## Acceptance Checklist

- [x] 首页推荐问题不再被前置 router clarification 误拦截。
- [x] low-confidence ambiguous 有 structured advisory。
- [x] hard ambiguity 仍 clarification。
- [x] 成功答案仍有真实 MCP/tool call。
- [x] 未引入业务事实伪造、schema inventory 冒充成功或权限绕过。
