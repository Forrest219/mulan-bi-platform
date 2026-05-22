# Proposal: Homepage Router Guardrail Advisory Mode

## Problem

Run `caaaccfc-3d7e-4403-a65e-3378b9a63460` 暴露了首页 Router Guardrail 的过度前置拦截问题。

用户点击首页推荐问题：

```text
你有哪些看板？
```

实际结果：

- `bi_agent_runs.status=completed`
- `response_type=fallback`
- `error_code=ROUTER_CLARIFY_REQUIRED`
- 未调用 Tableau MCP
- 返回 clarification：「我还不能确定你是想查看数据资产，还是查询业务数据。」

根因不是 Tableau MCP 不支持资产查询，而是 Mulan 的前置 Router Guardrail 没有把「看板」识别为 asset inventory 同义词：

```text
asset_score=0
data_score=0
route=clarify
reason=low_confidence_route
```

这说明当前收益不足以覆盖风险：一个由产品自己推荐的问题，在进入 MCP/Planner 前被规则路由拦截。

## Goals

1. 保留 Router Guardrail 的高置信路由和可观测价值。
2. 取消低置信 ambiguous 的默认硬拦截。
3. 将低置信 ambiguous 转为 `route_advisory`，继续进入 MCP Host / Planner。
4. 仅在强冲突、高风险、不可恢复歧义时返回 clarification。
5. 首页推荐问题必须进入回归测试，确保推荐语与后端路由能力一致。
6. 保证成功资产/问数答案仍必须来自真实工具调用，不允许 schema/cache 伪成功。

## Non-Goals

1. 不删除 Router Guardrail。
2. 不把权限、安全、字段合规判断交给 LLM。
3. 不绕过 `MCPToolExecutor.execute()` 或 `TableauMcpGuardrailService`。
4. 不为单个问题硬编码特殊分支。
5. 不新增通用 MCP Server Registry。
6. 不新增自定义 action DSL。
7. 不让 compiler 或 router 维护跨轮 conversation state。

## Desired Behavior

### High-confidence asset/data

高置信资产问题继续约束工具范围：

```text
你有哪些数据源？ -> asset_question -> asset route / MCP asset tools
你有哪些工作簿？ -> asset_question -> asset route / MCP asset tools
销售额和利润是多少？ -> data_question -> query route / MCP query tools
```

### Low-confidence ambiguous

低置信但非危险的问题不再直接 clarification：

```text
你有哪些看板？
```

应生成：

```json
{
  "route_advisory": {
    "status": "ambiguous",
    "reason": "low_confidence_route asset_score=0 data_score=0",
    "allowed_tool_hints": ["asset", "query"],
    "is_authoritative": false
  }
}
```

然后继续进入 MCP Host / LLM Planner。Planner prompt 必须明确 advisory 是 hint，不是事实。

### Hard ambiguity

强冲突仍 clarification，例如：

```text
<空字符串>
???
!
```

或危险/写操作/权限越界问题，以及 asset/data 同时强命中且无法消歧的问题。

注意：本地 Router 不再把「看一下」「这个怎么样」这类自然语言短问直接判为语义无价值。只要输入不是空白、纯标点、极短噪声，且未命中危险或强冲突规则，就默认 advisory handoff，由 MCP Host / Planner 决定是否需要澄清。

## Acceptance

- `你有哪些看板？` 不再被 router 直接 clarification。
- 低置信 route advisory 会进入 MCP Host / Planner。
- 强歧义仍返回 clarification，且不调用 MCP。
- Router trace 仍记录 `route_decision`、`route_advisory`、`guardrail_action`。
- 首页推荐问题全部有后端回归测试。
