# 数据库与 Alembic 硬性操作规范

⚠️ **DDL 变更是本项目最高风险操作，以下规范强制执行。**

## 禁止行为

- ❌ 直接在 PostgreSQL 执行 `ALTER TABLE` / `DROP TABLE` / `CREATE TABLE`（绕过 Alembic）
- ❌ 手动编辑已提交的迁移文件（破坏迁移链完整性）
- ❌ 在生产数据库执行未经本地验证的迁移
- ❌ 迁移脚本中写不可逆操作而不提供 `downgrade()` 实现
- ❌ 一次迁移混入多个不相关的表变更

## 必须遵守

1. **Model 先行**：先改 SQLAlchemy Model，再 `alembic revision --autogenerate`，不得反向操作
2. **检查自动生成内容**：autogenerate 可能遗漏 `server_default`、索引、自定义类型，提交前人工核查迁移文件
3. **本地验证三步**：`upgrade head` → 验证功能 → `downgrade -1` → `upgrade head`，三步全通过才可提交
4. **迁移描述清晰**：`-m` 参数使用 `动词_表名_字段名` 格式，如 `add_llm_api_key_updated_at`
5. **不可逆操作登记 ADR**：删列、删表、字段类型变更等操作须在 `docs/adr/` 登记，说明数据处理方案
6. **生产执行前备份**：生产环境执行迁移前，必须确认有当日备份

## 迁移文件命名约定

```
backend/alembic/versions/YYYYMMDD_HHMMSS_<描述>.py
```

## 验证命令

```bash
# 必须生成迁移脚本，不得手动修改表结构
cd backend && alembic revision --autogenerate -m "describe_your_change"

# 检查生成的迁移文件是否符合预期（人工确认）
cd backend && alembic upgrade head

# 验证可回滚
cd backend && alembic downgrade -1 && alembic upgrade head
```

## 表前缀约定

| 前缀 | 模块 | 表名示例 |
|------|------|---------|
| `auth_` | 用户认证 | auth_users, auth_user_groups |
| `bi_` | 核心业务 | bi_data_sources, bi_scan_logs, bi_requirements |
| `ai_` | LLM/AI | ai_llm_configs |
| `tableau_` | Tableau | tableau_connections, tableau_assets, tableau_field_semantics |
| `mcp_` | MCP 配置 | mcp_servers, mcp_debug_logs |
