# 冒烟测试完整性检查报告

**角色**：Tester  
**日期**：2026-05-15  
**范围**：`frontend/tests/` + `backend/tests/` + Playwright/pytest 配置  
**约束**：只读检查，不修改任何代码或文档，仅提出改善意见

---

## 执行摘要

| 维度 | 状态 | 主要问题 |
|------|------|---------|
| 前端冒烟测试覆盖 | ⚠️ | TESTING.md 索引严重过时，实际文件数是文档声称的 1.7x |
| 前端单元测试 | ✅ | 结构清晰，regression/ 子目录模式良好 |
| 后端测试结构 | ⚠️ | 根目录文件过于平铺，存在重复文件 |
| Playwright 配置 | ⚠️ | CI 参数存在逻辑矛盾 |
| pytest 配置 | ❌ | 未内嵌覆盖率阈值，需手动指定 |
| Global Teardown | ⚠️ | MCP 配置写库但无对应清理模式 |
| OpenSpec 可追溯性 | ❌ | SPEC → 测试的链路缺乏系统性 |

---

## 一、前端冒烟测试

### 1.1 文件数量失真

`docs/TESTING.md` 明确声称：
> 共 **37 个** `.spec.ts` 文件，覆盖前端所有已开发页面。

实际 `frontend/tests/smoke/` 中有 **62 个** `.spec.ts` 文件，差值 **+25**（67% 超出）。

**未被 TESTING.md 收录的文件（25 个）：**

| 文件 | 推测覆盖场景 |
|------|------------|
| `account-security.spec.ts` | 账户安全（密码修改等） |
| `agent-monitor.spec.ts` | Agent 监控页 |
| `app-sidebar-collapse.spec.ts` | 侧边栏折叠行为 |
| `governance-compliance.spec.ts` | 治理合规 |
| `home-explainability.spec.ts` | 首页可解释性 |
| `home-new-conversation.spec.ts` | 新对话流程 |
| `homepage-agent-mode.spec.ts` | 首页 Agent 模式 |
| `homepage-conversation-flow.spec.ts` | 对话完整流程 |
| `llm-config-validation.spec.ts` | LLM 配置校验 |
| `metric-detail.spec.ts` | 指标详情 |
| `metrics-maintenance-window.spec.ts` | 指标维护窗口 |
| `ops-workbench.spec.ts` | 运维工作台 |
| `platform-settings.spec.ts` | 平台设置（TESTING.md 标注"RBAC 权限校验"但无独立索引） |
| `publish-logs.spec.ts` | 发布日志（TESTING.md 标注"未覆盖"，实际文件存在！） |
| `qa-e2e-realapi.spec.ts` | QA 真实 API E2E |
| `query-alerts.spec.ts` | 问数告警 |
| `query-logs.spec.ts` | 查询日志 |
| `shared-permissions.spec.ts` | 共享权限 |
| `sync-logs-realtime.spec.ts` | 同步日志实时流 |
| `tableau-assets.spec.ts` | Tableau 资产（与 tableau-asset-list/detail 关系不明） |
| `tableau-health.spec.ts` | Tableau 健康度 |
| `uat-tableau-browse.spec.ts` | UAT Tableau 浏览 |
| `user-group-management.spec.ts` | 用户组管理 |
| `user-management-create.spec.ts` | 用户创建子流程 |
| `user-management-permissions.spec.ts` | 用户权限子流程 |
| `user-management-role-switch.spec.ts` | 角色切换子流程 |

**改善建议**：  
将 TESTING.md 的"冒烟测试用例索引"更新为实际 62 个文件，消除"声称 37 / 实有 62"的歧义。

### 1.2 "未覆盖模块"描述与现实矛盾

TESTING.md "开发中/未覆盖模块"一节：

| TESTING.md 声明 | 实际状态 |
|-----------------|---------|
| `publish-logs.spec.ts` 标注"前端为占位页，未覆盖" | **文件存在**，测试已编写 |
| `/dev/ddl-validator` 标注"未覆盖" | 未检查到对应 spec 文件（待核实） |
| `/system/groups` 标注"仅 RBAC 无独立冒烟" | `user-group-management.spec.ts` 存在 |

