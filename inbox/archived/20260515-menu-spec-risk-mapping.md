# Mulan BI Platform - 菜单结构与 Spec/风险映射梳理 (Draft)

> **创建日期**: 2026-05-15
> **阶段**: PM 草稿 (Inbox)

本文档整理了 Mulan BI Platform 当前 5 大业务域（基于 Spec 18 v0.3）的菜单结构，并映射了对应的二级菜单 URL、底层规格书（Spec）地址、开发进度以及相关的风险点（来源于 Risk Register）。

> **说明**：本文档仅映射存在 UI 前端入口的业务域模块。无可视菜单的底层协议与基础规范（如 Spec 01 错误码、Spec 02 API 约定、Spec 12 集成协议等）不在本表映射范围内。

## 1. 资产 (Assets) - `域 2`

| 二级菜单 | URL 路径 | 对应 Spec | 模块进度 | 风险点 (Risk ID) |
|---|---|---|---|---|
| Data Explorer | `/assets/explorer` | [Spec 46] Database Data Explorer | ⏭️ Next (准备实施) | - |
| 数仓资产 | `/assets/dw` | [Spec 03] 数据模型总览 | ✅ 已完成 | - |
| Tableau 资产 | `/assets/tableau` | [Spec 07] Tableau MCP V1 | ✅ 已完成 | **R-020** (连接缓存无限增长)<br>**R-010** (MCP 实例缓存单例复杂导致引用失效) |
| 知识库 | `/assets/knowledge` | [Spec 17] 知识库 | ✅ 已完成 | - |

## 2. 治理 (Governance) - `域 3`

| 二级菜单 | URL 路径 | 对应 Spec | 模块进度 | 风险点 (Risk ID) |
|---|---|---|---|---|
| 数仓巡检 | `/governance/dw-audit` | [Spec 11/35] 健康扫描/StarRocks合规 | 🚧 编写/实施中 | **R-017** (健康扫描失败重试使用的 ORM 模式错误报错) |
| Tableau 巡检 | `/governance/tableau-audit` | [Spec 10] Tableau 健康评分 | ✅ 已完成 | - |
| 数据质量监控 | `/governance/dqc` | [Spec 15/31] 数据质量监控/DQC Pipeline | ✅ 已完成 | - |
| 语义治理 | `/governance/semantic` | [Spec 09/19] 语义治理/发布日志 | ✅ 已完成 | - |
| 指标治理 | `/governance/metrics` | [Spec 30] Metrics Agent | ⏭️ Next (第一批) | **R-001** (P0: SQL注入风险 - 未转义的 f-string 拼接) |

## 3. 智能体 (Agents) - `域 4`

| 二级菜单 | URL 路径 | 对应 Spec | 模块进度 | 风险点 (Risk ID) |
|---|---|---|---|---|
| Data Agent | `/agents/data` | [Spec 28/36] Data Agent/架构 | 🚧 实施中/Next | **R-002** (P1: Prompt注入导致未授权Tool调用)<br>**R-018** (LLM降级静默失败)<br>**R-022** (P1: 同步调用阻塞事件循环) |
| SQL Agent | `/agents/sql` | [Spec 29] SQL Agent | ✅ 已完成 | **R-019** (P1: 数据源 ID 缺失导致敏感数据越权访问) |
| Metrics Agent | `/agents/metrics` | [Spec 30] Metrics Agent | ⏭️ Next (第一批) | (同指标治理模块 R-001) |
| Help Agent | `/agents/help` | [Spec 45] Help Agent | ⏭️ Next (准备实施) | - |
| Agent 监控 | `/agents/agent-monitor?tab=overview&view=runs` | [Spec 36] Agent 架构 (监控) | 🚧 实施中 | **R-012** (Agent Run 写库非事务导致僵尸记录) |
| 技能中心 | `/agents/skills` | [Spec 36] Agent 架构 (技能) | 🚧 实施中 | - |

## 4. 配置 (Config) - `域 5`

| 二级菜单 | URL 路径 | 对应 Spec | 模块进度 | 风险点 (Risk ID) |
|---|---|---|---|---|
| 数据连接 | `/system/data-connections` | [Spec 34/05] 连接管理整合/数据源 | 📋 待实施 / ✅ | **R-008** (解密后的 DB 密码残留在内存)<br>**R-025** (用户名未 URL Encode) |
| 服务配置 | `/system/service-configs` | [Spec 08/MCP统一配置] LLM/MCP | ✅ 已完成 | **R-011** (MCP会话重建无退避策略导致资源耗尽)<br>**R-014** (MCP并发SessionID硬编码预测风险) |
| MCP 调试器 | `/system/mcp-debugger` | [MCP统一配置附录] | ✅ 已完成 | **R-021** (初始化 Payload 包含客户端不该发送的 ServerInfo) |
| 任务管理 | `/system/tasks` | `/system/tasks` | ✅ 已完成 | - |

## 5. 管理 (Admin) - `域 6`

| 二级菜单 | URL 路径 | 对应 Spec | 模块进度 | 风险点 (Risk ID) |
|---|---|---|---|---|
| 用户管理 | `/system/users` | [Spec 04] 认证与 RBAC | ✅ 已完成 | **R-003** (Role 权限检查使用字典字符串比对，非强类型) |
| 权限配置 | `/system/permissions` | [Spec 04] 认证与 RBAC | ✅ 已完成 | **R-016** (P0: 权限验证底层包装器拦截返回了 Mock 数据，未透传到真实后端) |
| 操作日志 | `/system/activity` | [Spec 04] 认证与 RBAC | ✅ 已完成 | **R-023** (日志写入失败被静默吞掉，无重试队列机制) |
| Token 统计 | `/system/usage-stats/tokens` | [Spec 14] NL-to-Query | ✅ 已完成 | **R-015** (P1: CostMeter 为空实现(no-op)，Token与花费完全没有统计入库) |
| 平台设置 | `/system/platform-settings` | [Spec 27] 基础设施 | 📝 编写完成 | - |
| 消息通知 | `/notifications` | [Spec 16] 事件/通知系统 | ✅ 已完成 | - |
| 个人中心 | `/account/profile` | [Spec 04] 认证与 RBAC (个人中心模块) | ✅ 已完成 | - |

## 6. 全局/基建层风险 (Cross-cutting / Infrastructure)

部分核心组件服务于全局，不绑定单一菜单，其风险影响所有相关业务域。

| 组件模块 | 关联模块代码 | 风险点 (Risk ID) | 影响范围 |
|---|---|---|---|
| **通用限流组件** | `services/capability/rate_limiter.py` | **R-004** (PG Fallback 下限流组件 Fail-open 风险)<br>**R-005** (PG 限流检查放行逻辑缺陷) | 影响所有依赖 Rate Limiter 的底层能力服务 |
