# Spec 27 — 账户与设置功能规格书

| 版本 | 日期 | 状态 | Owner |
|------|------|------|-------|
| v0.1 | 2026-04-20 | Draft | Zhang Xingchen |

---

## 1. 背景与目标

本 spec 覆盖 mulan-bi-platform 的账户与设置功能补全，目标：
- 用户可自主找回密码、修改密码、管理双因素认证
- 管理员可完整编辑用户信息、管理用户组与权限
- 所有敏感操作可审计、可回滚

**Non-Goals**: 不做邮件发送（本期仅生成 token，管理员中转）；不做 SSO/OAuth。

---

## 2. 数据模型

### 2.1 新增表：`auth_password_reset_tokens`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | PK |
| `user_id` | UUID | FK → auth_users.id |
| `token_hash` | VARCHAR(64) | SHA-256(token)，不存明文 |
| `expires_at` | TIMESTAMP | 默认为 now() + 15min |
| `is_used` | BOOLEAN | 默认 false |
| `created_at` | TIMESTAMP | 默认 now() |

### 2.2 扩展表：`auth_refresh_tokens`

| 字段 | 类型 | 说明 |
|------|------|------|
| `ip_address` | VARCHAR(45) | 支持 IPv6 |
| `user_agent` | VARCHAR(512) | 浏览器 UA |
| `expires_at` | TIMESTAMP | 原有 |
| `is_revoked` | BOOLEAN | 原有 |

> 需 Alembic 迁移：`add_ip_address_user_agent_to_auth_refresh_tokens`

---

## 3. API 端点

### 3.1 忘记密码

**POST /api/auth/forgot-password**

Request:
```json
{ "email": "user@example.com" }
```

Response 200:
```json
{ "message": "如果邮箱存在，已发送重置链接" }
```

Response 4xx: `{ "detail": "请求过于频繁，请稍后再试" }`

**安全设计**：
- Token 生成：UUID v4 + SHA-256 存储（防泄露）
- 有效期：15 分钟
- 单次使用：is_used = true 后不可再用
- 防枚举：无论邮箱是否存在均返回相同信息
- 限速：同 IP 10 次/小时

**POST /api/auth/reset-password**

Request:
```json
{ "token": "uuid-token", "new_password": "NewPass123!" }
```

Response 200:
```json
{ "message": "密码已重置，请使用新密码登录" }
```

Response 400:
```json
{ "detail": "Token 无效或已过期" }
```

### 3.2 修改密码（已登录用户）

**PUT /api/auth/me/password**

Request:
```json
{ "old_password": "...", "new_password": "..." }
```

Response 200:
```json
{ "message": "密码已更新" }
```

Response 400:
```json
{ "detail": "旧密码不正确" }
```

### 3.3 活跃会话管理

**GET /api/auth/me/sessions**

Response 200:
```json
{
  "sessions": [
    {
      "session_id": "uuid",
      "ip_address": "10.0.0.1",
      "user_agent": "Mozilla/5.0 ...",
      "created_at": "2026-04-20T00:00:00Z",
      "is_current": true
    }
  ]
}
```

**DELETE /api/auth/me/sessions/{session_id}**

Response 200:
```json
{ "message": "会话已撤销" }
```

### 3.4 编辑用户

**PUT /api/users/{user_id}**

Request:
```json
{
  "display_name": "新名字",
  "email": "new@example.com",
  "role": "analyst",
  "group_ids": ["uuid1", "uuid2"],
  "is_active": true
}
```

Response 200:
```json
{ "id": "uuid", "display_name": "新名字", "email": "new@example.com", "role": "analyst" }
```

Response 422: `{ "detail": "Email 已被使用" }`

### 3.5 MFA（已有端点，本期仅补前端）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/mfa/setup` | GET | 返回 TOTP secret + QR码 URI |
| `/api/auth/mfa/verify` | POST | 验证 TOTP 后启用 |
| `/api/auth/mfa/disable` | POST | 禁用 MFA |
| `/api/auth/mfa/status` | GET | 返回是否启用 |
| `/api/auth/mfa/backup-codes` | GET | 返回备用码列表 |

### 3.6 邮件配置管理（本期后端完成，前端 P3）

**GET /api/admin/settings/email** — 返回 SMTP 配置（密码脱敏）
**PUT /api/admin/settings/email** — 更新 SMTP 配置

### 3.7 登出所有设备

**POST /api/auth/revoke-all-tokens**

Response 200:
```json
{ "message": "已撤销所有设备登录", "revoked": true }
```

> 仅吊销 refresh_token，不影响当前 session cookie。

---

## 4. 前端页面

### 4.1 忘记密码页 `/forgot-password`

- 邮箱输入框 + "发送重置链接"按钮
- 提交后显示成功提示（不区分邮箱是否存在）
- 已有账户用户收到管理员转发的 token 链接

### 4.2 重置密码页 `/reset-password?token=xxx`

