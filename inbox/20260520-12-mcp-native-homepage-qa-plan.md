# Mulan 首页问答 Transparent MCP Proxy 增量增强方案

> **状态**：评审修订版  
> **角色视角**：tester / 架构评审  
> **原始问题**：`run_id=e117472f-7019-4175-9cee-6f83fc6ade7a`，用户问「介绍管理费用数据源」，系统返回 24 个数据源清单  
> **修订原因**：吸收评审反对意见，避免另起炉灶，改为沿 Spec 54 `Transparent MCP Proxy + Guardrail` 主线做增量增强  
> **核心约束**：
> - 禁止用自然语言模式、题号、数据源名称或场景词写死修复
> - 禁止把 Schema Inventory / datasource list 作为 MCP-answerable 问题的成功 fallback
> - 所有 Tableau MCP 调用必须经过 `mcp_args_guardrail.py`
> - 表格响应必须符合 Spec 36 `table_display.columns` 契约
> - 用户可见行为、Agent workflow、跨模块架构调整需要走 OpenSpec

---

## 0. 本轮评审修订结论

原草案方向是对的：Mulan 应该从本地文本路由和 schema 清单答复，升级到 MCP 工具驱动的首页问答。

但原草案粒度偏重，容易演变成重建一套 MCP 编排平台。结合 Spec 54 与现有实现，修订后的建设方向应是：

> 不新建一套独立 MCP Host 平台；基于现有 `mcp_proxy_main.py`、`mcp_args_guardrail.py`、`tableau/mcp_client.py` 做增量增强，让首页问答直接使用 Tableau MCP 的真实工具能力。

四条评审意见的处理结论：

| 评审意见 | 处理结论 |
|---|---|
| 工具链层级过深，过度设计 | 同意。收缩为沿 Spec 54 增量增强，不做 P0 级通用 MCP Server Registry / Adapter 平台 |
| schema inventory fallback 不够决绝 | 同意。MCP-answerable 问题失败时必须结构化失败，不得退回 datasource list 冒充成功 |
| 不应自定义 action DSL | 同意。优先使用模型原生 tool/function calling；兼容 JSON 时也输出真实 MCP tool invocation |
| 缺少 table_display 契约 | 同意。所有表格类 response_data 必须接入 `table_display.columns` |

---

## 1. 当前问题复盘

### 1.1 运行记录

- `run_id`: `e117472f-7019-4175-9cee-6f83fc6ade7a`
- `question`: `介绍管理费用数据源`
- `connection_id`: `4`
- `status`: `completed`
- `tools_used`: `{schema}`
- `response_type`: `schema_inventory`
- 实际结果：返回 24 个 Tableau datasource 清单

数据库中存在目标 datasource：

- 名称：`管理费用数据源`
- Tableau LUID：`aa1829e8-bcd2-400e-b139-ea3402244e50`
- 项目：`01-自助分析数据源`
- 字段数：15

正确方向应是基于单个 datasource metadata 生成介绍，而不是返回全量 datasource list。

### 1.2 根因判断

现有错误链路：

```text
首页用户问题
  -> router guardrail 判定资产类问题
  -> agent.py 进入 deterministic schema inventory
  -> schema_inventory 返回 datasource list
  -> renderer 生成清单型答复
```

根因不是少了某个问法规则，而是资产问题被本地 schema inventory 抢先处理，绕过了 Tableau MCP 的真实工具。

---

## 2. 与 Spec 54 / Spec 36 的对齐

### 2.1 Spec 54 主方向

Spec 54 已经确立：

> LLM 负责基于 MCP Tool Description / Schema 生成 MCP 参数；Mulan 只在参数发往底层前做底线安全检查。Tableau MCP 是事实、聚合、筛选、字段语义和派生指标权威；Mulan 只包装、审计、追踪并解释 MCP response data。

因此本方案不应新增一套独立的 Agent 编排框架，而应增强现有：

