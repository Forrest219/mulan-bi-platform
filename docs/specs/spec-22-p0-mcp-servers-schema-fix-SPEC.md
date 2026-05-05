# SPEC — Spec 22 P0 `mcp_servers` Schema Drift 修复

> 角色：architect → coder
> 关联：[`spec-22-p0-mcp-servers-schema-fix-Context_Summary.md`](spec-22-p0-mcp-servers-schema-fix-Context_Summary.md)
> 优先级：P0（阻断 UAT）
> 预计改动量：1 个新迁移文件 + 1 个旧迁移文件重命名（仅 docstring + revision id）

---

## 1. 目标

新增一个 alembic 迁移，使数据库 `mcp_servers` 表结构与 `services/mcp/models.py::McpServer` 模型一致；同时解决迁移链中 `20260428_0001` revision 重复的问题，使后续 `alembic revision --autogenerate` 不再触发 "Revision present more than once" 警告。

完成后 `/api/mcp-configs/` 列表与创建接口恢复 200/201。

## 2. Coder 必做事项

### 2.1 新增迁移文件

**路径**：`backend/alembic/versions/20260430_120000_add_mcp_servers_spec22_fields.py`

**revision id**：`20260430_120000`
**down_revision**：`add_extra_settings_ps`

> 选择理由：`add_extra_settings_ps` 是当前 `alembic_version` 表中两个 head 之一，且与 mcp 域无关，链下挂载安全；本迁移不参与对另一 head（`20260429_000001`）的合并，多 head 合并是后续 ops 任务。

**upgrade() 必须做的事（顺序敏感）**：

```python
op.add_column('mcp_servers',
    sa.Column('site_name', sa.String(length=128), nullable=True))
op.add_column('mcp_servers',
    sa.Column('is_default', sa.Boolean(), nullable=False,
              server_default=sa.text('false')))
op.add_column('mcp_servers',
    sa.Column('priority', sa.Integer(), nullable=False,
              server_default=sa.text('0')))
op.add_column('mcp_servers',
    sa.Column('health_status', sa.String(length=32), nullable=False,
              server_default=sa.text("'unknown'")))
op.add_column('mcp_servers',
    sa.Column('consecutive_failures', sa.Integer(), nullable=False,
              server_default=sa.text('0')))

# 多站点路由查询用索引（site_selector.py 频繁过滤 is_default + is_active；round-robin 按 health_status）
op.create_index('ix_mcp_servers_default_active',
                'mcp_servers', ['is_default', 'is_active'])
op.create_index('ix_mcp_servers_health',
                'mcp_servers', ['health_status'])
```

**downgrade() 必须做的事（逆序）**：

```python
op.drop_index('ix_mcp_servers_health', table_name='mcp_servers')
op.drop_index('ix_mcp_servers_default_active', table_name='mcp_servers')
op.drop_column('mcp_servers', 'consecutive_failures')
op.drop_column('mcp_servers', 'health_status')
op.drop_column('mcp_servers', 'priority')
op.drop_column('mcp_servers', 'is_default')
op.drop_column('mcp_servers', 'site_name')
```

**字段-Model 一致性核查表**（coder 提交前必须比对 `services/mcp/models.py` 第 36–40 行）：

| 字段 | 类型 | nullable | server_default | 与 model 一致？ |
|------|------|----------|----------------|----------------|
| `site_name` | `String(128)` | True | 无 | ✅ |
| `is_default` | `Boolean` | False | `false` | ✅（model 写的是 `default=False`，DB 层改为 NOT NULL + default false 更安全） |
| `priority` | `Integer` | False | `0` | ✅ |
| `health_status` | `String(32)` | False | `'unknown'` | ✅ |
| `consecutive_failures` | `Integer` | False | `0` | ✅ |

> 注：model 的 `is_default`/`priority`/`health_status`/`consecutive_failures` 写的 `default=...` 是 Python 层默认。DB 迁移**必须**用 `nullable=False + server_default=...` 双保险，确保存量行（已有的旧记录，例如 UAT 测试时已经手工建的）也填上默认值。这是 `.claude/rules/gotchas.md` 陷阱 4 的标准要求。

### 2.2 解决 revision 重复 `20260428_0001`

**当前冲突**（详见 Context_Summary §4.1）：两个文件 `revision = "20260428_0001"`，下游 `20260428_0002_add_taskrun_core_tables.py` 的 `down_revision = "20260428_0001"` 实际指向哪一个不确定。

**实测：本次任务在 `mcp_servers` 修复路径上不直接需要解决该重复**（本次新迁移挂在 `add_extra_settings_ps` 下，不经过 `20260428_0001`）。但根据 `.claude/rules/no-shortcut-principle.md`（不允许"够用就行"留尾巴），coder **必须在同一 PR 内**完成以下重命名：

将 `backend/alembic/versions/20260428_0001_fix_kb_embedding_vector_type.py` 内的 `revision` 改为 `20260428_0001b`，并把文件重命名为 `20260428_0001b_fix_kb_embedding_vector_type.py`。

> 选择理由：
> - `20260428_0001_add_event_subscriptions.py` 的 `down_revision = ba52b50f68f8`，与 `20260428_0002_add_taskrun_core_tables.py` 的链路上下文（`20260428_0002` 创建 taskrun，与 spec 30/订阅/事件相关）更连贯，保留它占用 `20260428_0001` id 更合理。
> - `fix_kb_embedding_vector_type` 是知识库独立线，重命名不影响其语义；`down_revision = 20260427_0001` 不动。
> - 不修改任何下游迁移的 `down_revision`（因为下游链路实际跑通的方向是 event_subscriptions）。

**验证手段**：重命名后 `alembic heads` 输出应不再出现 "Revision 20260428_0001 is present more than once" 警告。