**改善建议**：  
"开发中/未覆盖"一节已失效，建议清空或重新扫描后更新。

### 1.3 命名一致性问题

smoke 目录存在命名风格不统一的问题：
- 部分文件按**功能模块**命名（`governance-health-center.spec.ts`）
- 部分按**操作子场景**命名（`user-management-create.spec.ts`, `user-management-role-switch.spec.ts`）
- `uat-tableau-browse.spec.ts` 使用了 `uat-` 前缀，与 smoke 定位混淆（UAT 通常是 User Acceptance Test，独立于冒烟）
- `qa-e2e-realapi.spec.ts` 使用了 `qa-` 前缀，语义也不属于冒烟

**改善建议**：  
明确冒烟测试命名约定：`<模块>-<子场景>.spec.ts`，`uat-` / `qa-` 前缀文件应移至独立目录或重命名。

---

## 二、前端单元测试

### 2.1 整体状态：✅ 良好

- `tests/unit/` 共 13 个测试文件（含 regression/ 子目录 7 个）
- `regression/` 目录追踪真实 Bug（如 `bug1-auto-import-packages.test.ts`），是很好的实践
- `auth-context-loop.test.tsx` 对应 gotchas.md 陷阱 1，闭环良好

### 2.2 轻微问题

- `tests/unit/` 根级与 `tests/unit/pages/` 子目录文件混排，部分文件（如 `assetChat.test.tsx`）可考虑移入对应 pages/ 子目录
- `tests/debug/` 目录存在但未在任何文档中提及，用途不明

---

## 三、Playwright 配置

### 3.1 CI 参数逻辑矛盾

```ts
fullyParallel: true,        // 全并行
workers: process.env.CI ? 1 : undefined,  // CI 中 1 个 worker
```

`fullyParallel: true` + `workers: 1` 在 CI 中等价于**串行执行**，`fullyParallel` 配置无意义。

**改善建议**：  
若 CI 资源有限，直接设 `workers: 1`，删除或注释 `fullyParallel`。若 CI 支持并发，将 workers 改为合理值（如 `4`）。

### 3.2 无 globalSetup

配置只有 `globalTeardown`，无 `globalSetup`。当前登录逻辑在每个 spec 文件的 `beforeEach` 中各自处理，每次测试均发一次 `/api/auth/login` 请求。

**改善建议**：  
可考虑用 `globalSetup` 创建 session 状态文件（`storageState`），在 `use` 中复用，减少重复登录请求，提升稳定性。

### 3.3 `webServer` 仅在非 CI 模式启动

```ts
webServer: process.env.CI ? undefined : { ... }
```

CI 中不自动启动 dev server，意味着 CI 要求外部提前启动前端服务。这是合理的，但文档中未说明 CI 环境的服务启动方式。

---

## 四、Global Teardown

### 4.1 已覆盖的清理模式

| 资源类型 | 清理模式 | 状态 |
|---------|---------|------|
| LLM 配置 | `删除测试-` / `编辑测试-` / `MiniMax-Test-` 等前缀 | ✅ |
| 用户 | `smoke-user-` 前缀 | ✅ |
| 用户组 | `smoke_test_group_` 前缀 | ✅ |
| 平台设置 | 恢复默认值 | ✅ |
| 限流处理 | 429 → sleep 61s 重试 | ✅ |

### 4.2 缺失的清理模式

smoke 目录有 6 个 MCP 配置相关测试（`mcp-config-add-tableau.spec.ts` 等），这些测试可能向 `mcp_servers` 表写入数据，但 `global-teardown.ts` 中**没有 MCP 配置的清理逻辑**。

**改善建议**：  
为 MCP 配置测试约定命名前缀（如 `smoke-mcp-`），并在 teardown 中添加对应清理逻辑。

---

## 五、后端测试

### 5.1 结构问题：根目录平铺过多

