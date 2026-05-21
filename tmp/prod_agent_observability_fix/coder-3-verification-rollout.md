# coder-3：测试、发布与历史数据处置任务说明

## 目标

为生产修复补充测试、发布验证与历史数据处置方案。

背景：

- fallback run 因 `error_code` 超长导致记录未成功落库。
- Agent 监控依赖 `bi_agent_runs`，记录缺失后监控不可见。
- assistant message 在异常链路中未持久化，刷新后只剩用户问题。

本文件只覆盖验证、发布、监控和历史数据处置规划，不修改业务代码，不要求回滚他人改动。

## 测试矩阵

| 场景 | 输入/条件 | 预期结果 | 验证重点 |
| --- | --- | --- | --- |
| 正常 Agent run | 无异常，正常生成 assistant message | run、message、监控数据均正常落库 | 不影响成功路径 |
| fallback run + 短 error_code | fallback 触发，error_code 在旧限制内 | fallback run 正常落库，assistant message 可见 | 兼容原路径 |
| fallback run + 长 error_code | `ROUTER_CLARIFY_REQUIRED` | run 正常落库，Agent 监控可见 | 核心修复路径 |
| fallback 持久化失败 | 模拟 run/step/message 写入异常 | 不返回 done，返回 error | 防止假成功 |
| 重试/幂等 | 同一 fallback 重试 | 不重复生成错误数据 | 幂等性 |
| 监控查询 | fallback run 已落库 | Agent 监控页面/API 可查到 run | 监控恢复 |
| 历史异常数据 | 修复前缺失或半缺失记录 | 能识别受影响范围 | 补偿前评估 |

## 生产验证步骤

1. 发布前确认修复版本包含：
   - error_code schema 扩容。
   - fallback 最终响应持久化一致性。
   - 持久化失败结构化日志。
   - 回归测试。

2. 预发环境执行核心场景：
   - fallback run + `ROUTER_CLARIFY_REQUIRED`。
   - fallback assistant message 正常写入。
   - fallback run 可在 Agent 监控中查询。

3. 生产发布后，使用内部账号触发可控 fallback：
   - 问题：`你有哪些看板？`
   - connection：`4`
   - 确认 run 记录成功落库。
   - 确认 assistant message 未丢失。
   - 确认 Agent 监控可见。

4. 抽查真实生产流量：
   - 发布后 15 分钟内检查新增 fallback run。
   - 发布后 1 小时内检查异常率、落库失败日志和监控展示。
   - 发布后 24 小时内复核是否仍有同类落库失败。

## 容器重建验证

1. 确认镜像版本：
   - 当前运行容器镜像 tag/digest 与发布版本一致。
   - 不存在旧镜像容器继续承接流量。

2. 执行重建或重启验证：
   - 重建 backend 容器。
   - 确认启动日志无 migration、配置或依赖错误。
   - 确认新容器能正常处理 Agent run。

3. 重建后重复核心验证：
   - 正常 run 可完成。
   - fallback run 可落库。
   - assistant message 可查询。
   - Agent 监控可见。

## 日志检查

重点检查关键词：

```text
fallback
error_code
assistant message
agent run
observability
value too long
DataError
IntegrityError
constraint
truncate
monitor
```

日志验收要求：

- 发布后不再出现因 `error_code` 超长导致 run 整体落库失败。
- 若仍有异常，日志必须包含可定位的 `run_id`、`conversation_id`、`trace_id`。
- 不允许异常被静默吞掉且无监控记录。

## 历史数据补偿策略

默认策略：不自动补造历史 assistant message 或 fallback run 记录。

原因：

- 历史缺失数据可能无法完整还原原始 assistant 输出。
- 自动补造可能制造误导性业务记录。
- 补偿动作可能影响审计、监控统计和用户侧历史会话展示。

历史数据处置三步：

1. 识别影响范围：
   - 查询修复前出现 fallback 但 run 未落库的请求日志。
   - 查询 assistant message 缺失但存在相关 trace 的会话记录。
   - 统计受影响时间窗口、用户、conversation、run 数量。

2. 生成补偿候选清单：
   - 只生成候选报告，不直接写库。
   - 每条候选包含证据来源：日志、trace_id、run_id、conversation_id、时间戳。
   - 标记可还原程度：完整可还原、部分可还原、不可还原。

3. 人工确认后再执行补偿：
   - 产品/业务负责人确认是否补造。
   - 研发确认补偿脚本范围和幂等策略。
   - DBA 或数据负责人确认写库影响。
   - 执行前备份目标数据或保存回滚 SQL。
   - 执行后抽样核对监控、会话记录和审计字段。

可选处置：

| 类型 | 处理方式 |
| --- | --- |
| 完整可还原 | 经人工确认后补写 run/message，并标记 `historical_repair` |
| 部分可还原 | 只补写最小审计记录，并明确标记内容不完整 |
| 不可还原 | 不补造业务内容，仅保留影响清单和事故说明 |
| 用户可见会话 | 默认不补写，除非业务明确要求且内容可准确还原 |

## 回滚与监控指标

重点监控指标：

- fallback run 落库成功率。
- assistant message 写入成功率。
- Agent run 总量与监控可见数量差异。
- fallback run 数量突增。
- 数据库写入错误数。
- Agent 相关接口 5xx。
- 用户会话中 assistant message 缺失率。
- `value too long` / `DataError` / `IntegrityError` 日志数量。

观察窗口：

- 发布后 15 分钟：确认无明显错误放大。
- 发布后 1 小时：确认核心链路稳定。
- 发布后 24 小时：确认同类问题未复发。

## 验收标准

- fallback run 在长 error_code 场景下不会因字段长度导致落库失败。
- assistant message 在 fallback 异常路径中可正常保存，或产生明确可追踪失败日志。
- Agent 监控能看到 fallback run。
- 发布后生产日志中不再出现同类 `error_code` 超长导致的落库失败。
- 容器重建后修复仍然生效。
- 历史数据已完成影响范围评估。
- 历史数据默认未自动补造；如需补偿，必须经过人工确认。
- 所有验证结果、异常发现和补偿决策都有记录可追踪。
