# Tester 验收计划：统一 Tableau MCP 接入入口

## 验收对象

OpenSpec change：

```text
openspec/changes/unify-tableau-mcp-entry/
```

核心目标：

- 用户只通过 Tableau 数据连接入口接入 Tableau。
- 系统自动完成 MCP Agent 绑定。
- PAT 只以 `tableau_connections.token_encrypted` 为权威存储。
- MCP Gateway 异常不影响 Tableau 连接保存。
- Tableau MCP runtime context 通过 `X-Mulan-*` headers 传递。

## 验收前置条件

- 已执行最新 Alembic 迁移。
- 后端、前端、Postgres、Redis、Celery 正常运行。
- 测试环境存在可用 Tableau PAT。
- 测试环境可以配置或临时取消配置：

```text
TABLEAU_MCP_GATEWAY_URL
```

## P0 验收项

### P0-1 Tableau 连接是唯一推荐入口

步骤：

1. 打开 `/system/data-connections?tab=tableau`
2. 新建 Tableau 连接
3. 填写 `name / server_url / site / token_name / token_value`
4. 勾选“启用 Agent 访问”
5. 保存

预期：

- 页面不要求填写 MCP HTTP Endpoint。
- 请求字段使用 `token_value`，不是 `token_secret`。
- Tableau 连接保存成功。
- 返回或页面展示 Agent 绑定状态。

### P0-2 自动创建或绑定 MCP 配置

步骤：

1. 保存启用 Agent 的 Tableau 连接。
2. 查询 MCP 配置页或 API。

预期：

- 存在 Tableau 类型 MCP 配置。
- `mcp_servers.tableau_connection_id` 指向刚创建的 Tableau 连接。
- `mcp_servers.server_url` 使用 `TABLEAU_MCP_GATEWAY_URL`。
- `binding_source = auto_tableau_connection` 或符合 SPEC 定义。
- `binding_status = bound`，若 health check 未执行则允许为可解释的 pending/unknown 状态。
- `mcp_servers.credentials` 不新增 `pat_value`。

### P0-3 Gateway 未配置不阻断 Tableau 保存

步骤：

1. 临时取消 `TABLEAU_MCP_GATEWAY_URL`。
2. 新建 Tableau 连接并勾选“启用 Agent 访问”。

预期：

- API 返回 `200/201`，不是 4xx/5xx。
- Tableau 连接成功保存。
- MCP 绑定状态为 `disabled`。
- 页面显示 Agent 未启用或待配置 Gateway 的可理解提示。
- 不出现“连接保存失败”的误导提示。

### P0-4 Gateway health check 失败不阻断 Tableau 保存

步骤：

1. 配置一个不可用的 `TABLEAU_MCP_GATEWAY_URL`。
2. 新建或更新 Tableau 连接并启用 Agent。

预期：

- API 返回 `200/201`。
- Tableau 连接成功保存。
- MCP 绑定状态为 `unhealthy`。
- `last_binding_error` 或等价字段记录失败原因。
- Tableau 资产同步能力不应因此被删除或回滚。

### P0-5 Runtime header 传递正确

步骤：

1. 触发一次 Tableau MCP 调用，例如 MCP `tools/list` 或 Agent 查询 Tableau 资产。
2. 查看后端/Gateway 日志或使用测试桩断言请求头。

预期 Gateway 请求包含：

```text
X-Mulan-Tableau-Connection-Id
X-Mulan-Mcp-Server-Id
X-Mulan-User-Id
X-Mulan-Trace-Id
```

并且：

- 不通过 query param 传 `connection_id`。
- 不把 `connection_id` 混入 JSON-RPC tool params。
- 前端不直接传 PAT。

### P0-6 PAT 权威存储

数据库检查：

```sql
select id, token_encrypted
from tableau_connections
order by id desc
limit 5;
```

```sql
select id, type, tableau_connection_id, credentials
from mcp_servers
where type = 'tableau'
order by id desc
limit 5;
```

预期：

