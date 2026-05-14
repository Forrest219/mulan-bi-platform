# Spec24 执行排期与协作机制（项目经理特工 Orchestrator 执行手册）

> 文档状态：Execution Ready（可执行）
> 版本：v1.0
> 负责人：项目经理特工（orchestrator）
> 创建日期：2026-04-16
> 适用范围：Spec 24 为主线，联动 Spec 18 / 21 / 22
> 约束基线：`docs/ARCHITECTURE.md`（分层、路由/API 解耦、服务职责边界）

---

## 0. 手册目标与执行边界

本手册用于“接管后续执行排期与协作机制”，将 Spec24 从架构草案推进到 6 周可验收交付。执行原则：

1) 以 Spec24 为总蓝图，Spec18/21/22 作为必须落地的依赖子轨道。  
2) 采用“滚动 6 周计划 + 周度门禁 + 风险台账 + 追踪矩阵”的治理方式。  
3) 不破坏现有 5 域（/dev, /governance, /assets, /analytics, /system）及既有 API 稳定性，遵循增量演进。  
4) 使用 feature flag、影子流量与灰度验收，避免一次性切换风险。

---

## 1. 执行组织与特工分工（architect / designer / backend / frontend / qa）

## 1.1 角色定义与职责边界

| 角色/特工 | 主责范围 | 关键输出 | 不做事项 |
|---|---|---|---|
| architect | 端到端架构守门、模块拆分、依赖顺序、技术风险把关 | 架构决策记录（ADR）、模块边界图、接口演进策略、性能与审计基线 | 不直接承担 UI 视觉细节与测试执行 |
| designer | 首页与连接中心的交互/视觉系统，WebUI 风格企业化适配 | Figma/设计稿、组件 token、状态页与空态/异常态设计、交互说明 | 不定义后端对象模型与审计策略 |
| backend | Task Runtime / Connection Hub / Governance Runtime / Audit API 的增量落地 | API 合约实现、数据模型映射、SSE 事件流、审计追踪、迁移脚本 | 不决策最终视觉样式 |
| frontend | HomeTaskShell / ConnectionCenterPage / RunTimeline / Data used UI | 页面与组件实现、状态管理、路由兼容、可观测埋点 | 不绕过后端策略层直接执行业务副作用 |
| qa | 测试策略、门禁执行、回归与发布风险控制 | 测试计划、用例库、自动化脚本、质量报告、上线闸门结论 | 不定义需求优先级 |

## 1.2 RACI 协作矩阵

| 工作流 | A(最终负责) | R(执行) | C(协作) | I(知会) |
|---|---|---|---|---|
| 架构分层与依赖冻结 | architect | architect | backend/frontend/qa | designer |
| 首页工作台（Spec21+24） | frontend lead | frontend | designer/backend/qa | architect |
| 连接中心（Spec24） | backend lead | backend+frontend | designer/qa | architect |
| 多站点MCP与多LLM（Spec22） | backend lead | backend | architect/qa | frontend |
| 策略审批与审计闭环（Spec24） | architect | backend | qa/frontend | designer |
| 周门禁评审与发布Go/No-Go | qa lead | qa | architect/backend/frontend | 全员 |

## 1.3 工作节奏（固定机制）

- 每日：15 分钟站会（阻塞项、依赖项、风险更新）。
- 每周一：计划会（冻结本周目标、依赖、验收门禁）。
- 每周三：中期风险巡检（风险台账更新 + 降级预案演练）。
- 每周五：演示 + 门禁评审（Go/No-Go，进入下一周）。
- 变更控制：任何跨 Spec 范围变更需 architect+orchestrator 双签。

---

## 2. 6 周滚动计划（周目标 / 里程碑 / 依赖）

说明：采用“W1-W6”滚动排期。每周周五完成验收，未过门禁则不进入下一周开发面。

| 周次 | 周目标 | 里程碑（Milestone） | 关键依赖 |
|---|---|---|---|
| W1（架构冻结周） | 冻结 Spec24 落地边界，确定增量迁移路线与基线指标 | M1：蓝图冻结（对象模型/API/路由演进/Feature Flag 清单） | Spec24 主文档；ARCHITECTURE 约束；Spec18 路由边界 |
| W2（Task Runtime 最小可用） | 打通 TaskRun + StepRun + SSE 主链路，首页 composer 可触发 run | M2：`/api/tasks/runs` 可用，RunTimeline 可显示基础事件 | Spec22 搜索主链；Spec21 AskBar 改造入口 |
| W3（首页工作台交付） | 完成 HomeLayout 对话态/空态与 Data used 微页脚，形成可用“任务驱动首页” | M3：首页首问-回包-重试闭环通过 | Spec21 布局组件；Spec22 调用协议；设计稿冻结 |
| W4（连接中心交付） | 上线统一 Connection Hub（DB/Tableau/LLM）及兼容跳转 | M4：`/assets/connection-center` 全量可访问（按权限） | Spec18 资产域路由；Spec22 多连接数据；后端映射表策略 |
| W5（治理闭环周） | 策略评估、审批门、审计链路贯通，高风险动作强制 review gate | M5：PolicyDecision + ApprovalTicket + AuditEvent 形成闭环 | Spec24 治理层定义；现有 RBAC 模型；系统日志链路 |
| W6（稳态发布周） | 端到端压测、回归、灰度发布与复盘，形成下一轮 backlog | M6：灰度发布通过并进入常态化运营指标看板 | QA 自动化覆盖率、影子流量结果、回滚预案演练 |

