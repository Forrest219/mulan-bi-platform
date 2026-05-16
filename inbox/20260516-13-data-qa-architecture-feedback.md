# 首页数据问答质量架构反馈

## 结论

`docs/tech/mulan-agent-architecture-blueprint.md` 和 `inbox/20260516-mcp-host-code-review.md` 对首页数据问答质量提升有明显价值，但它们目前更偏架构共识和代码风险识别，还不能直接支撑“100 人 × 1000 问”的语义准确率目标。

它们能帮助系统更稳定、更可控地运行；但如果不补结果级 benchmark、语义算子 golden case、上下文追问回归和失败闭环，只能保证 Agent 更稳定地执行，不能保证它更稳定地答对。

## 价值评估

### 1. `mulan-agent-architecture-blueprint.md`

价值评分：`7/10`

主要贡献：

- 明确 LLM 不碰计算、Renderer 不碰计算，这是首页问数走向企业级可信答案的底线。
- 明确 Guardrail 是 choke point，有助于阻止越权、危险操作、拉明细和高成本查询。
- 强调 Intent Gate / Task Plan，有助于把开放自然语言收敛成可审计、可预算、可验证的执行计划。
- 强调公式定义 SSOT，对利润率、客单价、占比等派生指标的口径治理有长期价值。

与 batch 2 经验的对应关系：

- Q10 早期拉明细的问题，证明必须有 detail scan guardrail 和计算下推约束。
- Q5 差集语义反向，证明系统不能只看接口成功，必须验证语义算子是否正确。
- Q8 连续增长、Q9 全周期亏损，证明自然语言中的“每年都”“一直”必须进入确定性语义计划。
- Q2/Q4 追问，证明上下文继承必须成为一等质量门禁。

### 2. `20260516-mcp-host-code-review.md`

价值评分：`6.5/10`

主要贡献：

- 指出 Structured Adapter 的必要性，有助于降低多模型 JSON 解析和格式漂移风险。
- 指出 Capability Registry 的方向，有助于把硬编码能力逐步迁移到可治理的能力目录。
- 指出执行熔断和超时机制，有助于在多人并发下保护 Mulan 不被底层 Tableau/MCP 拖垮。
- 肯定 detail scan guardrail 的价值，这对防止 Q10 类问题拉取大批明细非常关键。

局限：

- 代码审查更关注链路形态和模块边界，对结果级语义质量覆盖不足。
- 没有把 Q5/Q8/Q9/Q10 这类 batch 2 失败模式固化为 CI 质量门禁。
- 对 fallback 的评价偏工程可用性，没有充分强调“fallback 有回复不等于业务 Pass”。

## 对“100 人 × 1000 问”的贡献

这两份文档对规模化能力有正向贡献，主要体现在：

- 降低 LLM 自由裸跑工具导致的权限、成本和不可解释失败面。
- 通过 Guardrail 与 detail scan 拦截，减少明细扫描、OOM 和慢查询风险。
- 通过 Structured Adapter，提升不同模型供应商下的结构化输出稳定性。
- 通过 Capability Registry，支持不同租户、不同数据源、不同字段能力的统一治理。
- 通过 Task Plan 思路，为多步骤问题提供可审计的执行骨架，例如查询、对比、归因、钻取、解释。

但目前还缺少支撑 1000 问真实质量的关键机制：

- 标准化 benchmark harness。
- 持续回归的 golden case 集合。
- 结果级质量门禁：Row Count、字段粒度、聚合口径、TopN 核心值、是否拉明细。
- 上下文追问质量门禁：是否继承上轮指标、维度、过滤条件和时间范围。
- fallback 质量分级：只有语义正确才算 Pass，不能把“有回复”当成 Pass。
- 失败分类体系：路由降级、语义反向、拉明细、上下文断层、指标口径漂移、渲染误导。

## 反对意见

### 1. 反对把 QuerySpec 绝对化

文档中“QuerySpec 绝不能被 MCP Native Function Calling 取代”的表达过于绝对。

batch 2 证明的是“裸 MCP tools/list + LLM 自由生成参数”不可靠，而不是证明当前 QuerySpec 形态必须永远作为唯一主链路。更准确的结论应该是：必须存在一个稳定的 Semantic Plan / Task Plan 契约，但这个契约不必永久绑定为当前 QuerySpec 实现。

### 2. 反对把 fallback 当成高可用亮点直接表扬

从 Data QA 视角看，fallback 是风险点，不是天然亮点。

batch 2 早期问题里，Q5/Q8/Q9/Q10 都可能出现“接口不报错，但业务语义不合格”的情况。fallback 如果没有显式质量门禁，很容易把错误包装成可读答案，反而增加误导风险。

### 3. 反对只做参数级 guardrail，不做结果级 guardrail

MCP args 合法不代表答案正确。

质量门禁必须进入结果层，至少检查：

- 返回行数是否符合问题粒度。
- 是否返回明细而非聚合。
- 字段是否覆盖用户问到的核心维度和指标。
- TopN / 差集 / 连续增长 / 全周期亏损 / 归因等核心算子是否符合业务语义。
- 多轮追问是否继承上下文。

### 4. 反对 Python Postprocessor 宽泛接管计算

Python 可以对 MCP 已聚合结果做确定性集合和条件判断，例如 Q5 差集、Q8 连续增长、Q9 全周期亏损。

但利润率、客单价、占比、派生指标公式如果没有 Metrics Registry、公式版本和来源标记，不应在 Python 中宽泛接管。否则会重新制造事实双写和口径漂移。

### 5. 反对代码审查不绑定基准用例

架构评审必须绑定真实失败样本。

如果没有把 batch 2 的失败模式写入测试矩阵，后续 MCP Host、QuerySpec、Guardrail 或 Renderer 的重构都可能再次退化。

## 建议动作

1. 建立 `Data QA Golden Set`，将 batch 2 的 Q0-Q10 固化为第一组首页问数语义回归集。
2. 为每个 case 记录 MCP baseline、Mulan row count、核心字段值、语义判定规则和失败分类。
3. 把 Q5、Q8、Q9、Q10 升级为强制质量门禁 case。
4. 在 CI 或 nightly job 中运行同会话多轮追问，尤其覆盖 Q2 和 Q4 的上下文继承。
5. 为 fallback 增加结果级状态：`semantic_pass`、`semantic_fail`、`needs_review`，禁止把 fallback 自动视作成功。
6. 将 detail scan 检查从参数层扩展到结果层，返回超过阈值的原始明细时直接判 Fail。
7. 建立语义算子验收表，至少覆盖差集、连续增长、全周期条件、TopN 占比、客户合作记录和归因。
8. 将 Metrics Registry 作为派生指标治理前置条件，再允许 Python Deterministic Postprocessor 承担有限计算。

## 一句话总结

这两份文档对首页数据问答质量提升有方向性价值，但要真正支撑 100 人 1000 问，必须从“架构正确”继续推进到“结果可判、语义可测、失败可复现、回归可自动化”。
