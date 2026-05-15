# Mulan MCP Accuracy Repair Plan

生成时间：2026-05-15 15 点，Asia/Shanghai
文档类型：临时修复计划草案
落盘位置：`inbox/`

## 1. 问题理解

当前目标不是让 Mulan 在查询前比 MCP gateway 更复杂、更智能，而是先保证：

> 对问数类问题，Mulan 的数据准确性和可用性不能低于直连 Tableau MCP baseline。

已有 Batch 2 A/B 结果显示，MCP baseline 能稳定通过 Tableau MCP 返回结构化 `fields/rows`，而 Mulan 在多数问数问题上被前置链路阻断，主要表现为：

- planning skill 或 QuerySpec 生成失败后，Mulan 没有继续进入 MCP 执行。
- MCP baseline 可回答的问题，Mulan 返回 `QS_LLM_INVALID` 或链路错误。
- Q6 修复后已能进入 `tableau_mcp` 并返回真实聚合表，说明 Tableau MCP 和数据源本身可用。
- Mulan 当前价值链路过重地压在查询前：intent、planning skill、QuerySpec、校验、answer renderer 多层都可能成为失败点。

修复方向应反过来：

- 查询侧以 MCP baseline 为底线。
- 前置治理分层：QuerySpec 不应成为唯一阻断点，但执行安全门禁必须下沉为不可绕过的硬约束。
- `mcp_args_guardrail.py` 应成为所有访问 Tableau MCP 的唯一咽喉，无论上游来自 QuerySpec 还是 MCP proxy/direct，都必须经过同一套字段白名单、权限、聚合、limit、超时和行数约束。
- Mulan 的差异化价值主要放到 MCP 执行之后：确定性动态列计算、表格展示、指标解释、格式规范、模型切换体验一致性。

## 2. 修复目标

### P0 目标

1. 对问数类问题，只要 MCP baseline 能查出结构化结果，Mulan 必须至少进入一次 Tableau MCP 执行。
2. Mulan 最终必须返回稳定表格契约：
   - `done.response_type === "table"`
   - `done.response_data.fields` 非空
   - `done.response_data.rows` 非空
   - 尽量保留 `table_display`，用于列标签、格式和对齐。
3. Mulan 的核心字段、行数、排序和数值结果必须与 MCP baseline 对齐，允许明确的数值容差。
4. QuerySpec、planning skill 失败不能导致 baseline 可完成的问题提前失败；但任何查询降级路径都不得绕过 MCP Args Guardrail。
5. answer renderer 失败不能触发重新查询或伪造结果，只能降级为确定性表格输出。
6. 所有派生指标必须由 Python 后处理引擎确定性计算，LLM/Renderer 不得心算或改写数值。

### P1 目标

1. 建立 Batch 2 canary 回归集，优先覆盖 Q1、Q4、Q6、Q8、Q10。
2. 将 MCP baseline comparator 接入自动化验证，至少能比较：
   - 字段集合
   - 行数上限
   - Top N 排序
   - 数值容差
   - 关键派生指标
3. 前端表格展示与后端 `done.response_data` 契约对齐。
4. 追踪 `QuerySpec` 主路成功率；低于 80% 时必须优先回到 planning skill、prompt、repair 机制修复，而不是继续扩大降级依赖。

## 3. 非目标

以下事项不作为当前主线：

- 不把 deterministic QuerySpec fallback 作为必须建设的主路径。
- 不优先扩展复杂前置 intent/planning skill 体系。
- 不要求 Mulan 在 MCP 执行前完整理解所有语义算子。
- 不用自然语言 answer 代替结构化数据结果。
- 不为了通过单个问题引入不可复用的隐藏规则。
- 不把 MCP proxy/direct 作为替代 QuerySpec 的长期主路径。
- 不允许 Renderer Skill 执行业务计算；它只能消费已经计算完成的结构化数据。

## 4. 推荐目标链路

推荐将问数主链路调整为“双层执行、一层硬门禁”：

```text
用户问题
  -> connection / datasource 定位
  -> QuerySpec planning / repair 主路径
  -> Python Engine 解析 QuerySpec 为 MCP args
  -> MCP Args Guardrail
  -> Tableau MCP query-datasource 执行
  -> 结构化 fields/rows 归一化
  -> Dynamic Column Engine 确定性计算派生指标
  -> 输出侧 skill 渲染与解释
  -> done.response_data + answer
```

QuerySpec 主路径失败时，允许进入受控降级路径：

```text
QuerySpec planning / validation / repair 失败
  -> constrained MCP proxy/direct args 生成
  -> MCP Args Guardrail
  -> Tableau MCP query-datasource 执行
```

关键原则：

- MCP 执行结果是事实源。
- QuerySpec 是长期标准中间语言，不是摆设；MCP proxy/direct 只是战时止血和兜底路径。
- `mcp_args_guardrail.py` 是物理防火墙和唯一 choke point；没有通过 Guardrail 的请求不得访问 Tableau MCP。
- planning skill 缺失、QuerySpec invalid、repair 失败时，可以触发受控降级，但必须打 `FALLBACK_TRIGGERED`/`WARN` trace。
- 降级不是日常代步车；必须持续统计 QuerySpec 主路成功率。
- 派生指标由 Python Dynamic Column Engine 计算，公式来自统一 Metrics Registry。
- answer renderer 只能解释 `response_data`，不能生成、修改或心算任何指标。

