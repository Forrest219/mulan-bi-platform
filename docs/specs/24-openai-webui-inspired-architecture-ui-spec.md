# Spec 24: 借鉴 OpenAI WebUI 的木兰系统架构与 UI 升级方案

> 状态: Draft  
> 作者: Hermes（已调用 Claude Code 的 architect + designer 角色并汇总）  
> 日期: 2026-04-16  
> 依赖: Spec 18（菜单重构）, Spec 21（首页重构）, Spec 22（Ask Data 架构）, ARCHITECTURE.md

---

## 1. 背景与目标

本规格用于将木兰从“菜单驱动后台”升级为“任务驱动工作台”，并在不破坏现有 5 域结构（/dev, /governance, /assets, /analytics, /system）的前提下：

1) 引入 OpenAI WebUI 的核心交互范式（对话连续性、单一主入口、渐进式复杂度）  
2) 优化系统架构以支持多 Tableau Server、多数据库（含 Hive 类引擎）、多 LLM Provider  
3) 重点完成：首页与后台管理（连接中心）设计升级  
4) UI 风格向 WebUI 靠拢，但保持企业治理场景的可审计、可控、可追溯

---

## 2. OpenAI WebUI 可迁移启发（抽象层）

### 2.1 交互模式

- 对话优先，而非菜单优先：
  - 持久会话列表
  - 全局输入器（composer）作为核心入口
  - 历史上下文连续可回放
- Run 化执行：
  - 用户输入 -> 任务运行（TaskRun）-> 多步骤执行（StepRun）-> 流式事件
- 渐进式复杂度：
  - 默认界面简洁
  - 高级参数按需展开（连接策略、超时、限流、fallback）

### 2.2 视觉模式

- 低噪音中性底色 + 单一主强调色
- 柔和边框/圆角，减少重阴影
- 信息密度高但层级明确（主内容、元数据、控制项）

### 2.3 治理模式（企业化增强）

木兰不能只“像聊天产品”，必须强化：
- 数据来源披露（来源连接、数据时效）
- 策略决策留痕（PolicyDecision）
- 操作审计全链路（trace_id）

---

## 3. 架构升级方案（系统层）

## 3.1 目标架构分层

