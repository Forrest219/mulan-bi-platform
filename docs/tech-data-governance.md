# 数据治理模块 - 技术设计方案

> 文档版本：v1.0
> 日期：2026-04-01
> 状态：草案
> 适用范围：数据仓库体检 + 数据质量监控

---

## 一、模块定位

| 模块 | 关注点 | 与现有能力的关系 |
|------|--------|-----------------|
| **数据仓库体检** | 数据库对象的结构健康度：命名合规、对象统计、存储趋势 | 复用 DDL 检查引擎逻辑，但改为直连数据库扫描 |
| **数据质量监控** | 数据内容的质量：空值率、重复率、波动异常、业务规则校验 | 继承规则配置能力，但扩展为数据执行层 |

两者是**不同的执行层面**：
- 体检 → 跑在 DDL/Schema 层（结构层）
- 质量监控 → 跑在 Data 层（内容层）

---

## 二、数据仓库体检

### 2.1 能力范围

对目标数据库执行 Schema 扫描，输出健康度报告：

| 检查项 | 说明 |
|--------|------|
| 命名合规率 | 表名/字段名符合规则配置的比例 |
| 缺失注释 | 表或字段缺少 COMMENT 的情况 |
| 缺失主键 | 没有 PRIMARY KEY 的表 |
| 大表预警 | 记录数超过阈值的大表 |
| 无更新字段 | 没有 update_time / modified_at 的表 |
| 数据类型问题 | 金额字段类型不符合规范（e.g., 用 FLOAT 而非 DECIMAL） |

### 2.2 后端接口

#### POST /api/governance/health/scan

对指定数据源发起体检扫描。

**请求体**：

```json
{
  "datasource_id": 1,
  "db_name": "analytics_db",
  "options": {
    "check_naming": true,
    "check_comment": true,
    "check_primary_key": true,
    "check_update_field": true,
    "check_data_type": true,
    "large_table_threshold": 1000000
  }
}
```

**响应体**：

```json
{
  "scan_id": "scan_20260401_001",
  "datasource_id": 1,
  "db_name": "analytics_db",
  "scanned_at": "2026-04-01T10:00:00Z",
  "duration_sec": 12,
  "summary": {
    "total_tables": 156,
    "total_fields": 1847,
    "pass_rate": 0.78,
    "pass_count": 122,
    "fail_count": 34,
    "issue_by_type": {
      "naming": 8,
      "comment": 15,
      "primary_key": 5,
      "update_field": 12,
      "data_type": 2
    }
  },
  "score": 82,
  "issues": [
    {
      "object_type": "table",
      "object_name": "orders",
      "issue_type": "primary_key",
      "severity": "high",
      "description": "表 orders 缺少主键",
      "suggestion": "建议添加自增主键 id"
    }
  ]
}
```

#### GET /api/governance/health/scans

查询历史体检记录。

#### GET /api/governance/health/scans/{scan_id}

获取指定体检报告详情。

### 2.3 体检执行链路

```
POST /scan
    ↓
根据 datasource_id 读取连接配置
    ↓
连接数据库（读 schema，不读写数据）
    ↓
遍历所有表 + 字段，执行规则检查
    ↓
保存体检结果到数据库
    ↓
返回结构化报告
```

### 2.4 复用 DDL 检查引擎

`modules/ddl_check_engine` 的规则（`rules.py`）可直接复用，差异在于：

| 维度 | DDL 检查引擎（现有） | 数据仓库体检（新增） |
|------|---------------------|-------------------|
| 输入 | DDL 文本字符串 | 直连数据库扫描 |
| 执行方式 | 解析文本 | SQL 查询 schema |
| 规则复用 | 100% | 表命名规则、字段规则复用；主键、注释等需扩展 |

### 2.5 前端页面

`frontend/src/pages/data-governance/health/page.tsx`

布局建议：

```
数据仓库体检
├── 体检概览（统计卡片：总分、问题数、问题类型分布）
├── 一键扫描按钮
├── 问题列表（可筛选：severity / issue_type / database）
└── 历史记录 Tab
```

---

## 三、数据质量监控

### 3.1 能力范围

对指定表字段配置质量规则，定时执行并记录结果：

| 规则类型 | 说明 | 示例 |
|---------|------|------|
| 空值率 | 字段空值占比 | `order_id 空值率 < 1%` |
| 重复率 | 字段值重复占比 | `phone 重复率 < 5%` |
| 枚举校验 | 字段值必须在预设列表 | `status in (0,1,2,3)` |
| 波动检测 | 与历史均值偏差超阈值 | `日活与近7日均值偏差 < 20%` |
| 业务规则 | 自定义 SQL 表达式 | `销售额 >= 0` |

### 3.2 规则配置复用