- URL 中读取 token（query param）
- 新密码 + 确认密码输入
- 密码强度实时校验（8+ 字符，含大小写+数字）
- 提交后跳转登录页

### 4.3 个人设置页 `/settings`

Layout: 左侧边栏 + 右侧内容区

**Profile 标签页** `/settings/profile`:
- 头像（渐变色 initials avatar）
- display_name 编辑框
- email 编辑框（变更需 re-auth）
- 保存按钮

**Security 标签页** `/settings/security`:
- 修改密码表单（old_password + new_password + confirm）
- MFA 卡片：启用状态 + 二维码入口 / 禁用入口
- 活跃设备列表（GET /auth/me/sessions）
- 登出所有设备（危险区红色按钮）

### 4.4 MFA 设置页 `/settings/mfa`

- 二维码展示（base64 PNG）
- 手动密钥显示（供无法扫码的场景）
- 验证码输入框 + 验证按钮
- 备用码列表（首次显示一次，后续不再显示完整）

### 4.5 用户组管理页 `/admin/groups`

- 组列表（表格：名称、描述、成员数、操作）
- 创建/编辑组 Modal：组名、描述
- 组详情抽屉：成员管理 + 权限配置 CheckboxGroup

### 4.6 导航变更

- 侧边栏头像/用户名点击 → `/settings/profile`
- 用户下拉菜单增加"设置"入口
- 原 `/system/users` → `/admin/users`

---

## 5. 技术约束

- **TOTP**: 复用 pyotp，issuer 名称为 "Mulan BI"
- **Token 存储**: SHA-256 哈希，不存明文 token
- **密码哈希**: PBKDF2-SHA256（现有实现不变）
- **Session**: HTTP Only Cookie（现有不变）
- **Rate Limit**: forget-password 同 IP 10次/小时
- **邮件**: 本期只生成 token，不集成真实邮件；SMTP 配置管理留后端接口

---

## 6. 用户故事

| # | 故事 |
|---|------|
| US-1 | 作为普通用户，忘记密码时可通过邮箱找回（管理员中转） |
| US-2 | 作为普通用户，可随时修改自己的密码 |
| US-3 | 作为普通用户，可启用/禁用 MFA 认证器 |
| US-4 | 作为普通用户，可查看并撤销陌生设备的登录 |
| US-5 | 作为管理员，可编辑任意用户的 display_name/email/角色 |
| US-6 | 作为管理员，可创建/编辑/删除用户组 |
| US-7 | 作为管理员，可为用户组分配精确权限 |
| US-8 | 作为管理员，可通过 UI 配置 SMTP 邮件服务 |

---

## 7. 验收标准

### AC-1: 忘记密码

- [ ] POST /auth/forgot-password 写入 token 记录（有效期内未使用）
- [ ] 同一邮箱重复请求生成新 token，旧 token 立即失效
- [ ] Token 15 分钟后自动失效
- [ ] 已使用 token 再次提交返回 400
- [ ] 无效 token 返回 400

### AC-2: 重置密码

- [ ] 有效 token 可将密码更新为新密码
- [ ] 密码更新后 token 标记为已使用
- [ ] 登录页"忘记密码"链接指向 /forgot-password

### AC-3: 修改密码

- [ ] 正确旧密码可更新为新密码
- [ ] 错误旧密码返回 400
- [ ] 新密码需满足复杂度要求（8+ 字符）
- [ ] 密码变更后现有 refresh_token 不受影响

### AC-4: 活跃会话

- [ ] GET /auth/me/sessions 返回当前用户所有 refresh_token 记录
- [ ] 列表包含 ip_address、user_agent、created_at、is_current
- [ ] DELETE /auth/me/sessions/{id} 可撤销指定会话
- [ ] 撤销后会话立即无法用于 refresh

### AC-5: 编辑用户

- [ ] 管理员可更新用户 display_name、email、role
- [ ] email 唯一性校验，重复返回 422
- [ ] 组分配变更立即影响用户权限

### AC-6: MFA

- [ ] 未启用用户 GET /mfa/status 返回 { enabled: false }
- [ ] GET /mfa/setup 返回有效 TOTP secret 和 URI
- [ ] POST /mfa/verify 正确 TOTP 后 enabled 变为 true
- [ ] 禁用需验证 TOTP
- [ ] 备用码一次性显示，后续不可再查

### AC-7: 用户组

- [ ] 管理员可创建/编辑/删除用户组
- [ ] 组成员变更立即生效
- [ ] 权限配置保存后调用 set_group_permissions
- [ ] 删除组前需确认（组成员将被移除）

---

## 8. 实施批次

详见 `27-rollout-plan.md`

- **P0**: 忘记密码 + 密码修改 + 编辑用户（1-2天）
- **P1**: Settings 页面 + MFA（1-2天）
- **P2**: 用户组 UI + 登出所有设备（1-2天）
- **P3**: 邮件配置管理 UI（待定）
