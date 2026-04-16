# Spec 24 实施架构路线图（Architect 接管版）

> 文档目标：将 Spec 24 从“架构设想”落到可执行后端与平台改造计划（不改业务代码，仅输出实施方案）
> 
> 版本：v1.0
> 
> 日期：2026-04-16
> 
> 关联输入：
> - `docs/specs/24-openai-webui-inspired-architecture-ui-spec.md`
> - `docs/ARCHITECTURE.md`
> - `docs/specs/22-ask-data-architecture.md`
> - `docs/specs/20-capability-wrapper-spec.md`

---

## 1. 基线与约束

### 1.1 当前后端基线（已核对仓库）
- 路由层：`backend/app/api/*`，在 `backend/app/main.py` 统一注册。
- 业务层：`backend/services/*`，当前已有 `llm/tableau/datasources/governance/events/capability/tasks` 等模块。
- 已有能力：
  - `/api/search/query` 具备 NLQ 主链路（含 trace_id 审计写入 `bi_capability_invocations`）。
  - `/api/conversations/*` 已存在会话与消息 CRUD。
  - `/api/tasks/{task_id}/status` 目前仅 Celery 状态查询，不是 TaskRun 编排 API。
  - LLM 多 purpose（Spec 22）与 capability audit（Spec 20 Phase 1）已具备基础。

### 1.2 强制架构约束（来自 ARCHITECTURE）
- `backend/services` 禁止引入 FastAPI/Starlette。
- `backend/app/api` 仅做路由、参数校验、依赖注入、响应封装。
- 迁移必须走 Alembic，必须可 downgrade。
- 改造期间保持现有 5 域与现有 API 可用。

### 1.3 本路线图目标
1) 在不推翻现有结构下引入 Task Runtime + Connection Hub + Governance Runtime。
2) 以 P0-P4 分阶段推进，阶段内给出到模块级清单（`backend/app/api` 与 `backend/services`）。
3) 明确 Connection/TaskRun/PolicyDecision/AuditEvent 的迁移路径与兼容策略。
4) 每阶段给出 DoD、风险、回滚、验收指标。

---

## 2. 目标后端分层（落地映射）

### 2.1 API 层（`backend/app/api`）
新增/演进路由前缀：
- `/api/tasks/runs*`（新 TaskRun 编排接口；保留现 `/api/tasks/{id}/status`）
- `/api/connection-hub/*`（统一连接管理）
- `/api/governance/*`（策略评估与审批）
- `/api/audit/*`（审计与 trace 查询）

### 2.2 服务层（`backend/services`）
新增服务域：
- `task_runtime/`：planner、executor、state_machine、event_bus
- `connection_hub/`：统一 Connection 模型、adapter registry（tableau/sql/llm）
- `governance_runtime/`：策略决策、审批门、执行后风险评估
- `audit_runtime/`：统一 AuditEvent 写入与 trace 聚合查询

与现有模块关系：
- `services/llm`、`services/tableau`、`services/datasources` 作为 adapter 下游保留。
- `services/capability` 继续作为治理网关底座，与 governance_runtime 对接。
- `services/events` 作为通知分发可复用。

---

## 3. 分阶段实施计划（P0-P4）

## P0（基座对齐与可观测性兜底）
目标：不改变用户主流程，先打通 trace/audit 与新模型骨架。

### P0-API 改造清单（`backend/app/api`）
- `app/main.py`
  - 注册占位路由：`/api/audit`、`/api/governance`、`/api/connection-hub`（可先只开放 health/readiness 接口）。
- `api/search.py`
  - 标准化响应头透出 `trace_id`（兼容 body 中已有 `trace_id`）。
  - 补充对 TaskRun 预留字段（如 `task_run_id` 可空，不破坏现响应）。
- `api/tasks.py`
  - 保留旧接口 `/{task_id}/status`；新增文档标识 legacy。

### P0-Services 改造清单（`backend/services`）
- 新增 `services/audit_runtime/`：
  - `trace.py`（trace_id 生成/继承规范，兼容 capability.audit）。
  - `writer.py`（AuditEvent 抽象写入接口，先双写到旧审计表或映射层）。
- 新增 `services/task_runtime/`（骨架，不切流）：
  - `models.py`（TaskRun/TaskStepRun 状态枚举）
  - `state_machine.py`（pending/running/succeeded/failed/cancelled）
- 新增 `services/connection_hub/`（只做读模型聚合）：
  - `unified_view.py` 将 `tableau_connections` + `bi_data_sources` + `ai_llm_configs` 转为统一 Connection DTO。

