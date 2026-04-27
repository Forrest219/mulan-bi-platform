# Spec 27 — 账户与设置功能分阶段上线计划

| 版本 | 日期 | 状态 | Owner |
|------|------|------|-------|
| v0.2 | 2026-04-26 | Draft | Zhang Xingchen |

---

## 概述

本文档描述 Spec 27（账户与设置功能）的 6 周分阶段生产环境上线计划。

**上线范围：**
- 密码重置（Token 链路）
- 密码修改（已登录用户）
- 管理员用户管理
- TOTP 双因素认证
- 用户组权限 UI
- 活跃会话管理

**非上线范围（本期不发）：**
- 真实邮件发送（管理员中转 token）
- SMTP 配置 UI

---

## 上线架构图

```
Week 1-2 ─────────────────────────────────────────── Week 3-4 ─────────────────────────────────────────── Week 5-6
     │                                                        │                                                        │
     ▼                                                        ▼                                                        ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐      ┌─────────────┐  ┌─────────────┐                 ┌─────────────┐
│  Foundation │  │   Foundation│  │    Foundation│      │ TOTP Rollout │  │ TOTP Rollout │                 │Full Launch  │
│  ┌─────────┐│  │  ┌─────────┐│  │   ┌─────────┐│      │  ┌─────────┐│  │  ┌─────────┐│                 │  ┌─────────┐│
│  │Alembic  ││  │  │Admin API││  │   │Internal ││      │  │TOTP API ││  │  │QR Code  ││                 │  │Email Flow││
│  │Migration││  │  │Endpoints││  │   │ Testing ││      │  │ Setup   ││  │  │ Beta    ││                 │  │Monitoring││
│  └─────────┘│  │  └─────────┘│  │   └─────────┘│      │  └─────────┘│  │  └─────────┘│                 │  └─────────┘│
└─────────────┘  └─────────────┘  └─────────────┘      └─────────────┘  └─────────────┘                 └─────────────┘
     ▲             ▲             ▲                        ▲             ▲
     │             │             │                        │             │
     └─────────────┴─────────────┘                        └─────────────┘
                    Week 1-2 COMPLETE                              Week 3-4 COMPLETE
```

---

## Week 1: 数据库迁移与核心 API

### 1.1 目标

完成 `auth_password_reset_tokens` 表的 Alembic 迁移，为密码重置功能奠定数据层基础。

### 1.2 Pre-Deployment Checklist

- [ ] 所有迁移文件已通过 `alembic upgrade --dry-run` 语法检查
- [ ] 本地数据库 `mulan_bi` 执行 `upgrade head` 成功
- [ ] 回滚测试 `upgrade head → downgrade -1 → upgrade head` 三步通过
- [ ] 新表包含所需字段：`id`(UUID), `user_id`(FK), `token_hash`(VARCHAR 64), `expires_at`, `is_used`, `created_at`
- [ ] `auth_refresh_tokens` 扩展字段已添加：`ip_address`, `user_agent`
- [ ] 相关 Python 文件语法正确：`python3 -m py_compile app/models/auth.py app/services/auth.py`
- [ ] 测试覆盖：`pytest tests/test_auth_password_reset.py -v` 全绿
- [ ] 代码审查通过（PR approved + merged to main）

### 1.3 Deployment Steps

```bash
# 1. 备份生产数据库
pg_dump -h $PROD_DB_HOST -U mulan -d mulan_bi -F custom -f backup_$(date +%Y%m%d_%H%M%S).dump

# 2. 拉取最新代码
git pull origin main

# 3. 运行 Alembic 迁移（生产环境）
cd backend
alembic upgrade head

# 4. 验证新表存在
psql -h $PROD_DB_HOST -U mulan -d mulan_bi -c "\dt auth_password_reset_tokens"

# 5. 验证迁移版本记录
alembic current
```

### 1.4 Post-Deployment Verification

