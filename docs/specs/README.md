# Mulan BI Platform — 技术规格书索引

> 最后更新：2026-04-24

## 状态说明

| 标记 | 含义 |
|------|------|
| :white_check_mark: | 已完成 |
| :construction: | 编写中 |
| :clipboard: | 待编写 |
| :next_track_button: | Next（下一批开发） |
| :pause_button: | Deferred（暂不开发） |

---

## Tier 0 — 基础规范

| # | 文档 | 说明 | 状态 |
|---|------|------|------|
| 00 | [Spec 模板](00-spec-template.md) | 标准化模板 | :white_check_mark: |
| 01 | [统一错误码](01-error-codes-standard.md) | 错误码体系 + 模块前缀 | :white_check_mark: |
| 02 | [API 约定](02-api-conventions.md) | 认证/分页/响应包络/版本策略 | :white_check_mark: |
| 03 | [数据模型总览](03-data-model-overview.md) | 全量 ER 图 + 迁移 + 命名约定 | :white_check_mark: |

## Tier 1 — 核心模块

| # | 文档 | 说明 | 状态 |
|---|------|------|------|
| 04 | [认证与 RBAC](04-auth-rbac-spec.md) | 4 角色权限矩阵 | :white_check_mark: |
| 05 | [数据源管理](05-datasource-management-spec.md) | CRUD + 加密 + 6 DB 类型 | :white_check_mark: |
| 06 | [DDL 合规检查](06-ddl-compliance-spec.md) | DDL 检查引擎 + 规则配置 | :construction: v1.1 |
| 07 | [Tableau MCP V1](07-tableau-mcp-v1-spec.md) | Phase 1: 连接/同步/浏览 | :white_check_mark: |
| 08 | [LLM 能力层](08-llm-layer-spec.md) | 配置/服务/提示词模板 | :white_check_mark: |
| 09 | [语义治理](09-semantic-maintenance-spec.md) | 全生命周期 (draft→published) | :white_check_mark: |
| 10 | [Tableau 健康评分](10-tableau-health-scoring-spec.md) | 7 因子加权评分 | :white_check_mark: |
| 11 | [数仓健康扫描](11-health-scan-spec.md) | DDL 引擎 + 实时 DB 扫描 | :white_check_mark: |

## Tier 2 — 集成协议

| # | 文档 | 说明 | 状态 |
|---|------|------|------|
| 12 | [语义↔LLM 集成](12-semantic-llm-integration-spec.md) | 上下文组装 + 输出契约 | :white_check_mark: |
| 13 | [MCP V2 直连](13-tableau-mcp-v2-direct-connect-spec.md) | 直查协议 + 缓存 + 降级 | :white_check_mark: |

## Tier 3 — 特性扩展

