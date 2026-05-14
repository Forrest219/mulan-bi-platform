# Architect Review — SPEC §29 SQL Agent

> 审查角色：architect
> 审查人：Workhorse（代理审查）
> 日期：2026-04-20
> 审查对象：docs/specs/29-sql-agent-spec.md

---

## 总体结论

**有条件通过 ✅**

SPEC §29 整体架构清晰、安全框架合理、API 设计符合规范。与 Data Agent 的关联设计（分离 + FK）在第 11 章已解决三个开放问题。

**有 3 处 P1 问题需要修改，1 处 P2 建议优化**，无 P0 阻塞问题。

---

## 逐章节审查

### §1 概述

✅ 架构定位正确：执行层 Agent，非策略层
✅ 范围边界清晰（包含/不包含列表完整）
✅ 关联文档覆盖完整

**P1 - 1.2 范围表格**：Spec 14（NL-to-Query）列为"查询构建上游"，但 NL-to-Query 实际是**同层协作**而非上下游——它负责意图分类/字段映射，最终 SQL 执行才到 SQL Agent。建议改为"查询构建协作方，同层串联"。

---

### §2 系统架构

✅ 架构图清晰，分层（Router → Security → Executor → Formatter）正确
✅ 表格"核心设计决策"覆盖了关键决策点

**P1 - 2.1 架构图**：图中"目标数据源（用户数据）"包含 PostgreSQL，但 PostgreSQL 在本设计中仅用于"平台内部元数据库"（即 bi_data_sources 等平台表），并非用户数据分析目标数据源。建议明确区分"用户数据源（StarRocks/MySQL）"与"平台元数据库（PostgreSQL）"，避免误解。

**P2 - 2.2 表格中"PostgreSQL（平台内部）"定位**：PostgreSQL 作为平台元数据库，理论上不应该允许执行用户 SQL（因为查询的是平台自己的表）。当前设计允许 SELECT，但"连表限制 8 张表"规则对访问 `bi_data_sources` + `auth_users` 等平台表场景过于严格——平台内部查询通常是 2-3 张表。建议在配置矩阵中注明"仅用于管理查询，不做用户数据分析"。

---

### §3 多方言安全框架

✅ 方言配置矩阵完整，DROP/TRUNCATE/DELETE/ALTER 拦截覆盖全方言
✅ 安全校验流程（Step 1-5）逻辑清晰
✅ P0 MySQL SELECT only 决策正确

**P1 - 3.1 配置矩阵"连表限制"与"子查询深度"的方言差异**：StarRocks 的"连表 10 张"vs MySQL/PG 的"连表 8 张"，以及 StarRocks 子查询 5 层 vs 其他 3 层——这个差异是否有实际业务依据？从安全角度，更保守的限制（8 张 / 3 层）更稳妥。建议确认 StarRocks 是否真的有 10 张连表需求，如果是，保持差异化；否则建议统一为更严格的值。

**P1 - 3.3 危险语句拦截规则**：表格中 `information_schema（部分）`拦截描述过于模糊——具体哪些查询需要拦截？比如 `SELECT * FROM information_schema.processlist`（MySQL）在某些配置下可泄露连接信息。建议明确：
- MySQL：`information_schema.processlist`、`information_schema.security_users` 等可设定为"拦截"
- PostgreSQL：`pg_stat_activity`、`pg_roles` 等可泄露连接信息

**P2 - 3.2 安全校验流程**：Step 4（LIMIT 注入）写的是"仅在最外层 SELECT 注入 LIMIT（sqlglot 支持）"——这个实现在 spec 里没有明确说明，只是 context summary 里提到的缓解措施。建议在 §3 或 §10 测试策略里补充这一点作为已知限制。

---

### §4 数据模型

✅ `sql_agent_query_log` 表结构完整合理
✅ 索引设计满足查询模式（datasource+created、sql_hash+created）
✅ FK 关联设计在 §11 已解决

**P1 - 4.1 `sql_hash` 字段**：`SHA256(sql_text)` 用于去重，但不同数据库对同一 SQL 的文本表示可能不同（如大小写、空白）。建议明确：`sql_hash` 的计算在 LIMIT 注入**之后**进行，这样同一物理 SQL 不同 LIMIT 值会生成不同 hash，避免误去重。文档中"去重"语义需要澄清。

---

### §5 API 设计