```bash
# 1. 确认迁移版本
alembic current

# 2. 检查表结构
psql -h $PROD_DB_HOST -U mulan -d mulan_bi -c "\d auth_password_reset_tokens"

# 3. 冒烟测试 - 生成 token
curl -s -X POST http://localhost:8000/api/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com"}' | jq .

# 4. 检查数据库记录
psql -h $PROD_DB_HOST -U mulan -d mulan_bi -c "SELECT id, user_id, expires_at, is_used FROM auth_password_reset_tokens LIMIT 1;"

# 5. 后端日志无 ERROR 级别错误
grep -i error /var/log/mulan-bi/backend.log | tail -20
```

### 1.5 Rollback Procedure

```bash
# 立即回滚（如果发现数据问题）
cd backend
alembic downgrade -1

# 验证回滚成功
alembic current
psql -h $PROD_DB_HOST -U mulan -d mulan_bi -c "\dt auth_password_reset_tokens"  # 应报错：表不存在

# 如需完全恢复数据
pg_restore -h $PROD_DB_HOST -U mulan -d mulan_bi backup_YYYYMMDD_HHMMSS.dump
```

### 1.6 Success Metrics

| 指标 | 目标值 | 监控方式 |
|------|--------|----------|
| 迁移成功率 | 100% | `alembic current` 输出匹配预期版本 |
| 表创建正确率 | 100% | `\d auth_password_reset_tokens` 字段完整 |
| Token 生成成功率 | ≥99% | 冒烟测试 + 生产请求日志 |
| 迁移耗时 | <30 秒 | 部署日志时间戳差值 |
| 回滚成功率 | 100% | `downgrade -1` 无报错 |

### 1.7 Risk Mitigation

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 生产数据库已有同名表 | 低 | 高 | 部署前检查 `SELECT tablename FROM pg_tables WHERE tablename='auth_password_reset_tokens'` |
| 迁移阻塞其他连接 | 低 | 中 | 使用 `SET lock_timeout = '5s'` 限制等待时间 |
| 扩展字段与现有代码不兼容 | 中 | 高 | 先在 staging 环境完整测试一遍 |
| Token 表被意外写入 | 低 | 中 | 部署后立即监控 `auth_password_reset_tokens` 行数变化 |

---

## Week 2: 管理员用户管理 API 与内部测试

### 2.1 目标

上线管理员用户管理端点（`PUT /users/{user_id}`、`GET /users`），并完成内部员工测试。

### 2.2 Pre-Deployment Checklist

- [ ] `PUT /users/{user_id}` 端点实现完整（display_name、email、role、group_ids、is_active）
- [ ] `GET /users` 分页端点支持管理员过滤
- [ ] `GET /users/{user_id}` 详情端点返回完整字段
- [ ] `POST /users/{user_id}/groups` 组分配端点实现
- [ ] Email 唯一性校验通过（重复 email 返回 422）
- [ ] RBAC 检查：仅 admin/data_admin 可访问
- [ ] 所有端点通过 `pytest tests/test_users_api.py -v`
- [ ] 前端用户编辑 Modal 已绑定所有字段
- [ ] 负载测试：100 并发请求无超时（`pytest tests/test_users_api.py -k load`）
- [ ] OpenAPI 文档已更新 `/api/docs`

### 2.3 Deployment Steps

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 语法检查
cd backend && python3 -m py_compile app/api/users.py app/services/user_service.py

# 3. 迁移数据库（如有新迁移）
cd backend && alembic upgrade head

# 4. 重启后端服务
sudo systemctl restart mulan-bi-backend

# 5. 验证服务健康
curl -s http://localhost:8000/health | jq .

# 6. 冒烟测试
curl -s -b admin_cookies.txt http://localhost:8000/api/users | jq '.total'
```

### 2.4 Post-Deployment Verification

```bash
# 1. 管理员获取用户列表
curl -s -b admin_cookies.txt http://localhost:8000/api/users?page=1&page_size=10 | jq '.items | length'