现有**规则配置**页面（`/rule-config`）已维护命名规则，质量监控复用同一张表，但扩展规则类型：

```
规则配置（扩展）
├── DDL 命名规则（现有）
│     ├── 表名规则
│     └── 字段规则
└── 数据质量规则（新增）
      ├── 空值率规则
      ├── 重复率规则
      ├── 枚举校验规则
      ├── 波动检测规则
      └── 自定义 SQL 规则
```

数据库表设计建议扩展 `rules` 表：

| 新增字段 | 说明 |
|---------|------|
| `rule_type` | `ddl_naming` / `data_quality` |
| `target_type` | `table` / `field` |
| `check_target` | 针对哪个表/字段 |
| `execution_mode` | `realtime` / `scheduled` |
| `threshold` | 阈值配置（JSON） |

### 3.3 后端接口

#### POST /api/governance/quality/rules

创建质量规则。

```json
{
  "name": "订单ID空值率检查",
  "datasource_id": 1,
  "db_name": "orders_db",
  "table_name": "orders",
  "field_name": "order_id",
  "rule_type": "null_rate",
  "operator": "lt",
  "threshold": 1.0,
  "severity": "high",
  "execution_mode": "scheduled",
  "cron": "0 2 * * *"
}
```

#### GET /api/governance/quality/rules

查询规则列表。

#### POST /api/governance/quality/run/{rule_id}

手动执行单条规则，返回即时结果。

```json
{
  "rule_id": 10,
  "executed_at": "2026-04-01T10:00:00Z",
  "result": "pass",
  "actual_value": 0.12,
  "threshold": 1.0,
  "message": "order_id 空值率 0.12%，低于阈值 1%，通过"
}
```

#### POST /api/governance/quality/run-all

对所有已配置规则执行一次检查（用于批量验证）。

#### GET /api/governance/quality/results

查询规则执行结果历史。

```json
{
  "results": [
    {
      "id": 1,
      "rule_id": 10,
      "rule_name": "订单ID空值率检查",
      "executed_at": "2026-04-01T02:00:00Z",
      "status": "pass",
      "actual_value": 0.12,
      "threshold": 1.0,
      "duration_ms": 234
    }
  ],
  "total": 100,
  "page": 1
}
```

#### GET /api/governance/quality/metrics

获取质量指标概览（对应现有数据库监控页的"质量指标"Tab）。

```json
{
  "avg_score": 87,
  "total_rules": 45,
  "pass_count": 38,
  "fail_count": 7,
  "trend": "up",
  "top_issues": [
    { "rule_name": "phone空值率", "fail_count": 3, "latest_value": 8.5 }
  ]
}
```

### 3.4 定时执行

质量规则支持 Cron 表达式配置定时执行，与 Tableau 定时同步复用同一调度机制。

调度器扩展 `_sync_scheduler()`，新增 `_run_quality_checks()` 方法。

### 3.5 前端页面

复用现有 `/database-monitor` 路由，拆分内容：

```
/database-monitor  →  重命名为  /data-health
  ├── /data-health/report     → 数据仓库体检（体检报告 + 扫描）
  └── /data-health/quality   → 数据质量监控（规则配置 + 执行结果）
```

或新增独立路由：

```
/data-health/report    → 数据仓库体检
/data-health/quality    → 数据质量监控（规则配置）
/data-health/results   → 监控结果历史
```

### 3.6 与现有数据库监控页面的关系

现有 `database-monitor` 页面是 Mock 数据，质量监控 V1 可以：

**方案 A（推荐）**：将 `database-monitor` 改造为真实数据质量监控，保留数据源管理 Tab，替换质量指标 Tab 为真实数据

**方案 B**：保持 `database-monitor` 不变，新建 `data-health/quality` 页面

---

## 四、模块依赖

| 依赖 | 说明 |
|------|------|
| 数据源连接配置 | 需要能连接 MySQL/SQL Server 等数据库读取 Schema |
| 规则配置（复用） | `rules` 表扩展 `rule_type` |
| 定时调度（复用） | 复用现有的调度器框架 |
| 语义维护（参考） | 表字段元数据可辅助体检和质量规则配置 |

---

## 五、实施建议

### V1 优先级

1. **数据仓库体检** — 先做，单一数据源扫描
2. **质量规则 CRUD** — 创建规则、查看规则列表
3. **手动执行规则** — 点击执行，查看结果
4. **定时执行** — Cron 配置 + 调度器集成

V1 不做：
- 波动检测（需要历史数据积累）
- 多数据源联合质量检查

---

## 六、已确认事项

1. **体检扫描支持数据库类型**：MySQL、SQL Server、Hive、StarRocks
2. **质量监控数据源**：独立配置，与 Tableau 连接分开
3. **历史数据保留时间**：60 天（自动清理过期记录）