- `backend/services/data_agent/mcp_proxy_main.py`
- `backend/services/data_agent/mcp_args_guardrail.py`
- `backend/services/tableau/mcp_client.py`

### 2.2 Spec 36 红线

Spec 36 明确：

- 首页答案准确性不得低于底层 Tableau MCP / 工具参照链路
- 任何“错误成功”均视为 P0 失败
- MCP-answerable query 不得 fallback 到 SchemaTool / Schema Inventory 用资产列表、字段枚举或数据源介绍冒充业务答案
- 所有 Tableau MCP 执行路径必须经过 `mcp_args_guardrail.py`
- 表格响应必须包含兼容数据层 `fields` / `rows`，并生成可选但正式的 `table_display.columns`

本方案必须以这些约束为验收标准。

---

## 3. 修订后的目标链路

目标链路：

```text
用户问题
  -> chain selector 确认 DATA_AGENT_CHAIN_MODE=mcp_proxy
  -> mcp_proxy_main.py 读取当前连接与上下文
  -> 加载 Tableau MCP tool description / schema
  -> LLM 原生 tool/function calling 或兼容 MCP invocation JSON
  -> mcp_args_guardrail.py 校验 tool + args + 权限 + 规模
  -> tableau/mcp_client.py 调用官方 Tableau MCP Server
  -> response normalizer 生成 Mulan response_data
  -> table_display.py 生成 table_display.columns
  -> renderer 只解释 MCP response_data
  -> trace/audit 记录 tool call、guardrail decision、fallback reason
```

以「介绍管理费用数据源」为例：

```text
1. 当前连接为 Tableau，且 mcp_proxy enabled
2. toolset 限定为 Tableau readonly
3. LLM 选择 list-datasources 或 get-datasource-metadata
4. guardrail 校验 datasource 权限和 tool args
5. Tableau MCP 返回 datasource metadata
6. normalizer 输出 response_type=asset_metadata
7. renderer 只基于 metadata 生成介绍
```

---

## 4. 设计原则

### 4.1 沿现有主线增量增强

不在 P0 阶段新增完整平台化组件：

- 不新增通用 MCP Server Registry
- 不新增 Tableau MCP Adapter 层
- 不新增独立 Tool Catalog 平台
- 不新增自定义 action DSL

优先复用：

- `mcp_proxy_main.py`
- `mcp_args_guardrail.py`
- `tableau/mcp_client.py`
- `table_display.py`

### 4.2 不基于自然语言场景写死

禁止：

- 为「介绍 xxx 数据源」增加文本分支
- 为 `管理费用数据源` 增加名称特判
- 在 schema inventory 中继续堆问法规则
- 根据题号、样例或场景词决定工具路径

允许：

- 按连接能力选择 Tableau MCP
- 按用户权限过滤可见 datasource
- 按 MCP tool schema 校验参数
- 按 tool result 中的 datasource identity 做 exact/normalized match
- 候选不唯一时返回 clarification

### 4.3 MCP 失败不得伪装成功

MCP-answerable 问题失败时，不能 fallback 到更弱的 schema inventory 并标记成功。

正确行为：

```text
MCP server unavailable
  -> response_type=tool_unavailable 或 mcp_unavailable
  -> 用户可见说明本次无法安全回答
  -> trace 记录 FALLBACK_TRIGGERED / WARN
  -> 不输出业务结论
```

`schema_inventory` 可以保留，但只能用于用户明确询问资产清单或本地诊断，不能作为 Tableau MCP metadata/query 的语义降级。

### 4.4 优先原生 Tool / Function Calling

不再设计自定义 action 词汇。

优先输出真实 MCP tool invocation：

```json
{
  "tool": "get-datasource-metadata",
  "arguments": {
    "datasourceLuid": "aa1829e8-bcd2-400e-b139-ea3402244e50"
  }
}
```

如果当前 LLMService 暂不支持原生 tool/function calling，可以临时使用 JSON 兼容模式，但 JSON 结构仍应贴近 MCP tool invocation，而不是发明 `action=tool_call/final/clarify`。

