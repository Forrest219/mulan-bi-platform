# LLM QuerySpec Stability Repair - Coder Task

生成时间：2026-05-15 18 点，Asia/Shanghai
文档类型：Coder 可交付任务单
目标项目：`/Users/forrest/Projects/mulan-bi-platform`

## 1. 背景与问题

Batch 2 A/B 与当前 live trace 共同证明，Mulan 首页问数链路存在两类不同故障，但当前都被外层包装成 `QS_LLM_INVALID` 或 `MCP_ARGS_LLM_INVALID`，导致排查方向混乱。

已确认事实：

- LLM 配置不是单纯缺失。DB 中存在 active default 配置：`minimax / MiniMax-M2.7`，且 backend 容器内 API key 可解密。
- 13 点 raw 中，Q1-Q5、Q7-Q10 的 QuerySpec 失败真实根因是 provider 调用超时，MiniMax attempt 耗时约 `25.7s-26.0s`，错误为 `Request timed out or interrupted`。
- 当前 live 抽查中，最小 LLM 调用成功，说明配置当前可用。
- 当前 live 抽查中，真实 QuerySpec prompt 仍可能返回不可执行计划：
  - Q1：通过。
  - Q8：通过。
  - Q5/Q6/Q10：LLM 返回或抽取到局部 JSON，例如 `{"field":"指标Y","aggregation":"SUM"}`、`{"type":"all"}`，不是完整 QuerySpec。
- 代码当前会在 MiniMax/Anthropic 没有 `TextBlock` 时，把 `ThinkingBlock` 文本作为 content 返回；随后 `_call_llm_json` 从文本中抽第一个 JSON object，容易误把 prompt 示例、schema 片段或思考过程中的局部 JSON 当成 QuerySpec。

## 2. 修复目标

### P0

1. provider 超时、认证失败、空响应、thinking-only 响应、JSON 解析失败、QuerySpec 模型校验失败必须被区分记录，不能全部包装成 `QS_LLM_INVALID`。
2. JSON 规划类 purpose 不得把 `ThinkingBlock` 当正式 content。
3. `_call_llm_json` 不得从任意文本中抽第一个 JSON object 就算成功；候选 JSON 必须满足 QuerySpec 顶层契约。
4. 对 QuerySpec 模型校验失败支持一次短 repair，但 provider timeout/auth error 不做 repair。
5. 原有 MCP Args Guardrail 与 fallback 机制不能被绕过。

### P1

1. 为 `data_agent_queryspec` 建议或支持专用 LLM purpose 配置，避免长期依赖 default。
2. 增加 canary 单测或 eval 覆盖 Q1/Q5/Q6/Q8/Q10 的 QuerySpec 输出稳定性。
3. trace 中能清楚看到主路失败类型和是否触发 fallback。

## 3. 非目标

- 不重写 QuerySpec 整体 schema。
- 不移除 QuerySpec 主路径。
- 不把 MCP proxy/direct 变成长期主路径。
- 不让 Renderer 或 LLM 执行业务计算。
- 不在本任务里改 Tableau MCP 查询语义或前端展示逻辑，除非测试暴露出直接契约问题。

## 4. 建议改动范围

按需读取和修改以下文件：

- `backend/services/llm/service.py`
- `backend/services/data_agent/mcp_first_main.py`
- `backend/services/data_agent/queryspec_prompt_builder.py`
- `backend/services/data_agent/queryspec.py`
- `backend/services/data_agent/queryspec_validator.py`
- `backend/tests/services/data_agent/test_mcp_first_main.py`
- `backend/tests/services/data_agent/test_queryspec_prompt_builder.py`
- 可新增测试文件：`backend/tests/services/data_agent/test_llm_queryspec_stability.py`

如果需要调整 LLM purpose 配置或管理 API，再按需读取：

- `backend/services/llm/models.py`
- `backend/app/api/llm.py`

## 5. 实施任务

### Task 1：区分 LLM 错误类型

在 `LLMService.complete()` 或调用层增加可机器识别的错误分类，至少覆盖：

