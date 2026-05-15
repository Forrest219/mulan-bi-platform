# Mulan vs Tableau MCP AB Test - Batch 2

## 概览 (Overview)

- 测试时间：2026-05-15 13 点，Asia/Shanghai。
- 测试环境：本地 Mulan 首页问答后端 `http://localhost:8000/api/agent/stream`，Tableau MCP Gateway `http://localhost:3927/tableau-mcp`，Tableau Online connection_id=2，数据源 `订单+ (示例 - 超市)`，datasource_luid=`f4290485-26d3-428f-aa8d-ccc33862a411`。
- 总用例数：11 个，Q0-Q10；Mulan Phase B 使用同一个 conversation_id=`ad643a50-b876-439e-aa8c-6fdd6df0e577` 顺序执行。
- 平均耗时：MCP baseline 约 2.17s；Mulan 最终同会话重跑约 28.44s，业务问数 Q1-Q10 平均约 31.13s。
- 质量通过率：整体 2/11 = 18.2%；业务问数 Q1-Q10 为 1/10 = 10.0%。
- Quality Gate Loop 已执行修复：首次重跑 Q1-Q10 全部卡在 `planning_skill_loader`，报 `query_plan_unavailable`。已修复 `SkillPromptLoader` 默认路径，从仓库根目录 `skills/` 改为实际存在的 `backend/skills/`，并验证 aggregate/trend/ranking/set_difference/customer_record/root_cause planning skill 均可加载。修复后重跑，Q6 进入 `tableau_mcp` 并返回 10 行；其余业务题仍因 `QS_LLM_INVALID` 未生成可执行 QuerySpec。

## 多维对比表格 (Benchmarking Table)

| 问题 | MCP 时长 | Mulan 时长 | Mulan 返回行数 | MCP 核心结论 | Mulan 核心结论 | 状态(Pass/Fail) |
| --- | ---: | ---: | ---: | --- | --- | --- |
| Q0：介绍数据源 | 3.00s | 1.59s | 11 | 数据源字段 11 个：客单价、利润率、客户数、子类别、发货年份、发货日期、销售额、利润、客户名称、省/自治区、类别。 | 返回同样 11 个字段，并区分 measure/dimension 与计算字段。 | Pass |
| Q1：整体销售额、利润、利润率、客户数、客单价 | 1.43s | 27.95s | - | 销售额 1686.74万，利润 211.92万，利润率 12.56%，客户数 771，客单价 2.19万。 | `llm_queryspec` 返回 `QS_LLM_INVALID`，未生成可执行 QuerySpec，未进入 MCP 聚合。 | Fail |
| Q2：这个指标过去几年的趋势 | 1.19s | 30.62s | - | 2021-2025 年销售额约 347.86万、349.63万、446.64万、538.73万、3.88万；利润率约 10.28%、13.15%、13.60%、12.76%、18.69%。 | `QS_LLM_INVALID`，未继承 Q1 的指标集合，也未进入年度趋势查询。 | Fail |
| Q3：每个子类别销售额、利润、利润率 | 1.25s | 27.96s | - | 返回 17 个子类别；销售额 Top3 为椅子 243.43万、电话 240.59万、收纳具 162.87万；亏损项为桌子 -12.87万、书架 -2.63万、用品 -0.85万。 | `QS_LLM_INVALID`，未返回子类别聚合结果。 | Fail |
| Q4：继续拆分到每个年份 | 1.45s | 27.74s | - | 返回 80 行子类别×年份；例如书架 2021-2024 利润为 -0.45万、-1.81万、0.11万、-0.48万。 | `QS_LLM_INVALID`，追问没有落到“子类别×年份”的执行计划。 | Fail |
| Q5：2025 年没有销售记录的子类别 | 3.97s | 27.87s | - | 差集结果 5 个：信封、复印机、桌子、设备、配件。 | `QS_LLM_INVALID`，差集算子未执行，未返回缺失子类别。 | Fail |
| Q6：Top 10 大客户及占比 | 2.43s | 52.29s | 10 | Top3：李丽丽 18.16万(1.08%)、潘锦 13.81万(0.82%)、袁丽美 10.96万(0.65%)。 | 返回 10 行真实聚合表；Top3 为李丽丽 181,562.11(1.08%)、潘锦 138,128.58(0.82%)、袁丽美 109,600.71(0.65%)。 | Pass |
| Q7：邓保客户合作记录 | 3.05s | 28.92s | - | 邓保仅 2021、2022 有记录；2021 销售额 2.02万、利润 -0.26万；2022 销售额 0.42万、利润 0.03万；最近记录 2022 年。 | `QS_LLM_INVALID`，客户记录算子未执行。 | Fail |
| Q8：利润每年持续增长的子类别 | 1.45s | 29.91s | - | 按完整 2021-2024 年口径，持续增长子类别为器具、复印机、用具、系固件、纸张。 | `QS_LLM_INVALID`，连续增长算子未执行。 | Fail |
| Q9：哪些省份一直亏损 | 1.30s | 30.41s | - | 按完整 2021-2024 年口径，持续亏损省份为重庆。 | `QS_LLM_INVALID`，全周期亏损条件未执行。 | Fail |
| Q10：辽宁、福建 2024 巨亏归因 | 3.41s | 27.62s | - | 产品线 Top3 亏损：辽宁-装订机 -3.08万、福建-设备 -2.78万、辽宁-设备 -2.74万；客户 Top3：福建-殷丽雪 -2.77万、辽宁-黄涛 -2.48万、辽宁-柯巧 -2.12万。 | `QS_LLM_INVALID`，归因下钻未执行，没有返回产品线或客户贡献。 | Fail |

## 质量深度诊断 (Quality Observations - 结构化输出)

- **1. 计算下推与性能 (Pushdown)**：MCP baseline 全部使用 Tableau MCP 聚合或小规模集合查询，没有拉 1000 行明细；Mulan 修复后 Q6 有效下推并返回 10 行聚合表，但 Q1-Q5、Q7-Q10 未进入 MCP 执行，平均约 28-31s 后失败，性能和可用性仍不可接受。Q10 没有出现拉明细心算，但原因是 QuerySpec 失败而非正确下推。
- **2. 复杂语义算子 (Semantic Operators)**：Q5 差集、Q8 连续增长、Q10 归因在 MCP baseline 中均有明确口径；Mulan 三者均停在 `QS_LLM_INVALID`，没有进入 set_difference、trend_condition/root_cause 的执行算子，因此无法证明语义对齐。
- **3. 意图与路由 (Intent & Routing)**：Q0 正确路由为 schema inventory；Q1-Q10 没有降级到资产清单，这是正向变化。Q7 被识别为 `customer_record`，Q10 被识别为 `root_cause`，路由方向基本正确，主要失败点在 QuerySpec 生成层。
- **4. 上下文记忆 (Context Tracking)**：同一 conversation_id 顺序执行已确认；但 Q2、Q4 都在生成 QuerySpec 前失败，未能验证“这个指标”和“继续拆分到每个年份”的指标、维度继承能力。

## 核心结论与下一步 (Next Steps)

当前版本仅通过资产介绍与 Top10 客户一个业务题，不具备全量上线条件；核心卡点是 QuerySpec 规划层对 LLM 稳定输出依赖过强，且确定性 QuerySpec fallback 未覆盖或未启用到 Batch 2 的通用业务意图。