# 2. 管理员更新用户信息
curl -s -X PUT -b admin_cookies.txt http://localhost:8000/api/users/{test_user_id} \
  -H "Content-Type: application/json" \
  -d '{"display_name":"Test User","role":"analyst"}' | jq .

# 3. 验证 email 唯一性冲突
curl -s -X PUT -b admin_cookies.txt http://localhost:8000/api/users/{another_user_id} \
  -H "Content-Type: application/json" \
  -d '{"email":"alreadyexists@example.com"}' | jq '.detail'  # 应返回 422

# 4. 非管理员访问应返回 403
curl -s -b user_cookies.txt http://localhost:8000/api/users | jq '.detail'  # 应返回 403

# 5. 验证用户组分配
curl -s -b admin_cookies.txt http://localhost:8000/api/users/{user_id}/groups | jq '.'

# 6. 前端用户管理页功能验证
# - 打开 /admin/users
# - 点击编辑按钮
# - 修改 display_name、role、group_ids
# - 点击保存，验证更新成功
```

### 2.5 Rollback Procedure

```bash
# 立即回滚到上一版本
git revert HEAD --no-commit
git checkout HEAD -- app/api/users.py app/services/user_service.py
git commit -m "revert: rollback user management API"

# 或者使用 git reset
git reset --hard HEAD~1

# 重新部署
git push origin main
sudo systemctl restart mulan-bi-backend

# 验证回滚
curl -s http://localhost:8000/api/users | jq '.items'  # 旧版本响应格式
```

### 2.6 Success Metrics

| 指标 | 目标值 | 监控方式 |
|------|--------|----------|
| 用户更新 API 响应时间 | P99 < 200ms | Prometheus `http_request_duration_seconds` |
| 列表查询 API 响应时间 | P99 < 500ms | Prometheus 指标 |
| Email 冲突检测率 | 100% | 冒烟测试验证 |
| 403 拦截率（非管理员） | 100% | 冒烟测试验证 |
| 内部测试覆盖率 | ≥90% | 5 名员工完整走查 |

### 2.7 Risk Mitigation

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 权限校验漏洞（越权修改） | 中 | 极高 | 深度代码审查 + 自动化权限测试 |
| Email 唯一性索引缺失 | 低 | 高 | 部署前检查数据库约束 |
| 大数据量查询性能问题 | 中 | 中 | 添加适当索引 + 限制 page_size |
| 前端 Modal 与 API 字段不匹配 | 中 | 中 | 前后端 Contract 测试 |

---

## Week 3: TOTP API 上线与 Beta 测试准备

### 3.1 目标

上线 TOTP 双因素认证后端端点，为 Week 4 的 Beta 测试奠定基础。

### 3.2 Pre-Deployment Checklist

- [ ] `GET /api/auth/mfa/setup` 返回有效 TOTP secret（base32 编码，16 字符）和 URI
- [ ] `POST /api/auth/mfa/verify` 验证成功后 `mfa_enabled=true`
- [ ] `POST /api/auth/mfa/disable` 需验证 TOTP 才可禁用
- [ ] `GET /api/auth/mfa/status` 返回 `{enabled: bool, backup_codes_count: int}`
- [ ] `GET /api/auth/mfa/backup-codes` 首次返回 10 个备用码
- [ ] TOTP issuer 名称为 "Mulan BI"
- [ ] TOTP 有效期 30 秒，允许前后 1 个时间步容差
- [ ] 备用码使用 SHA-256 哈希存储
- [ ] `pytest tests/test_mfa.py -v` 全绿
- [ ] QR 码生成使用 `pyotp` + `qrcode` 库，返回 base64 PNG

### 3.3 Deployment Steps

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 依赖检查
cd backend && pip install pyotp qrcode[pil] -q
python3 -c "import pyotp; import qrcode; print('OK')"

# 3. 语法检查
cd backend && python3 -m py_compile app/api/auth/mfa.py app/services/mfa_service.py

# 4. 重启后端
sudo systemctl restart mulan-bi-backend

# 5. 健康检查
curl -s http://localhost:8000/health | jq .

# 6. MFA 状态端点验证
curl -s -b admin_cookies.txt http://localhost:8000/api/auth/mfa/status | jq .
```