### 4.5 表格展示契约必须纳入 normalizer

凡是返回表格数据，都必须遵守：

```json
{
  "fields": ["字段A", "SUM(指标B)"],
  "rows": [["x", 100]],
  "table_display": {
    "columns": [
      {
        "key": "SUM(指标B)",
        "label": "指标B",
        "semantic_type": "metric",
        "value_type": "number",
        "align": "right",
        "format": "number"
      }
    ]
  }
}
```

规则：

- `table_display.columns[i]` 必须与 `fields[i]` 一一对应
- `table_display` 只描述展示，不新增、删除、覆盖或重新计算业务事实
- renderer 和前端不得用展示契约重算事实
- 历史消息缺少 `table_display` 时，前端才 fallback 到 `fields + rows`

---

## 5. 参考模块的修订定位

### 5.1 mcp-agent

仍有参考价值，但只借鉴模式，不作为 P0 依赖：

- allowed tools filtering
- tool trace
- 多 server 聚合思路
- connection lifecycle

不在本轮实现完整 mcp-agent 式编排平台。

### 5.2 tableau-mcp

作为 Tableau 工具契约参考：

- `list-datasources`
- `get-datasource-metadata`
- `query-datasource`
- BoundedContext
- datasource permission check
- query limit 与 metadata validation

### 5.3 hermes-agent

作为后续生产稳定性参考：

- reconnect/backoff
- OAuth token reload
- 401 处理
- timeout
- credential stripping

这些可进入 P1/P2，不应阻塞本次 P0 修复。

---

## 6. 修订后的核心改动范围

### 6.1 扩展 `mcp_proxy_main.py`

当前 `mcp_proxy_main.py` 主体围绕 `query-datasource`。

需要增量支持 Tableau readonly toolset：

- `list-datasources`
- `get-datasource-metadata`
- `query-datasource`

职责：

- 将首页问题交给 LLM 选择真实 MCP tool
- 不再让资产介绍类问题进入 schema inventory 成功路径
- 保持 SSE 事件兼容
- 写入 trace/audit

### 6.2 扩展 `mcp_args_guardrail.py`

当前 guardrail 重点校验 `query-datasource`。

需要新增：

- `list-datasources` 参数校验
- `get-datasource-metadata` 参数校验
- datasource LUID 权限校验
- readonly tool allowlist
- metadata/list 工具的 result 安全边界

所有 Tableau MCP tool call 均必须通过该 choke point。

### 6.3 复用 `tableau/mcp_client.py`

不新增 Tableau Adapter。

需要检查并补齐：

- 是否已有 list datasource 调用封装
- 是否已有 datasource metadata 调用封装
- 是否已有 query datasource 调用封装
- HTTP/SSE 错误是否能结构化返回给上层

### 6.4 新增轻量 MCP Tool Schema Loader

不建设完整 Tool Catalog Service。

只做 P0 所需：

- 固定加载 Tableau readonly tools 的 schema/description
- 支持从 MCP server 动态获取时优先动态获取
- 动态获取失败时，不降级为错误成功
- 记录 schema source：`remote_mcp` / `local_contract`

### 6.5 新增 Tableau Response Normalizer

职责：

- `list-datasources` -> `response_type=asset_candidates`
- `get-datasource-metadata` -> `response_type=asset_metadata`
- `query-datasource` -> `response_type=query_result`
- MCP/guardrail 失败 -> `response_type=tool_unavailable` / `guardrail_rejected`

表格类结果必须调用 `infer_table_display_schema()` 生成 `table_display.columns`。

### 6.6 收紧 `agent.py` 首页入口

需要调整：

- Tableau MCP proxy enabled 时，资产介绍类问题不得先走 schema inventory
- deterministic schema inventory 只能作为明确资产清单工具或配置关闭 MCP proxy 后的 legacy 行为
- MCP-answerable 问题失败时返回结构化失败，不返回全量清单

