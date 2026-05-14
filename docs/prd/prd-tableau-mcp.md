# Tableau MCP 集成模块 PRD

> 文档版本：v1.2（草案）
> 更新日期：2026-03-30
> 状态：待审阅

---

## 1. 背景与目标

### 1.1 现状问题

- 每位分析师各自配置 Tableau 连接，重复且分散
- Tableau Server 凭据散落在各人客户端，无法统一管控
- BI 资产（报表、Dashboard、数据源）没有统一检索入口
- Mulan 与 Tableau 完全割裂，无法协同

### 1.2 目标（Phase 1）

在 Mulan 内部统一接入 Tableau Server，让 BI 中心一次配置、平台统一托管、分析师直接使用 Mulan 提供的能力。

**最终效果：**
- Tableau 连接配置只在 Mulan 后台维护一次
- 凭据只保存在 Mulan 平台侧
- Mulan 自动同步 Tableau 资产
- 分析师通过 Mulan 搜索、查看、解释 Tableau 报表
- 后续可继续扩展为完整 Data Agent 底座

### 1.3 非目标（Phase 1 不做）

| 不做 | 说明 |
|------|------|
| 资产发布 | 不发布新的 Tableau 资产 |
| 数据源修改 | 不修改 Tableau 数据源 |
| Extract 刷新 | 不控制 extract 刷新 |
| 权限写回 | 不将 Mulan 权限同步回 Tableau |
| 直连 | 不让每位分析师以个人账号直连 Tableau |
| 多工具编排 | 不做跨工具联动 |

**一句话：** 本阶段只做统一只读接入 + 资产管理 + 搜索解释能力。

---

## 2. 用户故事

| 角色 | 故事 |
|------|------|
| BI 中心管理员 | 我想统一配置 Tableau Server 连接，所有凭据保存在 Mulan，不用告诉每个人账号密码 |
| 业务分析师 | 我想通过 Mulan 搜索 Tableau 报表，找到后直接查看摘要和关键图表说明，不需要打开 Tableau |
| 数据工程师 | 我想通过 Mulan 看到 Tableau 报表依赖的是哪张表、哪个数据源，方便追踪数据血缘 |
| 平台管理员 | 我想看到 Tableau 连接的健康状态和同步日志，确保资产同步正常 |

---

## 3. 功能需求

### 3.1 Tableau 连接配置

> **多 Server / 多 Site 支持说明**
>
> Tableau 组织结构：Server → Site → Project → Workbook/View
> - 一个 Server 可有多个 Site（独立用户体系和资产命名空间）
> - PAT 绑定在 Site 级别，不是 Server 级别
>
> **设计映射**：每条连接记录 = 一个 Site
> - 同一 Server 不同 Site → 加多条记录，`server_url` 相同，`site` 不同
> - 不同 Server → 加多条记录，`server_url` 不同
> - UI 上用「连接名称」区分（如"生产-Site A""测试-Site B"）

**3.1.1 添加 Tableau Server / Site**
- 字段：
  - 连接名称（业务命名，如"生产-Site A"）
  - 服务器地址（Server URL）
  - Site 名称（区分同一 Server 下的多个 Site）
  - API Version（默认 v3）
  - Personal Access Token Name / Token Secret
- 连接测试：验证 Token 是否有效、Server + Site 是否可达

**3.1.2 Tableau 资产同步**
- 同步内容（只读）：
  - Workbooks（报表）
  - Dashboards
  - Views（单个图表视图）
  - Data Sources（数据源）
- 同步频率：手动触发 + 可选定时（每天凌晨）
- 同步记录：每次同步的时间、资产数量、失败数

### 3.2 资产浏览与搜索

**3.2.1 资产列表**
- 按类型（Workbook / View / Dashboard）分类展示
- 显示：名称、所在项目、创建者、最近更新时间
- 状态标签：已同步 / 同步失败

**3.2.2 全文搜索**
- 按报表名称、项目名称、描述搜索
- 搜索结果按相关性排序

**3.2.3 报表详情**
- 显示报表基本信息（名称、项目、创建者、描述）
- 显示关联的数据源列表（数据血缘起点）
- 显示关键 View 列表

### 3.3 报表解读（AI 能力预留）

**3.3.1 基础摘要**
- 提取报表的元信息：使用的字段、数据源、筛选器列表
- 标注报表的创建时间和最近刷新时间

**3.3.2 字段血缘（Phase 1.5 规划，非本阶段）**
- 关联 Tableau 数据源 → Mulan 已接入的数据库表 → 字段映射

---

## 4. 页面结构

```
/tableau
├── 连接管理页（admin / data_admin）
│   ├── 已配置实例列表（名称、URL、Site、同步状态）
│   ├── 「添加连接」按钮
│   └── 同步历史日志
├── 资产浏览页（所有已登录用户）
│   ├── 左侧：Site/连接选择下拉 + 项目树导航
│   ├── 右侧：资产列表（Workbooks / Views）
│   └── 顶部：全局搜索框
└── 报表详情页
    ├── 基本信息（名称、项目、描述）
    ├── 关联数据源（可跳转 DDL 检查）
    └── 解读摘要（预留 AI 能力）
```