### 3.4 Post-Deployment Verification

```bash
# 1. MFA 状态检查（未启用用户）
curl -s -b test_user_cookies.txt http://localhost:8000/api/auth/mfa/status | jq '.enabled'  # 应为 false

# 2. MFA setup 生成 secret
RESPONSE=$(curl -s -b test_user_cookies.txt http://localhost:8000/api/auth/mfa/setup)
echo $RESPONSE | jq '.secret'    # 16字符 base32
echo $RESPONSE | jq '.uri'       # otpauth://totp/...
echo $RESPONSE | jq '.qr_code'   # base64 PNG

# 3. 使用正确 TOTP 码验证
TOTP=$(python3 -c "import pyotp; print(pyotp.TOTP('$(echo $RESPONSE | jq -r .secret)').now())")
curl -s -b test_user_cookies.txt -X POST http://localhost:8000/api/auth/mfa/verify \
  -H "Content-Type: application/json" \
  -d "{\"code\":\"$TOTP\"}" | jq '.enabled'  # 应为 true

# 4. 错误 TOTP 码验证
curl -s -b test_user_cookies.txt -X POST http://localhost:8000/api/auth/mfa/verify \
  -H "Content-Type: application/json" \
  -d '{"code":"000000"}' | jq '.detail'  # 应返回错误

# 5. 禁用 MFA（需提供正确 TOTP）
curl -s -b test_user_cookies.txt -X POST http://localhost:8000/api/auth/mfa/disable \
  -H "Content-Type: application/json" \
  -d "{\"code\":\"$TOTP\"}" | jq '.message'

# 6. 备用码生成
curl -s -b test_user_cookies.txt http://localhost:8000/api/auth/mfa/backup-codes | jq '.codes | length'  # 应为 10
```

### 3.5 Rollback Procedure

```bash
# 立即回滚
git reset --hard HEAD~1
git push origin main --force
sudo systemctl restart mulan-bi-backend

# 验证
curl -s http://localhost:8000/api/auth/mfa/status -b test_user_cookies.txt | jq '.enabled'
```

### 3.6 Success Metrics

| 指标 | 目标值 | 监控方式 |
|------|--------|----------|
| TOTP 验证成功率 | ≥99% | 成功/失败日志统计 |
| Secret 生成正确率 | 100% | `pyotp` 库验证 |
| QR 码可扫描率 | 100% | Authenticator 实际扫码测试 |
| 并发 TOTP 验证 | 50 并发无错误 | 负载测试 |
| 备用码生成 | 10 码/次，SHA-256 存储 | 验证数据库记录 |

### 3.7 Risk Mitigation

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| TOTP 时间漂移 | 中 | 高 | 允许前后 1 个时间步（60 秒窗口） |
| Secret 存储不安全 | 低 | 极高 | Secret 加密存储（若已有 KMS 集成） |
| 备用码暴力猜测 | 低 | 高 | 备用码单次使用 + 5 次错误锁定 |
| QR 码生成性能问题 | 低 | 低 | 添加缓存或异步生成 |

---

## Week 4: TOTP Beta 测试与二维码前端

### 4.1 目标

完成 TOTP 前端页面（设置页、二维码、验证流程），并在管理员群体中开展 Beta 测试。

### 4.2 Pre-Deployment Checklist

- [ ] `/settings/security` 页面已部署，包含 MFA 卡片
- [ ] `/settings/mfa` 页面显示二维码（base64 PNG）和手动密钥
- [ ] TOTP 验证码输入框 + 验证按钮
- [ ] 备用码列表展示（首次显示，后续不再显示完整）
- [ ] MFA 启用状态正确显示（已启用/未启用）
- [ ] 禁用 MFA 需验证 TOTP
- [ ] `npm run type-check` 零错误
- [ ] `npm run build` 成功，无新增 lint warning
- [ ] `vitest run` 全绿
- [ ] Beta 测试人员名单确定（5-10 名管理员）