---

## 7. Task 拆分

### T0. OpenSpec Delta

**优先级**：P0  
**类型**：规格 / 架构

基于 Spec 54，不另起新架构。

产出：

- `openspec/changes/mcp-proxy-tableau-metadata-tools/proposal.md`
- `openspec/changes/mcp-proxy-tableau-metadata-tools/design.md`
- `openspec/changes/mcp-proxy-tableau-metadata-tools/tasks.md`

必须明确：

- `mcp_proxy_main.py` 支持 Tableau metadata/list/query tools
- 禁止 schema inventory 作为 MCP-answerable 成功 fallback
- tool invocation 格式
- guardrail 范围
- `table_display.columns` 契约
- 验收样例

### T1. 扩展 Tableau readonly toolset

**优先级**：P0  
**类型**：后端 MCP proxy

范围：

- 在 `mcp_proxy_main.py` 增加 `list-datasources` / `get-datasource-metadata`
- 保留 `query-datasource`
- toolset 由连接能力和 readonly policy 决定，不由文本规则决定

验收：

- LLM 可选择真实 MCP tool
- tool name 必须属于 allowed toolset
- 未知 tool 被拒绝并记录 trace

### T2. 扩展 Guardrail

**优先级**：P0  
**类型**：安全 / 权限

范围：

- `list-datasources` schema 校验
- `get-datasource-metadata` schema 校验
- datasource 权限校验
- readonly tool allowlist
- result 脱敏/截断策略

验收：

- 无权限 datasource metadata 不可返回
- 未通过 guardrail 的 args 不到达 Tableau MCP
- guardrail decision 写入 trace

### T3. MCP Tool Invocation 生成

**优先级**：P0  
**类型**：LLM 调用

范围：

- 优先接入 LLM 原生 tool/function calling
- 如果短期不具备，使用兼容 JSON：

```json
{
  "tool": "get-datasource-metadata",
  "arguments": {
    "datasourceLuid": "..."
  }
}
```

禁止：

- 自定义 `action` DSL
- 输出 QuerySpec
- 让模型生成最终答案后再反推工具

验收：

- 生成结果可直接进入 guardrail
- JSON parse 失败时返回结构化失败
- 不通过 schema 时不执行 MCP

### T4. Tableau Response Normalizer + Table Display

**优先级**：P0  
**类型**：响应契约

范围：

- 标准化 `asset_candidates`
- 标准化 `asset_metadata`
- 标准化 `query_result`
- 标准化 `tool_unavailable` / `guardrail_rejected`
- 表格类结果接入 `infer_table_display_schema()`

验收：

- `query_result` 包含 `fields` / `rows` / `table_display.columns`
- metadata 字段表若以表格展示，也包含 `table_display.columns`
- `table_display.columns[i]` 与 `fields[i]` 一一对应
- renderer 不新增事实

### T5. 首页入口收紧

**优先级**：P0  
**类型**：后端 API / SSE

范围：

- 调整 `agent.py` 中 asset/schema 相关分支优先级
- MCP proxy enabled 时优先进入 Transparent MCP Proxy
- 禁止 MCP-answerable 问题 fallback 到 schema inventory 成功答复
- 保持现有 SSE 事件兼容

验收：

- `介绍管理费用数据源` 不返回 24 个 datasource 清单
- MCP unavailable 时返回结构化失败
- trace 中能看到 route path、tool invocation、guardrail decision

### T6. 回归测试与质量门禁

**优先级**：P0  
**类型**：测试 / tester gate

核心用例：

- `介绍管理费用数据源`
- `你有哪些数据源`
- `管理费用数据源有哪些字段`
- `查询管理费用本月总金额`
- 多个相似 datasource 候选
- 无权限 datasource
- MCP server unavailable
- tool schema unavailable

验收：

