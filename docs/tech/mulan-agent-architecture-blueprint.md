# Mulan Agent Architecture Blueprint

> 状态：**Active** | 日期：2026-05-16
> 本文档记录了 Mulan BI Platform 在引入 MCP Host 与 Data Agent 架构重构过程中达成的核心技术共识。它旨在解决“大模型灵活性”与“企业级 BI 确定性”之间的固有矛盾，指导后续 Agent 的长期演进。

## 1. 核心架构流转：QuerySpec 作为业务语义契约

**结论**：不要用大模型的“智能”去替代系统工程的“确定性”。MCP Native Function Calling 绝不能取代 `QuerySpec`。

*   **反模式**：直接将底层 MCP `tools/list` 的 Schema 喂给 LLM，让其直接生成执行参数。这种模式丢失了业务上下文、指标定义和时间粒度，导致生成的参数虽结构合法，但业务不可用。
*   **最佳实践 (Semantic Plan)**：`QuerySpec` 不是僵死的 Pydantic 壳，而是 Mulan 的**核心业务语义契约 (Business Semantic Contract)**。它负责表达业务意图、能力声明与执行约束。
*   **标准流转路径**：
    `User Intent` -> `QuerySpec (Semantic Plan)` -> `Semantic-Enriched MCP Catalog View` -> `MCP Args` -> `MCP Args Guardrail` -> `Tableau MCP`

## 2. 防线的交集公式 (The Guardrail Equation)

**结论**：安全边界必须由 Mulan 自身牢牢掌控（Choke Point），不可被下游工具 Schema “越俎代庖”。

*   **反模式**：将所有参数合法性校验完全交给下游 MCP Schema（如 Tableau 允许某个复杂的 Calculated Field，Mulan 就放行）。
*   **交集公式**：
    **`valid_args = MCP live schema ∩ Mulan policy ∩ tenant/user permission ∩ cost guardrail`**
*   **实践指导**：虽然硬编码（如 `ALLOWED_AGGREGATIONS`）带有技术债，但在彻底建立 `Capability Registry`（由 MCP 同步能力，再由 Mulan Policy 收敛）之前，不能为了 DRY 原则而牺牲本地 Guardrail 的安全拦截能力（如 OOM 拦截、危险操作拦截）。

## 3. LLM 抽象层职责边界 (The Structured Adapter)

**结论**：业务 Planner 必须纯净，JSON 的脏活交给底层适配器。

*   **反模式**：在业务层的 Planner 中写正则或 `while` 循环去抠出 JSON；或者盲目信任特定 Provider（如 OpenAI）的 `JSON Mode`，导致系统无法无缝切换到其他底座模型（如 MiniMax, Anthropic）。
*   **最佳实践**：在 LLM Service 层封装统一的 **`Provider-Agnostic Structured Adapter`**。该层负责：
    *   模型差异抹平 (Structured Generation)
    *   严格的 Schema Validation
    *   自动修复逻辑 (Repair)
    *   错误分类 (Error Classification)
    业务层 Planner 只接收通过校验的 `Validated Object` 或具体的 `Typed Error`。

## 4. 计算权威的本质 (SSOT of Formula Definition)

**结论**：公式定义唯一 (SSOT)，而不是执行位置唯一。大模型和前端渲染层永远不碰计算。

*   **反模式**：因为“计算下推 (Push-down)”的教条，强制所有派生指标都在 Tableau 内完成；或者在 Python 层随意硬编码派生逻辑，导致系统存在两套事实标准。
*   **最佳实践**：
    1.  **公式定义 SSOT**：所有的公式和口径都必须来自统一的权威注册表 (Metrics Registry)。
    2.  **执行尽量 Push-down**：基础聚合、过滤、时间粒度优先下推至 Tableau MCP。
    3.  **确定性的 Python 接管**：当 Push-down 不可用时（例如特殊的派生展示列），由 Python 的 Deterministic Postprocessor 根据 Registry 确定性计算。
    4.  **底线**：Renderer 不计算，LLM 不计算。

## 5. 走向任务编排 (Task Plan over Tool Free-play)

**结论**：Intent Gate (意图门控) 是安全与产品边界，不要为了所谓的“Agentic”而让大模型自由裸跑所有工具。

*   **反模式**：取消 8 大意图门控，给 LLM 提供所有工具（包括诊断、写入工具），让其随意决定调用链，导致权限、成本和失败面失控。
*   **最佳实践**：
    从“单标签 Intent”平滑升级为**结构化多步骤任务计划 (Task Plan)**。例如，将复杂问题拆解为 `[query, compare, explain, drilldown]`。
    关键在于：每个 Step 在执行前，都必须经过带约束（Tool Permission / Cost Budget / Data Scope）的 Guardrail 校验。自然语言可以无限开放，但系统执行必须绝对收敛。

---
*关联文档：*
*   `docs/specs/36-data-agent-architecture-spec.md`
*   `docs/specs/54-data-agent-transparent-mcp-proxy-plan.md`
