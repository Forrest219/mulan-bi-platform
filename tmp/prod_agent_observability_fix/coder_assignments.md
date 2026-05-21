# Coder 并行分工

## 协作规则

- 本轮先产出任务文档，不改业务代码。
- 后续正式执行时，每个 coder 只能修改自己任务范围内的文件。
- 不回滚其他 coder 或用户已有改动。
- 数据库 schema 变更必须走 Alembic，不允许临时 SQL 作为正式方案。
- 测试失败最多自愈 3 次；超过后产出 blocker。

## coder-1：数据库契约与 migration

写入范围：
- `backend/alembic/versions/*`
- `backend/services/data_agent/models.py`
- 必要的 schema/migration 测试文件

禁止：
- 修改 Agent stream 业务流程。
- 修改前端。
- 截断 error code。

交付文档：
- `tmp/prod_agent_observability_fix/coder-1-db-contract.md`

## coder-2：fallback 持久化链路

写入范围：
- `backend/app/api/agent.py`
- `backend/services/data_agent/session.py`，仅在确有必要时
- fallback path 相关单测

禁止：
- 修改 Alembic migration。
- 修改 Agent 监控页面查询事实源。
- 引入独立 telemetry 表或新 action DSL。

交付文档：
- `tmp/prod_agent_observability_fix/coder-2-persistence.md`

## coder-3：测试、发布验证、历史处置

写入范围：
- `backend/tests/**`
- `tmp/prod_agent_observability_fix/*`
- 必要的验证脚本草案，必须先复核

禁止：
- 直接改生产数据。
- 自动补造历史 assistant 回复。
- 修改业务代码主链路。

交付文档：
- `tmp/prod_agent_observability_fix/coder-3-verification-rollout.md`

## 主 coder：集成与复核

职责：
- 维护 OpenSpec。
- 合并 task 输出。
- 控制执行顺序和验证闭环。
- 最终向用户提交修改文件、验证结果和残余风险。
