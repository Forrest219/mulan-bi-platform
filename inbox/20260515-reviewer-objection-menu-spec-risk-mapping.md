# Reviewer 反对意见书

> **被评审文件**：`inbox/20260515-menu-spec-risk-mapping.md`
> **评审角色**：Reviewer
> **评审日期**：2026-05-15
> **评审依据**：`agents/reviewer.md` + `AGENT_PIPELINE.md`

---

## 评审结论

| 维度 | 结论 | 核心问题数 |
|------|------|-----------|
| SPEC_Compliance_Check | ⚠️ PASS（含3条反对意见） | 3 |
| RealWorld_Risk_Check | ⚠️ 有保留通过 | 2 |

---

## 反对意见一：R-001 风险描述措辞失准

**严重程度**：中等

**文件声称**：
> `R-001 (P0: SQL注入风险 - 未转义的 f-string 拼接)` → 指标治理模块

**实质证据**：
- 风险来源文件：`docs/RISK_REGISTER.md` R-001 条目
- 实际描述：Metrics Agent 执行探测时，若上游返回的 `metric_name` 包含特殊字符（`'`、`"`、`` ` ``），直接拼接到 SQL 的 LIKE 子句……

**问题分析**：

| 对比维度 | md文件描述 | RISK_REGISTER实际 |
|---------|-----------|------------------|
| 风险性质 | SQL注入（主动攻击） | 上游数据污染导致拼接异常 |
| 触发条件 | 未说明 | 上游返回特殊字符 |
| 影响范围 | 泛指 | 仅 LIKE 子句 |

**反对理由**：
- "SQL注入"是主动攻击场景，R-001 实际是**数据层面的特殊字符未转义**，两者在 OWASP 分类中属不同风险类型
- 错误归类会导致修复方案偏差（注入防御 ≠ 字符串转义）

**修正建议**：
> R-001 (P0: metric_name 特殊字符未转义导致 SQL 语法错误/注入风险)

---

## 反对意见二：R-004/R-005 风险归属路径误导

**严重程度**：中等

**文件声称**：
> `R-004 / R-005`（限流组件在 Postgres Fallback 下直接放行）→ `平台设置` (`/system/platform-settings`)

**实质证据**：
- R-004 代码位置：`services/capability/rate_limiter.py` L79-82
- R-005 代码位置：`services/capability/rate_limiter.py` L156-158
- 该模块为**通用限流组件**，被多处引用，非 `platform-settings` 独有

**问题分析**：

```
services/capability/rate_limiter.py  ← R-004/R-005 实际位置
         ↑ 公共模块，被以下模块调用：
         ├── platform-settings
         ├── data-connections
         └── (可能其他服务)
```

**反对理由**：
- 将通用组件风险归因于单一菜单路径，会误导排查方向
- 实际影响范围覆盖所有使用限流器的服务，而非仅限于平台设置

**修正建议**：
> R-004 / R-005 归属应为 `services/capability/`（通用组件），并注明"影响所有依赖限流器的服务"

---

## 反对意见三：进度状态缺乏源码依据（重大）

**严重程度**：高

**文件声称**：各模块进度状态（✅ 已完成 / 🚧 实施中 / ⏭️ Next）

**问题**：

| 模块 | 声称状态 | 问题 |
|------|---------|------|
| Data Explorer (`/assets/explorer`) | ⏭️ Next | 无代码实现，路由缺失 |
| 数仓资产 (`/assets/dw`) | ✅ 已完成 | 路由存在但未验证实现 |
| 指标治理 (`/governance/metrics`) | ⏭️ Next (第一批) | Spec 30 存在，实现状态不明 |

**反对理由**：
1. "Next" 标注无任何 `git log`、`branch`、`tag` 或 CI 状态佐证
2. "已完成" 模块未提供测试通过率、API 验收记录
3. Reviewer 无法仅凭此文档核实任何进度判断

**修正建议**：
> 进度状态需附 CI pipeline 链接、最后一次 commit hash 或 Test Report 引用，否则一律标注为"**状态待核实**"

---

## 附加意见：Spec 覆盖度存缺口（供参考）

以下 Spec 编号在 `docs/specs/` 中存在，但在 5 大业务域菜单中**无对应入口**：

| 缺失 Spec | 说明 |
|----------|------|
| Spec 01, 02 | 未确认归属业务域 |
| Spec 06, 12, 13, 18, 20-26 | 业务归属不明 |
| Spec 32, 33, 37-44 | 未出现在菜单结构中 |

**注**：此条不构成打回条件，但建议 PM 在下一版中补充说明。

---

## 处理建议

| 反对编号 | 处理方式 |
|---------|---------|
| 反对一 | **打回修正**：R-001 措辞修正为"特殊字符未转义" |
| 反对二 | **打回修正**：R-004/R-005 归属路径修正为 `services/capability/` |
| 反对三 | **打回修正**：进度状态必须附带 CI / commit 引用 |
| 附加意见 | **建议跟进**：PM 补充缺失 Spec 的业务域归属说明 |

---

## Change Budget

本次 review 涉及文件改动：
- 本文件（`inbox/20260515-reviewer-objection-menu-spec-risk-mapping.md`）
- 无代码修改，未触发 Change Budget 上限