- Tableau PAT 只存在于 `tableau_connections.token_encrypted`。
- 新建 Tableau MCP 绑定的 `mcp_servers.credentials` 不包含 `pat_value`。
- 前端和 API 响应不返回 PAT Secret。

### P0-7 重复 Tableau 站点处理

步骤：

1. 使用相同 `server_url + site + owner_id` 再创建一次 Tableau 连接。

预期：

- 不静默创建重复主连接。
- 返回 `409` 或提示复用已有连接。
- 不产生新的重复 active MCP 绑定。

### P0-8 关闭 Agent 访问

步骤：

1. 编辑已有 Tableau 连接。
2. 关闭“启用 Agent 访问”。
3. 保存。

预期：

- Tableau 连接仍存在且可用于资产同步。
- MCP 绑定被停用或 `binding_status=disabled`。
- `tableau_connections.mcp_direct_enabled=false`。
- MCP 配置页显示该绑定已停用或未启用。

## P1 验收项

### P1-1 MCP 配置页 Tableau 类型行为

步骤：

1. 打开 MCP 配置页。
2. 新建 Tableau 类型 MCP 配置。

预期：

- 默认要求选择已有 Tableau 连接。
- 不默认展示 Tableau PAT 输入。
- 自定义 MCP endpoint 仅在高级模式出现。
- 非 Tableau MCP 类型行为不变。

### P1-2 历史数据迁移

步骤：

1. 在带历史 `mcp_servers` 的数据库执行迁移。
2. 检查回填结果。

预期：

- Alembic 不因历史冲突失败。
- 能匹配的历史 Tableau MCP 被绑定到 `tableau_connection_id`。
- 冲突记录标记为 `binding_status=unbound`，并有 `last_binding_error`。
- 不自动删除历史记录。
- 首版迁移未强加 active 唯一索引导致失败。

### P1-3 Tableau MCP Client endpoint 优先级

预期解析顺序：

1. active `mcp_servers` with `tableau_connection_id`
2. 合法的 `tableau_connections.mcp_server_url`
3. 全局 fallback

并且不会把 Tableau Server URL 当作 MCP Gateway URL。

### P1-4 UI 状态展示

预期：

- Tableau 连接列表能展示 Agent 状态：已启用、未启用、异常。
- 保存成功但 Agent 异常时，提示是“连接已保存，Agent 绑定异常”，不是“保存失败”。
- MCP 配置页能显示来源 Tableau 连接名称。

## 回归范围

必须确认以下能力未被破坏：

- Tableau 连接创建、编辑、删除
- Tableau REST 连接测试
- Tableau 资产同步
- Tableau 同步日志
- 非 Tableau MCP 配置，例如 StarRocks
- Data Agent 非 Tableau 工具调用
- 权限控制：非授权用户不能创建/修改连接

## 建议验证命令

```bash
cd backend && pytest tests/ -x -q
cd frontend && npm run type-check
cd frontend && npm run lint
cd frontend && npm test -- --run
```

如前端路由或构建受影响：

```bash
cd frontend && npm run build
```

## 数据库核查 SQL

```sql
select id, name, server_url, site, mcp_direct_enabled, mcp_server_url
from tableau_connections
order by id desc
limit 10;
```

```sql
select id, name, type, server_url, tableau_connection_id, binding_source, binding_status, last_binding_error, credentials
from mcp_servers
where type = 'tableau'
order by id desc
limit 10;
```

## 放行标准

可以放行：

- P0 全部通过。
- P1 无阻塞问题。
- 未发现 PAT 泄露或重复存储。
- Gateway 异常不影响 Tableau 连接保存。
- Runtime header 验证通过。
- 非 Tableau MCP 回归通过。

不建议放行：

- `token_secret` 被引入为主字段。
- `mcp_servers.credentials` 新增保存 `pat_value`。
- Gateway 失败导致 Tableau 连接保存失败。
- MCP 调用缺少 `X-Mulan-Tableau-Connection-Id`。
- 同 URL + Site 被静默创建多个主连接。
- 非 Tableau MCP 行为被破坏。