## 5. 分阶段修复计划

### Phase 0：固定准确性基线

目标：让团队明确“不能低于 MCP”到底如何判断。

任务：

1. 从 Batch 2 raw/baseline 中固化 reviewed MCP snapshot。
2. 首批 canary：
   - Q1：整体 KPI，覆盖聚合与派生指标。
   - Q4：继续拆分到每个年份，覆盖上下文继承。
   - Q6：Top 10 客户，覆盖排序、limit、占比。
   - Q8：利润每年持续增长，覆盖趋势条件。
   - Q10：辽宁/福建巨亏归因，覆盖多维 breakdown。
3. 明确每个 case 的 `required_fields`、`max_rows`、`sort_key`、`numeric_tolerance`。
4. 记录每次 Mulan 运行是否进入 `tableau_mcp`、最终是否产生 `done.response_data`。

验收：

- 有 reviewed baseline 文件。
- canary case 能被 comparator 离线比较。
- Mulan run 报告能区分“未进入 MCP”“MCP 执行失败”“输出契约失败”“数值不一致”。

### Phase 1：建立 MCP Args Guardrail 唯一咽喉

目标：所有访问 Tableau MCP 的请求，无论来自 QuerySpec 主路径还是 MCP proxy/direct 降级路径，都必须经过同一个参数级硬门禁。

任务：

1. 收敛或新增 `mcp_args_guardrail.py`，作为访问 Tableau MCP 前的唯一 choke point。
2. Guardrail 必须校验：
   - connection/datasource 授权。
   - datasource LUID 来源。
   - 字段必须来自 metadata 白名单。
   - 聚合函数、排序、过滤算子必须在允许集合内。
   - 查询必须有合理 limit 或聚合约束。
   - 禁止无界明细拉取。
   - 超时、最大行数、最大字段数、并发控制。
3. QuerySpec 主路径和 MCP proxy/direct 降级路径都只能输出待校验 MCP args，不能直接执行 MCP。
4. Guardrail 拒绝时返回可诊断错误，不得伪造成功回答。

验收：

- 代码层面不存在绕过 Guardrail 直接访问 Tableau MCP 的问数执行路径。
- Guardrail 拒绝未知字段、无 limit 明细、非法 datasource、非法聚合函数。
- 成功问数均能在 trace 中看到 Guardrail pass 记录。

### Phase 2：受控降级与 QuerySpec 主路治理

目标：baseline 能回答的问题，Mulan 不再卡死在 planning skill 或 QuerySpec；同时避免降级路径破窗化。

任务：

1. QuerySpec 继续作为长期主路径：`LLM -> QuerySpec -> Python Engine -> MCP args -> Guardrail -> MCP`。
2. 将以下 QuerySpec 主路径失败从 hard fail 改为 MCP proxy/direct fallback trigger：
   - planning skill missing
   - QuerySpec invalid
   - QuerySpec validation failed
   - QuerySpec repair failed
3. 触发 MCP proxy/direct 降级时，必须：
   - 写入 `FALLBACK_TRIGGERED` trace。
   - 记录 fallback reason。
   - 记录原始 QuerySpec 错误。
   - 继续经过 MCP Args Guardrail。
4. answer renderer unavailable 只能触发 renderer fallback：保留已计算的 `response_data`，返回确定性摘要或仅表格，不得重新查询。
5. 建立 `QuerySpec` 主路成功率指标。
6. 如果 QuerySpec 主路成功率低于 80%，必须把优化 planning skill、prompt、query repair 作为优先修复项。

验收：

- Q1/Q6/Q10 至少都能进入 `tableau_mcp`。
- 不再出现 MCP baseline 成功而 Mulan 因 `QS_LLM_INVALID` 直接终止的情况。
- 成功问数均产生 `done.response_data.fields/rows`。
- 每次降级都有显式 trace，不允许静默降级。
- 可以按天/版本统计 QuerySpec 主路成功率和 fallback rate。

### Phase 3：Dynamic Column Engine 与表格输出契约

目标：后端、SSE、前端对表格数据有同一份契约；派生指标由 Python 确定性计算后进入 `response_data`。

任务：

1. 成功问数的最终 `done` 必须包含：
   - `response_type: "table"`
   - `response_data.fields`
   - `response_data.rows`
   - `response_data.table_display`
2. `table_data` 事件与最终 `done.response_data` 使用同一结构来源。
3. 在 MCP 返回之后、Renderer 介入之前插入独立的 Dynamic Column Engine。
4. Dynamic Column Engine 从 Metrics Registry 读取公式，确定性计算并追加派生列：
   - 利润率
   - 客单价
   - 销售占比
   - 年度增长或持续条件判断结果
5. answer 文案只基于结构化结果生成。

验收：