### P0 DoD
- [ ] 新增路由前缀均可被主应用加载，`/health` 不回归。
- [ ] `trace_id` 在 search 链路可稳定透传（日志、响应、审计至少两处一致）。
- [ ] 不影响现有 `/api/search/*`、`/api/conversations/*`、`/api/tasks/{id}/status` 行为。
- [ ] 新增服务骨架无 FastAPI 依赖，符合分层约束。

---

## P1（Task Runtime 最小闭环）
目标：首页/对话入口可调用 TaskRun，新旧链路并存。

### P1-API 改造清单（`backend/app/api`）
新增文件建议：
- `api/task_runs.py`
  - `POST /api/tasks/runs`：创建并启动 run（同步返回 run_id）。
  - `GET /api/tasks/runs/{id}`：查询 run 状态与 step 摘要。
  - `GET /api/tasks/runs/{id}/events`：SSE 事件流。
  - `POST /api/tasks/runs/{id}/cancel`：取消。
- `api/conversations.py`
  - `conversation_messages` 增加 `task_run_id` 输出（字段可空，向后兼容）。

兼容要求：
- 旧 `/api/search/query` 继续可用，内部可“桥接调用” TaskRuntime（feature flag 控制）。

### P1-Services 改造清单（`backend/services`）
- `services/task_runtime/`
  - `planner.py`：将用户问题映射为 step plan（route/generate/execute）。
  - `executor.py`：复用 `services.llm.nlq_service`、`services.tableau.mcp_client`。
  - `event_bus.py`：SSE 可消费事件协议（run.started/step.finished/run.failed）。
  - `repository.py`：TaskRun/TaskStepRun 持久化。
- `services/capability/`
  - 在 invoke 链路中记录 `task_run_id`（若存在）。

### P1 DoD
- [ ] `/api/tasks/runs` 四个核心端点可用，OpenAPI 可见。
- [ ] 单次 run 至少生成 1 条 step 记录和完整状态流转。
- [ ] SSE 能实时推送 run 生命周期事件。
- [ ] `/api/search/query` 保持兼容（请求/响应字段不删）。

---

## P2（Connection Hub 上线：统一连接域）
目标：统一 DB/Tableau/LLM 连接视图与管理 API；先映射后收敛。

### P2-API 改造清单（`backend/app/api`）
新增文件建议：
- `api/connection_hub.py`
  - `GET /api/connection-hub/connections`
  - `POST /api/connection-hub/connections`
  - `PATCH /api/connection-hub/connections/{id}`
  - `POST /api/connection-hub/connections/{id}/test`
  - `POST /api/connection-hub/connections/{id}/rotate-secret`
  - `GET /api/connection-hub/bindings`
  - `PUT /api/connection-hub/bindings/{binding_id}`

兼容路由策略：
- 保留旧路由：`/api/datasources`、`/api/tableau`、`/api/llm`。
- 在响应中增加 `connection_id`（统一域 ID）并透出 `legacy_ref`。

### P2-Services 改造清单（`backend/services`）
- 新增 `services/connection_hub/`
  - `models.py`：Connection/ConnectionBinding。
  - `registry.py`：adapter registry（tableau/sql/llm）。
  - `service.py`：统一 CRUD + test/health。
  - `secret_manager.py`：secret_ref 生命周期（仅引用不回显）。
- 适配器建议：
  - `adapters/tableau_adapter.py` 调用 `services.tableau`。
  - `adapters/sql_adapter.py` 调用 `services.datasources`。
  - `adapters/llm_adapter.py` 调用 `services.llm`。

### P2 DoD
- [ ] Connection Hub API 能列出三类连接并支持基础操作。
- [ ] 旧三套 API 与新 Hub API 并存且数据一致（抽样比对）。
- [ ] 凭据轮换接口不返回明文 secret。
- [ ] 连接测试可观测（成功率、耗时、错误码）可被审计查询。

---

## P3（Governance Runtime：策略与审批闭环）
目标：高风险动作“先决策后执行”，策略留痕可追溯。

### P3-API 改造清单（`backend/app/api`）
新增文件建议：
- `api/governance_runtime.py`
  - `POST /api/governance/evaluate`
  - `GET /api/governance/approvals`
  - `POST /api/governance/approvals/{id}/approve`
  - `POST /api/governance/approvals/{id}/reject`
- `api/audit.py`
  - `GET /api/audit/events`
  - `GET /api/audit/traces/{trace_id}`

### P3-Services 改造清单（`backend/services`）
- 新增 `services/governance_runtime/`
  - `policy_engine.py`：产出 PolicyDecision（allow/deny/review）。
  - `approval_service.py`：ApprovalTicket 创建与状态机。
  - `enforcer.py`：副作用步骤执行前强制校验 `policy_decision_id`。
