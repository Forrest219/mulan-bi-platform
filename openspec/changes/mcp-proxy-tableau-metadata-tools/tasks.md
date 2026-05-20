# Tasks: mcp-proxy-tableau-metadata-tools

## Phase 1: Execution Mainline & Datasource Resolver

- [x] Task 1: 清理并整合 `mcp_proxy_main.py`
  - 移除内部不可达的实验链路代码，将其定位为路由入口。
  - 将工具的加载与执行明确委托给 `mcp_host/runtime.py`（复用 `MCPToolCatalog` 和 `MCPToolExecutor`）。
- [x] Task 2: 实现 Deterministic Datasource Resolver
  - 提取 Datasource Mention，在 `tableau_assets` 中做 Normalize 后的 Exact Match，找不到则 Contains Match（上限 5 个）。
  - 若为 1 候选：系统直接触发 `get-datasource-metadata` 调用。
  - 若为 0 候选：用户明确查询列表则走 `list-datasources`；若是问介绍 X 失败，返回 `asset_not_found` 或带近似候选项的 `asset_candidates`。
  - 若为 N 候选：阻断执行，返回 `asset_candidates` 给用户澄清。

## Phase 2: Guardrail Matrix & Response Contracts

- [x] Task 3: 重构 `mcp_args_guardrail.py` 矩阵
  - 添加基于 Tool Name 的细分策略，落地 MVP 权限控制（验证 `connection_id` 当前用户可用，并且 `datasource_luid` 属于该 `connection_id`）。
  - 对 `list-datasources` 添加当前连接强限制和条数保护。
- [x] Task 4: 落实 Response Contracts (对齐 done 事件)
  - 创建 Normalizer 将 `list-datasources` 等转换成 `asset_candidates`，`get-datasource-metadata` 转为 `asset_metadata`。
  - 结构必须扁平为 `done` 事件格式：抛弃 `data` 包裹，直接设置 `response_type` 与 `response_data`。
  - 对含有表格数据的（如 `query_result`）强制执行 `table_display.columns` 推断和注入。
  - [x] Follow-up 4.1: 补齐前端通用结构化渲染层，按 `response_type + response_data.reason` 渲染 asset inventory / ambiguity / metadata / query result，避免仅展示 answer 文本。
  - [x] Follow-up 4.2: 修复 Tableau metadata normalizer，支持 `fieldGroups[].fields[]`，输出 `metadata_quality` / `field_groups` / `analysis_suggestions`。
  - [x] Follow-up 4.3: 增强前端 `asset_metadata` 通用展示，展示字段分组、元数据质量提示和分析建议。

## Phase 3: Fallback Policy & Quality Gate

- [x] Task 5: 严格化本地缓存 Fallback (禁止错误成功)
  - 针对 `get-datasource-metadata` 异常情况，执行 `catalog_cache` 完备性检查（Asset 存在且 Field 数量 > 0）。
  - 若完备则组装返回，并在 `response_data` 强标记 `source="catalog_cache"`。不完备立即返回工具异常，Renderer 配合给出降级说明。
- [x] Task 6: 验收与回归测试
  - 验证 1 候选（如“管理费用数据源”）能够无歧义触发 metadata 工具并返回 `asset_metadata`。
  - 验证 N 候选或 Fuzzy Match 时安全中断，返回 5 个以内带原因的 `asset_candidates`。
  - 验证表格数据和 Metadata 数据的 JSON 契约精确对齐 `done` 事件（无多余 `data` 嵌套），且 Table 包含 display contract。