### 4.3 Deployment Steps

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 前端依赖安装
cd frontend && npm install

# 3. 类型检查
npm run type-check

# 4. 构建
npm run build

# 5. 部署前端
sudo systemctl restart mulan-bi-frontend

# 6. 验证前端健康
curl -s https://mulan-bi.example.com/health | jq .

# 7. 验证新页面路由
curl -s -I https://mulan-bi.example.com/settings/security | grep HTTP
curl -s -I https://mulan-bi.example.com/settings/mfa | grep HTTP
```

### 4.4 Post-Deployment Verification

```bash
# 1. Beta 测试清单
# - [ ] 管理员 A 登录 → 进入 /settings/security → 看到 MFA 卡片
# - [ ] 点击"启用双因素" → 跳转 /settings/mfa → 看到二维码
# - [ ] 使用 Authenticator 扫码 → 输入 6 位码 → 验证成功
# - [ ] 刷新页面 → MFA 状态显示"已启用"
# - [ ] 点击"禁用双因素" → 输入正确码 → 禁用成功
# - [ ] 点击"禁用双因素" → 输入错误码 → 提示错误

# 2. 备用码测试
# - [ ] 首次查看备用码 → 显示 10 个码
# - [ ] 刷新页面 → 不再显示完整码（只显示已使用/未使用状态）
# - [ ] 使用一个备用码登录 → 成功 + 该码标记为已使用

# 3. 登录流程测试
# - [ ] 已启用 MFA 用户登录 → 输入邮箱密码 → 提示输入 TOTP 码
# - [ ] 输入正确码 → 登录成功
# - [ ] 输入错误码 → 提示错误，保留在 MFA 验证页

# 4. 会话管理测试
# - [ ] 查看 /settings/security → 显示活跃设备列表
# - [ ] 点击某设备"撤销" → 该设备无法继续使用
```

### 4.5 Rollback Procedure

```bash
# 回滚前端
git reset --hard HEAD~1
git push origin main --force
cd frontend && npm run build
sudo systemctl restart mulan-bi-frontend

# 后端保持 Week 3 状态（MFA API 已上线）
# 如需同时回滚后端
git reset --hard HEAD~1
sudo systemctl restart mulan-bi-backend
```

### 4.6 Success Metrics

| 指标 | 目标值 | 监控方式 |
|------|--------|----------|
| Beta 测试人员参与率 | ≥80% | 测试报告统计 |
| MFA 启用成功率 | ≥90% | Beta 用户启用比例 |
| TOTP 验证成功率 | ≥95% | Beta 用户验证统计 |
| 页面加载成功率 | 100% | 浏览器 console 无错误 |
| 二维码扫码成功率 | ≥95% | Beta 用户反馈 |
| 备用码使用成功率 | 100% | 备用码登录测试 |

### 4.7 Risk Mitigation

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Beta 用户启用 MFA 后无法登录 | 低 | 高 | 提供备用码 + 紧急恢复链接 |
| 二维码在某些 Authenticator 无法扫描 | 中 | 中 | 提供手动密钥输入选项 |
| Beta 用户反馈二维码不清晰 | 中 | 低 | 提供 PNG 下载选项 |
| 用户误点"禁用"导致安全感下降 | 中 | 中 | 强提示"禁用后账户风险增加" |

---

## Week 5: 密码重置完整链路与监控

### 5.1 目标

完成密码重置完整链路的上线（包括前端页面），并建立监控告警机制。

### 5.2 Pre-Deployment Checklist

- [ ] `/forgot-password` 页面已部署
- [ ] `/reset-password?token=xxx` 页面已部署
- [ ] 登录页包含"忘记密码"链接
- [ ] `POST /api/auth/forgot-password` 端点实现
- [ ] `POST /api/auth/reset-password` 端点实现
- [ ] Token 限流：同 IP 10 次/小时
- [ ] Token 15 分钟过期
- [ ] Token 单次使用（is_used=true）
- [ ] 防邮箱枚举（无论存在与否均返回相同消息）
- [ ] 密码强度校验（8+ 字符，含大小写+数字）
- [ ] 监控告警已配置（错误率、响应时间）
- [ ] `npm run build` 成功

### 5.3 Deployment Steps

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 后端部署
cd backend && alembic upgrade head
sudo systemctl restart mulan-bi-backend

# 3. 前端部署
cd frontend && npm run build
sudo systemctl restart mulan-bi-frontend

# 4. 监控配置更新
# - 添加密码重置相关指标到 Prometheus
# - 设置错误率告警阈值（>1% 触发 PagerDuty）
# - 设置响应时间告警（P99 >2s 触发）

# 5. 健康检查
curl -s http://localhost:8000/health | jq .
curl -s https://mulan-bi.example.com/health | jq .
```