- 不出现 schema inventory 冒充 MCP metadata
- 不出现 QuerySpec 作为新主链路 plan contract
- 不出现错误成功
- 所有 Tableau MCP tool call 经过 guardrail
- 表格结果满足 `table_display.columns`

### T7. 生产可观测性补强

**优先级**：P1  
**类型**：运维 / 观测

范围：

- trace 中增加 `mcp_tool_name`
- trace 中增加 `guardrail_decision`
- trace 中增加 `tool_schema_source`
- trace 中增加 `fallback_reason`
- 统计 MCP unavailable / guardrail rejected / tool error

验收：

- 任意 run_id 可判断失败点属于 LLM、guardrail、MCP server、权限还是 renderer

---

## 8. 验收标准

### 8.1 本次问题验收

输入：

```text
介绍管理费用数据源
```

预期：

- 不返回 24 个 datasource 清单
- 不走 schema inventory 成功路径
- 调用 Tableau MCP metadata 能力，或在无法调用时返回结构化失败
- 若成功，定位 datasource：`管理费用数据源`
- `response_type=asset_metadata`
- trace 中包含真实 MCP tool invocation 与 guardrail decision

### 8.2 schema inventory 红线

以下行为一律视为失败：

- MCP server 挂了，返回 datasource list 并标记成功
- metadata tool 失败，返回字段枚举并标记成功
- query tool 失败，返回资产介绍并标记成功
- renderer 失败后触发另一次 MCP fallback 查询

### 8.3 table_display 验收

所有 `query_result` 必须满足：

- `fields` 存在
- `rows` 存在
- `table_display.columns` 存在
- `len(table_display.columns) == len(fields)`
- 每个 column 至少包含 `key`、`label`、`semantic_type`、`value_type`、`align`、`format`

---

## 9. 风险与控制

### 风险 1：LLM tool invocation 不稳定

控制：

- 优先使用原生 tool/function calling
- 兼容 JSON 模式必须贴近真实 MCP tool invocation
- JSON parse/schema 失败返回结构化失败
- 不进行语义补救式硬猜

### 风险 2：MCP unavailable 被误包装为成功

控制：

- 禁止 schema inventory 成功 fallback
- MCP failure 统一 response_type
- trace 必须有 `FALLBACK_TRIGGERED` / `WARN`
- tester 增加 unavailable 回归用例

### 风险 3：权限泄漏

控制：

- prompt 前只提供用户可访问 datasource
- guardrail 前校验 datasource LUID
- tool result 后做脱敏与截断

### 风险 4：表格契约断裂

控制：

- normalizer 统一接入 `infer_table_display_schema()`
- 单测校验 `columns` 与 `fields` 对齐
- 前端继续保留历史消息 fallback

---

## 10. 不建议做的修复

不建议：

- 在 `schema_inventory.py` 里追加「介绍 xxx 数据源」分支
- 在 router guardrail 中扩充自然语言场景规则
- 为 `管理费用数据源` 做名称特判
- 新建完整 MCP Server Registry / Adapter 平台作为 P0 前置
- 自定义 action DSL 替代模型原生 tool/function calling
- MCP 失败时用 datasource list、字段枚举或资产介绍冒充成功答案

---

## 11. 建议实施顺序

第一阶段：规格收口

1. T0 OpenSpec Delta
2. 明确 schema inventory 红线
3. 明确 table_display 验收

第二阶段：P0 修复

1. T1 Tableau readonly toolset
2. T2 Guardrail 扩展
3. T3 Tool invocation 生成
4. T4 Response normalizer + table_display
5. T5 首页入口收紧

第三阶段：质量门禁

1. T6 回归测试
2. T7 观测补强

---

## 12. 下一步建议

评审通过后，先写 OpenSpec Delta，再让 Coder 按 T1-T5 实施。

首个验收样例锁定：

```text
介绍管理费用数据源
```

该用例必须从 `schema_inventory` 清单答复升级为 Tableau MCP metadata 答复；若 MCP 不可用，则必须结构化失败，不允许错误成功。