- 新增 `services/audit_runtime/query.py`
  - 聚合 capability audit + task step + policy decision 形成 trace timeline。
- 对接 `services/events`：审批事件通知。

### P3 DoD
- [ ] 高风险动作无法绕过 policy gate（无 decision_id 即拒绝）。
- [ ] review 决策会生成审批单并驱动后续状态。
- [ ] `trace_id` 可串联 TaskRun、PolicyDecision、AuditEvent。
- [ ] 审批 API 具备 RBAC 防护与完整审计记录。

---

## P4（默认入口切换与旧接口渐进收敛）
目标：以 TaskRun + Connection Hub + Governance 作为默认执行面，旧入口兼容保留。

### P4-API 改造清单（`backend/app/api`）
- `/api/search/query` 标记 deprecated（Header: `Sunset` + 文档公告）。
- 新增 `/api/tasks/runs` 能力说明与迁移指引。
- 旧连接 API 返回迁移提示字段：`{"deprecation": {...}}`。

### P4-Services 改造清单（`backend/services`）
- `task_runtime` 成为默认编排入口；search 变 adapter。
- `connection_hub` 成为唯一写入口；旧服务降为兼容 facade。
- `audit_runtime` 作为统一审计查询入口，`bi_capability_invocations` 作为历史数据源之一。

### P4 DoD
- [ ] 新首页工作台流量 >80% 走 TaskRun（可观测统计）。
- [ ] 旧接口调用失败率不高于改造前基线。
- [ ] 发布后 2 个迭代内无 P1 级事故（数据错连/策略绕过/审计缺失）。
- [ ] 形成可执行下线计划（但暂不强制下线旧接口）。

---

## 4. 数据模型迁移策略（Connection / TaskRun / PolicyDecision / AuditEvent）

原则：先“并存映射”，后“统一收口”；每一步可回滚。

### 4.1 Connection 迁移
目标表（建议）：`bi_connections`、`bi_connection_bindings`。

阶段策略：
1. P0-P1：只做读映射（不改旧表）。
2. P2：创建新表并回填：
   - `tableau_connections` -> `bi_connections(type='tableau_site')`
   - `bi_data_sources` -> `bi_connections(type='sql_database')`
   - `ai_llm_configs` -> `bi_connections(type='llm_provider')`
3. P2-P3：双写（新写入同时回写旧表或保持映射关系）。
4. P4：新写入口只走 `bi_connections`，旧表只读兼容。

关键字段建议：
- `legacy_type` + `legacy_id`（强制保留）
- `secret_ref`（替代明文/可逆回显）
- `health_status/last_check_at/last_error`

### 4.2 TaskRun 迁移
目标表（建议）：`bi_task_runs`、`bi_task_step_runs`。

阶段策略：
1. P1 直接新建表，不复用 Celery result backend。
2. 为会话消息增加可空关联：`conversation_messages.task_run_id`。
3. `/api/search/query` 在桥接模式写入 TaskRun（可选）。
4. 后续统一由 TaskRun 驱动会话与执行轨迹。

### 4.3 PolicyDecision 迁移
目标表（建议）：`bi_policy_decisions`、`bi_approval_tickets`。

阶段策略：
1. P3 新建表并仅接入高风险动作。
2. 将 capability 拒绝/放行记录标准化沉淀为 PolicyDecision。
3. 强制副作用步骤引用 `policy_decision_id`（外键或逻辑约束）。

### 4.4 AuditEvent 迁移
目标表（建议）：`bi_audit_events`（append-only）。

阶段策略：
1. P0 创建统一写入接口，先可双写到 `bi_capability_invocations`。
2. P3 起重要链路写 `bi_audit_events`，旧表作为历史兼容源。
3. P4 统一查询入口 `/api/audit/*` 聚合新旧表，逐步去除对旧表直查。

### 4.5 Alembic 实施顺序（建议）
- `rev_a`: create_bi_connections_and_bindings
- `rev_b`: create_bi_task_runs_and_step_runs + add_task_run_id_to_conversation_messages
- `rev_c`: create_bi_policy_decisions_and_approval_tickets
- `rev_d`: create_bi_audit_events + indexes
- 每个 revision 均提供 downgrade（删表/删列/删索引）。

---

## 5. API 契约清单与兼容策略

### 5.1 新增契约（目标态）
- Tasks
  - `POST /api/tasks/runs`
  - `GET /api/tasks/runs/{id}`
  - `GET /api/tasks/runs/{id}/events` (SSE)
  - `POST /api/tasks/runs/{id}/cancel`