A. API 层（backend/app/api）
- 职责：参数校验、鉴权依赖注入、响应封装
- 新增/演进路由：
  - /api/tasks/*
  - /api/connection-hub/*
  - /api/governance/*
  - /api/audit/*

B. 任务编排层（新增 backend/services/task_runtime）
- planner: 意图 -> 计划
- executor: 执行 StepRun
- state_machine: 生命周期流转
- event_bus: 事件流（SSE）

C. 连接中枢层（新增 backend/services/connection_hub）
- 统一连接抽象（Connection）
- provider adapter registry：
  - tableau_adapter
  - sql_adapter_registry（含 hive/postgres/mysql/...）
  - llm_adapter_registry（openai/anthropic/others）

D. 治理策略层（新增 backend/services/governance_runtime）
- 执行前策略判断（allow/deny/review）
- 审批门（ApprovalTicket）
- 执行后评估与风险记录

E. 身份与审计基座（扩展 auth/logs/capability）
- 全链路 trace_id
- append-only AuditEvent
- 无 PolicyDecision 不允许执行副作用步骤

## 3.2 前端目标结构（React）

- shells/
  - HomeTaskShell（任务/对话优先）
  - DomainShell（现有 5 域操作壳）
- features/task-runtime/
  - composer、run timeline、artifact viewer
- features/connection-hub/
  - 连接中心（统一 DB/Tableau/LLM）
- features/governance/
  - 审批队列、策略诊断
- platform/state/
  - ConversationStore + TaskRunStore

---

## 4. 统一对象模型（关键）

## 4.1 核心实体

1) Connection
- id, type(tableau_site/sql_database/llm_provider), provider
- name, env, owner_id, is_active, health_status
- secret_ref（只存引用/密文，不回显）
- last_check_at, last_error

2) ConnectionBinding
- task_type / purpose -> preferred connection(s)
- priority, fallback_order

3) TaskRun
- id, conversation_id, user_id, intent, status
- started_at, finished_at, trace_id

4) TaskStepRun
- task_run_id, step_type(route/generate/execute/approve/publish), status
- input_ref, output_ref, error_code

5) PolicyDecision
- policy_name, decision(allow/deny/review), reason

6) ApprovalTicket
- required_role, status, approver_id, acted_at

7) AuditEvent（append-only）
- trace_id, actor_id, action, target_type, target_id, payload_hash

## 4.2 现有表映射建议

- tableau_connections -> Connection(type=tableau_site)
- bi_data_sources -> Connection(type=sql_database)
- ai_llm_configs -> Connection(type=llm_provider)
- conversations/messages 保持不动，增加与 TaskRun 的关联

---

## 5. API 合约（v2 建议，增量演进）

## 5.1 Tasks
- POST /api/tasks/runs
- GET /api/tasks/runs/{id}
- GET /api/tasks/runs/{id}/events (SSE)
- POST /api/tasks/runs/{id}/cancel

## 5.2 Conversation
- 延续现有 /api/conversations/*
- message 可挂接 task_run_id

## 5.3 Connection Hub
- GET /api/connection-hub/connections
- POST /api/connection-hub/connections
- PATCH /api/connection-hub/connections/{id}
- POST /api/connection-hub/connections/{id}/test
- POST /api/connection-hub/connections/{id}/rotate-secret
- GET/PUT /api/connection-hub/bindings/*

## 5.4 Governance / Audit
- POST /api/governance/evaluate
- GET /api/governance/approvals
- POST /api/governance/approvals/{id}/approve|reject
- GET /api/audit/events
- GET /api/audit/traces/{trace_id}

---

## 6. 首页优化（重点）

## 6.1 目标定位

首页升级为 AI 工作台（而非导航页），路径保持：
- / -> HomeLayout + 空态工作台
- /chat/:id -> HomeLayout + 对话时间线

## 6.2 页面结构

左栏（Conversation Rail，260px）
- New Chat
- 对话检索
- 对话分组（今天/近7天/更早）
- 对话项状态（active/menu/rename/delete）
- 快捷入口（治理/资产/系统）

主区（Workspace）
- 顶部上下文条：环境、连接/模型、治理徽章
- 空态：Hero + 4 张建议卡 + composer
- 对话态：消息时间线 + 结构化结果卡（表格/SQL/解释）

底部（Sticky Composer）
- 输入框（Enter 发送，Shift+Enter 换行）
- 发送按钮（主 CTA）
- 次级控制（数据源选择、附件占位、快捷键提示）

## 6.3 企业化增强（相对 WebUI）

每条助手回答增加 “Data used” 微页脚：
- connection 名称
- 数据时间戳
- 权限作用域
- 可展开 “Show SQL/logic”

---

## 7. 后台管理优化（重点）：连接中心

## 7.1 IA 重构

新增统一入口：/assets/connection-center

兼容跳转：
- /assets/datasources -> /assets/connection-center?type=db
- /assets/tableau-connections -> /assets/connection-center?type=tableau

Tab：
- Overview
- DB
- Tableau
- Sync Logs
- Policies（admin）

## 7.2 连接中心布局

- Header：连接中心 + New Connection + Bulk Actions
- KPI 条：Total / Healthy / Warning / Failed / 24h 同步成功率
- Filter 行：搜索、状态、owner、环境、激活状态
- 主区：列表/卡片双视图
- 右侧详情抽屉：连接配置、健康、日志、审计、凭据策略

## 7.3 核心交互状态

- Test Connection：idle -> running -> success/fail
- Sync Now：queued -> running -> completed/failed
- 批量操作：bulk test / bulk sync / bulk enable
- 空态：无连接向导
- 错误态：重试 + 诊断日志 + 权限提示

---

## 8. 视觉风格系统（贴合 WebUI）

## 8.1 Design Tokens（建议）

颜色
- bg.canvas: #F8FAFC
- bg.surface: #FFFFFF
- border.default: #E2E8F0
- text.primary: #1A202C
- text.tertiary: #6B7280
- accent.primary: #2563EB
- accent.primary.hover: #1D4ED8
- success: #059669
- warning: #D97706
- danger: #DC2626

排版
- title: 24/32, 700
- h2: 18/28, 600
- body: 14/22, 400
- caption: 12/18, 400

圆角/阴影/动效
- radius: 8/10/12/16
- shadow.overlay: 0 10px 30px rgba(2,6,23,0.12)
- transition: 150-220ms

## 8.2 风格原则

- 少即是多：优先用排版与边框组织信息
- 单一强调色：蓝色仅用于主动作与聚焦
- 治理信号色：绿/黄/红只用于健康与风险，不用于主导航

---

## 9. 分阶段落地计划

Phase 0（准备）
- 保持现有 5 域和 API
- 补齐 trace_id 贯通与审计字段

Phase 1（任务运行壳）
- 上线 /api/tasks/runs + SSE
- 首页 composer 接入 TaskRun
- 其他域页面不动

Phase 2（连接中枢）
- 建立 connection-hub API 与统一列表页
- 适配 existing 表（先映射，不强制大迁移）

Phase 3（治理闭环）
- 策略引擎 + 审批流上线
- 高风险动作强制 review gate

Phase 4（导航策略升级）
- “首页工作台”为默认入口
- 5 域保留为“运营/管理视图”
- 渐进弃用旧分散入口

---

## 10. 风险与护栏

风险
- 跨连接误用（错站点/错库）
- 旧接口绕过策略层
- 审计碎片化
- 编排链路导致时延增加

护栏
- run 启动时固定 connection scope（不可变）
- adapter 执行前必须携带 policy_decision_id
- 审计 append-only + trace_id 强制
- 副作用接口加 idempotency key
- 全部改造走 feature flag + 影子流量验证

---

## 11. 首页与后台页实现清单（React 级）

首页
- [ ] Home page 空态/对话态状态机
- [ ] AskBar 升级为 sticky composer + toolbar slots
- [ ] MessageTimeline + ResultCard 变体
- [ ] 回答底部 Data used / Show SQL 折叠

后台（连接中心）
- [ ] 新增 ConnectionCenterPage
- [ ] 统一 view model（DB/Tableau/LLM）
- [ ] KPI + Filter + Table/Card 双视图
- [ ] 详情抽屉 + 事件时间线
- [ ] 批量操作与权限态处理

验收
- [ ] 首页首问成功率、恢复能力（错误重试）
- [ ] 连接测试/同步可观测闭环
- [ ] role-based 可见性正确
- [ ] 移动端抽屉与输入区可用

---

## 12. 结论

本方案不是“复制 OpenAI 页面”，而是提炼其高效范式并企业化：
- 交互上：任务驱动 + 对话连续性
- 架构上：Task Runtime + Connection Hub + Governance Runtime
- UI 上：首页工作台化、后台连接中心化
- 管控上：RBAC、审批、审计成为系统底座

该路径可在不推翻现有 5 域体系的情况下，完成木兰从“功能后台”到“治理操作系统”的升级。
