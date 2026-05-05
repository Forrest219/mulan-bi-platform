# IMPLEMENTATION_NOTES — Spec 22 P0 `mcp_servers` Schema Drift 修复

> 角色：coder
> 日期：2026-04-30
> 关联：[`spec-22-p0-mcp-servers-schema-fix-SPEC.md`](spec-22-p0-mcp-servers-schema-fix-SPEC.md)、[`spec-22-p0-mcp-servers-schema-fix-Context_Summary.md`](spec-22-p0-mcp-servers-schema-fix-Context_Summary.md)

---

## 1. 交付制品

| 文件 | 类型 | 路径 |
|------|------|------|
| 新增迁移 | 新文件 | `backend/alembic/versions/20260430_120000_add_mcp_servers_spec22_fields.py` |
| 重命名迁移 | 重命名 + 内部 revision id 改写 | `backend/alembic/versions/20260428_0001b_fix_kb_embedding_vector_type.py` |

### 1.1 新增迁移核心内容

- `revision = '20260430_120000'`
- `down_revision = 'add_extra_settings_ps'`（与 SPEC §2.1 一致）
- `upgrade()` 顺序：`site_name` → `is_default` → `priority` → `health_status` → `consecutive_failures` → `ix_mcp_servers_default_active` → `ix_mcp_servers_health`
- `downgrade()` 完全逆序
- 4 个 NOT NULL 字段全部带 `server_default`（`false`/`0`/`'unknown'`/`0`）
- `site_name` 保持 `nullable=True`（与 model 一致）

### 1.2 revision 重复修复

- `20260428_0001_fix_kb_embedding_vector_type.py` → `20260428_0001b_fix_kb_embedding_vector_type.py`
- 文件内 `revision: str = "20260428_0001b"`
- `down_revision` **未修改**（仍为 `20260427_0001`）
- 另一文件 `20260428_0001_add_event_subscriptions.py` **未触碰**（保留 `20260428_0001` id）
- 所有下游迁移的 `down_revision` **未触碰**

---

## 2. 三步验证输出

环境变量：`DATABASE_URL=postgresql://mulan:mulan@localhost:5432/mulan_bi`

> 注：当前仓库存在 8 个 alembic head（属遗留治理任务，见 Context_Summary §4.2），故验证使用 SPEC 指定的 head label `20260430_120000` 而非 `head`，避免 multi-head 歧义。这是 SPEC §3 范围之外的环境约束，不影响本次目标。

### Step 1 — `alembic upgrade 20260430_120000`

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade add_extra_settings_ps -> 20260430_120000, add mcp_servers spec22 multi-site fields
```

### Step 2 — `alembic downgrade add_extra_settings_ps`

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 20260430_120000 -> add_extra_settings_ps, add mcp_servers spec22 multi-site fields
```

### Step 3 — `alembic upgrade 20260430_120000`

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade add_extra_settings_ps -> 20260430_120000, add mcp_servers spec22 multi-site fields
```

### `alembic current` 输出（步骤后）

```
20260430_120000 (head)
20260429_000001 (branchpoint)
```

**无任何 "Revision 20260428_0001 is present more than once" 警告**。

---

## 3. AC 逐条勾选

| AC# | 检查项 | 结果 | 证据 |
|-----|--------|------|------|
| AC-1 | 迁移可正向应用 | ✅ | Step 1 / Step 3 退出码 0，仅 INFO 日志 |
| AC-2 | 列表 API 恢复 | ✅ | `GET /api/mcp-configs/` 返回 HTTP 200，JSON 数组（见 §4） |
| AC-3 | 创建 API 恢复 | ⚠️ 间接验证 | 列表 API 已能完整序列化 `to_dict()`（含全部 14 字段），证明 ORM SELECT 不再抛 UndefinedColumn；POST 路径与 GET 共用 ORM，未单独构造 POST 请求避免污染数据。tester 阶段补 POST 用例。 |
| AC-4 | 存量行有默认值 | ✅ | `(5, 'mcp_test_0419', False, 0, 'unknown', 0, None)` |
| AC-5 | 迁移可回滚再应用 | ✅ | Step 2 + Step 3 均成功 |
| AC-6 | 索引存在 | ✅ | `pg_indexes` 输出含 `ix_mcp_servers_default_active` 与 `ix_mcp_servers_health` |
| AC-7 | revision 重复警告消失 | ✅ | `alembic current` / `alembic heads` 输出不再含 "present more than once" |
| AC-8 | site_selector 路径冒烟 | ⏭ 移交 fixer 阶段 | 本阶段范围限于 schema 修复；mcp 测试由 tester/fixer 跑 |
| AC-9 | model 未被改动 | ✅ | `backend/services/mcp/models.py` 零差异 |
| AC-10 | to_dict() 形状未变 | ✅ | API 返回 14 字段顺序与 model `to_dict()` 一致 |

---

## 4. API 验证输出

```bash
# 登录获取 cookie
curl -s -c /tmp/mulan_cookies.txt -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'
# => {"success":true,...}

# 调用列表接口
curl -s -b /tmp/mulan_cookies.txt -w "\n=== HTTP_CODE: %{http_code} ===\n" \
  http://localhost:8000/api/mcp-configs/
```

```json
[
  {
    "id": 5,
    "name": "mcp_test_0419",
    "type": "tableau",
    "server_url": "https://online.tableau.com",
    "description": "",
    "is_active": true,
    "credentials": { "...": "..." },
    "created_at": "2026-04-23T22:38:53.251417",
    "updated_at": "2026-04-25T01:05:41.865094",
    "site_name": null,
    "is_default": false,
    "priority": 0,
    "health_status": "unknown",
    "consecutive_failures": 0
  }
]
=== HTTP_CODE: 200 ===
```

不再返回 `SYS_001`，`UndefinedColumn` 故障消除。

---

## 5. Python 直连验证输出

```python
# Columns (14 个，含 5 个新字段)
id, name, type, server_url, description, is_active, created_at, updated_at,
credentials, site_name, is_default, priority, health_status, consecutive_failures

# Row（存量数据 server_default 生效）
(5, 'mcp_test_0419', False, 0, 'unknown', 0, None)

# Indexes
mcp_servers_pkey
ix_mcp_servers_name
ix_mcp_servers_type_active
ix_mcp_servers_default_active   # 新增
ix_mcp_servers_health           # 新增
```

---

## 6. 编译检查

```bash
$ cd backend && python3 -m py_compile \
    alembic/versions/20260430_120000_add_mcp_servers_spec22_fields.py \
    alembic/versions/20260428_0001b_fix_kb_embedding_vector_type.py
OK
```

---

## 7. 偏离 / 备注

- **未触发的范围**：Context_Summary §4.2 列出的另 7 个 head 未合并（SPEC §6 / N8 显式排除）。
- **uvicorn 重启**：未手动重启后端；当前进程的 SQLAlchemy ORM 只读取 model 定义，不缓存表结构，DDL 即时生效。已用 curl 验证 API 200 通过。
- **N1–N9 全部遵守**：未改 `services/mcp/models.py`，未直接 ALTER TABLE，未改 `to_dict()`，未改 `add_event_subscriptions`，未改 site_selector / dispatcher / mcp_configs.py，未合并多 head。

无需 SPEC_GAP_REPORT。
