# 事故报告：bi_operation_logs 缺列导致登录 SYS_001

**发生时间**：2026-05-10 15:29（用户报告）
**处理状态**：已解决
**根因分类**：Alembic 迁移未应用

---

## 现象

`admin/admin123` 登录 `http://localhost:3000/login` 返回 `SYS_001`，前端显示"系统暂时无法响应，请稍后再试"。

---

## 根因

`bi_operation_logs` 表缺少 `ip_address`、`user_agent`、`trace_id` 三列。

代码层已通过 Alembic 迁移脚本新增这三列，但数据库未执行 `alembic upgrade head`，导致运行时 SQLAlchemy 模型与数据库 schema 不一致。

---

## 排查过程（错误路径）

1. 检查 uvicorn 进程冲突（两个进程监听 8000 端口）→ 干扰排查
2. 反复 kill/restart uvicorn → 制造多进程冲突和限流，进一步干扰
3. 手动重置 admin 密码后 curl 测试"通了" → 误判为修通，实际碰巧触发另一代码路径
4. 知道有 Alembic 规范但没第一时间验证数据库版本

---

## 正确排查顺序（教训）

遇到 `SYS_001`（未捕获异常）时，排查顺序应为：

1. **第一步**：查 uvicorn stderr，不是在应用层反复测试
2. **第二步**：运行 `alembic current` 确认数据库版本
3. **第三步**：确认数据库 schema 与代码层模型同步
4. **再查**：认证层逻辑

---

## 修复方法

```bash
cd backend && alembic current        # 确认当前版本
cd backend && alembic upgrade head   # 应用所有迁移
```

---

## 防范措施

| 措施 | 说明 |
|------|------|
| 部署 checklist | 数据库迁移作为独立步骤，不得与代码部署混为一谈 |
| 验证命令 | 上线后立即执行 `alembic current` 确认版本 |
| 监控告警 | Alembic 版本与代码版本不一致时告警 |

---

## SYS_001 含义

`SYS_001` = FastAPI 层未捕获的异常（服务器内部错误）。遇到此错误，第一动作必须是查 uvicorn stderr，不是在应用层反复测试。