- `LLM_NOT_CONFIGURED`
- `LLM_AUTH_CONFIG_ERROR`
- `LLM_PROVIDER_TIMEOUT`
- `LLM_PROVIDER_ERROR`
- `LLM_EMPTY_RESPONSE`
- `LLM_THINKING_ONLY_RESPONSE`

要求：

- 不输出 API key。
- 保留 provider、model、latency_ms、purpose。
- provider timeout 不应被展示成“用户问题不明确”。
- 解密失败应明确归类为 auth/config 问题。

### Task 2：禁止 QuerySpec purpose 使用 ThinkingBlock 降级内容

当前 `LLMService._anthropic_complete()` 在无 `TextBlock` 但有 thinking 文本时会返回 thinking content。

修改要求：

- 对 `purpose in {"data_agent_queryspec", "data_agent_mcp_proxy_args"}`，没有 `TextBlock` 时返回结构化错误，不得把 thinking 当 content。
- 对普通摘要类 purpose 是否保留 thinking fallback，可按现有行为兼容，但必须避免影响 JSON 规划类调用。
- 如果 `LLMService._anthropic_complete()` 当前拿不到 purpose，可调整调用签名或在调用层检测返回内容来源。

验收：

- MiniMax thinking-only 响应不会进入 `_call_llm_json` 的 JSON 抽取逻辑。
- trace 中能看到 `LLM_THINKING_ONLY_RESPONSE` 或等价错误。

### Task 3：收紧 `_call_llm_json` 的 JSON 抽取

当前 `_call_llm_json` 会：

1. `json.loads(full_content)`
2. 失败后 `_extract_first_json_object(content)`
3. 成功解析就返回 `ok=True`

修改要求：

- 为 QuerySpec 规划增加专用抽取函数，例如 `_extract_queryspec_json(content)`。
- 候选 JSON 必须是 object，并且至少包含以下顶层字段：
  - `intent`
  - `operator` 或可由 `intent` 推导
  - `datasource`
  - `metrics`
  - `dimensions`
  - `filters`
- 候选 JSON 中 `metrics` 必须是 list，不能是单个 metric object。
- 对包含多个 JSON object 的文本，不能默认取第一个；应选择第一个满足 QuerySpec 契约的 object。
- 找不到合格 QuerySpec 时返回 `QS_JSON_NOT_FOUND` 或 `QS_JSON_INVALID`，并保留截断 raw 片段用于诊断。

验收：

- `{"field":"利润","aggregation":"SUM"}` 不再被当作 QuerySpec 成功返回。
- `{"type":"all"}` 不再被当作 QuerySpec 成功返回。
- 完整 QuerySpec JSON 仍可正常解析。

### Task 4：拆分 QuerySpec 失败错误码

在 `mcp_first_main.py` 中拆分失败类型：

- LLM provider timeout -> `LLM_PROVIDER_TIMEOUT`
- LLM auth/config -> `LLM_AUTH_CONFIG_ERROR`
- empty/no text -> `LLM_EMPTY_RESPONSE`
- thinking-only -> `LLM_THINKING_ONLY_RESPONSE`
- JSON 不可解析或未找到合格 QuerySpec -> `QS_JSON_INVALID` / `QS_JSON_NOT_FOUND`
- Pydantic 模型校验失败 -> `QS_MODEL_INVALID`
- semantic validator 拒绝 -> `QS_VALIDATION_FAILED`

要求：

- 对用户可见文案保持克制，不暴露内部敏感信息。
- 对 trace/detail 保留足够诊断信息。
- `fallback_reason` 必须使用上述稳定分类，而不是一整段异常字符串。

### Task 5：增加一次 QuerySpec Repair

仅对以下情况允许 repair：

- `QS_JSON_INVALID`
- `QS_JSON_NOT_FOUND`
- `QS_MODEL_INVALID`
- `QS_VALIDATION_FAILED`

不允许 repair：

- provider timeout
- auth/config error
- no active config
- thinking-only response

Repair prompt 输入：

