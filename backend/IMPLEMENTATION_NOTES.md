# NL-to-Query 流水线实现笔记
# Spec 14 v1.1 修复交付

## 修复清单

| # | 函数/方法 | 文件 | 修复内容 |
|---|----------|------|---------|
| 1 | `one_pass_llm()` | `services/llm/nlq_service.py` | `complete_with_temp` → `complete_for_semantic`（OpenAI `response_format=json_object`） |
| 2 | `_retry_with_feedback()` | `services/llm/nlq_service.py` | 重试调用同样改用 `complete_for_semantic` |
| 3 | `get_datasource_fields_cached()` | `services/llm/nlq_service.py` | 查询 `TableauDatasourceField`（修复错误查询 `TableauAsset` 的 N+1 逻辑） |
| 4 | `_build_fields_with_types()` | `app/api/search.py` | 使用 `ContextAssembler.build_field_context` 实现 P0-P5 截断 + 2500 Token 预算 |
| 5 | `sanitized_fields` 构建 | `app/api/search.py` | 批量 JOIN `TableauFieldSemantics` 查 sensitivity_level，完成字段级敏感过滤 |
| 6 | `resolve_fields()` 调用 | `app/api/search.py` | 传入 `sanitized_fields`（非 raw fields），防止敏感字段泄露至阶段2 |

---

## 对比校验表

| 功能点 | Spec 定义 | 实际实现状态 | 是否对齐 |
|--------|---------|-------------|---------|
| 并发安全 (P0) | 使用 contextvars 传递 PAT，严禁操作 os.environ | MCP Client 通过 JSON-RPC `env` payload 传递凭据（per-request 隔离，非 os.environ），架构无竞态 | ✅ |
| 流水线架构 | One-Pass 合并输出 intent 与 vizql_json，Stage 1 与 Stage 2 无循环依赖 | Stage 1 使用原始字段表（已 sanitized）生成 vizql_json；Stage 2 为独立后置校验 | ✅ |
| Token 预算 | 严格执行 3000 Tokens 预算与 P0-P5 截断，剔除 HIGH 敏感字段 | `ContextAssembler.build_field_context` 处理 P0-P5 截断（2500 tokens）；`sanitize_fields_for_llm` 过滤 HIGH/CONFIDENTIAL | ✅ |
| 敏感字段过滤 | Stage 1 上下文中禁止 HIGH/CONFIDENTIAL 字段 | 批量 JOIN `TableauFieldSemantics` 获取 sensitivity_level，`sanitize_fields_for_llm` 过滤后注入上下文 | ✅ |
| 路由性能 | 多数据源评分调用字段时命中 Redis 缓存，无 DB N+1 扫描 | `get_datasource_fields_cached` 先查 Redis，未命中才查 DB（`TableauDatasourceField`）并回写缓存 | ✅ |
| JSON 重试 | 仅重试 1 次，且强制在 Prompt 追加上一次的解析错误原因 | `_retry_with_feedback` 使用 `ONE_PASS_RETRY_TEMPLATE` 追加 error_details，重试耗尽返回 NLQ_003 | ✅ |
| LLM 超参 | temperature=0.1（硬编码），OpenAI 额外 `response_format=json_object` | `complete_for_semantic` 内部路由：OpenAI → `_openai_complete_with_semantic`(json_object)；Anthropic → `_anthropic_complete_with_temp`(temp=0.1) | ✅ |
| Schema 校验 | 意图仅限 aggregate/filter/ranking/trend/comparison | `ONE_PASS_OUTPUT_SCHEMA` enum 约束；非 enum 值触发校验失败 → 重试 → NLQ_003 | ✅ |
| 置信度阈值 | confidence < 0.5 → NLQ_002 | `search.py` 置信度检查在 one_pass_result 返回后立即执行 | ✅ |
| 数据源路由 | 字段覆盖度×0.5 + 新鲜度×0.25 + 字段数×0.1 + 使用频次×0.15，阈值 0.3 | `calculate_routing_score` 实现完整公式；低于阈值返回 None → NLQ_005 | ✅ |

---

## 架构决策说明

### 1. PAT 凭据传递方式（Constraint A）
**Spec 要求**：严禁 `os.environ` 写入，改为 contextvars 或函数传参。

**实际实现**：MCP Client 通过 JSON-RPC 请求体中的 `env` 字段传递 PAT（per-request HTTP 调用隔离），未触碰 `os.environ`。

**理由**：`os.environ` 是进程级全局变量，在 FastAPI 异步并发场景下会产生竞态。但当前 MCP Client 通过 HTTP JSON-RPC 与 MCP Server 通信，每个请求的生命周期仅限于一次 HTTP 往返，不存在跨请求污染。`env` 字典作为请求体参数传递，属请求级隔离，安全。

**若未来 MCP Server 改为在进程内 spawn subprocess 并从 `env` 设置 `os.environ`**，则需引入 `contextvars` 改造。当前设计已留有改造空间（凭据不依赖全局状态）。

### 2. Token 预算分配
- System Prompt: 200 tokens
- User Instruction (数据源信息 + 术语映射 + 问题): 300 tokens
- **字段上下文可用**: 2500 tokens (`MAX_CONTEXT_TOKENS=3000 - 200 - 300`)
- 总上限: 3000 tokens（与 Spec 12 §3.2 对齐）

### 3. 字段敏感度批量查询
`search.py` 在获取字段列表后，批量查询 `TableauFieldSemantics`（按 `field_registry_id IN (...)`），合并 sensitivity_level 到字段字典。避免 N+1 查询问题。

---

## 待观察项（Open Issues）

| # | 问题 | 优先级 | 说明 |
|---|------|--------|------|
| OI-01 | `resolve_fields` 现阶段仅做精确匹配，缺少同义词/模糊匹配/LLM 兜底 | P1 | 完整实现需接入同义词表、语义标注、编辑距离算法 |
| OI-02 | 计算字段（formula 非空）是否允许 NL-to-Query，VizQL 支持情况待验证 | P2 | Spec 14 OI-09 |
| OI-03 | MCP Server 若 spawn subprocess 并设置 os.environ，则需 contextvars 改造 | P1 | 见上文"架构决策 1" |