### 5.4 Post-Deployment Verification

```bash
# 1. 密码重置完整链路测试
# - [ ] 访问 /forgot-password
# - [ ] 输入邮箱 → 点击"发送重置链接"
# - [ ] 提示"如果邮箱存在，已发送重置链接"（不区分是否存在）
# - [ ] 检查数据库：SELECT * FROM auth_password_reset_tokens WHERE user_id = 'xxx';

# 2. Token 使用测试
# - [ ] 使用测试 token 访问 /reset-password?token=xxx
# - [ ] 输入新密码（满足强度要求）
# - [ ] 点击"重置密码"
# - [ ] 跳转登录页，提示"密码已重置"
# - [ ] 使用新密码登录成功

# 3. Token 过期测试
# - [ ] 使用过期 token 访问 /reset-password
# - [ ] 提示"Token 已过期"（不暴露具体原因）

# 4. Token 重复使用测试
# - [ ] 使用已使用 token 访问
# - [ ] 提示"Token 无效或已过期"

# 5. 限流测试
# - [ ] 同 IP 发送 10 次以上 forgot-password 请求
# - [ ] 第 11 次返回 429 "请求过于频繁"

# 6. 监控仪表盘验证
# - [ ] Grafana 密码重置错误率 <1%
# - [ ] Grafana P99 响应时间 <500ms
```

### 5.5 Rollback Procedure

```bash
# 整体回滚（前端 + 后端）
git reset --hard HEAD~1
git push origin main --force

# 后端回滚
cd backend && alembic downgrade -1
sudo systemctl restart mulan-bi-backend

# 前端回滚
cd frontend && npm run build
sudo systemctl restart mulan-bi-frontend

# 验证
curl -s http://localhost:8000/api/auth/forgot-password \
  -X POST -H "Content-Type: application/json" \
  -d '{"email":"test@example.com"}' | jq .
```

### 5.6 Success Metrics

| 指标 | 目标值 | 监控方式 |
|------|--------|----------|
| Token 生成成功率 | ≥99% | 日志统计 |
| Token 验证成功率 | ≥98% | 成功/失败比 |
| 密码重置成功率 | ≥95% | 完成率 |
| 限流拦截率 | 100% | 429 响应统计 |
| 前端页面加载成功率 | 100% | 监控 |
| 监控告警误报率 | <5% | 告警记录 |

### 5.7 Risk Mitigation

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Token 生成算法可预测 | 低 | 极高 | 使用 UUID v4 + 密码学安全随机数 |
| Token 通过 URL 泄露 | 中 | 高 | HTTPS only + 日志脱敏 |
| 暴力猜测 Token | 低 | 高 | 限流 + Token 足够长度（64 字符哈希） |
| 邮件token 被中间人拦截 | 低 | 高 | 管理员通过安全渠道转发 |
| 用户无法收到管理员转发的 token | 中 | 中 | 提供备选：联系管理员重新发送 |

