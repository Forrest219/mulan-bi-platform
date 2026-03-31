# Mulan BI Platform — 功能清单与开发状态

> 更新日期：2026-03-31

---

## 总览

| 模块 | PRD 版本 | 开发阶段 | 状态 |
|------|---------|---------|------|
| 用户认证与权限 | v1.0 | Phase 1 ✅ | 已完成 |
| 数据源管理 | v1.0 | Phase 2 ✅ | 已完成 |
| Tableau MCP 集成 | v1.2 | Phase 1 ✅ | 已完成 |
| DDL 规范检查 | — | 已完成 | 功能完成 |
| 规则配置 | — | 已完成 | 功能完成 |
| 数据库监控 | v0.2 | Phase 1 | 规划中 |
| AI 能力（搜索/解读） | — | 待规划 | 未开始 |

---

## 1. 用户认证与权限 ✅ 已完成

**PRD:** 无独立文档（内嵌于各模块）

### 功能清单

- [x] 用户注册 / 登录 / 登出
- [x] Session/Cookie 认证（HTTP Only）
- [x] 4 角色体系（admin / data_admin / analyst / user）
- [x] 角色默认权限 + 个人权限叠加
- [x] 用户 CRUD（管理员）
- [x] 用户组管理
- [x] 权限配置矩阵
- [x] 访问日志记录

### 待优化（安全 Review）

| 问题 | 严重度 | 状态 |
|------|--------|------|
| Session 令牌可伪造（无签名） | 🔴 CRITICAL | ✅ 已修复 |
| 默认弱口令 admin/admin123 | 🔴 CRITICAL | ✅ 已修复 |
| rules/requirements/logs/activity 路由无认证 | 🟠 HIGH | ✅ 已修复 |
| 注册成功后跳转 Home 而非 Login | Low | 可选修复 |

---

## 2. 数据源管理 ✅ 已完成

**PRD:** 无独立文档（Phase 2 数据源隔离）

### 功能清单

- [x] 数据源 CRUD（admin/data_admin）
- [x] 所有者隔离（非 admin 只能看/改自己的）
- [x] Fernet 加密存储密码
- [x] 连接测试（10 秒超时保护）
- [x] 多数据库类型支持（MySQL / SQLServer / PostgreSQL / Hive / StarRocks / Doris）

### 待优化

| 问题 | 严重度 | 状态 |
|------|--------|------|
| 硬编码 PBKDF2 Salt | 🔴 CRITICAL | ✅ 已修复 |
| 跨服务共用加密密钥 | 🔴 CRITICAL | ✅ 已修复 |
| Singleton 并发竞态（已修复，加锁） | 已修复 | ✅ |

---

## 3. Tableau MCP 集成 ✅ Phase 1 已完成

**PRD:** `docs/prd-tableau-mcp.md` v1.2

### 功能清单

**P0 — 已完成**
- [x] Tableau 连接配置（PAT 认证）
- [x] 连接测试 API + UI
- [x] Workbooks / Views / DataSources 同步
- [x] 资产浏览列表（按项目分类）
- [x] 资产详情页
- [x] 多 Site 支持（每条连接 = 一个 Site）

**P1 — 已完成**
- [x] 全文搜索
- [x] 项目树侧边栏
- [x] 资产关联数据源展示

**P2 — 未开始**
- [ ] 定时同步任务（APScheduler）
- [ ] 同步日志查看

**P3 — 未开始**
- [ ] AI 解读摘要（依赖 LLM 接入）

### 待优化

| 问题 | 严重度 | 状态 |
|------|--------|------|
| 资产列表存在 IDOR（可枚举他 人 connection） | 🟠 HIGH | ✅ 已修复 |
| 同步异常静默吞掉（只 print） | Medium | 可选修复 |
| tableauserverclient 模块级导入失败静默跳过 | Medium | 可选修复 |

---

## 4. DDL 规范检查 ✅ 已完成

### 功能清单

- [x] DDL 语法解析
- [x] 8 类规则检查（表名规范、字段规范、索引规范、外键规范、注释规范、命名规范、DDL 事务规范、综合规范）
- [x] 规则 YAML 配置化
- [x] 规则 CRUD API
- [x] 违规详情展示

### 待优化

| 问题 | 严重度 | 状态 |
|------|--------|------|
| rules 路由完全无认证 | 🟠 HIGH | **待修复** |

---

## 5. 规则配置 ✅ 已完成

### 功能清单

- [x] 规则列表展示
- [x] 按分类/级别筛选
- [x] 规则开关
- [x] 严重度过滤

---

## 6. 数据库监控 📋 规划中

**PRD:** `docs/prd-database-monitor.md` v0.2

### 规划功能

| 优先级 | 功能 |
|--------|------|
| P0 | 多数据库实例配置（MySQL / PostgreSQL） |
| P0 | 实时 QPS / 连接数 / 慢查询监控 |
| P1 | 监控大盘 |
| P1 | 告警规则 |
| P2 | 历史趋势图 |

### 前置依赖

- [ ] 数据源管理模块 Phase 2（已完成 ✅）
- [ ] 用户权限体系（已完成 ✅）

---

## 7. AI 能力 📋 待规划

### 远景目标

- [ ] 首页自然语言搜索（Text-to-SQL）
- [ ] 报表 AI 解读摘要
- [ ] 数据血缘自动关联
- [ ] 异常检测

### 前置依赖

- [ ] LLM API 接入
- [ ] 向量数据库（可选，用于语义搜索）

---

## 安全问题汇总（按严重度排序）

| # | 严重度 | 问题 | 影响模块 | 状态 |
|---|--------|------|----------|------|
| 1 | 🔴 CRITICAL | Session 令牌可伪造 | 认证 | ✅ 已修复（PyJWT HS256 签名） |
| 2 | 🔴 CRITICAL | 默认弱口令 admin/admin123 | 认证 | ✅ 已修复（环境变量 ADMIN_PASSWORD） |
| 3 | 🔴 CRITICAL | 硬编码 PBKDF2 Salt | 数据源/Tableau | ✅ 已修复（随机 salt） |
| 4 | 🔴 CRITICAL | 跨服务共用加密密钥 | Tableau | ✅ 已修复（TABLEAU_ENCRYPTION_KEY） |
| 5 | 🟠 HIGH | 多个路由无认证 | rules/requirements/logs/activity | ✅ 已修复 |
| 6 | 🟠 HIGH | Tableau 资产列表 IDOR | Tableau | ✅ 已修复 |
| 7 | 🟠 HIGH | 活动日志无认证 | activity | ✅ 已修复 |
| 8 | 🟡 MEDIUM | 同步异常静默吞掉 | Tableau | 可选修复 |
| 9 | 🟡 MEDIUM | tableauserverclient 导入失败静默 | Tableau | 可选修复 |
| 10 | 🟡 MEDIUM | Log 注入风险 | 日志 | 可选修复 |

---

## 下一步计划

### 立即（安全问题修复）
1. Session 令牌签名（itsdangerous） ✅
2. 移除默认 admin/admin123 ✅
3. 修复 Salt + 密钥问题 ✅
4. 补全 rules/requirements/logs/activity 认证 ✅
5. 修复 Tableau IDOR ✅

### 短期（功能补全）
- Tableau P2：定时同步 + 日志
- 数据库监控 Phase 1

### 中期
- 数据库监控 P1 告警
- AI 能力规划
