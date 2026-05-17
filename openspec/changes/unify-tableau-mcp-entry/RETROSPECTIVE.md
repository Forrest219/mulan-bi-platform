# Retrospective: Home Data Agent vs Full Tableau MCP

> 日期：2026-05-17
> 角色：Architect
> 主题：首页 Data Agent 与 Claude/Codex + 官方 Tableau MCP 的能力差距复盘

## 1. 背景

理想目标：

> Mulan 首页问答应提供不劣于 Claude Code / Codex + Tableau MCP 的数据问答、探索和交互能力。

实际现状：

> 首页 Data Agent 已接入 Tableau MCP 相关能力，但体验明显弱于模型直接使用完整 Tableau MCP 工具集。

本报告用于沉淀差距原因，作为后续 PRD / SPEC 补强依据。

## 2. 外部基准：官方 Tableau MCP 能力

官方 Tableau MCP 定位为一组 developer primitives，包括 tools、resources、prompts，用于让 AI 应用集成 Tableau。

来源：

- `web.open https://github.com/tableau/tableau-mcp`
- `web.open https://tableau.github.io/tableau-mcp/docs/intro`
- `web.open https://tableau.github.io/tableau-mcp/docs/category/tools`

官方关键能力面：

| 类别 | 工具能力 |
|------|----------|
| Data Q&A | `list-datasources`、`get-datasource-metadata`、`query-datasource` |
| Workbooks | `list-workbooks`、`get-workbook` |
| Views | `list-views`、`get-view-image`、`get-view-data`、custom view 相关 |
| Pulse | metric definitions、metrics、subscriptions、insight bundle、insight brief |
| Content Exploration | `search-content` |

官方 MCP 示例也覆盖三类典型任务：

- 查询 datasource 中的业务数据。
- 查找最近一年最常查看的 workbook。
- 获取指定 view 的图片。

这说明完整 Tableau MCP 不是单一“查数接口”，而是覆盖 Tableau 内容探索、视图读取、数据查询、Pulse 洞察的工具生态。

## 3. 当前 Mulan 首页链路

已核查：首页真实问答入口走：

```text
frontend useStreamingChat
→ frontend/src/api/agent.ts streamAgent()
→ POST /api/agent/stream
→ backend/app/api/agent.py agent_stream()
```

关键源码来源：

- `frontend/src/api/agent.ts`
- `frontend/src/hooks/useStreamingChat.ts`
- `backend/app/api/agent.py`

后端链路核心结构：

```text
intent_classifier
→ route_decision
→ clarification fallback
→ deterministic schema route
→ fast MCP route
→ controlled ReAct path
```

其中 controlled ReAct path 根据环境选择：

```text
DATA_AGENT_CHAIN_MODE=legacy_queryspec      # 默认
DATA_AGENT_CHAIN_MODE=mcp_proxy             # 需 DATA_AGENT_MCP_PROXY_ENABLED=true
```

来源：

- `backend/services/data_agent/runner.py`
- `backend/services/data_agent/chain_selector.py`
- `backend/services/data_agent/mcp_proxy_main.py`

## 4. 核心结论

差距不主要出在“有没有接 Tableau MCP”，而是出在：

> Mulan 首页 Data Agent 没有把 Tableau MCP 当成完整 MCP Host 来默认使用，而是把能力收窄成受控的数据源查询 / QuerySpec / 单 datasource 分析链路。

Claude/Codex + Tableau MCP 的强项是：

```text
模型直接看到 tools/list
→ 自主选择工具
→ 多步探索 Tableau 内容
→ 查询 / 取图 / 查 view / 查 workbook / 查 Pulse
→ 根据工具结果继续追问和修复
```

Mulan 首页当前更接近：

```text
平台先分类问题
→ 选定一条受控链路
→ 尝试定位 datasource
→ 生成 query-datasource 参数
→ 返回文本/表格/简单图表
```

这两个范式导致体验差距。

## 5. 分层差距

### 5.1 工具覆盖差距