| # | 文档 | 说明 | 状态 |
|---|------|------|------|
| 14 | [NL-to-Query](14-nl-to-query-pipeline-spec.md) | 自然语言查询全链路 | :white_check_mark: |
| 15 | [数据质量监控](15-data-governance-quality-spec.md) | 规则定义层（规则引擎 + CRUD） | :white_check_mark: |
| 16 | [事件/通知系统](16-notification-events-spec.md) | 统一事件总线 + 通知 | :white_check_mark: |
| 17 | [知识库](17-knowledge-base-spec.md) | 术语表 + Schema + RAG | :white_check_mark: |
| 18 | [菜单重构](18-menu-restructure-spec.md) | 5 域导航布局 | :white_check_mark: |
| 19 | [发布日志](19-semantic-publish-logs-spec.md) | 回写审计日志 UI | :white_check_mark: |
| 20 | [运维工作台](spec-20-ops-workbench.md) | Split-Pane 问数+资产+健康统一入口 | :construction: |
| 26 | [Agentic Tableau MCP / Tableau Agent](26-agentic-tableau-mcp-spec.md) | 从"查数"到"控场"：字段匹配 + 视图控制 + 语义写回 | :pause_button: Deferred |
| 26A | [Viz Agent](26-viz-agent-addendum.md) | 图表推荐 + Tableau 输出引导（Spec 26 附录） | :pause_button: Deferred |
| 28 | [Data Agent](28-data-agent-spec.md) | 归因分析 + 自动报告生成 + 主动洞察（ReAct 框架） | :next_track_button: Next（第 2 批） |
| 29 | [SQL Agent](29-sql-agent-spec.md) | 多方言 SQL 执行 + 安全校验 + 查询日志 | :white_check_mark: |
| 30 | [Metrics Agent](30-metrics-agent-spec.md) | 指标注册 + 血缘追踪 + 一致性校验 + 异常检测 | :next_track_button: Next（第 1 批） |
| 31 | [DQC Pipeline](31-governance-dqc-pipeline-spec.md) | 执行层（流水线调度 + 执行 + 结果存储） | :white_check_mark: |
| 32 | [MCP-Tableau Bridge](32-mcp-tableau-connection-bridge-spec.md) | MCP→Tableau 连接自动桥接 | :white_check_mark: |
| 33 | [任务管理](33-task-management-spec.md) | Celery 任务调度与监控 | :white_check_mark: |
| 34 | [连接管理整合](34-connection-management-spec.md) | 恢复 CRUD 路由 + 汉化 + 冒烟测试 + 导航修复 | :clipboard: 待实施 |
| 35 | [StarRocks 数仓合规巡检](35-starrocks-compliance-inspection-spec.md) | 扩展健康扫描引擎，25 条 StarRocks 规则 + 数仓合规 Tab | :construction: |
| 36 | [Data Agent 架构](36-data-agent-architecture-spec.md) | Agent 框架（ReAct 引擎 + 工具注册 + 首页接入），Spec 28 的实施基座 | :construction: |
| 38 | [问数界面](38-query-interface-spec.md) | Connected Apps JWT 用户模拟 + 内建问数前端 | :white_check_mark: |

## 附录 — 独立 Spec

| 文档 | 说明 | 状态 |
|------|------|------|
| [MCP 统一配置](spec-mcp-configs.md) | MCP Server CRUD + AI 解析（v1.1 补 credentials） | :white_check_mark: |
| [LLM-Tableau-MCP 配置](spec-llm-tableau-mcp-config.md) | 早期 MCP 状态卡（部分被 spec-mcp-configs 取代） | :white_check_mark: |
| [首页 UI 修复](spec-homepage-ui-bug-fix.md) | 首页 Bug 修复 | :white_check_mark: |
| [反馈 API](feedback-api-spec.md) | Ask Data 反馈接口 | :white_check_mark: |
| [KB HNSW 维护](knowledge_base_hnsw_maintenance.md) | 知识库向量索引维护 | :white_check_mark: |

---

## 依赖关系

```
Tier 0: 01 → 02 → 03 → ARCHITECTURE.md
        ↓
Tier 1: 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 (可并行)
        ↓
Tier 2: 12 (依赖 08+09，AI 语义生成专用) | 13 (依赖 07)
        ↓
Tier 3: 14 (依赖 12[Token预算] + 13[MCP]) | 15 (依赖 06) | 16 (全局) | 17 (依赖 12[RAG语境]) | 18 (独立) | 19 (依赖 09)
```

> **Spec 12 v1.1 变更**：NL-to-Query LLM 集成已移至 Spec 14。Spec 12 现为**纯语义生成**协议，不再覆盖 NL-to-VizQL。

## 文件归口规则

- 所有技术规格书统一存放于 `docs/specs/`
- 文件名格式：`{序号}-{模块名}-spec.md`
- PRD 保留在 `docs/prd-*.md`
- 技术方案保留在 `docs/tech-*.md`
- Spec 是 PRD 和技术方案的精确实现合约