✅ 端点设计符合 REST 规范，路径前缀 `/api/sql-agent` 合理（不对 `/api` 造成污染）
✅ 请求/响应 Schema 完整
✅ 错误响应结构符合 01-error-codes-standard.md

**P1 - 5.1 端点列表**：GET `/api/sql-agent/query/{log_id}` 但 HTTP 方法写了"GET"，实际意图是"根据 log_id 查询执行记录"。当前 JSON 响应里已有 `log_id`，用户拿到执行结果后一般不需要再查一次。建议：
- 如果目的是"查历史记录"（不重新执行），保留 GET `/{log_id}`
- 如果目的是"查询结果已经在响应里返回了"，考虑删除此端点，避免冗余

**P2 - 5.2 `truncated` 语义**：当 `truncated = true` 时，用户只知道"结果被截断"，但不知道是LIMIT 上限导致的截断，还是目标数据库主动停止了传输。建议增加字段说明（如 `truncated_reason: "limit_applied" | "network_error" | "unknown"`）。

---

### §6 错误码

✅ 覆盖完整，HTTP 状态码映射正确

**P1 - 6.1 `SQLA_001` 消息**：错误消息"危险语句拦截：XXX 操作不允许"会直接告诉攻击者哪些操作被拦截，这本身是信息泄露。建议改为通用消息如"该语句不符合安全策略"。

---

### §7 安全

✅ 角色权限矩阵正确
✅ 连接安全说明完整
✅ SQL 注入防护（参数化）已说明

**无问题。**

---

### §8 集成点

✅ 上游依赖清晰
✅ 事件发射覆盖了关键场景

**P2 - 8.1 表格中"NL-to-Query（Spec 14）"写成"下游服务"**：这是笔误，NL-to-Query 是上游/协作方，不是下游消费者。

---

### §9 时序图

✅ 序列完整，涵盖了 Data Agent 调用主场景
✅ 危险语句拒绝路径有画

**无问题。**

---

### §10 测试策略

✅ 覆盖了核心路径
✅ 边界场景有覆盖（DROP 拦截、LIMIT 注入、truncated）

**P1 - 10.1 场景 2**：`DELETE FROM orders WHERE ...` 被拦截，但实际执行 DELETE 时 sqlglot 会解析成功，拦截点在"白名单扫描"阶段。建议测试用例覆盖**带注释的注入尝试**（如 `DELETE FROM orders WHERE id=1; -- DROP TABLE users`）以验证注释剥离后仍被正确拦截。

---

### §11 与 Data Agent 的关联设计

✅ 分离原则清晰
✅ FK 关联设计合理（nullable sql_agent_log_id）
✅ 开放问题已全部解决

**无问题。**

---

### §12 开放问题

✅ 三个问题已关闭，保留 P1/P2 各一条

---

## 问题汇总

| # | 章节 | 问题 | 严重度 | 行动 |
|---|------|------|--------|------|
| 1 | §1.2 | NL-to-Query 是同层协作，不是上下游 | P1 | 修改描述文字 |
| 2 | §2.1 | 架构图需区分"用户数据源"与"平台元数据库" | P1 | 修改架构图说明 |
| 3 | §3.1 | StarRocks 连表/子查询限制差异需确认业务依据 | P1 | 确认后统一或保持差异化 |
| 4 | §3.3 | information_schema 拦截规则过于模糊 | P1 | 明确列出需拦截的具体表/视图 |
| 5 | §3.2 | LIMIT 注入"仅最外层"作为已知限制需写入正文 | P1 | 补充说明 |
| 6 | §4.1 | sql_hash 在 LIMIT 注入前还是后计算需明确 | P1 | 明确为注入后计算 |
| 7 | §5.1 | GET /query/{log_id} 端点必要性存疑 | P1 | 确认是否需要或改为"查询执行详情"语义 |
| 8 | §5.2 | truncated 需补充 reason 字段 | P2 | 增强响应 Schema |
| 9 | §6 | SQLA_001 错误消息存在信息泄露 | P1 | 改为通用消息 |
| 10 | §8.1 | NL-to-Query 标注为"下游"是笔误 | P2 | 修正为"协作方" |

---

## 修改优先级

**必须修改（阻塞通过）**：1, 3, 4, 6, 9
**建议修改（不影响通过）**：2, 5, 7, 8, 10
