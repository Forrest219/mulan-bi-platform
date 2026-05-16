# 代码审查报告：Mulan MCP Host 与代理执行链路 (最终版)

**审查时间**：2026-05-16
**审查范围**：`backend/services/data_agent/mcp_host/` (runtime.py, planner.py, quality_gate.py) 以及周边的核心调度与防线 (`mcp_proxy_main.py`, `mcp_args_guardrail.py`, `mcp_first_main.py`)。
**关联架构蓝图**：详见 `docs/tech/mulan-agent-architecture-blueprint.md`。

---

## 1. 架构与设计层 (Architecture & Design)

### 🟢 亮点与最佳实践
*   **平滑回滚机制 (Graceful Fallback)**：`mcp_first_main.py` 中的 `_run_mcp_main_route` 设计非常稳健。它尝试走 `mcp_host` 链路，一旦发生错误或大模型吐出了非法的结构，代码能够立即回退到 `mcp_host_thin_fallback`，这保证了重构期间的线上高可用。
*   **运行时抽象隔离 (`MCPHostRuntime`)**：在 `runtime.py` 中，底层通信客户端 (`TableauMCPClient`) 与 MCP 工具的解析抽象被良好隔离。`MCPHostRuntime` 会调用 `tools/list` 缓存 Catalog，并将请求委托给 `MCPToolExecutor` 执行。

### 🔴 设计约束与架构共识 (基于技术评审)
经过架构深潜，我们确立了以下核心架构原则，这些原则比单纯的代码走查更为重要：

1.  **QuerySpec 是业务语义契约，而非僵死的壳**：
    MCP Native Function Calling 不能取代 `QuerySpec`。`QuerySpec` 是 Mulan 的核心业务语义层。正确的流转必须是：`User Intent -> QuerySpec (Semantic Plan) -> Semantic-Enriched MCP Catalog View -> MCP Args -> Guardrail -> Tableau MCP`。LLM 直接看着 `tools/list` 生成参数是不可控的，大模型必须输出带有业务约束的 Semantic Plan。
2.  **防线的交集公式 (The Guardrail Equation)**：
    安全防线必须由 Mulan 自己持有，不能推回给下游 MCP Schema。合法的参数必须是：`valid_args = MCP live schema ∩ Mulan policy ∩ tenant/user permission ∩ cost guardrail`。Mulan 必须做策略收敛，不能单纯信任下游工具声明。
3.  **公式定义的 SSOT (Single Source of Truth)**：
    核心原则是“公式定义唯一，而不是执行位置唯一”。执行可以下推给 Tableau (Push-down)，或者在不可用时由 Python 的 Deterministic Postprocessor 接管，只要 LLM 和前端 Renderer 坚决不碰计算，并统一使用 Metrics Registry 即可。
4.  **Intent Gate 是安全与产品边界**：
    Intent 锁死并非限制扩展性，放任 LLM 自由编排 MCP Tool 会导致成本、权限和失败面失控。未来的演进方向是从“单标签 intent”升级到“多步骤结构化任务计划 (Task Plan)”，每个步骤带上执行约束，而不是取消 Intent。

---

## 2. 代码实现层 (Implementation Details)

### `planner.py` (LLM 规划器)
*   **重构手写 JSON 解析**：
    当前使用 `_extract_single_json_object` 尝试容错解析 JSON。这部分脏代码不应散落在业务 Planner 里，但也不能盲目信任底层 API 的 JSON Mode（因为多模型差异）。
    **改进建议**：在 LLM Service 层封装一个 `Provider-Agnostic Structured Adapter`，由它来处理多模型的 Structured Generation、Schema Validation、自动修复和错误分类。业务层 Planner 只接收 `Validated Object`。

### `mcp_args_guardrail.py` (安全护栏)
*   **优异的防 SQL 注入与破坏性校验**：
    `_find_unsafe_operation` 遍历了 `args` 的深层结构，检查 `DANGEROUS_OPERATIONS` 和 `DANGEROUS_SQL_TOKENS`。
*   **`_validate_detail_scan` (明细扫描拦截)**：
    有效防止 OOM 的关键业务 Guardrail。
*   **硬编码枚举的处理**：
    目前代码中有大量的硬编码字典（如 `ALLOWED_AGGREGATIONS`）。虽然有技术债，但**不能简单删除或用 JSON Schema 替代**。
    **改进建议**：未来应建立 Capability Registry，从 MCP schema 同步结构能力，再由 Mulan Policy 做最终过滤。DRY 原则不能凌驾于安全边界之上。

### `runtime.py` (执行器)
*   **缺失执行层级的熔断/超时**：
    `MCPToolExecutor.execute` 中缺乏客户端层面的熔断机制。建议增加 Circuit Breaker 和超时的动态衰减逻辑，抛出专属 Error Code，防止底层 Tableau Server 雪崩拖垮 Mulan。

### `quality_gate.py` (质量门禁)
*   定位清晰，仅作验证。代码中不携带业务逻辑，符合防重构劣化的预期。

---

## 3. 总体结论与 Action Items

Mulan 的 `mcp_host` 模块在提供 MCP 直连能力上构建了坚实的基础，本次 Review 进一步厘清了它在 Mulan 整体“业务语义驱动”架构中的适配器定位。

**后续优化建议（Action Items）**：
1.  **抽取 LLM Structured Adapter**：将 `planner.py` 的解析抽离为独立组件，实现 provider-agnostic 的安全结构生成。
2.  **构建 Capability Registry 雏形**：在不削弱本地 Guardrail 的前提下，规划如何将硬编码字典动态化并结合 Mulan Policy 过滤。
3.  **增加执行熔断器**：在 `runtime.py` 调用底层 Client 时增加 Circuit Breaker，防止雪崩。
4.  **架构原则宣贯**：所有的后续 Agent 演进必须遵循 `mulan-agent-architecture-blueprint.md` 中的共识。
