# config_mulan UAT 初始化报告

执行时间：2026-05-15 12:46 CST
执行身份：Tester
前端入口：http://localhost:3000
配置来源：`/Users/forrest/Documents/my_vault/20_Projects/21_mulan_bi_platform/config_mulan.md`

## 结论

本次 UAT 结论：部分通过，不能判定为全量 PASS。

已通过的关键链路：
- 管理员登录成功。
- 平台设置与 config_mulan 一致。
- MiniMax LLM 已重新保存 API Key，真实调用成功。
- Tableau MCP `Tableau-online` 已配置为后端可访问地址，并完成真实 MCP 工具调用。
- 首页问答 `你有哪些数据源？` 在 3000 前端真实渲染结果，返回 `Tableau-online 数据源清单`，共 24 个 datasource。
- MySQL 数据源使用 config_mulan 密码重保存后，保存态连接测试成功。

未通过/待处理：
- StarRocks 数据库连接 `金山云 StarRocks` 已新增，但连接测试失败。
- `数据管理员` 用户组配置中的成员 `zhaoying` 在用户清单中不存在，因此未加入该组；本次未擅自创建未在用户管理段落声明的账号。
- StarRocks MCP `StarRocks-ai` 已新增，HTTP 探测到 `/mcp` 返回 404；仅能证明后端地址可达，不能证明 StarRocks MCP 工具调用成功。

## 初始化与核对结果

### 平台设置

状态：PASS

- 平台名称：`MULAN`
- 平台副标题：`企业经营语义与 Data Agent 能力平台`
- Logo URL：与 config_mulan 一致

### 用户

状态：PASS

历史保留：
- `admin` 已存在，角色为 admin。历史邮箱为 `admin@mulan.local`，与 config_mulan 不一致；按用户要求保留历史数据，不覆盖。

本次新增：
- `zhangxingchen`，admin
- `zhangying`，data_admin
- `xuchao`，data_admin
- `xieyue`，user
- `linxinru`，user
- `liyi`，user
- `yanglijing`，user

环境中另有历史测试账号：
- `smoke_analyst`，analyst

### 用户组

状态：部分通过

本次新增：
- `管理员`，成员：`admin`、`zhangxingchen`
- `数据管理员`，成员：`xuchao`
- `财数中心`，成员：`liyi`、`yanglijing`
- `参谋部-信息技术部`，成员：`xieyue`、`linxinru`

未完成：
- `数据管理员` 组要求成员 `zhaoying`，但用户清单中没有该账号，未加入。

### LLM

状态：PASS

配置：
- Display Name：`MiniMax-M2.7`
- Provider：`minimax`
- Base URL：`https://api.minimaxi.com/anthropic`
- Model：`MiniMax-M2.7`
- Active：true

处理：
- 历史配置存在，但测试返回 `LLM_002`，提示 API Key 无法解密。
- 已用 config_mulan 的 Token 重新保存同一配置。

真实调用结果：
- `/api/llm/config/test`
- status：200
- success：true
- message：`连接正常`
- model：`MiniMax-M2.7`
- latency：约 4803ms

### Tableau MCP

状态：PASS

配置：
- 名称：`Tableau-online`
- Tableau Server：`https://online.tableau.com`
- Site：`zy_bi`
- PAT 名称：`mcp_test_0419`
- MCP Gateway：`http://host.docker.internal:3927/tableau-mcp`

处理：
- 历史配置存在，PAT 与 config_mulan 一致，保留。
- 原 `localhost:3927` 在后端探测中不可达；已调整为后端可访问的 `host.docker.internal:3927`。
- Tableau connection bridge 更新成功，连接 ID：2。

真实调用结果：
- `list-datasources`：success，duration 2475ms，debug log id 8
- `list-workbooks`：success，duration 1449ms，debug log id 9
- 返回数据包含 `Superstore Datasource`、`TS Users`、`Superstore`、`World Indicators` 等真实 Tableau 资产。

### 数据源连接

状态：部分通过

MySQL：
- 历史配置：`UAT Data Explorer MySQL 20260513`
- Host：`rm-bp1t0ie3sj4g7561hpo.mysql.rds.aliyuncs.com`
- Database：`openclaw_db`
- Username：`bi_zy`
- 初始保存态 `/test` 返回 500。
- 用 config_mulan 密码重保存后，保存态连接测试成功。
- 最终状态：PASS

StarRocks：
- 本次新增：`金山云 StarRocks`
- Host：`10.69.65.62`
- Port：`8090`
- Database：`ai`
- Username：`admin`
- `/api/datasources/{id}/test` 返回：`success=false, message=连接失败`
- 额外对比 8090 与 9030 draft 测试均失败。
- 本机 HTTP 探测 `10.69.65.62:8090` 超时。
- 最终状态：FAIL

### StarRocks MCP

状态：未通过真实工具调用

本次新增：
- 名称：`StarRocks-ai`
- Type：`starrocks`
- Server URL：`http://localhost:8000/mcp`
- Credentials：按 config_mulan 写入，密钥未在本报告展开。

测试结果：
- `/api/mcp-configs/{id}/test` 返回 online，但 HTTP status 为 404。
- 该结果只能说明地址可达，不能证明 MCP server 工具可用。
- 未找到可用的 StarRocks MCP 工具调用闭环，因此不判定通过。

## 首页问答 UAT

状态：PASS

操作：
1. 使用 `admin / admin123` 登录 3000 前端。
2. 进入首页。
3. 当前连接显示 `Tableau-online`。
4. 输入问题：`你有哪些数据源？`
5. 点击发送。

可见结果：
- 页面渲染 `Tableau-online 数据源清单`
- 显示 `共 24 个Tableau datasource`
- 页面列出多个真实 datasource，包括：
  - `Superstore Datasource`
  - `TS Users`
  - `订单+ (示例 - 超市)`
  - `orders-订单明细表`
  - `products-产品维度表`
- 页面显示分析过程入口：`识别为 schema_inventory`

判定：
- 不是“仅配置通过”，而是前端真实问答 + MCP/LLM 链路可见结果通过。

## 阻塞项

1. StarRocks 数据库连接失败。
   - config_mulan 的 `10.69.65.62:8090` 从当前环境探测超时。
   - `8090` 与 `9030` 均未通过后端 draft 连接测试。

2. StarRocks MCP 未完成真实工具调用。
   - 当前 `http://localhost:8000/mcp` 返回 404。
   - 需要提供实际 StarRocks MCP server URL，或启动对应 MCP server 后复测。

3. `zhaoying` 不是已声明用户。
   - 按用户确认，该拼写不是问题。
   - 但系统无法把不存在的用户加入用户组，本次未自行创建。

## Tester 判定

本次 UAT 初始化达到可用状态的范围：
- 用户基础数据：可用
- 平台设置：可用
- LLM：可用
- Tableau MCP：可用
- 首页问答：可用
- MySQL 数据源：可用

本次 UAT 未通过范围：
- StarRocks 数据库连接
- StarRocks MCP 工具调用
- `zhaoying` 用户组成员绑定

最终结论：PARTIAL PASS。首页 Tableau Data Agent 主链路通过；StarRocks 相关链路不应标记为通过。