> **分析师的入口**：登录 Mulan 后，顶部导航「Tableau」或左侧菜单 → 进入 `/tableau/assets`（资产浏览页），无需进入「连接管理」页。

---

## 5. 数据模型

### 5.1 Tableau 连接表 `tableau_connections`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| name | VARCHAR(128) | 连接名称（UI 显示，如"生产-Site A"） |
| server_url | VARCHAR(512) | Tableau Server URL |
| site | VARCHAR(128) | Site 名称/ID（一个 URL 可对应多个 Site） |
| api_version | VARCHAR(16) | API 版本（如 v3） |
| token_name | VARCHAR(128) | Personal Access Token 名称 |
| token_encrypted | TEXT | Token Secret（Fernet 加密） |
| owner_id | INT | 创建者用户 ID |
| is_active | BOOL | 启用状态 |
| last_sync_at | DATETIME | 最近同步时间 |
| created_at | DATETIME | 创建时间 |

### 5.2 Tableau 资产表 `tableau_assets`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| connection_id | INT | 关联连接 |
| asset_type | VARCHAR(16) | workbook / dashboard / view / datasource |
| tableau_id | VARCHAR(128) | Tableau 原始 ID |
| name | VARCHAR(256) | 资产名称 |
| project_name | VARCHAR(256) | 所属项目 |
| description | TEXT | 描述 |
| owner_name | VARCHAR(128) | 创建者 |
| thumbnail_url | VARCHAR(512) | 缩略图 URL |
| content_url | VARCHAR(512) | Tableau 访问 URL |
| raw_metadata | TEXT | 原始 JSON（按需存储） |
| synced_at | DATETIME | 同步时间 |

### 5.3 资产关联表 `tableau_asset_datasources`

| 字段 | 类型 | 说明 |
|------|------|------|
| asset_id | INT | Tableau 资产 ID |
| datasource_name | VARCHAR(256) | 数据源名称 |
| datasource_type | VARCHAR(64) | 数据源类型 |

---

## 6. API 设计

> 所有资产相关 API 均以 `connection_id`（即 Site）为隔离边界，不会跨 Site 混查。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/tableau/connections | 连接列表（admin/data_admin） |
| POST | /api/tableau/connections | 添加连接 |
| PUT | /api/tableau/connections/{id} | 编辑连接 |
| DELETE | /api/tableau/connections/{id} | 删除连接 |
| POST | /api/tableau/connections/{id}/test | 测试连接 |
| POST | /api/tableau/connections/{id}/sync | 触发同步 |
| GET | /api/tableau/assets | 资产列表（分页、筛选，按 connection_id） |
| GET | /api/tableau/assets/{id} | 资产详情 |
| GET | /api/tableau/assets/search?q= | 搜索资产（跨 Site 可选） |
| GET | /api/tableau/projects | 项目列表（树形，按 connection_id） |

---

## 7. 技术实现要点

### 7.1 Tableau API

使用 Tableau Server REST API：
- 认证：Personal Access Token（替代用户名密码）
- API Version：支持 3.14+（当前主流版本）
- 依赖库：`tableauserverclient`（Python）

### 7.2 同步策略

- 增量同步：基于 `updatedAt` 字段，只拉取有变化的资产
- 软删除：资产在 Tableau 侧删除时，在 Mulan 侧标记 `is_deleted`
- 限流控制：避免高频请求触发 Tableau API 限流

### 7.3 密码加密

与数据源模块一致，使用 `cryptography.fernet.Fernet` 对 Token Secret 加密存储。

### 7.4 前端状态管理

- Tableau 连接和资产数据使用 React Query 管理（缓存 + 轮询）
- 资产列表支持虚拟滚动（大列表优化）

---

## 8. 优先级排序

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | Tableau 连接配置 + 连接测试 | 模块基础 |
| P0 | Workbooks + Views 资产同步 | 核心能力 |
| P0 | 资产浏览列表（按项目分类） | 基础体验 |
| P1 | 全文搜索 | 提升检索效率 |
| P1 | 报表详情 + 数据源关联 | 资产理解 |
| P2 | 定时同步任务 | 工程化 |
| P2 | 同步日志查看 | 可观测性 |
| P3 | AI 解读摘要（依赖 LLM 接入） | 增值能力 |

---

## 9. 验收标准

- [ ] 管理员可配置 Tableau Server 连接（Token 认证）
- [ ] 可以测试连接，失败显示具体错误
- [ ] 可以触发同步，Workbooks / Views 出现在资产列表
- [ ] 非管理员用户可以看到同步后的 Tableau 资产
- [ ] 可以按项目筛选资产列表
- [ ] Token Secret 在数据库中加密存储
- [ ] 同步失败有错误日志可查

---

## 10. 与现有模块的关系

| 已有能力 | 如何复用/整合 |
|----------|--------------|
| 数据源管理（Phase 2） | 复用 `DataSource` 加密存储模式 |
| 用户认证 | 直接复用 Session/Cookie 体系 |
| 权限系统 | 数据分析师（analyst）角色可看 Tableau 资产 |
| DDL 检查 | Tableau 资产关联数据源 → 可跳转 DDL 检查 |
