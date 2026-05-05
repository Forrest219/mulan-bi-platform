# Context Summary — Spec 22 P0 `mcp_servers` Schema Drift 修复

> 角色：architect
> 日期：2026-04-30
> 关联 Spec：[`22-ask-data-architecture.md`](22-ask-data-architecture.md)、[`spec-mcp-configs.md`](spec-mcp-configs.md)
> 关联规则：`.claude/rules/alembic.md`、`.claude/rules/gotchas.md`（陷阱 4：`server_default` 遗漏）

---

## 1. 故障背景

UAT 在 `/system/mcp-configs` 页面执行"新增 MCP 配置"场景时触发阻断性 500：

| 接口 | 现象 | 错误码 |
|------|------|--------|
| `GET /api/mcp-configs/` | 500 | SYS_001 |
| `POST /api/mcp-configs/` | 500 | SYS_001 |
| `POST /api/mcp-configs/parse` | 200（不查 DB） | — |

后端日志：`psycopg2.errors.UndefinedColumn: column mcp_servers.site_name does not exist`。

## 2. 根因链（已实测确认）

### 2.1 Schema Drift（直接根因）

`backend/services/mcp/models.py` 中 `McpServer` 模型在第 36–40 行新增 5 个字段（注释标注 "Spec 22 P0 多站点扩展"）：

```python
site_name            = Column(String(128), nullable=True)
is_default           = Column(Boolean,    default=False, server_default=sa_text("false"))
priority             = Column(Integer,    default=0,     server_default=sa_func.cast(0, Integer()))
health_status        = Column(String(32), default="unknown", server_default=sa_text("'unknown'"))
consecutive_failures = Column(Integer,    default=0,     server_default=sa_func.cast(0, Integer()))
```

**实测数据库 `mcp_servers` 列**（连 `localhost:5432/mulan_bi` 验证）共 9 列，无任一新增字段：

```
id, name, type, server_url, description, is_active, created_at, updated_at, credentials
```

`alembic/versions/` 全量扫描：**没有任何迁移脚本写入这 5 个字段**。Model 改了，迁移忘了，纯遗漏。

### 2.2 SQLAlchemy 行为

ORM `session.query(McpServer).all()` 会按模型字段生成 `SELECT site_name, is_default, ...`，PostgreSQL 立即抛 `UndefinedColumn`。`/parse` 接口不走 DB 因此幸存。

### 2.3 Spec 22 文档本身的缺陷

[`22-ask-data-architecture.md`](22-ask-data-architecture.md) §2.4 改动文件清单中 `services/tableau/models.py` 标注"不变"，**全文未要求扩展 `mcp_servers` 表**，路由策略走 `tableau_connections.mcp_server_url`（Strategy A）。

但实际实现中 `services/mcp/site_selector.py` 已使用这 5 个字段进行 `is_default` / `priority` / `health_status` 的路由判断（见 site_selector.py:107-120, 158-182），且 `concurrent_dispatcher.py` 也消费了 `SiteInfo.site_name`。也就是说：**实现已经偏离了 Spec 22 的"仅复用 tableau_connections 字段"的设计**，Spec 文档需要补 §2.4a 描述 `mcp_servers` 表扩展。

## 3. 影响范围

| 维度 | 影响 |
|------|------|
| 用户可见 | `/system/mcp-configs` 完全不可用（增/查/启停全部 500），阻断 UAT |
| 上游依赖 | `services/mcp/site_selector.py`、`services/mcp/concurrent_dispatcher.py` 已 import 这些字段；`services/mcp/health_*` 类目的代码若存在亦会读 `health_status` |
| 下游依赖 | 多站点 MCP 路由（Spec 22 P0）功能名义存在但实际未通线 |
| 数据风险 | 存量行只有 9 列；若直接给新列加 `NOT NULL` 无 default 会报 `null value in column ... violates not-null constraint` |

## 4. 附加发现：Alembic 迁移链多头 + revision 重复

### 4.1 `20260428_0001` revision ID 重复（必须解决，否则下次 `revision --autogenerate` 会失败）

| 文件 | 内部 `revision` | 内部 `down_revision` |
|------|----------------|---------------------|
| `20260428_0001_add_event_subscriptions.py` | `20260428_0001` | `ba52b50f68f8` |
| `20260428_0001_fix_kb_embedding_vector_type.py` | `20260428_0001` | `20260427_0001` |
| `20260428_0001_add_bi_agent_dual_write_audit.py` | `add_bi_agent_dual_write_audit` | `20260426_0002` |

下游 `20260428_0002_add_taskrun_core_tables.py` 的 `down_revision = "20260428_0001"` 在两个候选间歧义。`alembic` 当前对 `mcp_servers` 故障无影响（这两个迁移本身无关），但是 **新生成的迁移会再次踩到此警告，且是潜在的合并冲突源头**。

### 4.2 多 head（8 个 head，相互独立）

```
20260427_0002, 20260428_0001(×2), 20260428_0002, add_anomaly_algorithm_column,
20260428_100000, 20260429_000002, 20260429_120000, add_extra_settings_ps
```

`alembic_version` 表当前 2 行：`20260429_000001`、`add_extra_settings_ps`。Spec 22 修复 PR 必须正确指定 `down_revision`（见 SPEC §3.2），否则要么不被应用、要么挂在错误分支。

## 5. 约束（不可破坏）

| # | 约束 | 来源 |
|---|------|------|
| C1 | 不得手 `ALTER TABLE` 绕过 Alembic | `.claude/rules/alembic.md` 禁止行为 |
| C2 | Model 是真值源，禁止反向修改 model 去迁就 DB（即不得删除这 5 个字段） | `.claude/rules/alembic.md` 必须遵守#1 |
| C3 | 必须写 `server_default`，存量行也要有默认值 | `.claude/rules/gotchas.md` 陷阱 4 |
| C4 | 迁移必须 `upgrade head` → `downgrade -1` → `upgrade head` 全过 | `.claude/rules/alembic.md` 必须遵守#3 |
| C5 | 禁止改 `to_dict()` 形状（前端契约） | 本 SPEC §4 验收 |
| C6 | 禁止"先救急 alter，后补迁移"两步方案 | `.claude/rules/no-shortcut-principle.md` |
| C7 | 单次迁移只做这一件事，不混入其他表变更 | `.claude/rules/alembic.md` 禁止行为#5 |

## 6. 不在本 SPEC 处理的事项（显式声明）

- 8 个 alembic head 的全面合并（属另一次治理任务，本次只解决与本迁移相关的 head 选择 + revision 重命名）
- `services/mcp/site_selector.py` 的逻辑修复（model 字段恢复后即可正常工作，无需改）
- Spec 22 文档本身的修订（建议另起一次 spec 修订 PR，本 SPEC 仅在 §1 注明文档缺陷）

---

## 附录 A：实测命令清单（供 coder 复现）

```bash
# 验证 DB 实际列
psql postgresql://mulan:mulan@localhost:5432/mulan_bi -c "\d mcp_servers"

# 验证当前 alembic 状态
cd backend && alembic current
cd backend && alembic heads
```
