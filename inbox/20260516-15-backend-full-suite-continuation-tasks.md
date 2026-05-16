# Backend Full Suite Continuation Tasks

Date: 2026-05-16

## Context

本轮目标是继续完成 P1：

- 跑完 full backend suite。
- 补齐 SCHEMA_DRIFT_ALERT 的 nightly/CI 运维闭环。
- 补齐 Virtual Metrics Registry 的产品化治理入口。

当前工作被中断在 `tests/test_data_agent_e2e.py` focused 验证阶段。最后一次命令被用户主动中断，因此后续验证未完成。

## 已完成且已验证

### P1 DevOps / PM 文档化落地

已新增：

- `backend/services/data_agent/data_qa_drift.py`
- `backend/services/data_agent/virtual_metrics_registry.py`
- `backend/tests/services/data_agent/test_data_qa_drift.py`
- `backend/tests/services/data_agent/test_virtual_metrics_registry.py`
- `scripts/data-agent-schema-drift-alert.py`
- `.github/workflows/data-agent-nightly.yml`

已验证：

- Data QA drift + Virtual Metrics Registry focused tests 通过。
- 新增模块和 CLI py_compile 通过。
- drift CLI alert 样例返回 exit 2。
- drift CLI no-alert 样例返回 exit 0。

### Full backend suite 过程中已修复并 focused 通过的阻塞

已修复并通过对应 focused tests：

- `backend/tests/services/data_agent/test_queryspec_fallback.py`
- `backend/tests/evals/test_data_agent_mcp_proxy_baseline.py`
- `backend/services/data_agent/table_display.py`
- `backend/tests/services/data_agent/test_table_display.py`
- Metrics Agent fixture schema drift 相关测试
- `backend/services/semantic_maintenance/rollback_service.py`
- `backend/tests/services/semantic_maintenance/test_rollback_service.py`
- Tableau MCP tools 相关 registry / dispatcher / field resolution / parameter control / view control
- `backend/tests/services/task_runtime/test_state_machine.py`
- `backend/services/events/redactor.py`
- homepage agent mode 相关 dual-write / intent registry / keyword match / tests
- `backend/tests/services/test_starrocks_compliance.py`
- token budget 相关 `budget.py` / `policies.py` / tests
- `backend/services/auth/service.py`
- `backend/app/api/chat.py`
- `backend/tests/test_chat_ask_data_api.py`
- `backend/services/tasks/cleanup_tasks.py`
- `backend/tests/test_cleanup_task.py`

最后确认：

```bash
cd /Users/forrest/Projects/mulan-bi-platform/backend
PYTHONPYCACHEPREFIX=/private/tmp/mulan-pycache .venv/bin/python -m pytest tests/test_cleanup_task.py -q
```

结果：`7 passed`

## Full backend suite 最新进度

最后一次完整后端 suite 命令：

```bash
cd /Users/forrest/Projects/mulan-bi-platform/backend
rm -f .coverage
PYTHONPYCACHEPREFIX=/private/tmp/mulan-pycache .venv/bin/python -m pytest tests/ -x -q
```

结果：

- 运行到约 58%。
- `1686 passed, 20 skipped` 后停止。
- 当前阻塞：`tests/test_data_agent_e2e.py::TestDataAgentE2E::test_e2e_stream_direct_answer`（注：本轮已改测试问题措辞，但 focused 验证被中断，未确认通过）

失败现象：

- 旧测试期望 `metadata + token + done`。
- 当前路由先输出 `intent_classifier + route_decision + explainability + done`。
- 对 `"你好"` 这类低置信问题，新路由会触发 clarification fallback，不再进入 mocked ReAct engine。

## 已修改但未完成验证

> **重要接管提示**：以下文件已被修改，但 focused 验证均被中断，接手时必须视为"未确认通过"状态：

- `backend/tests/test_data_agent_e2e.py` — 测试问题措辞已改
- `backend/app/api/rules.py` — scoped_session rollback 防护
- `backend/app/core/database.py` — scoped_session rollback 防护
- `backend/services/data_agent/skill_loader.py` — graceful degradation rollback

### Data Agent E2E 测试问题改写

- `"你好"` -> `"查询销售额是多少"`
- `"测试问题"` -> `"查询销售额测试问题"`
- `"测试观测"` -> `"查询销售额测试观测"`
- `"步骤测试"` -> `"查询销售额步骤测试"`
- `"会失败"` -> `"查询销售额会失败"`
- `"反馈测试"` -> `"查询销售额反馈测试"`

目的：

- 让这些 E2E 测试继续验证标准 ReAct/SSE/observability 流。
- 不绕过真实 clarification fallback 逻辑。

状态：

- 未完成 focused 验证。

### scoped_session / aborted transaction 防护

focused 跑 `tests/test_data_agent_e2e.py` 时，单独进程暴露了测试库 fallback schema 场景下的事务污染：

