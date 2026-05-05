# UAT 测试案例：问数配置 — Connected App 密钥

> 模块：`/system/mcp-configs`
> 前置条件：admin / admin123 已登录，页面底部已有一个激活的 Tableau 连接（如 Tableau-Prod-New）

---

## 场景：配置 Connected App 密钥

- 进入「MCP 配置管理」页面，滚动到页面底部「问数配置 — Connected App 密钥」区块
- 展开任意一个折叠面板（如 Tableau-Prod-New），在表单中填写 Client ID 和 Secret Value（从 Tableau 管理后台获取的真实凭证）
- 点击「保存密钥」按钮
- 观察到 Toast 提示「Connected App 密钥已保存」；面板标题变为「更新密钥」；Secret Value 框被脱敏遮蔽（不再回显明文）
- 刷新页面后重新展开该面板，确认配置状态和脱敏显示仍然保持
- 在 NL→SQL 查询页面发起提问（如"本月销售额是多少？"），观察返回结果正常（而非 Q_JWT_001 错误），说明 JWT 签发链路打通
- **（回归）** 在该 MCP 配置行的「操作」列点击「删除」，确认删除
- 查询数据库 `query_connected_app_secrets` 表，确认该 connection_id 的记录数为 **0**（硬删除），而非 `is_active=False`（软停用）