### 2.3 不允许做的事（硬约束）

| # | 禁止 | 原因 |
|---|------|------|
| N1 | 修改 `services/mcp/models.py`（包括字段定义、`to_dict()` 形状） | model 是真值源，前端 UI 已消费 5 个字段 |
| N2 | 在 PostgreSQL 直接执行 `ALTER TABLE mcp_servers ADD COLUMN ...` 绕过 Alembic | `.claude/rules/alembic.md` 禁止#1 |
| N3 | 将本次迁移与其他表变更合并为一个文件 | `.claude/rules/alembic.md` 禁止#5 |
| N4 | 省略 `server_default` 仅依赖 model 的 Python 层 `default=` | `.claude/rules/gotchas.md` 陷阱 4 |
| N5 | 修改 `services/mcp/site_selector.py` / `concurrent_dispatcher.py` | 它们已经按 model 正确写法编码，schema 修好后即正常 |
| N6 | 修改 `app/api/mcp_configs.py` 或 `to_dict()` 返回形状 | 前端契约不变 |
| N7 | 把 `is_default` / `priority` / `health_status` / `consecutive_failures` 设为 `nullable=True` | model 期望非空语义；nullable 会让 site_selector 比较运算符出错 |
| N8 | 同 PR 试图合并所有 8 个 alembic head | 超出本次 SPEC 范围；属于另一次治理任务 |
| N9 | 删除或合并 `20260428_0001_add_event_subscriptions.py` 文件 | 仅允许重命名 `fix_kb_embedding_vector_type.py` |

## 3. 验收标准（AC）

> tester 在阶段二必须逐条对照执行。

| AC# | 检查项 | 验证手段 | 通过标准 |
|-----|--------|---------|---------|
| AC-1 | 迁移可正向应用 | `cd backend && alembic upgrade head` | 退出码 0，无 warning（除遗留多 head 提示）|
| AC-2 | 列表 API 恢复 | `curl -i http://localhost:8000/api/mcp-configs/`（带登录 cookie） | HTTP 200，返回 JSON 数组 |
| AC-3 | 创建 API 恢复 | `curl -X POST .../api/mcp-configs/ -d '{...}'` | HTTP 201，返回的 `to_dict()` 包含全部 14 个字段（9 原有 + 5 新增）|
| AC-4 | 存量行有默认值 | `psql ... -c "SELECT id, is_default, priority, health_status, consecutive_failures FROM mcp_servers;"` | 所有行：`is_default=false`、`priority=0`、`health_status='unknown'`、`consecutive_failures=0`、`site_name IS NULL` |
| AC-5 | 迁移可回滚再应用 | `alembic downgrade -1 && alembic upgrade head` | 两步均成功；回滚后 5 列消失，重新 upgrade 后再次出现 |
| AC-6 | 索引存在 | `psql -c "\\d mcp_servers"` | 包含 `ix_mcp_servers_default_active` 与 `ix_mcp_servers_health` |
| AC-7 | revision 重复警告消失 | `alembic heads 2>&1` | 输出不含 "Revision 20260428_0001 is present more than once" |
| AC-8 | site_selector 路径冒烟 | `pytest backend/tests/ -k "mcp" -x` | 所有 mcp 相关 unit/integration 测试通过；若现有测试不足以覆盖 default/round-robin 路径，fixer 阶段补足 |
| AC-9 | model 未被改动 | `git diff backend/services/mcp/models.py` | 无输出（零差异）|
| AC-10 | to_dict() 形状未变 | `git diff backend/services/mcp/models.py backend/app/api/mcp_configs.py` | 无 to_dict 形状改动 |

## 4. 交付制品

| 文件 | 类型 | 必须 |
|------|------|------|
| `backend/alembic/versions/20260430_120000_add_mcp_servers_spec22_fields.py` | 新增 | ✅ |
| `backend/alembic/versions/20260428_0001b_fix_kb_embedding_vector_type.py` | 重命名 + 内部 revision id 改 | ✅ |
| `IMPLEMENTATION_NOTES.md` | coder 阶段二输出 | ✅ |

## 5. 风险与回滚

| 风险 | 缓解 |
|------|------|
| 生产环境 `mcp_servers` 表存量行较多，`ADD COLUMN` 短暂锁表 | PostgreSQL 对 `ADD COLUMN ... NOT NULL DEFAULT <const>` 是 metadata-only 操作（PG 11+），不重写表，无明显锁等待 |
| 迁移挂在错误 head 导致部分环境跑不到 | 上线前 `alembic current` 必须显示 `add_extra_settings_ps`；不一致环境先跑 `alembic upgrade add_extra_settings_ps` 对齐 |
| 索引创建在大表上耗时 | 当前表 < 10 行（UAT 阶段），可忽略；生产同步操作前 ops 评估 |

**回滚策略**：`alembic downgrade -1` 即恢复至迁移前。前端 5 个新字段读取得到 `undefined`，UI 表现为字段不显示，不影响其他流程（已有原 9 字段功能）。但回滚后 site_selector 路由会再次抛 UndefinedColumn，因此**回滚 = 整体 revert PR**，不允许部分回滚。

---

## 6. 给 Spec 22 文档维护者的备注（不属于本 SPEC 范围，仅记录）

`docs/specs/22-ask-data-architecture.md` §2.4 改动文件清单不完整，未要求扩展 `mcp_servers` 表，但实际实现 `services/mcp/site_selector.py` + `services/mcp/concurrent_dispatcher.py` 已强依赖。建议另起一次 spec 修订 PR，在 §2.4 后追加 §2.4a 描述 `mcp_servers` 表新增 5 字段的语义（site_name / is_default / priority / health_status / consecutive_failures）和迁移要求。本 SPEC 不替代该修订动作。