- Alembic upgrade 失败后测试框架 fallback 到 ORM metadata 建表。
- app import 期间 `rules` seed 因表尚未存在失败。
- `SessionLocal` 是 `scoped_session`，失败事务可能污染同线程后续请求。
- `SkillLoader.load_and_override()` 捕获 DB 查询异常后没有 rollback，导致同一请求 session 后续 `persist_message()` 进入 `InFailedSqlTransaction`。

已改：

- `backend/app/api/rules.py`
  - rules seed 的 `finally` 中调用 `SessionLocal.remove()`。
- `backend/app/core/database.py`
  - `get_db()` 取 session 后先 `session.rollback()` 清理继承状态。
  - 请求结束后 `session.close()` + `SessionLocal.remove()`。
- `backend/services/data_agent/skill_loader.py`
  - DB 查询失败并 graceful degradation 时执行 `db.rollback()`。

状态：

- 最后一条 focused 验证命令被用户中断，未确认通过。

## 下一步 P0/P1 Continuation Tasks

### TASK 1: 完成 Data Agent E2E focused 验证

执行：

```bash
cd /Users/forrest/Projects/mulan-bi-platform/backend
PYTHONPYCACHEPREFIX=/private/tmp/mulan-pycache .venv/bin/python -m pytest tests/test_data_agent_e2e.py -q
```

若失败：

- 优先确认是否仍为 `InFailedSqlTransaction`。
- 若仍是事务污染，继续查同请求内是否还有捕获 DB 异常但未 `rollback()` 的 graceful degradation 分支。
- 若转为断言失败，按当前 router contract 修正测试，而不是弱化 clarification guardrail。

### TASK 2: 重新运行 full backend suite

focused 通过后执行：

```bash
cd /Users/forrest/Projects/mulan-bi-platform/backend
rm -f .coverage
PYTHONPYCACHEPREFIX=/private/tmp/mulan-pycache .venv/bin/python -m pytest tests/ -x -q
```

验收：

- **正式完成标准：full backend suite 跑完**（不是"过当前阻塞点后继续"就算）。
- 若遇到新的第一个失败点，记录为"新阻塞点"，但 **不算** TASK 2 完成。
- TASK 2 的状态由最终跑完决定，而非通过阻塞点的人数。

### TASK 3: 回归 P1 新增质量治理能力

执行：

```bash
cd /Users/forrest/Projects/mulan-bi-platform/backend
PYTHONPYCACHEPREFIX=/private/tmp/mulan-pycache .venv/bin/python -m pytest \
  tests/services/data_agent/test_data_qa_drift.py \
  tests/services/data_agent/test_virtual_metrics_registry.py \
  -q
```

验收：

- SCHEMA_DRIFT_ALERT evaluator 仍通过。
- Virtual Metrics Registry governance validator 仍通过。

### TASK 4: 检查 git worktree，准备提交边界

执行：

```bash
cd /Users/forrest/Projects/mulan-bi-platform
git status --short
```

注意：

- worktree 中存在大量 `inbox/` 归档/删除类改动，可能是用户已有改动。
- 不要自动 stage 全部文件。
- 只提交本轮验证通过且相关的代码、测试、workflow、script、task 文档。

## 执行指令（接替执行时必须严格遵守）

> 先不要继续扩功能，也不要 commit。第一步只跑 `tests/test_data_agent_e2e.py -q`，确认当前未验证补丁是否成立；若失败，只修第一个失败点。focused 通过后再跑 full backend suite。任何时候不得通过弱化 router guardrail / clarification fallback 来迁就旧测试。

推荐交付命令顺序：

```bash
cd /Users/forrest/Projects/mulan-bi-platform/backend
PYTHONPYCACHEPREFIX=/private/tmp/mulan-pycache .venv/bin/python -m pytest tests/test_data_agent_e2e.py -q
```

然后：

```bash
rm -f .coverage
PYTHONPYCACHEPREFIX=/private/tmp/mulan-pycache .venv/bin/python -m pytest tests/ -x -q
```

最后：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mulan-pycache .venv/bin/python -m pytest \
  tests/services/data_agent/test_data_qa_drift.py \
  tests/services/data_agent/test_virtual_metrics_registry.py \
  -q
```

## 暂不应提交的风险

在以下条件满足前，不建议 commit：

- `tests/test_data_agent_e2e.py` focused 通过。
- full backend suite 跑完（达到最终 passed/skip/fail 数字）。
- 明确区分本轮改动和用户已有 `inbox/archived` 变更。

**commit 前必须做 git 边界检查**，不能混入 `inbox/archived` 等用户已有改动。

> **注意**：用户中断了验证，4 个文件的补丁状态均为"已改未确认通过"，接管时需优先验证。

P1 的 SCHEMA_DRIFT_ALERT 和 Virtual Metrics Registry 治理能力已经完成基础实现与 focused 验证。

剩余关键工作不是继续扩展功能，而是把 full backend suite 跑穿，并确认 Data Agent E2E 在新 router guardrail contract 下的测试表达是正确的。