当前 Mulan 已具备或部分具备：

- `list-datasources`
- `get-datasource-metadata`
- `query-datasource`
- generic `list_tools` / `call_tool` 雏形

来源：

- `backend/services/tableau/mcp_client.py`
- `backend/services/data_agent/mcp_host/runtime.py`
- `backend/services/data_agent/mcp_host/planner.py`

但首页主体验未产品化覆盖：

- `list-workbooks`
- `get-workbook`
- `list-views`
- `get-view-image`
- `get-view-data`
- custom view data / image
- Pulse metric / insight tools
- `search-content`

影响：

- 用户问“帮我找某个 workbook / view / dashboard”时，Mulan 容易退化或失败。
- 用户问“给我看某个 view 的图”时，Mulan 缺少图片结果容器和工具链。
- 用户问 Pulse 指标洞察时，Mulan 首页没有对应路径。

### 5.2 Agent 自主性差距

Mulan 首页是强路由：

```text
intent → route_decision → deterministic / fast / controlled path
```

Claude/Codex + MCP 是工具原生探索：

```text
tools/list → model plan → tools/call → inspect result → next tool
```

Mulan 的设计更安全、可控，但限制了模型自主组合工具的能力。

具体表现：

- 不会默认从 `search-content` 开始做内容发现。
- 不会自然地从 workbook 跳到 views，再取 view image/data。
- 多轮追问常被压回 QuerySpec 或 datasource 查询，而不是切换工具。

### 5.3 上下文发现差距

MCP Proxy 路径当前要求明确 datasource 上下文；缺少 datasource 时会提示用户先选择。

来源：

- `backend/services/data_agent/mcp_proxy_main.py`

这会让首页在开放式问题上表现弱：

- “找最近一年最常看的 workbook”
- “展示财务项目里的 Economy view”
- “这个看板有哪些视图”

这些问题在 Claude/Codex + Tableau MCP 中可以通过 `search-content`、`list-workbooks`、`list-views` 先探索。

### 5.4 查询表达差距

Mulan 对 `query-datasource` 做了强 guardrail：

- `query.fields` 必须是 field object。
- 字段必须来自 queryable field list。
- 不允许随意发明业务指标。
- 不鼓励模型输出 QuerySpec 以外的结构。

来源：

- `backend/services/data_agent/mcp_args_guardrail.py`
- `backend/services/data_agent/mcp_proxy_main.py`

优点：

- 降低幻觉字段和越权查询。
- 更容易审计。

代价：

- 对复杂业务问题表达弱。
- 对 Tableau 已有计算字段 / 视图上下文 / Pulse 语义利用不足。
- 对多步探索式分析支持不足。

### 5.5 前端交互容器差距

当前前端 SSE 消费类型主要是：

```text
metadata / thinking / tool_call / tool_result / explainability
token / table_data / chart_data / done / error
```

来源：

- `frontend/src/api/agent.ts`
- `frontend/src/hooks/useStreamingChat.ts`

缺少产品化容器：

- workbook card
- view card
- content search result
- Tableau view image
- view data CSV preview
- Pulse insight card
- Tableau deep link with filter / parameter
- 用户选择候选 datasource / workbook / view 的交互

因此即便后端能调用更多 MCP 工具，首页也无法充分呈现完整 Tableau MCP 结果。

### 5.6 Runtime / 配置一致性差距

当前项目正在通过 `unify-tableau-mcp-entry` 解决：

- Tableau 连接入口与 MCP 配置入口重复。
- Tableau Server URL 与 MCP HTTP Endpoint 容易混淆。
- PAT 可能在 `tableau_connections` 与 `mcp_servers.credentials` 中重复。
- MCP Gateway runtime context 需要稳定传递。

来源：

- `openspec/changes/unify-tableau-mcp-entry/SPEC.md`

如果底层连接和 runtime context 不稳定，首页 Data Agent 很难稳定达到 Claude/Codex + MCP 的体验。

## 6. 根因排序

按影响程度排序：

