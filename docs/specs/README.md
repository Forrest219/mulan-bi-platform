# Mulan BI Platform — 技术规格书索引

> 最后更新：2026-04-04

## 状态说明

| 标记 | 含义 |
|------|------|
| :white_check_mark: | 已完成 |
| :construction: | 编写中 |
| :clipboard: | 待编写 |

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
| 06 | [DDL 合规检查](06-ddl-compliance-spec.md) | DDL 检查引擎 + 规则配置 | :white_check_mark: |
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
| 15 | [数据质量监控](15-data-governance-quality-spec.md) | 规则引擎 + 定时执行 | :white_check_mark: |
| 16 | [事件/通知系统](16-notification-events-spec.md) | 统一事件总线 + 通知 | :white_check_mark: |
| 17 | [知识库](17-knowledge-base-spec.md) | 术语表 + Schema + RAG | :white_check_mark: |
| 18 | [菜单重构](18-menu-restructure-spec.md) | 5 域导航布局 | :white_check_mark: |
| 19 | [发布日志](19-semantic-publish-logs-spec.md) | 回写审计日志 UI | :white_check_mark: |

---

## 依赖关系

```
Tier 0: 01 → 02 → 03 → ARCHITECTURE.md
        ↓
Tier 1: 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 (可并行)
        ↓
Tier 2: 12 (依赖 08+09) | 13 (依赖 07)
        ↓
Tier 3: 14 (依赖 12+13) | 15 (依赖 06) | 16 (全局) | 17 (依赖 12) | 18 (独立) | 19 (依赖 09)
```

## 文件归口规则

- 所有技术规格书统一存放于 `docs/specs/`
- 文件名格式：`{序号}-{模块名}-spec.md`
- PRD 保留在 `docs/prd-*.md`
- 技术方案保留在 `docs/tech-*.md`
- Spec 是 PRD 和技术方案的精确实现合约
