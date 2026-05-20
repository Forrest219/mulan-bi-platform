# Proposal: mcp-proxy-tableau-metadata-tools

## Overview
Mulan 首页问答 Transparent MCP Proxy 增量增强方案，旨在通过规范化的 MCP 工具（`list-datasources` 和 `get-datasource-metadata`）处理资产介绍等问题。本方案摒弃大模型自由选工具的幻觉风险，引入严格的确权机制和确定性 Resolver（0/1/N 候选）；明确在 `mcp_host` 执行层落地；规范 `done` 事件的流式返回契约（`response_type` 与 `response_data` 展平）；并对本地 catalog cache 降级给出清晰的“完备性”标准，严禁静默伪装“错误成功”。

## Motivation
在 `run_id=e117472f-7019-4175-9cee-6f83fc6ade7a` 中，用户问题「介绍管理费用数据源」被错误地退化为了展示 24 个全量数据源列表。
之前的方案设计存在让 coder “猜”执行细节的风险：
1. Response Contract 与现存流式 `done` 事件（`response_type` / `response_data`）结构脱节。
2. 1 候选时执行意图暧昧，存在让模型再次猜测是否调用工具的隐患。
3. 0 候选与多意图混淆，没有划清“查列表”和“查不到介绍”的界限。
4. Fuzzy 匹配缺失明确算法约束，容易失控。
5. 权限模型脱离现状（虚构了 datasource-level ACL）。
6. `catalog_cache` 数据完备性无量化判定。

## Goals
1. **收拢执行主线**：明确 `mcp_proxy_main.py` 的 wrapper 身份，具体工具编排接入 `mcp_host/runtime.py` (`MCPToolCatalog`, `MCPToolExecutor`)。
2. **确定性 Datasource 解析**：建立确定性 Resolver。匹配算法限定为 `exact match` 与 `contains match`，上限 5 个；1 候选直接触发调用；0/N 候选走清晰的澄清或报错逻辑。
3. **完善 Guardrail 矩阵**：重构 `mcp_args_guardrail.py`。权限模型严格对齐现状：校验 `connection_id` 用户可见，且 `datasource_luid` 确属该 connection。
4. **规范响应与 Fallback 契约**：对齐现存 `done` 事件结构（`response_type` 与 `response_data`）。MCP 失败时，有明确标准的本地 cache 校验，成功则带上 `source="catalog_cache"`，严禁假冒 MCP。

## Non-Goals
1. 不抛弃 `mcp_host` 另起炉灶，避免架构重叠。
2. 不要求 LLM 自由、无引导地选择 datasource。
3. MVP 阶段不做基于语义或中文同义词的模糊搜索。

## Resolved Open Questions
- **主改文件是哪个？** `mcp_proxy_main.py` 作为入口 Wrapper，工具执行依赖 `mcp_host/*`。
- **1 候选怎么处理？** 绝对确定性：Resolver 发现 1 个候选后，直接由系统构建并触发 `get-datasource-metadata` 调用，LLM 仅根据 metadata 结果做文本渲染，不得干预是否调用工具。
- **0 候选与明确查列表的区别？** 若问题意为“有哪些数据源”，调用 `list-datasources`；若问题意为“介绍 X 数据源”但找不出 X，返回 `asset_not_found`（最多带 5 个近似候选），绝不拉全量列表冒充。
- **权限判断依据？** MVP 校验 `connection_id` 当前用户可见，并确认 `datasource_luid` 归属该连接。`list-datasources` 输出必须限定在此 `connection_id` 内。
- **`catalog_cache` 的完备性标准？** `tableau_assets` 存在该记录，且在 `tableau_datasource_fields` 中该 LUID 的字段条数 > 0。