---

## Week 6: 全量上线与紧急回滚预案

### 6.1 目标

全量开放所有功能（密码修改、用户组 UI、会话管理），并建立完整的监控与回滚机制。

### 6.2 Pre-Deployment Checklist

- [ ] `/settings/profile` 页面（display_name、email 修改）
- [ ] `/settings/security` 页面（密码修改表单、活跃设备列表）
- [ ] `/admin/groups` 页面（用户组 CRUD）
- [ ] 组详情页（成员管理、权限配置）
- [ ] 用户编辑 Modal 增加 group_ids 多选
- [ ] 登出所有设备功能
- [ ] 侧边栏用户头像 → `/settings/profile` 导航
- [ ] 所有新页面 `npm run build` 成功
- [ ] 全量测试通过：`pytest tests/ -x && vitest run`
- [ ] 性能测试通过：100 并发无显著延迟
- [ ] 安全扫描通过：`npm run audit` 无高危漏洞
- [ ] 回滚预案已文档化并演练
- [ ] 支持团队已培训

### 6.3 Deployment Steps

```bash
# Phase 1: 后端全量部署（周一）
git pull origin main
cd backend && alembic upgrade head
sudo systemctl restart mulan-bi-backend
curl -s http://localhost:8000/health

# Phase 2: 前端全量部署（周二）
cd frontend && npm run build
sudo systemctl restart mulan-bi-frontend
curl -s https://mulan-bi.example.com/health

# Phase 3: 功能全量开放（周三）
# - 取消所有功能的 feature flag
# - 通知所有用户新功能上线

# Phase 4: 监控验证（上线后 48 小时）
# - 每 4 小时检查一次监控仪表盘
# - 收集用户反馈
```

### 6.4 Post-Deployment Verification

```bash
# 1. 用户设置页验证
# - [ ] 用户登录 → 点击头像 → 进入 /settings/profile
# - [ ] 修改 display_name → 保存成功
# - [ ] 修改 email → 保存成功 → 跳转登录（重新认证）

# 2. 密码修改验证
# - [ ] 进入 /settings/security
# - [ ] 输入旧密码 + 新密码 + 确认密码
# - [ ] 点击"修改密码" → 提示"密码已更新"
# - [ ] 使用新密码重新登录成功

# 3. 用户组管理验证（管理员）
# - [ ] 进入 /admin/groups
# - [ ] 点击"创建用户组" → 填写名称描述 → 保存成功
# - [ ] 点击组名称 → 进入详情 → 添加成员
# - [ ] 配置权限 → 保存成功
# - [ ] 删除组 → 确认提示 → 删除成功

# 4. 会话管理验证
# - [ ] 进入 /settings/security
# - [ ] 查看活跃设备列表（显示 IP、浏览器、位置）
# - [ ] 点击某设备"撤销" → 提示"会话已撤销"
# - [ ] 被撤销设备刷新页面 → 被登出

# 5. 登出所有设备验证
# - [ ] 点击"登出所有设备"（危险区）
# - [ ] 确认弹窗 → 点击"确认登出"
# - [ ] 所有设备被登出，仅保留当前设备
```

### 6.5 Rollback Procedure

```bash
# 紧急回滚触发条件：
# - 错误率 >5% 持续 5 分钟
# - P99 响应时间 >5s 持续 5 分钟
# - 关键功能（登录/密码重置）完全不可用

# 紧急回滚步骤：
# 1. 立即通知相关团队（PagerDuty）
# 2. 执行回滚
git reset --hard HEAD~1
git push origin main --force

# 3. 后端回滚
cd backend && alembic downgrade -1
sudo systemctl restart mulan-bi-backend

# 4. 前端回滚
cd frontend && npm run build
sudo systemctl restart mulan-bi-frontend

# 5. 验证回滚成功
curl -s http://localhost:8000/health | jq .
curl -s https://mulan-bi.example.com/health | jq .

# 6. 发送状态更新
# - 内部状态页更新为"部分回滚"
# - 用户通知（如需要）

# 7. 问题排查
# - 查看错误日志
# - 确定回滚范围（全部还是部分功能）
```