---

## 3. 每周交付物与验收门禁

## 3.1 周交付物清单

| 周次 | 必交付物（Artifacts） |
|---|---|
| W1 | ① ADR（任务编排/连接中枢/治理层）② API 合约草案 v2 ③ Feature Flag 与灰度方案 ④ 风险台账 v1 |
| W2 | ① `/api/tasks/runs`、`/events`、`/cancel` 最小实现 ② Home composer 接入 TaskRun ③ RunTimeline 初版 ④ 联调记录 |
| W3 | ① HomeLayout 空态/对话态上线 ② Conversation Rail（分组/检索/新建）③ Data used 微页脚 + Show SQL 折叠 ④ 错误重试体验 |
| W4 | ① ConnectionCenterPage（Overview/DB/Tableau/Sync Logs/Policies）② KPI+Filter+DetailDrawer ③ 旧入口兼容跳转 ④ 批量操作基础能力 |
| W5 | ① Governance evaluate/approvals API ② 审批队列前端 ③ 审计查询（trace维度）④ 高风险动作 Gate 生效证据 |
| W6 | ① E2E 回归报告 ② 压测与稳定性报告 ③ 灰度发布记录与回滚演练记录 ④ 项目复盘与下一轮滚动计划 |

## 3.2 验收门禁（Gate）

| 周次 | 门禁项 | 通过标准 |
|---|---|---|
| W1 Gate | 架构/接口冻结 | ADR 审核通过；跨团队无 P0 依赖冲突；feature flag 覆盖全部新增能力 |
| W2 Gate | Task Runtime 可用性 | 创建 run 成功率 ≥ 95%；SSE 首包 < 2s；失败可 cancel 且状态可追踪 |
| W3 Gate | 首页体验可用性 | 首问成功率 ≥ 90%；错误重试成功率 ≥ 80%；移动端输入与抽屉可用 |
| W4 Gate | 连接中心可运营 | 连接测试/同步状态闭环完整；兼容跳转正确率 100%；RBAC 可见性正确 |
| W5 Gate | 治理与审计闭环 | 副作用动作 100% 绑定 policy_decision_id；trace_id 全链路可查询 |
| W6 Gate | 发布就绪 | P0/P1 缺陷清零；回滚演练通过；灰度期核心指标无显著劣化 |

---

## 4. 依赖管理与协作机制

## 4.1 关键依赖顺序（不可逆）

1) 先冻结架构边界（W1），再开编码（W2+）。  
2) Task Runtime（W2）先于首页工作台完整体验（W3）。  
3) Connection Hub（W4）先于治理强门禁（W5），否则审批对象不统一。  
4) 治理闭环（W5）先于灰度放量（W6）。

## 4.2 跨特工协作协议

- 合约先行：backend 在每周一提供可联调 OpenAPI 片段，frontend 同日完成 mock 对齐。  
- 设计冻结：designer 在开发周开始前冻结“必需交互态”；新增状态走“补丁设计单”。  
- 测试左移：qa 参与周一评审，提前定义用例与自动化脚本，不接受“开发完成后再补测试”。  
- 冲突处理：涉及 `mcp_client.py`、`llm/service.py`、首页路由等高冲突文件，按“串行合并窗口”执行（每日 2 次固定窗口）。

## 4.3 发布策略

- 全部新增能力默认 behind feature flag。  
- 先影子流量（只观测不生效）→ 再小流量灰度（10%-30%）→ 再全量。  
- 任一 Gate 不通过：冻结新需求，仅允许缺陷修复与稳定性加固。

---

## 5. 风险台账与应对策略