1. **完整 MCP Host 模式未成为首页默认主链路**
   代码存在 `tools/list` / `call_tool` / MCP Host planner 雏形，但首页默认仍偏 legacy QuerySpec / 受控链路。

2. **官方 Tableau MCP 全工具集未被产品化**
   首页实际能力集中在 datasource 查询，未覆盖 workbook / view / Pulse / search-content。

3. **上下文发现能力弱**
   开放式问题缺少“先搜索 Tableau 内容，再定位对象，再调用合适工具”的链路。

4. **查询链路过度结构化**
   QuerySpec 与 guardrail 提升安全性，但牺牲了模型直接使用 MCP schema 的表达能力。

5. **前端结果表达不足**
   当前首页适合文本、表格、简单图表，不适合 Tableau 内容对象和交互结果。

6. **连接 / Gateway / 凭证模型仍在规范化**
   未完全统一前，Data Agent 的 MCP runtime 可靠性会低于本地 Codex/Claude MCP 配置。

7. **缺少对标评测集**
   没有用官方 Tableau MCP 能力定义 golden set，导致改进无法量化。

## 7. 建议改进路径

### 7.1 短期：让首页具备 MCP Host 主链路

目标：

```text
首页 Data Agent 默认可以 tools/list → plan → tools/call
```

建议：

- 增加首页 MCP Host 灰度模式。
- 默认允许只读工具：`search-content`、`list-*`、`get-*`、`query-datasource`。
- 保持写操作和 custom view 写入受确认机制保护。
- 将 `mcp_host` planner 从实验 / fallback 路径提升为可选主链路。

### 7.2 短期：补首页结果类型

新增结果类型：

- `content_results`
- `workbook_card`
- `view_card`
- `view_image`
- `view_data`
- `pulse_insight`
- `tableau_deeplink`
- `candidate_selection`

否则后端工具能力即使增强，用户也感知不到。

### 7.3 中期：标准探索链

定义标准链：

```text
search-content
→ list-workbooks / list-views
→ get-workbook / get-view-image / get-view-data
→ get-datasource-metadata
→ query-datasource
→ final answer
```

并允许模型根据问题跳过不必要步骤。

### 7.4 中期：落地统一 Gateway

完成 `unify-tableau-mcp-entry`：

- `tableau_connections` 为主配置。
- `mcp_servers` 绑定 `tableau_connection_id`。
- `TABLEAU_MCP_GATEWAY_URL` 为共享 endpoint。
- runtime header 传递 `X-Mulan-Tableau-Connection-Id` 等上下文。

### 7.5 中期：建立对标评测集

Golden set 应覆盖：

| 类别 | 示例任务 |
|------|----------|
| datasource 查询 | “Superstore 2025 销售额最高的 5 个州” |
| content search | “找最近一年最常看的 workbook” |
| view image | “展示 Finances 项目里的 Economy view 图片” |
| view data | “导出这个 view 的明细数据预览” |
| metadata | “这个数据源有哪些可查询字段” |
| follow-up | “按月份拆一下刚才的结果” |
| Pulse | “生成这个 Pulse metric 的洞察摘要” |

每个任务记录：

- 是否选对工具。
- 是否选对 Tableau 对象。
- 是否返回正确数据。
- 是否可继续追问。
- 是否有可解释 trace。

## 8. Architect 判断

当前首页 Data Agent 并不是“弱版 Tableau MCP”，而是另一种产品形态：安全、受控、面向结构化问数。但用户期待的是 Claude/Codex + Tableau MCP 那种“完整工具探索型 Agent”。

因此后续不应只优化 prompt 或修几个字段，而应明确产品路线：

> 首页 Data Agent 从“受控 NLQ 查询器”升级为“Tableau MCP Host + Mulan 治理上下文”的 Agent。

这需要三条线并行：

1. 工具面：接完整 Tableau MCP tools/list。
2. 产品面：支持 Tableau 对象、图片、链接、候选选择等结果类型。
3. 基础设施面：统一 Tableau 连接与 MCP Gateway runtime。