### 6.6 Success Metrics

| 指标 | 目标值 | 监控方式 |
|------|--------|----------|
| 功能可用性 | ≥99.9% | 监控仪表盘 |
| 登录成功率 | ≥99% | 登录日志统计 |
| 密码修改成功率 | ≥98% | 修改操作日志 |
| 用户组操作成功率 | ≥98% | 组管理日志 |
| 用户反馈满意度 | ≥85% | 反馈调查 |
| 紧急回滚次数 | 0 次 | 回滚日志 |
| 监控告警次数 | <5 次/天 | 告警统计 |

### 6.7 Risk Mitigation

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 新功能引入安全漏洞 | 低 | 极高 | 上线前安全扫描 + 代码审查 |
| 用户不会使用新功能 | 中 | 低 | 提供使用指引 + 工具提示 |
| 性能下降 | 中 | 中 | 渐进式放量 + 实时监控 |
| 密码修改后用户无法登录 | 低 | 高 | 提供紧急恢复链接 + 备用码 |
| 用户组权限配置错误导致权限问题 | 中 | 高 | 管理员培训 + 操作日志审计 |

---

## 紧急联系人与支持

| 角色 | 联系人 | 职责 |
|------|--------|------|
| 技术负责人 | Zhang Xingchen | 紧急决策 + 回滚授权 |
| 值班工程师 | On-call rotation | 问题响应 |
| DBA | Database Team | 数据库相关问题 |
| 安全团队 | Security Team | 安全事件响应 |

---

## 文档清单

| 文档 | 路径 | 状态 |
|------|------|------|
| 规格书 | `docs/specs/27-infra-accounts-and-settings.md` | ✅ |
| 实施计划 | `docs/specs/27-rollout-plan.md` | ✅ |
| 实现备注 | `docs/specs/27-IMPLEMENTATION_NOTES.md` | ⬜ |
| 测试报告 | `docs/specs/27-TESTER_PASS.md` | ⬜ |
| Spec 合规检查 | `docs/specs/27-SPEC_Compliance_Check.md` | ⬜ |
| 发布备注 | `docs/specs/27-RELEASE_NOTES.md` | ⬜ |

---

## 附录 A：完整部署时间线

```
Week 1 (Day 1-5)     Week 2 (Day 6-10)    Week 3 (Day 11-15)   Week 4 (Day 16-20)   Week 5 (Day 21-25)   Week 6 (Day 26-30)
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
                     
[数据库迁移]          [管理员用户API]       [TOTP API]           [TOTP Beta测试]      [密码重置链路]        [全量上线]
 - Alembic迁移        - PUT /users/{id}     - MFA Setup API      - /settings/mfa      - /forgot-password    - /settings/profile
 - Token表创建        - GET /users          - MFA Verify API     - 二维码显示         - /reset-password     - /settings/security
 - 内部测试           - 用户编辑Modal       - 备用码API          - Beta测试           - 监控告警           - /admin/groups
                     - 内部员工测试         - 内部测试            - 问题修复           - 完整测试           - 监控验证
                                                                                       - 回滚预案
```

---

## 附录 B：监控指标列表

| 指标名称 | 类型 | 告警阈值 |
|----------|------|----------|
| `auth_password_reset_errors_total` | Counter | >100 触发告警 |
| `auth_password_reset_duration_seconds` | Histogram | P99 >2s |
| `auth_mfa_verification_errors_total` | Counter | >50 触发告警 |
| `auth_session_revocation_total` | Counter | 监控异常峰值 |
| `user_group_operations_total` | Counter | 监控 CRUD 比例 |
| `api_request_duration_seconds` | Histogram | P99 >1s |
| `api_error_rate` | Gauge | >1% 触发告警 |
