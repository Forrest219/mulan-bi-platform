# Tasks

- [ ] RTMF-01: 增加字段能力模型设计，定义 `catalog_fields`、`queryable_fields`、`catalog_only_fields`、`mcp_queryable`、`mcp_checked_at`、`mcp_last_error` 的 API/DB 语义。
- [ ] RTMF-02: 增加 Alembic 迁移，为 `tableau_datasource_fields` 增加 MCP 查询能力标记字段，或新增独立 reconciliation 表；实现前需二选一并写入 design 决策。
- [ ] RTMF-03: 实现 `TableauFieldReconciliationService`，输入 `asset_id / connection_id / datasource_luid`，读取本地字段并调用 MCP metadata，输出差异集。
- [ ] RTMF-04: 在 Tableau 资产同步完成后触发 best-effort reconciliation；失败不得影响资产同步成功，只记录 `mcp_last_error`。
- [ ] RTMF-05: 更新 `/api/tableau/assets/{asset_id}/fields` 和 `/api/tableau/datasources/{asset_id}/metadata` 响应，返回字段级 `mcp_queryable`、整体 `catalog_field_count`、`queryable_field_count`、`catalog_only_count`、`mcp_checked_at`。
- [ ] RTMF-06: 更新 Tableau 资产页字段表，展示“Agent 可查询 / 仅资产目录 / 未校验 / MCP 异常”等状态，不隐藏 catalog-only 字段。
- [ ] RTMF-07: 更新 Data Agent datasource routing，保留 `catalog_fields` 用于数据源匹配，但在输出 datasource context 时附带 catalog/queryable 差异摘要。
- [ ] RTMF-08: 更新 Data Agent query planning/preflight：用户提及字段只存在于 catalog fields 时，先返回可解释冲突，不进入 MCP 查询规划。
- [ ] RTMF-09: 更新 MCP args guardrail 错误语义：区分 `unknown_field` 与 `catalog_only_field`，给出可替代 queryable 字段候选。
- [ ] RTMF-10: 更新回答渲染文案，明确“字段存在于 Tableau 资产目录，但当前 Agent/MCP 不支持查询”。
- [ ] RTMF-11: 增加后端测试，固定资产 422 类似 fixture：catalog 32、queryable 11、catalog-only 字段触发 preflight、queryable 字段正常放行。
- [ ] RTMF-12: 增加前端测试，覆盖字段状态标签、统计数字、MCP 异常提示、不会把 catalog-only 字段显示为 Agent 可查询。

## Dependencies

- RTMF-01/02 必须先于 RTMF-03/05/06。
- RTMF-03 是 RTMF-04/05/07/08 的共享依赖。
- RTMF-08 必须先于 RTMF-09/10。
- RTMF-11/12 应随实现同步补齐，不得事后补。

## Gate

- Data Agent 查询规划和 guardrail 必须只接受 MCP queryable fields。
- catalog-only 字段不得被静默改写为近似 queryable 字段，除非用户确认或规则明确标记为安全替代。
- MCP metadata refresh 失败不得删除或覆盖 catalog fields。
- 资产页必须保留完整 catalog fields，不得为了避免冲突隐藏字段。
- 所有新增 API 字段必须向后兼容，旧前端未使用时不破坏字段列表展示。
