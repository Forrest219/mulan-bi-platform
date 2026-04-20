# Spec 27 — 账户与设置功能实施计划

| 版本 | 日期 | 状态 | Owner |
|------|------|------|-------|
| v0.1 | 2026-04-20 | Draft | Zhang Xingchen |

---

## 背景与现状

本计划覆盖 Spec 27（infra-accounts-and-settings）的分批实施路径。

| 能力 | 后端 | 前端 | 缺口说明 |
|------|------|------|---------|
| 忘记密码 | 🟡 存根（永远返回 200，无实际逻辑） | ❌ 无页面 | 缺 token 表 + 邮件发送 + 重置端点 |
| 密码修改 | ❌ 无端点 | ❌ 无 UI | 需新增 `PUT /auth/me/password` |
| 编辑用户 | ✅ 有 role/active/permission 更新 | 🟡 Modal 骨架存在，功能待补全 | editingUser state 已有，缺字段绑定 |
| 个人设置页 | 🟡 有 `/auth/me` | ❌ 无独立页面 | 需 display_name/email 更新端点 |
| MFA 设置页 | ✅ 完整端点（setup/verify/disable） | ❌ 无 UI 入口 | 纯前端工作 |
| 用户组权限 UI | ✅ 完整后端 CRUD | ❌ 无页面 | 纯前端工作 |
| 登出所有设备 | ✅ `revoke_all_refresh_tokens` 端点 | ❌ 无 UI 入口 | 纯前端工作 |

---

## 实施批次

### P0 — 核心认证流程闭环（1-2 天）

**目标**：用户可以找回账号、修改密码、管理员可完整编辑用户信息。

| # | 模块 | 组件 | 描述 |
|---|------|------|------|
| P0-1 | 后端 | `auth_password_reset_tokens` 表 | Alembic 迁移：token(UUID)、user_id、expires_at、is_used |
| P0-2 | 后端 | `POST /auth/forgot-password` | 生成 reset token，写 DB，返回 token（管理员中转） |
| P0-3 | 后端 | `POST /auth/reset-password` | 验证 token + 更新 password_hash + 标记 token is_used |
| P0-4 | 后端 | `PUT /auth/me/password` | 需 session，验证旧密码后更新 hash |
| P0-5 | 前端 | `/forgot-password` 页面 | 邮箱输入表单 + 提交成功状态 |
| P0-6 | 前端 | `/reset-password?token=xxx` 页面 | token 验证 + 新密码输入 + 确认 |
| P0-7 | 前端 | 登录页加"忘记密码"链接 | `<Link to="/forgot-password">` |
| P0-8 | 前端 | 编辑用户 Modal 补全 | 绑定 display_name / email / role / permissions / group_ids 字段 + PUT 调用 |

**依赖关系**:
```
P0-1(Alembic) → P0-2(forgot-password) → P0-5(前端页面)
P0-2 → P0-3(reset-password) → P0-6(前端页面)
P0-4(change-password) → P0-8(编辑用户Modal, 密码重置入口)
P0-7 依赖 P0-5 路由存在
```

### P1 — 个人设置与 MFA（1-2 天）

**目标**：用户可以自主管理个人信息和双因素认证。
**前置条件**：P0 全部 Gate 通过。

| # | 模块 | 组件 | 描述 |
|---|------|------|------|
| P1-1 | 后端 | `PUT /users/me` | 更新当前用户 display_name / email（需密码确认）|
| P1-2 | 前端 | `/settings/profile` 个人资料页 | 头像（渐变色）/ display_name / email 编辑 + 保存 |
| P1-3 | 前端 | `/settings/security` 安全设置页 | 修改密码表单（调 P0-4）+ MFA 模块 |
| P1-4 | 前端 | MFA 设置卡片 | 展示启用状态 + 二维码（setup）+ 验证码输入 + 禁用入口 |
| P1-5 | 前端 | 侧边栏/导航入口 | 用户头像点击 → `/settings/profile` |

### P2 — 用户组权限 UI + 安全增强（1-2 天）

**目标**：管理员可通过 UI 管理用户组和权限；用户可登出所有设备。
**前置条件**：P1 全部 Gate 通过。