- 前端无需猜测即可渲染表格。
- Q1 的利润率、客单价不能只存在于自然语言中。
- Q6 的占比必须出现在结构化结果或 `table_display` 中。
- 派生指标值来自 Python 后处理，不来自 LLM 文案。

### Phase 4：建设输出侧 skill

目标：Mulan 的价值重心从“查询前拦截”转到“查询后呈现”，但 Renderer Skill 严格只做渲染和解释。

任务：

1. 建立输出侧 skill 输入契约：
   - 用户问题
   - MCP fields/rows
   - 字段类型
   - 已由 Dynamic Column Engine 计算完成的派生指标
   - baseline comparator 结果
2. 输出侧 skill 负责：
   - 中文业务摘要。
   - 表格列名规范。
   - 数值单位展示格式，如万、百分比。
   - Top N、同比、占比、亏损原因等常见表达。
   - 多模型切换时保持语气、结构和字段解释一致。
3. 输出侧 skill 不负责：
   - 编造查询结果。
   - 覆盖 MCP rows。
   - 计算利润率、客单价、占比等业务指标。
   - 隐式修改排序或过滤口径。

验收：

- 同一结构化结果在不同模型下，核心数值和表格保持一致。
- 文案差异只体现在表达，不影响事实。
- answer 与 `response_data` 不一致时触发质量警告。

### Phase 5：接入质量门禁

目标：让“不低于 MCP”变成自动检查，而不是人工判断。

任务：

1. 将 canary comparator 接入测试或手动 quality gate。
2. 每次输出报告至少包含：
   - MCP baseline result
   - Mulan response_data
   - UI tableData
   - 对齐结果
3. 质量门禁失败分类：
   - 未进入 MCP
   - 无表格契约
   - 字段缺失
   - 行数错误
   - 排序错误
   - 数值偏差
   - answer 与 rows 不一致
   - Guardrail 未经过或拒绝
   - fallback rate 过高
   - QuerySpec 主路成功率低于 80%

验收：

- Q1/Q4/Q6/Q8/Q10 canary 可重复跑。
- 任一 canary 劣于 MCP 时，报告能定位失败层。
- 修复完成后再扩大到 Q1-Q10 全量 Batch 2。

## 6. 推荐实施顺序

1. 先建立或收敛 MCP Args Guardrail，确保所有 MCP 执行路径只有一个 choke point。
2. 固化 Q1/Q6/Q10 reviewed MCP baseline。
3. 打通受控 MCP proxy/direct fallback，确保 QuerySpec 失败不阻断执行，但所有降级都必须过 Guardrail 并打 trace。
4. 插入 Dynamic Column Engine，保证派生指标由 Python 确定性计算。
5. 统一 `done.response_data` 表格契约。
6. 为 Q1/Q6/Q10 接 comparator。
7. 追踪 QuerySpec 主路成功率和 fallback rate。
8. 扩展 Q4/Q8。
9. 建设输出侧 skill。
10. 扩展到 Batch 2 全量 Q1-Q10。

## 7. 风险与取舍

1. MCP proxy/direct 依赖模型生成 tool args，仍可能选错字段。
   - 短期可通过 reviewed baseline canary 和 comparator 发现问题。
   - 中期可沉淀常见问题模板，但不让模板成为新的硬阻断。
   - 所有生成 args 必须经过 Guardrail，不能直接执行。
2. 降级路径可能导致 QuerySpec 破窗化。
   - 每次降级必须显式 trace。
   - 必须追踪 QuerySpec 主路成功率。
   - 主路成功率低于 80% 时，优先修复 planning skill、prompt、query repair。
3. 输出侧 skill 可能美化错误结果。
   - 必须规定 answer 只能解释结构化 rows。
   - answer 与 rows 不一致时标记失败。
   - 派生指标只能来自 Dynamic Column Engine。

## 8. 初始验收定义

第一轮修复可按以下标准判定通过：

- Q1、Q6、Q10 均进入 `tableau_mcp`。
- Q1 返回整体销售额、利润、利润率、客户数、客单价，数值与 MCP baseline 容差内一致。
- Q6 返回 Top 10 客户，Top3 客户、销售额、占比与 MCP baseline 一致。
- Q10 返回辽宁/福建 2024 亏损的产品线和客户 breakdown，Top 结果与 MCP baseline 一致。
- 所有成功问数都有 `done.response_type === "table"` 和非空 `response_data.fields/rows`。
- 所有问数执行路径都经过 MCP Args Guardrail。
- 每次 fallback 都有 `FALLBACK_TRIGGERED`/`WARN` trace 和 reason。
- 能输出 QuerySpec 主路成功率与 fallback rate。

## 9. 后续需要按需读取的代码位置

后续进入实现时，建议只按任务读取以下位置：

- `/api/agent/stream` SSE 入口与 `done.response_data` 输出。
- MCP first path 与 MCP proxy path。
- QuerySpec 失败处理与 fallback 选择逻辑。
- MCP Args Guardrail 或 Tableau MCP 调用封装层。
- Dynamic Column Engine / Metrics Registry 可落点。
- 前端 streaming chat 表格提取逻辑。
- baseline fixtures、comparator、quality gate。

读取代码前应再次确认具体实施任务与变更边界。