| 风险ID | 风险描述 | 概率 | 影响 | 触发信号 | 责任人 | 缓解措施（预防） | 应急预案（兜底） |
|---|---|---|---|---|---|---|---|
| R1 | 首页改造影响现有 5 域导航心智，用户迷失 | 中 | 高 | 首页跳出率上升、功能页访问下降 | frontend+designer | 保留 Quick Links 与旧入口映射；显式“进入管理视图”入口 | 灰度回退到旧首页入口 |
| R2 | Task Runtime 引入额外时延 | 中 | 高 | SSE 首包超时、首问耗时上升 | backend | 事件分步流式返回；耗时步骤异步化；缓存热路径 | 超时阈值触发降级到旧查询链路 |
| R3 | 多连接误用（错站点/错库） | 中 | 高 | 查询结果异常、跨环境混淆 | backend+qa | run 启动即固定 connection scope；UI 明示环境与连接 | 触发只读降级并要求人工确认 |
| R4 | 策略层被旧接口绕过 | 低-中 | 极高 | 副作用日志缺少 policy_decision_id | architect+backend | 在适配器前强制校验 policy_decision_id | 立即熔断副作用接口并回滚 |
| R5 | 审计链路不完整（trace 断链） | 中 | 高 | trace 查询缺环节 | backend+qa | trace_id 贯穿 API→service→adapter；append-only 审计 | 审计缺失即阻断发布 Gate |
| R6 | Spec22 多MCP/多LLM 改造与 Spec24 并行冲突 | 中 | 中-高 | 同文件冲突、回归失败 | architect | 冻结冲突文件合并窗口；先后顺序明确 | 冲突模块单独回滚，不影响主线 |
| R7 | 设计与实现状态不一致（空态/异常态缺失） | 中 | 中 | 验收发现未覆盖状态 | designer+frontend | 设计稿必须含 loading/error/empty/permission denied 四态 | 允许补丁周修复后再放量 |
| R8 | 测试不足导致灰度后质量波动 | 中 | 高 | 灰度缺陷激增 | qa | 关键路径 E2E 自动化，周门禁卡住 P0/P1 缺陷 | 立即暂停灰度并回滚 |

风险升级规则：
- 任一“高影响 + 已触发”风险，24 小时内必须提交专项处置单。  
- 任一“极高影响”风险触发，直接进入发布冻结。

---

## 6. 与现有 Specs 的追踪矩阵（Spec 18/21/22/24）

## 6.1 能力-规格映射矩阵

| 能力域 | Spec18（菜单重构） | Spec21（首页重构） | Spec22（问数架构） | Spec24（总架构/UI升级） | 当前状态 | 验收负责人 |
|---|---|---|---|---|---|---|
| 导航与信息架构 | 5 域路由与统一侧栏 | 首页独立 HomeLayout 与 `/chat/:id` | - | 首页工作台 + 域视图并存策略 | In Progress | architect + frontend |
| 首页交互（对话优先） | 不破坏域导航 | Conversation Rail / Suggestion / AskBar | 搜索请求与问数链路参数 | TaskRun 驱动、Data used 企业化增强 | Planned→W3 | designer + frontend |
| 任务运行时 | - | 与首页交互衔接 | 使用既有搜索链路作为执行步骤 | TaskRun/StepRun/SSE/状态机 | Planned→W2 | backend |
| 连接中枢 | 资产域路由基础 | 首页连接上下文展示 | 多站点 MCP、多连接路由 | Connection 统一抽象与中心页 | Planned→W4 | backend + frontend |
| 治理与审计 | RBAC 可见性基础 | 前端展示治理徽章 | 查询链路日志基础 | PolicyDecision/Approval/AuditTrace 强约束 | Planned→W5 | architect + qa |
| 灰度发布与兼容 | 旧路由重定向 | 首页新旧共存 | 单链路兼容 fallback | Feature Flag + 影子流量 + 逐步切流 | Planned→W6 | qa |

## 6.2 关键追踪项（Checklist）

- [ ] Spec18：旧路由兼容与 5 域可见性规则不被破坏。  
- [ ] Spec21：首页空态/对话态/移动端行为与文案一致。  
- [ ] Spec22：多连接与多 LLM 的最小可用链路已可回归验证。  
- [ ] Spec24：Task Runtime + Connection Hub + Governance Runtime 三层均有可运行最小版本。  
- [ ] 审计要求：副作用动作具备 trace_id 与 policy_decision_id 双标识。

---

## 7. 质量与度量（执行看板）

发布前核心 KPI（周度观测）：

1) 首页首问成功率（目标：≥90%）。  
2) TaskRun 成功完结率（目标：≥95%）。  
3) SSE 首包时间 P95（目标：<2s）。  
4) 连接测试成功率（目标：≥95%）。  
5) 策略评估覆盖率（副作用动作 100% 覆盖）。  
6) 审计可追溯率（trace 闭环 100%）。  
7) P0/P1 缺陷存量（上线前为 0）。

---

## 8. Orchestrator 执行指令模板（周会直接使用）

每周一发布：
- 本周唯一目标（One Goal）  
- 三个关键里程碑（M1/M2/M3）  
- 三个不可延期依赖（Deps）  
- 本周 Gate 与量化标准  
- 风险 Top3 与责任人

每周五收口：
- 已完成 / 未完成 / 阻塞原因  
- Gate 结论（Go/No-Go）  
- 下周滚动调整（仅允许调整 W+2 之后计划）

---

## 9. 结论

该执行手册将 Spec24 的“架构愿景”转化为可执行的 6 周滚动工程计划，并通过：
- 清晰分工（architect/designer/backend/frontend/qa）
- 周交付与门禁
- 风险台账
- Spec18/21/22/24 追踪矩阵

实现“边建设、边验证、可回滚”的稳态升级路径，确保木兰从菜单驱动后台平滑演进为任务驱动工作台。