- 原用户问题
- intent
- datasource
- queryable_fields
- 原始 LLM 输出或错误摘要
- validator/model 错误
- QuerySpec schema guide

Repair prompt 输出要求：

- 只输出完整 QuerySpec JSON object。
- 不输出 Markdown。
- 不输出局部 metric/filter object。

验收：

- repair 最多一次，避免死循环。
- repair 成功后重新走 `QuerySpec.model_validate` 和 `validate_queryspec`。
- repair 失败后进入现有受控 fallback，不绕过 `mcp_args_guardrail.py`。

### Task 6：缩短 QuerySpec 调用超时并检查 retry

当前 `_call_llm_json` 使用 `timeout=45`。首页问数体验下，QuerySpec 规划不应拖到 25s+ 才失败。

建议：

- 将 `data_agent_queryspec` 和 `data_agent_mcp_proxy_args` 的单次调用硬超时调到 `15-20s`。
- 检查 Anthropic/Minimax client 是否有默认 retry，避免一次规划实际等待超过预期。
- 如果 client cache 与 timeout 绑定不明确，确认 timeout 变更能生效。

验收：

- provider 超时时，trace latency 与配置超时接近，不再隐式拖到 25s+ 或 60s+。
- 超时错误归类为 `LLM_PROVIDER_TIMEOUT`。

### Task 7：测试覆盖

新增或补充测试，至少覆盖：

1. active config 存在但 provider timeout，返回 `LLM_PROVIDER_TIMEOUT`。
2. API key 解密失败，返回 `LLM_AUTH_CONFIG_ERROR`。
3. MiniMax thinking-only response，JSON planning purpose 返回 `LLM_THINKING_ONLY_RESPONSE`。
4. `_call_llm_json` 遇到局部 JSON `{"field":"指标Y","aggregation":"SUM"}`，返回失败。
5. `_call_llm_json` 遇到多个 JSON 片段时，只接受完整 QuerySpec。
6. QuerySpec model invalid 触发一次 repair。
7. provider timeout 不触发 repair。
8. Q1/Q8 QuerySpec canary 可通过。
9. Q5/Q6/Q10 在修复后不再因局部 JSON 被误判成功；若模型仍输出不合格，必须清晰失败或 repair 成功。

## 6. 验收标准

本任务完成后，至少满足：

- 不再把 provider timeout 伪装成“用户问题不明确”或普通 `QS_LLM_INVALID`。
- thinking-only 响应不会被当成正式 QuerySpec。
- 局部 JSON 不会被误判为 QuerySpec。
- `fallback_reason` 是稳定分类码，可用于统计。
- QuerySpec repair 有且只有一次。
- MCP fallback 仍必须经过 `mcp_args_guardrail.py`。
- 相关 backend 测试通过。

## 7. 推荐验证命令

修改 Python 文件后执行：

```bash
cd backend && python3 -m py_compile $(git diff --name-only | grep '\.py$')
cd backend && pytest tests/services/data_agent/test_llm_queryspec_stability.py -q
cd backend && pytest tests/services/data_agent/test_mcp_first_main.py tests/services/data_agent/test_queryspec_prompt_builder.py -q
```

如果改动影响 LLM service 通用行为，再追加：

```bash
cd backend && pytest tests/services/llm tests/test_llm_purpose_routing.py -q
```

如果改动影响 agent stream 或 quality gate，再追加：

```bash
cd backend && pytest tests/evals/test_data_agent_batch2_baseline.py tests/services/data_agent/test_quality_gate.py -q
```

## 8. Coder 注意事项

- 当前工作区已有大量未提交改动，不要回滚无关文件。
- 只暂存或提交本任务相关文件，除非用户另有指令。
- 不要输出或记录明文 API key。
- 不要为了通过测试把 QuerySpec Validator 放松到允许危险查询。
- provider 失败、JSON 失败、QuerySpec 校验失败是三类不同问题，必须在 trace 和错误码上分开。
- 用户可见错误应简洁，开发诊断信息放在 detail/trace 中。
