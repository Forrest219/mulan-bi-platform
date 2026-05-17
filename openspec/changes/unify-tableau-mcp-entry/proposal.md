# Unify Tableau MCP Entry

> Status: proposed

## Why

当前产品存在两个 Tableau 相关配置入口：

- `数据连接 / 新建 Tableau 连接`
- `服务配置 / MCP 配置`

两者都会涉及 Tableau URL、Site、PAT、连接名称和权限范围，用户容易误以为需要重复接入同一个 Tableau 环境。实际语义应区分为：Tableau 连接负责资产接入与治理对象，MCP 配置负责 Agent 运行时工具能力。

## What Changes

- 将 `数据连接 / Tableau 连接` 定义为用户唯一推荐入口。
- MVP 采用内置共享 MCP Gateway，不让用户填写 MCP HTTP Endpoint。
- 用户只填写 Tableau URL / Site / PAT；系统自动生成或绑定 Tableau MCP 工具配置。
- `服务配置 / MCP 配置` 保留通用 MCP 管理能力，但 Tableau 类型默认绑定已有 Tableau 连接，不再推荐独立录入 Tableau 凭证。
- 后端以 `tableau_connections` 为主实体，`mcp_servers` 作为 Agent 工具绑定，新增显式关联与一致性约束。

## User Interaction Flow

1. 管理员进入 `系统管理 / 数据连接`，点击新建 Tableau 连接。
2. 填写 Tableau Server URL、Site、PAT 名称、PAT Secret、连接名称。
3. 勾选“启用 Agent 访问”。
4. 后端测试 Tableau REST 连接。
5. 后端自动使用内置共享 MCP Gateway 生成或绑定 Tableau MCP 配置。
6. 前端展示连接状态：`资产同步可用`、`Agent 已启用 / 启用失败`。

## Non-Goals

- 不要求用户手动填写 MCP HTTP Endpoint。
- 不在 MVP 中支持每个 Tableau 连接独立启动一个 MCP Server 进程。
- 不删除通用 MCP 配置页。
- 不重构 Data Agent ReAct 主链路。
- 不改变非 Tableau MCP 类型（如 StarRocks）的配置方式。

## Impact

- 后端：`tableau_connections` 与 `mcp_servers` 的绑定关系、事务一致性、自动 MCP Gateway endpoint 生成。
- 前端：Tableau 新建/编辑表单增加 Agent 访问开关和状态展示；MCP 配置页调整 Tableau 类型引导。
- API：Tableau 连接创建/更新请求增加 `agent_enabled` / `mcp_binding_mode` 等字段。
- 数据库：`mcp_servers` 需要能引用 `tableau_connections.id`，并约束 active Tableau MCP 绑定唯一性。
- 测试：覆盖创建、更新、启停、MCP health check 失败、重复绑定等场景。

## Success Metrics

- 用户接入 Tableau 只需走一个入口。
- 同一个 Tableau URL + Site 不会被重复创建为多个主连接。
- 勾选“启用 Agent 访问”后自动创建或绑定 MCP 配置。
- MCP 启用失败不会影响 Tableau 资产连接保存。
- Data Agent 可通过绑定关系找到正确的 MCP Gateway 与 Tableau 连接上下文。