| # | 模块 | 组件 | 描述 |
|---|------|------|------|
| P2-1 | 前端 | `/admin/groups` 用户组管理页 | 组列表 + 创建/编辑/删除组 Modal |
| P2-2 | 前端 | 组详情 — 成员管理 | 添加/移除用户，展示当前成员头像列表 |
| P2-3 | 前端 | 组详情 — 权限配置 | CheckboxGroup 绑定 `ALL_PERMISSIONS`，调 `set_group_permissions` |
| P2-4 | 前端 | 用户管理页 — 组分配列 | 用户行展示所属组 badge，编辑 Modal 增加组多选 |
| P2-5 | 前端 | `/settings/security` — 登出所有设备 | 危险区按钮 + 确认 Modal，调 `POST /auth/revoke-all-tokens` |

---

## Gate 检查

### P0 Gate

```bash
# 1. 后端语法检查
cd backend && python3 -m py_compile app/api/auth.py services/auth/service.py

# 2. 运行相关测试
cd backend && pytest tests/test_auth.py -x -q

# 3. 迁移验证（三步）
cd backend && alembic upgrade head
cd backend && alembic downgrade -1
cd backend && alembic upgrade head

# 4. 关键端点冒烟测试
curl -s -X POST http://localhost:8000/api/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com"}' | grep "message"

# 5. 前端构建
cd frontend && npm run type-check && npm run build
```

### P1 Gate

```bash
# 1. 后端新端点测试
cd backend && pytest tests/test_auth.py -k "change_password or update_me" -v

# 2. 前端类型检查
cd frontend && npm run type-check

# 3. MFA 流程集成
curl -s -b cookies.txt http://localhost:8000/api/auth/mfa/status | grep "enabled"
```

### P2 Gate

```bash
# 1. 前端全量构建
cd frontend && npm run type-check && npm run lint && npm run build

# 2. 用户组 API 冒烟
curl -s -b admin_cookies.txt http://localhost:8000/api/users/groups | jq '.[0]'

# 3. 登出所有设备端点
curl -s -X POST -b cookies.txt http://localhost:8000/api/auth/revoke-all-tokens \
  | grep "revoked"
```

---

## 验收标准

### P0 完成定义

- [ ] 用户访问 `/forgot-password`，输入邮箱，后端写入 `auth_password_reset_tokens` 表
- [ ] 访问 `/reset-password?token=xxx`，输入新密码后可正常登录
- [ ] 登录后调用 `PUT /auth/me/password`，旧密码正确则更新，错误则返回 400
- [ ] 用户管理页编辑 Modal 可保存 display_name / email / role / permissions 变更
- [ ] `npm run type-check` 零错误，`pytest tests/test_auth* -x` 全绿

### P1 完成定义

- [ ] `/settings/profile` 页面可编辑并保存 display_name / email
- [ ] `/settings/security` 页面展示密码修改表单，提交后生效
- [ ] MFA 卡片：未启用时展示二维码入口，已启用时展示禁用入口
- [ ] 侧边栏用户头像可导航至 `/settings/profile`
- [ ] `npm run type-check` 零错误

### P2 完成定义

- [ ] 管理员可在 `/admin/groups` 创建/编辑/删除用户组
- [ ] 可为组添加/移除成员，权限 Checkbox 保存后立即生效
- [ ] 用户管理页编辑 Modal 可多选组并保存
- [ ] `/settings/security` 登出所有设备按钮经确认后调用成功，返回 `revoked` 字段
- [ ] `npm run build` 零错误，`npm run lint` 无新增警告

---

## 制品清单

| 制品 | 产出角色 | 路径 |
|------|---------|------|
| 规格书 | architect | `docs/specs/27-infra-accounts-and-settings.md` |
| 本实施计划 | designer | `docs/specs/27-rollout-plan.md` |
| 实现备注 | coder | `docs/specs/27-IMPLEMENTATION_NOTES.md` |
| Tester 报告 | tester | `docs/specs/27-TESTER_PASS.md` 或 `27-TESTER_FAIL.md` |
| SPEC 合规检查 | reviewer | `docs/specs/27-SPEC_Compliance_Check.md` |
| 发布备注 | shipper | `docs/specs/27-RELEASE_NOTES.md` |