- Connection Hub
  - `GET/POST/PATCH /api/connection-hub/connections*`
  - `POST /api/connection-hub/connections/{id}/test`
  - `POST /api/connection-hub/connections/{id}/rotate-secret`
  - `GET/PUT /api/connection-hub/bindings*`
- Governance / Audit
  - `POST /api/governance/evaluate`
  - `GET /api/governance/approvals`
  - `POST /api/governance/approvals/{id}/approve|reject`
  - `GET /api/audit/events`
  - `GET /api/audit/traces/{trace_id}`

### 5.2 既有契约保留（兼容）
- `/api/search/query`（保留至 P4）
- `/api/datasources/*`、`/api/tableau/*`、`/api/llm/*`（保留至 P4）
- `/api/tasks/{task_id}/status`（legacy，直至 TaskRun 完全替代）

### 5.3 兼容机制
- 版本策略：默认 v1 路径不变；新能力通过新增前缀发布。
- 字段策略：仅“加字段不删字段”，例如响应加 `task_run_id/connection_id/trace_id`。
- 行为策略：旧接口内部可桥接新服务，但响应结构保持原样。
- 退场策略：P4 开始发出 deprecation header 与迁移文档，不立即硬切。

---

## 6. 风险、回滚与验收指标

### 6.1 关键风险
1. 跨连接误路由导致错库/错站点查询。
2. 旧接口绕过治理层，形成“无决策执行”。
3. 审计分散，trace 断链。
4. TaskRun 编排引入时延，影响首页首问成功率。
5. 双写/映射期间数据一致性漂移。

### 6.2 护栏
- Run 启动时固化 connection scope（执行过程不可变）。
- 副作用 step 强制校验 `policy_decision_id`。
- AuditEvent append-only + trace_id 必填。
- 幂等键：`Idempotency-Key` 用于取消/审批/rotate-secret。
- 全链路 feature flag：`TASK_RUNTIME_ENABLED`、`CONNECTION_HUB_WRITE_ENABLED`、`GOVERNANCE_GATE_ENFORCED`。

### 6.3 回滚策略
- 代码回滚：按 phase 灰度开关逐级关闭新入口，回到旧链路。
- 数据回滚：
  - 新表保留（不立即删），停止写入即可。
  - 回滚至旧 API 时，读路径切回 legacy service。
- 发布回滚触发条件（建议）：
  - 首问成功率下降 >5%
  - P1/P2 缺陷（审计丢失、策略绕过、错库执行）出现任一即回滚

### 6.4 验收指标（全局）
- 功能指标：
  - TaskRun 成功率、取消成功率、SSE 断流率
  - Connection test 成功率、平均耗时
  - 审批 SLA（review 到决策耗时）
- 治理指标：
  - 无 decision_id 的副作用调用次数（目标=0）
  - trace 贯通率（TaskRun→PolicyDecision→AuditEvent）
- 稳定性指标：
  - P95 响应时延（与改造前基线对比）
  - 错误码分布（4xx/5xx，按模块）

---

## 7. 阶段里程碑与交付物

- P0 交付物：
  - 路由骨架、trace 规范、审计统一写接口设计稿、feature flag 定义
- P1 交付物：
  - TaskRun API + service 最小闭环、SSE 事件协议、桥接方案
- P2 交付物：
  - Connection Hub API、统一连接模型、adapter registry、secret_ref 机制
- P3 交付物：
  - governance evaluate/approval API、policy gate 强制执行、audit trace 查询
- P4 交付物：
  - 默认入口切换方案、兼容公告、旧接口退场时间表

---

## 8. 执行建议（节奏）

建议迭代节奏：
- Sprint A：P0 + P1（先让 TaskRun 可跑）
- Sprint B：P2（连接中心统一）
- Sprint C：P3（治理强制化）
- Sprint D：P4（默认入口切换与收敛）

每个 Sprint 发布前必须满足：
1) 数据迁移已在 staging 完成 upgrade/downgrade 演练。
2) 兼容回归（search/conversations/tableau/datasources/llm）通过。
3) 观测看板新增指标可见并有报警阈值。

---

## 9. 最终结论

本路线图采用“并存映射 -> 双写桥接 -> 默认切换 -> 渐进收敛”的低风险路径，将 Spec 24 抽象架构落到可执行后端计划：
- 以 TaskRun 替代散装执行链路；
- 以 Connection Hub 统一三类连接模型；
- 以 Governance Runtime + AuditEvent 建立可审计可追溯闭环；
- 全程保持现有 API 与 5 域结构可用，满足渐进式演进与可回滚要求。
