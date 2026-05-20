# Design: mcp-proxy-tableau-metadata-tools

## 1. Execution Mainline 架构整合
**设计调整**：
- 将 `mcp_proxy_main.py` 确立为入口 Wrapper，清理内部实验死代码。
- MCP 工具调用必须委托给 `backend/services/data_agent/mcp_host/runtime.py` 里的 `MCPToolCatalog` 和 `MCPToolExecutor`。

## 2. Deterministic Datasource Candidate Resolver
避免大模型“自由选”工具，引入系统强控的 Resolver：
- **匹配算法**（MVP 限制）：
  1. Normalize（去空格与特殊字符、统一大小写）后执行 Exact Match。
  2. 若无 Exact 匹配，执行 Contains Match。
  3. 不做复杂的中文同义词或 Semantic 搜索。
  4. 候选上限限制为 5 个。
- **0 候选控制流**：
  - 如果用户问“有哪些数据源 / 列出数据源”：系统明确执行 `list-datasources`。
  - 如果用户问“介绍 X 数据源”但本地 0 候选：返回 `response_type=asset_not_found`（或 `asset_candidates` 附加少数近似），严禁全量拉取。
- **1 候选控制流**：
  - 系统获得唯一的 `datasourceLuid` 后，**必须确定性地直接调用** `get-datasource-metadata`，LLM 仅负责最后一步的自然语言解释，无权决断是否调用工具。
- **N 候选控制流** (1 < N <= 5)：
  - 中断执行，返回 `asset_candidates` 要求用户澄清。

## 3. Tool Guardrail Matrix
重构 `mcp_args_guardrail.py`，明确当前权限与约束逻辑：

| Tool Name | Allowlist Enablement | Permission / Scope Guardrail | Query / Args Guardrail | Result Size / Timeout Guardrail |
|-----------|-------------------------|------------------------------|------------------------|---------------------------------|
| `query-datasource` | 仅受控/配置允许 | `connection_id` 可访问 && `luid` 属该连接 | 必须符合 VizQL Schema | 强制 limit (默认/最大), 超时控制 |
| `list-datasources` | 默认开放，资产探索 | 限定返回当前授权的 `connection_id` 下的资源 | 校验 `limit` 参数安全区间 | 限制最大返回项数，防止全量拉爆 |
| `get-datasource-metadata` | 默认开放，资产解答 | `connection_id` 可访问 && `luid` 属该连接 | `datasourceLuid` 不为空 | 无特殊限制，返回常规 Schema |

## 4. Response Contracts (对齐流式 done 事件)
契约必须与现有流式 `done` 事件（`response_type` 与 `response_data` 平级展平）完全一致，不再引入额外 `data` 包裹：

### 4.1 `asset_candidates`
用于 N 候选澄清，或 0 候选时的近似推介：
```json
{
  "response_type": "asset_candidates",
  "response_data": {
    "source": "mcp", // 或 "catalog_cache"
    "candidates": [
      {
        "datasource_luid": "...",
        "datasource_name": "...",
        "project_name": "...",
        "match_reason": "contains match"
      }
    ],
    "message": "请问您要查询以下哪个数据源？"
  }
}
```

### 4.2 `asset_metadata`
用于 1 候选的明确资产介绍：
```json
{
  "response_type": "asset_metadata",
  "response_data": {
    "source": "mcp", // MCP不可用且本地完备时为 "catalog_cache"
    "datasource_luid": "...",
    "datasource_name": "...",
    "project_name": "...",
    "field_count": 15,
    "fields": [
      {"name": "...", "dataType": "...", "role": "..."}
    ],
    "metadata_freshness": "2026-05-20T10:00:00Z"
  }
}
```

### 4.3 `query_result`
用于表格展示（必须有 `table_display` 契约）：
```json
{
  "response_type": "query_result",
  "response_data": {
    "source": "mcp",
    "fields": ["...", "..."],
    "rows": [["...", "..."]],
    "table_display": {
      "columns": [
        {
          "key": "...",
          "label": "...",
          "semantic_type": "metric",
          "value_type": "number",
          "align": "right",
          "format": "number"
        }
      ]
    }
  }
}
```

## 5. Fallback 策略与 "catalog_cache" 完备性
- **禁止错误成功**：绝不允许在问“介绍 X 数据源”时发生 MCP unavailable，就降级返回全量数据源列表。
- **`catalog_cache` 完备性判别**：
  当 `get-datasource-metadata` 网络超时或不可达时，检查本地数据库：
  1. `tableau_assets` 表中存在该 LUID 且未标记已删除。
  2. `tableau_datasource_fields` 表中归属此 LUID 的字段行数 `count > 0`。
  满足以上两点，视为缓存完备，组装并返回 `asset_metadata`（强标记 `response_data.source = "catalog_cache"`）。否则返回 `tool_unavailable`。
- **Renderer 约束**：渲染器接收到 `source="catalog_cache"` 时，必须生成明确的用户可见的解释（如“MCP 服务当前不可用，以下为最近缓存记录”）。