`backend/tests/` 根目录有 **50+ 个 `.py` 文件**直接平铺，而项目已建立了完善的子目录分层（`unit/`, `services/`, `integration/`, `regression/`, `evals/`）。这些根目录文件的归属关系不明确。

典型例子：
- `test_auth.py` / `test_auth_service.py`（根目录）vs `tests/unit/test_auth_service.py`（unit/ 下）— 同名不同路径，关系不清晰
- `test_tableau.py`（根目录）vs `tests/services/tableau/test_mcp_client.py`（services/ 下）

**改善建议**：  
根目录保留 `conftest.py` 即可，其余文件应归入对应子目录。

### 5.2 重复文件

以下文件在 `tests/` 根目录和 `tests/evals/` 均存在：

| 文件名 | 根目录 | evals/ |
|--------|--------|--------|
| `test_llm_purpose_routing.py` | ✅ | ✅ |
| `test_migration_server_defaults.py` | ✅ | ✅ |

违反单一来源原则，维护时需同步两份。

**改善建议**：  
明确 evals/ 的定位（基线评估 vs 回归测试），去掉其中一份，或用不同的测试用例集区分。

### 5.3 pytest.ini 未内嵌覆盖率阈值

```ini
addopts = -v --tb=short --import-mode=importlib
```

CLAUDE.md 要求的运行命令：
```bash
pytest tests/ --cov=services --cov=app --cov-fail-under=50
```

但 `pytest.ini` 的 `addopts` 中**没有** `--cov` 和 `--cov-fail-under=50`，覆盖率检查依赖开发者手动添加参数，CI 中容易遗漏。

**改善建议**：  
将 `--cov=services --cov=app --cov-fail-under=50` 加入 `addopts`（需同时安装 `pytest-cov`），或在 `pyproject.toml` 中用 `[tool.pytest.ini_options]` 管理。

---

## 六、OpenSpec 可追溯性

### 6.1 当前状态

`backend/tests/` 中存在 `test_spec28_e2e.py` 和 `test_spec28_e2e_standalone.py`，表明早期尝试过"按 SPEC 编号命名测试"的实践，但后续没有延续。

整个测试体系中**没有** SPEC → 测试的系统性映射：
- 无 `spec_id` 标注（如 `@pytest.mark.spec("SPEC-28")`）
- 无文档说明哪个 SPEC 由哪些测试文件验收
- `TESTER_PASS.md` / `TESTER_FAIL.md` 规范仅在 AGENT_PIPELINE.md 定义，`docs/tests/` 目录是否存在存档记录未知

### 6.2 改善建议

| 优先级 | 建议 |
|--------|------|
| P1 | 为每个新 SPEC 在 TESTING.md 的冒烟索引中追加对应测试条目（保持索引真实） |
| P2 | 在 `backend/pytest.ini` 中注册 `spec` marker（`markers = spec: link test to spec id`） |
| P3 | 将历史 `TESTER_PASS.md` / `TESTER_FAIL.md` 存档至 `docs/tests/archive/`，形成可查阅的验收记录 |

---

## 七、总结：改善优先级

| 优先级 | 问题 | 影响 |
|--------|------|------|
| P0 | TESTING.md 索引与实际文件严重不符（37 vs 62） | 文档失去参考价值 |
| P0 | pytest.ini 缺少覆盖率阈值，CI 可能静默跳过覆盖门槛 | 合并质量保障失效 |
| P1 | Global teardown 缺少 MCP 配置清理 | 测试数据污染积累 |
| P1 | `publish-logs` 等模块状态描述与现实矛盾 | 误导后续开发者 |
| P2 | Playwright CI workers 配置逻辑矛盾 | 无实际运行影响但配置可读性差 |
| P2 | 后端 tests/ 根目录平铺 50+ 文件 + 重复文件 | 目录可维护性下降 |
| P3 | SPEC → 测试链路缺乏系统性 | 影响流水线审计可追溯性 |

---

*本报告为只读检查产出，不修改任何代码或文档。*
