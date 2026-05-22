# Design: Homepage Router Guardrail Advisory Mode

## Current Flow

当前首页链路：

```text
question
-> classify_intent()
-> classify_homepage_question()
-> if route_decision.needs_clarification and no intent match:
     return clarification fallback
-> deterministic route / MCP proxy / runner
```

问题在于 `needs_clarification` 对低置信 ambiguous 和真正不可恢复歧义没有分层。低置信同义词缺口会被直接拦截。

## New Boundary

Router Guardrail 改为三类输出语义：

1. `allow`
   - 高置信 asset/data。
   - 可约束工具范围。

2. `advisory`
   - 低置信 ambiguous。
   - 不阻断。
   - 作为 `route_advisory` 传给 MCP Host / Planner。

3. `clarify`
   - 强冲突或不可恢复歧义。
   - 阻断并返回 clarification。

## Classification Policy

### Advisory Cases

满足以下条件时应 advisory handoff：

- `asset_score=0` 且 `data_score=0`，但输入非绝对空字符串/标点符号，且字数满足最低阈值（如 > 2字符），无明确的高风险、强冲突或已知的纯系统噪声。
- 命中弱资产对象词或业务同义词但未进入高置信词表。
- 首页推荐问题或用户自然语言短问，无法通过规则确定但风险较低。

**核心原则：废除基于动词的正则判定，实施“疑罪从无”的默认放行策略，将语义鉴别权下放给 MCP Host / Planner。**

### Clarification Cases

以下场景继续 hard clarification：

- 空问题、纯标点符号、极短噪声输入。
- 同时强命中 asset 和 data，且工具选择会导致完全不同事实源。
- 涉及危险、写操作、权限边界、非 read-only 工具。
- Planner 也返回 clarification 或低置信失败。

本地 Router 不负责判定自然语言短问的语义价值。诸如「看一下」「这个怎么样」「大屏在哪」这类非空自然语言输入，如果没有命中危险或强冲突规则，应进入 advisory handoff，由 MCP Host / Planner 返回可执行计划或 `needs_clarification=true`。

## Data Contract

新增或复用结构化 route advisory：

```json
{
  "status": "ambiguous",
  "action": "advisory",
  "reason": "low_confidence_route asset_score=0 data_score=0",
  "question_type": "ambiguous",
  "confidence": 0.35,
  "candidate_routes": ["asset_question", "data_question"],
  "allowed_tool_hints": ["schema", "query"],
  "is_authoritative": false
}
```

约束：

- `route_advisory` 是 hint，不是事实。
- 不得直接授权工具执行。
- 最终 tool call 仍必须通过 `MCPToolExecutor.execute()`。
- 权限、datasource、字段、limit 仍由 `TableauMcpGuardrailService` / executor 处理。
- **传递闭环**：`RouteDecision.route_advisory` 必须平滑转移到 `ToolContext.analysis_context["router_advisory"]`，并在 Prompt 层面与 `compiler_advisory` 保持概念隔离。

## Runtime Flow

```text
question
-> intent_classifier
-> router_guardrail
-> allow:
     continue existing constrained route
-> advisory:
     attach RouteDecision.route_advisory to ToolContext.analysis_context["router_advisory"]
     deterministic compiler precheck (may append compiler_advisory)
     continue MCP Host / Planner (consumes both router & compiler advisories distinctively)
-> clarify:
     return clarification fallback
```

## Homepage Suggestions

首页推荐问题需要一条 contract：

- 每条 suggestion 要么能被 router 高置信识别。
- 要么能进入 advisory handoff 并由 MCP Host / Planner 处理。
- 不允许推荐问题稳定触发 router clarification。

## Observability

Trace 中记录：

- `route_decision`
- `route_guardrail_action=allow|advisory|clarify`
- `route_advisory`
- `planner_received_route_advisory=true|false`
- `mcp_tool_name`
- `guardrail_decision`

## Risk Control

- 不一次性移除 router hard stop。
- 先只放开 low-confidence ambiguous。
- 强歧义和危险场景保留 clarification。
- 对首页推荐语建立回归测试，避免产品文案再次漂移。
