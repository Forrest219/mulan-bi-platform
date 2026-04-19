# Spec 27 P0 — 实现备注

| 版本 | 日期 | 状态 | Author |
|------|------|------|--------|
| v1.0 | 2026-04-20 | 完成，待 review | coder |

---

## 改动文件清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `backend/alembic/versions/20260420_020000_add_auth_password_reset_tokens.py` | P0-1：新建 `auth_password_reset_tokens` 表迁移 |
| `frontend/src/pages/forgot-password/page.tsx` | P0-5：忘记密码页 |
| `frontend/src/pages/reset-password/page.tsx` | P0-6：重置密码页（含实时密码强度指示器）|

### 修改文件

| 文件 | 改动摘要 |
|------|---------|
| `backend/services/auth/models.py` | 新增 `PasswordResetToken` ORM 模型；`UserDatabase` 新增 4 个 token 管理方法 |
| `backend/services/auth/service.py` | 新增 `create_password_reset_token`、`reset_password_with_token`、`change_password`、`update_user_profile` |
| `backend/app/api/auth.py` | 替换 stub `forgot_password`；新增 `reset_password`（POST）、`change_password`（PUT /me/password）；新增 `ForgotPasswordRequest`、`ResetPasswordRequest`、`ChangePasswordRequest` Pydantic 模型；忘记密码速率限制 10次/小时 |
| `backend/app/api/users.py` | 新增 `PUT /{user_id}` 完整更新端点（role/group_ids）；新增 `GET /groups` 端点供前端列组 |
| `frontend/src/router/config.tsx` | 新增 `/reset-password` 路由（lazy load `ResetPasswordPage`）|
| `frontend/src/pages/admin/user-management/page.tsx` | 编辑 Modal 新增角色选择器和用户组复选框；`editUserData` state 增加 `role`/`group_ids`；`handleSaveEdit` 发送完整字段；新增 `fetchGroups` 初始化 |

---

## P0 Gate 执行结果

```
# 后端语法检查
cd backend && python3 -m py_compile app/api/auth.py services/auth/service.py services/auth/models.py
→ 通过

# users.py
python3 -m py_compile app/api/users.py
→ 通过

# 前端类型检查
cd frontend && npm run type-check
→ 零错误

# 前端构建
cd frontend && npm run build
→ ✓ built in 2.08s（无 error，仅 chunk size 警告，已存在非本次引入）
```

> 注：后端集成测试（`pytest tests/test_auth.py`）和迁移验证（`alembic upgrade head`）需要 PostgreSQL 连接，在 worktree 环境暂未执行。

---

## 关键设计决策

### Token 安全设计（P0-2/P0-3）

- Token 生成：`uuid.uuid4()`（128-bit 随机），不可预测
- 存储：`hashlib.sha256(raw_token.encode()).hexdigest()` — 只存 hash，原始 token 不落库
- 有效期：`datetime.utcnow() + timedelta(minutes=15)`
- 重复请求：调用 `invalidate_previous_reset_tokens(user_id)` 将用户所有未使用 token 标记 `is_used=True`
- 防枚举：`forgot_password` 端点无论邮箱是否存在均返回 `{"message": "如果邮箱存在，已发送重置链接"}`；邮箱存在时额外返回 `reset_token` 字段供管理员中转

### 密码复杂度（P0-3/P0-4）

`_validate_password_complexity` helper：≥8 字符 + 含大写 + 含小写 + 含数字。在 `reset_password` 和 `change_password` 端点均校验，前端 `ResetPasswordPage` 实时展示四条规则进度指示器。

### 速率限制

忘记密码：`_forgot_attempts` dict，10次/小时/IP，使用与注册速率限制相同的滑动窗口模式。

### 编辑用户 Modal（P0-8）

- 新增角色下拉（与创建用户一致的 `ROLES` 数组）
- 新增用户组复选框（从 `GET /api/users/groups` 获取，保持 group_ids 一致性）
- `PUT /api/users/{id}` 统一处理 display_name/email/role/permissions/group_ids（单端点而非多端点）

### users.py 路由顺序

`GET /groups` 路由定义在 `GET /{user_id}` 之前，避免 FastAPI 将 "groups" 当作 user_id 字符串匹配。

---

## 遗留问题 / 未覆盖项

- 后端集成测试（`test_auth.py`）：现有测试可能未覆盖新端点，等待 fixer 阶段补充
- `alembic upgrade head` 三步验证：需 PostgreSQL 连接在真实环境执行
- 前端 `/forgot-password` 页面展示 `reset_token` 时为纯文本；若未来集成真实邮件发送，该字段应从响应中移除（P3 邮件配置阶段处理）
