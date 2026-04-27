# DDL 合规检查技术规格书

| 属性 | 值 |
|------|------|
| 版本 | v1.1 |
| 日期 | 2026-04-06 |
| 状态 | Draft v1.1 |
| 作者 | Mulan BI Team |

---

## 目录

1. [概述](#1-概述)
2. [数据模型](#2-数据模型)
3. [API 设计](#3-api-设计)
4. [业务逻辑](#4-业务逻辑)
5. [错误码](#5-错误码)
6. [安全](#6-安全)
7. [集成点](#7-集成点)
8. [时序图](#8-时序图)
9. [测试策略](#9-测试策略)
10. [开放问题](#10-开放问题)

---

## 1. 概述

### 1.1 背景

DDL 合规检查模块为 Mulan BI 平台的核心数据治理能力之一。该模块接收用户提交的 CREATE TABLE DDL 语句，基于可配置的规则引擎进行自动化检查，输出合规评分、问题列表和可执行性判定，帮助 BI 团队在建表阶段即发现并纠正命名、类型、结构等方面的规范性问题。

### 1.2 目标

- 提供在线 DDL 合规检查 API，支持 MySQL / SQL Server 两种数据库类型
- 通过可量化的评分体系（0-100）衡量 DDL 规范程度，支持按业务场景（ODS/DWD/ADS）差异化配置
- 规则可配置，支持内置规则与自定义规则的 CRUD 管理
- 扫描结果可审计，支持历史查询
- 通过正则 + AST 双引擎保障解析覆盖率（正则优先，复杂场景自动降级到 sqlglot/sqlparse）
- 全库扫描支持任务拆分并发执行（Celery 分布式）

### 1.3 范围

| 包含 | 不包含 |
|------|--------|
| CREATE TABLE 语句在线检查 | ALTER TABLE / DROP TABLE 检查 |
| 规则 CRUD 管理 API | DDL 自动修复/改写 |
| 运行时规则引擎（从数据库加载） | 基于 rules.yaml 的静态规则引擎（仅作 Seed） |
| 数据库连接扫描全库表 | 跨库联合检查 |
| 评分与可执行性判定 | 与 CI/CD Pipeline 集成 |
| 规则变更审计日志（bi_rule_change_logs） | — |

### 1.4 关键模块

| 模块 | 路径 | 职责 |
|------|------|------|
| DDL Check API | `backend/app/api/ddl.py` | HTTP 接口层 |
| Rules Config API | `backend/app/api/rules.py` | 规则 CRUD 接口层 |
| DDLParser | `backend/services/ddl_checker/parser.py` | SQL 解析，提取 TableInfo（正则优先 + AST 回退） |
| DDLValidator | `backend/services/ddl_checker/validator.py` | 规则匹配与违规检测 |
| RuleCache | `backend/services/ddl_checker/cache.py` | 规则运行时缓存（Redis） |
| DDLScanner | `backend/services/ddl_checker/scanner.py` | 全库扫描编排器 |
| TaskSplitter | `backend/services/ddl_checker/task_splitter.py` | 扫描任务拆分（Celery）— **未实现，scanner.py 当前为同步迭代** |
| RulesSeedService | `backend/app/api/rules.py` (模块级 `seed_defaults`) | 种子文件同步（幂等 UPSERT） |
| RuleConfig Model | `backend/services/rules/models.py` | 规则持久化 ORM |
| DDL Check Engine | `modules/ddl_check_engine/` | 独立可分发的检查引擎模块 |
| 规则配置文件 | `config/rules.yaml` | 静态规则定义（Seed） |

---

## 2. 数据模型

### 2.1 核心数据表

#### bi_rule_configs（规则配置表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO_INCREMENT | 自增主键 |
| rule_id | VARCHAR(64) | UNIQUE, NOT NULL, INDEX | 规则标识符，如 RULE_001 |
| name | VARCHAR(256) | NOT NULL | 规则名称 |
| description | VARCHAR(1024) | NOT NULL, DEFAULT '' | 规则描述 |
| level | VARCHAR(32) | NOT NULL, DEFAULT 'MEDIUM' | 风险级别：HIGH / MEDIUM / LOW |
| category | VARCHAR(64) | NOT NULL, DEFAULT 'general' | 分类：Naming / Structure / Type / Index / Audit |
| db_type | VARCHAR(32) | NOT NULL, DEFAULT 'MySQL' | 适用数据库类型 |
| suggestion | VARCHAR(1024) | NOT NULL, DEFAULT '' | 修复建议 |
| enabled | BOOLEAN | NOT NULL, DEFAULT TRUE | 是否启用 |
| is_custom | BOOLEAN | NOT NULL, DEFAULT FALSE | 是否为自定义规则 |
| **is_modified_by_user** | **BOOLEAN** | **NOT NULL, DEFAULT FALSE** | **用户是否手动修改过（Seed 幂等性保护）** |
| **scene_type** | **VARCHAR(16)** | **NOT NULL, DEFAULT 'ALL'** | **适用场景：ODS / DWD / ADS / ALL** |
| config_json | JSONB | NOT NULL, DEFAULT '{}' | 规则扩展参数（含场景化扣分权重配置） |
| created_at | DATETIME | NOT NULL, SERVER_DEFAULT now() | 创建时间 |
| updated_at | DATETIME | NOT NULL, SERVER_DEFAULT now(), ON UPDATE now() | 更新时间 |

#### bi_scan_logs（扫描日志表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO_INCREMENT | 自增主键 |
| **trace_id** | **VARCHAR(64)** | **NOT NULL, INDEX** | **追踪 ID（关联日志系统）** |
| database_name | VARCHAR(128) | NOT NULL | 扫描的数据库名 |
| db_type | VARCHAR(32) | NOT NULL | 数据库类型 |
| table_count | INTEGER | NOT NULL | 扫描表数量 |
| total_violations | INTEGER | NOT NULL | 违规总数 |
| error_count | INTEGER | NOT NULL | High 级别数量 |
| warning_count | INTEGER | NOT NULL | Medium 级别数量 |
| info_count | INTEGER | NOT NULL | Low 级别数量 |
| duration_seconds | FLOAT | NOT NULL | 扫描耗时（秒） |
| status | VARCHAR(32) | NOT NULL | 扫描状态：completed / failed |
| error_message | TEXT | NULL | 失败原因 |
| results | JSONB | NULL | 原始扫描结果（含敏感列名） |
| **results_masked** | **JSONB** | **NULL** | **脱敏后扫描结果（敏感关键词已处理）** |
| created_at | DATETIME | NOT NULL, SERVER_DEFAULT now() | 创建时间 |

#### bi_rule_change_logs（规则变更审计表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO_INCREMENT | 自增主键 |
| rule_id | VARCHAR(64) | NOT NULL | 关联规则 ID |
| action | VARCHAR(32) | NOT NULL | 操作类型：create / toggle / delete |
| old_value | JSONB | NULL | 变更前快照 |
| new_value | JSONB | NULL | 变更后快照 |
| operator | VARCHAR(128) | NOT NULL | 操作人 |
| created_at | DATETIME | NOT NULL, SERVER_DEFAULT now() | 操作时间 |

### 2.2 ER 关系图

```
bi_rule_configs 1───* bi_rule_change_logs
       |                    (rule_id)
       |
       |  (规则应用于检查)
       |
bi_scan_logs
  (独立，存储扫描结果快照)
```

### 2.3 索引策略

| 表 | 索引 | 类型 | 用途 |
|------|------|------|------|
| `bi_rule_configs` | `rule_id` | UNIQUE | 按规则 ID 精确查找 + Seed 幂等 UPSERT |
| `bi_rule_configs` | `(db_type, enabled)` | 普通 | 按数据库类型过滤活跃规则（RuleCache 加载） |
| `bi_scan_logs` | `trace_id` | 普通 | 日志系统关联追踪 |
| `bi_scan_logs` | `created_at` | 普通 | 按时间范围查询扫描历史 |
| `bi_rule_change_logs` | `rule_id` | 普通 | 按规则查看变更历史 |

### 2.4 迁移说明

- `bi_rule_configs` 和 `bi_scan_logs` 已通过 Alembic 迁移建表
- `is_modified_by_user` 和 `scene_type` 为 v1.1 新增列，需 Alembic 增量迁移
- `results_masked` 列已在 spec 中定义，代码中尚未实现脱敏写入逻辑

### 2.5 内存数据模型

#### TableInfo

```python
class TableInfo:
    name: str               # 表名
    columns: List[ColumnInfo]  # 列列表
    indexes: List[IndexInfo]   # 索引列表
    comment: str            # 表注释
    database: str           # 所属数据库
```

#### ColumnInfo

```python
class ColumnInfo:
    name: str               # 列名
    data_type: str          # 数据类型（大写）
    nullable: bool          # 是否可空
    default: Optional[str]  # 默认值
    comment: str            # 注释
    is_primary_key: bool    # 是否主键
    is_foreign_key: bool    # 是否外键
```

#### IndexInfo

```python
class IndexInfo:
    name: str               # 索引名
    columns: List[str]      # 索引列
    is_unique: bool         # 是否唯一
    is_primary: bool        # 是否主键索引
```

#### Violation

```python
class Violation:
    level: ViolationLevel   # ERROR / WARNING / INFO
    rule_name: str          # 规则名
    message: str            # 违规描述
    table_name: str         # 表名
    column_name: str        # 列名（可选）
    suggestion: str         # 修复建议
```

---

## 3. API 设计

### 3.1 DDL 检查 API（/api/ddl）

#### POST /api/ddl/check

在线检查 DDL 语句合规性。

**认证要求**: 任意已认证用户

**请求体**:

```json
{
  "ddl_text": "CREATE TABLE dim_user (\n  id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键',\n  user_name VARCHAR(128) NOT NULL COMMENT '用户名',\n  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',\n  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间',\n  is_deleted TINYINT DEFAULT 0 COMMENT '软删除标记'\n) COMMENT='用户维度表';",
  "db_type": "mysql"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ddl_text | string | 是 | CREATE TABLE SQL 语句，**最大长度 64KB**，超长返回 `DDL_004` |
| db_type | string | 否 | 数据库类型，默认 "mysql" |
| scene_type | string | 否 | 业务场景：`ODS` / `DWD` / `ADS` / `ALL`，默认 `ALL` |

**响应体**（统一响应结构）:

```json
{
  "code": "DDL_000",
  "message": "检查完成",
  "trace_id": "a1b2c3d4-e5f6-7890",
  "data": {
    "passed": true,
    "score": 85,
    "summary": {
      "High": 0,
      "Medium": 1,
      "Low": 2
    },
    "issues": [
      {
        "rule_id": "data_type",
        "risk_level": "Medium",
        "object_type": "column",
        "object_name": "status",
        "description": "列 'status' 使用不推荐的数据类型 TINYINT",
        "suggestion": "建议使用 BIGINT, DECIMAL, VARCHAR, TEXT, DATETIME, DATE, BOOLEAN 之一"
      }
    ],
    "executable": true,
    "parse_mode": "regex",
    "scene_type": "ODS"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| code | string | 业务错误码，DDL_000=成功，DDL_xxx=业务错误 |
| message | string | 人类可读的消息 |
| trace_id | string | 追踪 ID，贯穿日志系统 |
| data.passed | boolean | 是否通过（executable=true 且 score >= 80） |
| data.score | integer | 合规评分 0-100 |
| data.summary | object | 按风险级别汇总：High / Medium / Low |
| data.issues | array | 违规问题列表 |
| data.executable | boolean | 是否可执行（score >= 60 且无 High 问题） |
| data.parse_mode | string | 解析模式：`regex`（正则）或 `ast`（AST 回退） |
| data.scene_type | string | 使用的业务场景 |

#### GET /api/ddl/rules

获取当前从 rules.yaml 加载的活跃规则列表。

**认证要求**: 任意已认证用户

**响应体**:

```json
{
  "rules": [
    {"rule_id": "RULE_001", "name": "表命名规范", "risk_level": "High"},
    {"rule_id": "RULE_002", "name": "字段命名规范", "risk_level": "High"}
  ],
  "total": 8
}
```

---

### 3.2 规则管理 API（/api/rules）

#### GET /api/rules/

获取持久化规则列表，支持筛选。

**认证要求**: 任意已认证用户

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| category | string | 否 | 分类过滤：Naming / Structure / Type / Index / Audit / ALL |
| level | string | 否 | 级别过滤：HIGH / MEDIUM / LOW / ALL |
| db_type | string | 否 | 数据库类型过滤：MySQL / SQL Server / ALL |
| status | string | 否 | 状态过滤：enabled / disabled / ALL |

**响应体**:

```json
{
  "rules": [
    {
      "id": "RULE_001",
      "name": "表命名规范",
      "description": "表名必须以小写字母开头，支持小写字母、数字、下划线",
      "level": "HIGH",
      "category": "Naming",
      "db_type": "MySQL",
      "suggestion": "表名格式：dim_xxx, fact_xxx, ods_xxx",
      "status": "enabled",
      "built_in": true,
      "config_json": {}
    }
  ],
  "total": 12,
  "enabled_count": 10,
  "disabled_count": 2
}
```

#### POST /api/rules/

创建自定义规则。

**认证要求**: admin 或 data_admin 角色

**请求体**:

```json
{
  "id": "RULE_100",
  "name": "自定义字段长度限制",
  "level": "MEDIUM",
  "category": "Type",
  "description": "VARCHAR 字段长度不得超过 4000",
  "suggestion": "将 VARCHAR 长度限制在 4000 以内，超长文本使用 TEXT",
  "db_type": "MySQL",
  "built_in": false,
  "status": "enabled"
}
```

**响应体**:

```json
{
  "rule": { "...规则对象..." },
  "message": "自定义规则创建成功"
}
```

**后置操作**: 创建成功后，异步写入 `bi_rule_change_logs`：
```json
{
  "rule_id": "<新规则ID>",
  "action": "create",
  "old_value": null,
  "new_value": "<规则完整快照>",
  "operator": "<当前用户名>"
}
```

**错误**: 409 Conflict — 规则 ID 已存在

#### PUT /api/rules/{rule_id}/toggle

切换规则启用/禁用状态。

**认证要求**: admin 或 data_admin 角色

**路径参数**: `rule_id` — 规则标识符

**响应体**:

```json
{
  "rule_id": "RULE_001",
  "status": "disabled",
  "message": "规则已禁用"
}
```

**后置操作**: 切换成功后，异步写入 `bi_rule_change_logs`：
```json
{
  "rule_id": "<rule_id>",
  "action": "toggle",
  "old_value": "<变更前快照>",
  "new_value": "<变更后快照>",
  "operator": "<当前用户名>"
}
```

**错误**: 404 Not Found — 规则不存在

#### DELETE /api/rules/{rule_id}

删除自定义规则（内置规则不可删除）。

**认证要求**: admin 或 data_admin 角色

**路径参数**: `rule_id` — 规则标识符

**响应体**:

```json
{
  "message": "规则删除成功"
}
```

**后置操作**: 删除成功后，异步写入 `bi_rule_change_logs`：
```json
{
  "rule_id": "<rule_id>",
  "action": "delete",
  "old_value": "<删除前快照>",
  "new_value": null,
  "operator": "<当前用户名>"
}
```

**错误**:
- 404 Not Found — 规则不存在
- 403 Forbidden — 无法删除内置规则

#### POST /api/rules/test

Dry Run：测试新规则对指定 DDL 的拦截效果（不保存规则）。

**认证要求**: admin 或 data_admin 角色

**请求体**:

```json
{
  "rule": {
    "rule_id": "RULE_TEST",
    "name": "测试规则",
    "level": "HIGH",
    "pattern": "^RULE_.*$",
    "check_target": "table_name",
    "enabled": true
  },
  "ddl_text": "CREATE TABLE rule_test_table (\n  id BIGINT PRIMARY KEY\n);",
  "db_type": "mysql"
}
```

**响应体**:

```json
{
  "code": "DDL_000",
  "message": "Dry Run 完成",
  "trace_id": "test-123-456",
  "data": {
    "rule_id": "RULE_TEST",
    "ddl_text": "CREATE TABLE rule_test_table (...)",
    "hit": true,
    "violations": [
      {
        "level": "HIGH",
        "message": "表名 'rule_test_table' 不符合正则 ^RULE_.*$",
        "suggestion": "表名必须以 RULE_ 开头"
      }
    ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| rule | object | 待测试的规则配置 |
| ddl_text | string | 测试用 DDL 文本 |
| db_type | string | 数据库类型 |

**用途**: 管理员修改规则正则模式后，在不保存的情况下预验证规则是否按预期拦截/放行。

---

## 4. 业务逻辑

### 4.1 DDL 检查处理流程

```
用户提交 DDL 文本
       |
       v
  DDLParser.parse_create_table(sql)
       |
       |--- 正则解析优先 ---
       |   若关键元数据（表名/列名）为空且 SQL 合法
       |         |
       |         v
       |   自动降级 AST 解析（sqlglot/sqlparse）
       |         |
       |--- 解析失败 ---> 返回 score=0, DDL_001
       |
       v
  TableInfo (表名、列列表、索引列表)
       |
       v
  RuleCache.get_active_rules(scene_type)
       |
       |--- Redis 缓存未命中 ---> 从 bi_rule_configs 加载 + 写入缓存
       |
       v
  DDLValidator.validate_table(table_info, scene_type)
       |
       |--- TableValidator (表级检查)
       |       |-- _check_naming()       表命名规范
       |       |-- _check_comment()      表注释规范（含 COMMENT='xxx' 解析支持）
       |       |-- _check_primary_key()  主键规范
       |       |-- _check_timestamp_fields()  时间戳规范
       |       |-- _check_soft_delete()  软删除规范
       |       |-- _check_indexes()      索引规范
       |
       |--- ColumnValidator (列级检查)
       |       |-- _check_naming()       列命名规范
       |       |-- _check_data_type()    数据类型规范
       |       |-- _check_comment()      列注释规范
       |
       v
  List[Violation]
       |
       v
  _calculate_score(violations, scene_type)
       |
       v
  DDLCheckResponse (score, passed, executable, issues, parse_mode, scene_type)
```

#### 解析器双引擎策略

DDLParser 采用正则优先 + AST 回退的双引擎策略：

1. **正则解析**（优先）：保持轻量，处理标准 CREATE TABLE 语句
2. **AST 解析**（降级）：当正则提取的关键元数据（表名、列名）为空且 SQL 语法合法时，自动调用 `sqlglot` 或 `sqlparse` 进行完整语法树解析

| 解析模式 | 触发条件 | 优点 |
|----------|----------|------|
| `regex` | 正则提取到表名/列名 | 性能优，轻量 |
| `ast` | 正则提取失败但 SQL 合法 | 覆盖复杂语法 |

#### 规则缓存策略

`RuleCache` 使用 Redis 作为缓存层：

- **缓存键**：`ddl:rules:{scene_type}:{db_type}`
- **TTL**：300 秒（5 分钟）
- **失效机制**：
  - API 层变更规则（toggle/create/delete）时，主动 `DEL` 对应缓存键
  - `functools.lru_cache` 不适用于请求级 DDLValidator 实例，**禁止使用**

#### API 层缓存失效

```
POST /api/rules/        -> 删除 {ALL} 缓存键
PUT  /api/rules/{id}/toggle -> 删除 {ALL} + {ODS/DWD/ADS} 缓存键
DELETE /api/rules/{id}  -> 删除 {ALL} 缓存键
```

### 4.2 评分算法

起始分值为 100 分，按违规级别逐项扣分：

| 违规级别 | 映射关系 | 默认扣分 |
|----------|----------|----------|
| High（error） | ViolationLevel.ERROR | -20 分/项 |
| Medium（warning） | ViolationLevel.WARNING | -5 分/项 |
| Low（info） | ViolationLevel.INFO | -1 分/项 |

**边界约束**:
- 最低分: 0
- 最高分: 100

**场景化评分（scene_type）**:

不同业务场景可以设置不同的扣分权重，通过 `config_json` 配置：

```json
{
  "scene_weights": {
    "ODS": { "high": -15, "medium": -3, "low": -1 },
    "DWD": { "high": -20, "medium": -5, "low": -1 },
    "ADS": { "high": -25, "medium": -8, "low": -2 }
  }
}
```

| 场景 | 特点 | 建议权重 |
|------|------|----------|
| ODS（原始层） | 数据刚入库，规范要求相对宽松 | high=-15, medium=-3 |
| DWD（明细层） | 标准数仓层，严格规范 | high=-20, medium=-5（默认） |
| ADS（应用层） | 直接面向业务，严苛要求 | high=-25, medium=-8 |

**输入安全约束**:
- `ddl_text` 最大长度限制为 **64KB**（65,536 字节），超长输入直接返回 `DDL_004` 错误
- **ReDoS 防护**：正则匹配单次超时设置为 **200ms**，超时后立即终止并返回 `DDL_005` 错误

**判定逻辑**:

```python
scene_weights = config_json.get("scene_weights", {}).get(scene_type, DEFAULT_WEIGHTS)
high_penalty = scene_weights.get("high", -20)
medium_penalty = scene_weights.get("medium", -5)
low_penalty = scene_weights.get("low", -1)

score = 100 + (high_count * high_penalty) + (medium_count * medium_penalty) + (low_count * low_penalty)
score = max(0, min(100, score))

executable = score >= 60 AND high_count == 0
passed     = executable AND score >= 80
```

| 条件 | executable | passed |
|------|-----------|--------|
| score=95, High=0 | true | true |
| score=75, High=0 | true | false |
| score=85, High=1 | false | false |
| score=50, High=0 | false | false |

### 4.3 规则分类与级别映射

| 规则类别 | rule_name | 风险级别 | 检查内容 |
|----------|-----------|----------|----------|
| 表命名规范 | table_naming | High | 正则匹配 `^[a-z][a-z0-9_]*$`，长度 <= 64，前缀白名单 |
| 字段命名规范 | column_naming | High | 正则匹配 `^[a-z][a-z0-9_]*$`，长度 <= 64，保留字检测 |
| 数据类型规范 | data_type | Medium | 不推荐类型（FLOAT, DOUBLE, TINYINT, SMALLINT）检测 |
| 主键规范 | primary_key | High | 必须包含主键 |
| 索引规范 | index | Medium | 单表索引数不超过 10 |
| 注释规范 | comment | Medium | 表和列必须包含注释 |
| 时间戳规范 | timestamp | High | 必须包含 create_time 和 update_time 字段 |
| 软删除规范 | soft_delete | Medium | 必须包含 is_deleted 字段 |

### 4.4 rules.yaml 配置结构

> ⚠️ **重要定位说明**：本文件的定位为**初始化种子文件 (Seed)**，仅在系统初次部署时用于向 `bi_rule_configs` 表写入内置规则。运行时规则引擎**必须**从数据库（`bi_rule_configs` 表，`enabled=true`）中加载规则配置。rules.yaml 文件本身不参与任何运行时决策。

#### Seed 幂等性策略

RulesSeedService 基于 `rule_id` 执行 **UPSERT**（Insert or Update on Conflict）：

```
for each rule in rules.yaml:
    if rule_id exists in bi_rule_configs:
        if is_modified_by_user == FALSE:
            UPDATE rule from rules.yaml
        else:
            SKIP (保留用户修改)
    else:
        INSERT new rule
        SET is_modified_by_user = FALSE
```

> 用户通过 API 修改过的规则，Seed 文件不会覆盖（`is_modified_by_user = TRUE` 时跳过）。

```yaml
table_naming:
  enabled: true
  pattern: "^[a-z][a-z0-9_]*$"
  max_length: 64
  prefix_whitelist: []    # 允许前缀，如 ["dim_", "fact_", "ods_"]

column_naming:
  enabled: true
  pattern: "^[a-z][a-z0-9_]*$"
  max_length: 64
  reserved_words: ["id", "create_time", "update_time", "creator", "updater", "is_deleted"]

data_type:
  enabled: true
  recommended_types: [BIGINT, DECIMAL, VARCHAR, TEXT, DATETIME, DATE, BOOLEAN]
  deprecated_types: [FLOAT, DOUBLE, TINYINT, SMALLINT]

primary_key:
  enabled: true
  require_primary_key: true
  primary_key_name_pattern: "pk_{table_name}"

index:
  enabled: true
  max_index_count_per_table: 10
  index_name_pattern: "idx_{table_name}_{column}"
  unique_index_name_pattern: "uk_{table_name}_{column}"

comment:
  enabled: true
  require_table_comment: true
  require_column_comment: true
  max_comment_length: 500

timestamp:
  enabled: true
  require_create_time: true
  require_update_time: true
  create_time_type: "DATETIME"
  update_time_type: "DATETIME"

soft_delete:
  enabled: true
  require_is_deleted: true
  is_deleted_type: "TINYINT"
  default_value: 0
```

### 4.5 DDL 解析能力

DDLParser 采用**正则优先 + AST 回退**双引擎策略，支持以下语法元素：

| 元素 | 正则解析 | AST 回退 |
|------|----------|----------|
| CREATE TABLE (IF NOT EXISTS) | 支持 | 支持 |
| 反引号/引号包裹的标识符 | 支持 | 支持 |
| 列定义（类型、NOT NULL、DEFAULT、COMMENT） | 支持 | 支持 |
| PRIMARY KEY（内联和独立声明） | 支持 | 支持 |
| INDEX / KEY | 支持 | 支持 |
| UNIQUE INDEX / KEY | 支持 | 支持 |
| FOREIGN KEY | 不支持（跳过） | 支持 |
| **表级 COMMENT** (`COMMENT='xxx'` 或 `COMMENT="xxx"`) | **支持** | 支持 |
| 分区定义 | 不支持 | 支持 |
| 复杂 DEFAULT 值（函数、表达式） | 有限支持 | **完整支持** |
| 复杂 CHECK 约束 | 不支持 | **完整支持** |

**回退触发条件**：正则提取到空表名/空列名且 SQL 语法合法时，自动降级 AST 解析。

**ReDoS 深度防护**：正则匹配时设置单次超时 200ms，超时则中断并尝试 AST 模式。

### 4.6 数据库连接扫描模式

DDLScanner 支持通过 DatabaseConnector 直连数据库执行全库扫描：

1. `connect_database(db_config)` — 建立**独立短连接池**
2. `scan_all_tables()` — **任务拆分模式**：只下发"扫描单表"任务到 Celery 队列，由分布式 Worker 并发执行
3. `scan_table(table_name)` — 扫描单表（Worker 执行单元）
4. `scan_sql(sql)` — 扫描 SQL 文本（不需要数据库连接）
5. 扫描完成后自动记录 bi_scan_logs

#### 任务拆分策略

当目标库表数量 ≥ 阈值（如 100 张）时，启用任务拆分：

```
scan_all_tables()
    |
    v
获取表名列表 [t1, t2, ..., t10000]
    |
    v
批量下发 Celery 任务：
  - scan_table_task.delay(t1)
  - scan_table_task.delay(t2)
  - ...
  （每个任务独立连接 + 独立规则缓存）
    |
    v
汇总任务收集结果 + 生成报告
```

#### 连接池精细化配置

| 连接类型 | 配置 | 说明 |
|----------|------|------|
| Mulan 平台连接池 | 全局 PG 连接池 | 管理自身元数据 |
| 目标库连接池 | **独立短连接池 + statement_timeout=30s** | 防止目标库慢查询耗尽连接 |

> ⚠️ **重要**：目标库连接必须使用**独立连接池**，不得复用 Mulan 平台连接池，避免因目标库问题影响平台自身稳定性。

---

## 5. 错误码

> ⚠️ **统一响应规范**：所有 API 响应统一使用 `{ "code": "...", "message": "...", "data": {...}, "trace_id": "..." }` 结构。HTTP 状态码仅用于区分网络层错误（404/500 等），业务错误统一使用 `DDL_xxx` 错误码。

| 错误码 | HTTP 状态码 | 说明 | 触发场景 |
|--------|------------|------|----------|
| DDL_000 | 200 | 成功 | 检查成功 |
| DDL_001 | 400 | DDL 语法无效 | DDLParser 无法解析提交的 SQL 语句 |
| DDL_002 | 404 | 规则不存在 | toggle/delete 操作时找不到指定 rule_id |
| DDL_003 | 400 | 规则配置无效 | 创建自定义规则时参数校验失败 |
| DDL_004 | 400 | 输入超长 | ddl_text 超过 64KB 限制 |
| **DDL_005** | **400** | **正则解析超时** | **单次正则匹配超时 200ms（ReDoS 深度防御）** |
| **DDL_006** | **400** | **规则 Dry Run 失败** | **POST /api/rules/test 验证失败** |
| DDL_409 | 409 | 规则 ID 冲突 | 创建自定义规则时 rule_id 已存在 |
| DDL_403 | 403 | 操作被拒绝 | 尝试删除内置规则 |

---

## 6. 安全

### 6.1 认证与授权

| 接口 | 最低权限 |
|------|----------|
| POST /api/ddl/check | 任意已认证用户（get_current_user） |
| GET /api/ddl/rules | 任意已认证用户（get_current_user） |
| GET /api/rules/ | 任意已认证用户（get_current_user） |
| POST /api/rules/ | admin 或 data_admin |
| PUT /api/rules/{id}/toggle | admin 或 data_admin |
| DELETE /api/rules/{id} | admin 或 data_admin |

### 6.2 输入安全

- **SQL 注入防护**: DDLParser 仅做正则解析，不执行提交的 SQL 语句，无注入风险
- **请求体大小**: `ddl_text` 最大长度限制为 **64KB**（65,536 字节），在 API 入口处截断并返回 `DDL_004` 错误
- **ReDoS 深度防护**:
  - 第一道防线：64KB 长度限制
  - 第二道防线：正则匹配**单次超时 200ms**（`signal.SIGALRM` 或 `multiprocessing` 进程超时），超时立即中断并降级 AST 模式，超时返回 `DDL_005`
  - 第三道防线：禁止使用用户传入的动态正则（所有正则来自 `config_json` 白名单）
- **rules.yaml 路径**: 硬编码为相对于项目根目录的固定路径，不接受用户输入的文件路径
- **敏感数据脱敏**: `bi_scan_logs.results_masked` 字段对命中敏感关键词（如 `phone`, `id_card`, `password`, `secret`）的列名进行脱敏处理

### 6.3 数据库连接安全

- DatabaseConnector 连接信息不通过 API 暴露
- 数据库连接凭据应通过环境变量或加密配置注入
- 扫描操作仅执行 SELECT 级别的元数据查询
- **目标库连接隔离**：DDLScanner 直连目标库时，必须使用**独立短连接池**（不得复用 Mulan 平台连接池），并强制设置 `statement_timeout=30000`（30 秒），防止目标库慢查询耗尽平台连接资源

### 6.4 审计

- 规则变更操作应记录到 bi_rule_change_logs，包含操作人、操作类型、变更前后快照
- 扫描操作记录到 bi_scan_logs，包含结果和耗时
- **审计可靠性**：
  - 关键规则变更（`delete`、`disable`）必须在**同一数据库事务内同步写入** `bi_rule_change_logs`，不允许使用 `BackgroundTasks`（进程崩溃会丢失）
  - 一般规则变更（`create`、`toggle`）可使用 Celery 任务队列（利用其重试机制确保审计记录存在）
  - 所有 API 响应包含 `trace_id`，贯穿日志系统便于定位问题

---

## 7. 集成点

### 7.1 内部集成

| 集成目标 | 方式 | 说明 |
|----------|------|------|
| 认证模块 | FastAPI Depends | 通过 get_current_user / require_roles 依赖注入 |
| PostgreSQL | SQLAlchemy ORM | bi_rule_configs / bi_scan_logs / bi_rule_change_logs 表操作 |
| Redis | 规则缓存 | 运行时规则缓存（TTL 300s），API 层触发失效 |
| Celery | 任务队列 | 全库扫描任务拆分 + 重试机制（审计日志保障） |
| rules.yaml | 文件读取 | **仅在初始化时读取一次**作为内置规则种子数据；**运行时规则从数据库加载** |
| 前端 DDL 检查页面 | REST API | /api/ddl/check 接口 |
| 前端规则管理页面 | REST API | /api/rules/ CRUD 接口 |
| 前端 DDL 暂存区 | 前端本地存储 | 记录上次检查的 DDL 文本，支持 Diff 高亮对比 |

### 7.2 外部集成

| 集成目标 | 方式 | 说明 |
|----------|------|------|
| 目标数据库（MySQL 等） | DatabaseConnector | 全库扫描模式，通过 SQLAlchemy 反射读取元数据 |
| 报告导出 | ReportGenerator | 支持 HTML / JSON 格式导出 |

### 7.3 模块间依赖

```
app/api/ddl.py
    |--- services/ddl_checker/parser.py   (DDLParser)
    |--- services/ddl_checker/validator.py (DDLValidator) ← 从数据库加载规则，非 rules.yaml
    |--- app/core/dependencies.py         (get_current_user)
    |--- bi_rule_configs 表              (运行时规则来源)

app/api/rules.py
    |--- services/rules/models.py         (RuleConfigDatabase)
    |--- app/core/dependencies.py         (get_current_user, require_roles)
    |--- bi_rule_change_logs             (审计日志写入)

services/ddl_checker/scanner.py
    |--- services/ddl_checker/connector.py (DatabaseConnector)
    |--- services/ddl_checker/parser.py    (DDLParser)
    |--- services/ddl_checker/validator.py (DDLValidator)
    |--- services/ddl_checker/reporter.py  (ReportGenerator)
```

---

## 8. 时序图

### 8.1 DDL 在线检查流程

```
用户(前端)          API Layer           DDLParser         DDLValidator        rules.yaml
   |                   |                   |                   |                   |
   |-- POST /check --> |                   |                   |                   |
   |   {ddl_text}      |                   |                   |                   |
   |                   |-- parse_create    |                   |                   |
   |                   |   _table(sql) --> |                   |                   |
   |                   |                   |-- 正则提取表名 ---|                   |
   |                   |                   |-- 正则提取列定义 -|                   |
   |                   |                   |-- 正则提取索引 ---|                   |
   |                   |<- TableInfo ------|                   |                   |
   |                   |                   |                   |                   |
   |                   |    [解析失败时直接返回 score=0]       |                   |
   |                   |                   |                   |                   |
   |                   |-- validate_table(table_info) ------> |                   |
   |                   |                   |                   |-- 加载配置 -----> |
   |                   |                   |                   |<- config ---------|
   |                   |                   |                   |                   |
   |                   |                   |                   |-- 表命名检查      |
   |                   |                   |                   |-- 主键检查        |
   |                   |                   |                   |-- 时间戳检查      |
   |                   |                   |                   |-- 注释检查        |
   |                   |                   |                   |-- 软删除检查      |
   |                   |                   |                   |-- 索引检查        |
   |                   |                   |                   |-- 列命名检查      |
   |                   |                   |                   |-- 数据类型检查    |
   |                   |                   |                   |-- 列注释检查      |
   |                   |<- List[Violation] ------------------|                   |
   |                   |                   |                   |                   |
   |                   |-- _calculate_score(violations)        |                   |
   |                   |-- 判定 executable / passed            |                   |
   |                   |                   |                   |                   |
   |<- DDLCheckResponse|                   |                   |                   |
   |   {score, issues} |                   |                   |                   |
```

### 8.2 规则管理流程

```
管理员(前端)        API Layer         require_roles      RuleConfigDatabase    PostgreSQL
   |                   |                   |                   |                   |
   |-- POST /rules --> |                   |                   |                   |
   |   {rule body}     |-- 角色校验 -----> |                   |                   |
   |                   |<- admin/data_admin |                   |                   |
   |                   |                   |                   |                   |
   |                   |-- get_by_rule_id(id) --------------> |                   |
   |                   |                   |                   |-- SELECT -------> |
   |                   |                   |                   |<- 无重复 ---------|
   |                   |                   |                   |                   |
   |                   |-- create_rule(**kwargs) ------------> |                   |
   |                   |                   |                   |-- INSERT -------> |
   |                   |                   |                   |<- RuleConfig -----|
   |                   |<- {rule, message} |                   |                   |
   |<- 201 Created ----|                   |                   |                   |
```

### 8.3 全库扫描流程

```
调用方              DDLScanner        DatabaseConnector    DDLValidator       ReportGenerator
   |                   |                   |                   |                   |
   |-- connect_db() -> |                   |                   |                   |
   |                   |-- connect() ----> |                   |                   |
   |                   |<- success --------|                   |                   |
   |                   |                   |                   |                   |
   |-- scan_all() ---> |                   |                   |                   |
   |                   |-- get_table_names |                   |                   |
   |                   |               --> |                   |                   |
   |                   |<- [table_names] --|                   |                   |
   |                   |                   |                   |                   |
   |                   |  [for each table]                     |                   |
   |                   |-- get_columns --> |                   |                   |
   |                   |-- get_indexes --> |                   |                   |
   |                   |-- get_comment --> |                   |                   |
   |                   |                   |                   |                   |
   |                   |-- validate_table(table_info) ------> |                   |
   |                   |<- violations -----|                   |                   |
   |                   |                   |                   |                   |
   |                   |-- generate(results) -----------------------------------> |
   |                   |<- CheckReport ------------------------------------------|
   |                   |                   |                   |                   |
   |                   |-- _log_scan_result (写入 bi_scan_logs)                    |
   |<- DDLScanResult --|                   |                   |                   |
```

---

## 9. 测试策略

### 9.1 单元测试

| 测试范围 | 测试目标 | 关键用例 |
|----------|----------|----------|
| DDLParser | 解析正确性 | 标准 CREATE TABLE、IF NOT EXISTS、反引号标识符、多列、多索引 |
| DDLParser | AST 回退 | 正则提取失败时自动降级 AST（复杂 DEFAULT、分区表） |
| DDLParser | ReDoS 超时 | 恶意正则 200ms 超时，抛出 DDL_005 |
| TableValidator | 表命名规则 | 合规表名、大写表名、超长表名、数字开头、前缀白名单 |
| TableValidator | 主键规则 | 有主键、无主键、复合主键 |
| TableValidator | 时间戳规则 | 有 create_time/update_time、缺失其一、缺失全部 |
| ColumnValidator | 列命名规则 | 合规列名、驼峰命名、保留字 |
| ColumnValidator | 数据类型规则 | 推荐类型、不推荐类型（FLOAT, DOUBLE） |
| ColumnValidator | 注释规则 | 有注释、无注释 |
| 评分算法 | 分值计算 | 零违规(100分)、全 High(0分)、混合违规、边界值 |
| 评分算法 | 场景化权重 | ODS/DWD/ADS 不同权重配置下的分值差异 |
| 判定逻辑 | executable/passed | 各组合条件下的判定结果 |
| RuleCache | 缓存命中/失效 | 缓存写入、读取、API 触发失效 |
| 敏感数据脱敏 | 列名脱敏 | phone, id_card, password 等关键词脱敏处理 |
| Dry Run | 规则验证 | POST /api/rules/test 验证新规则拦截效果 |

### 9.2 集成测试

| 测试范围 | 测试目标 |
|----------|----------|
| POST /api/ddl/check | 端到端检查流程，验证请求-解析-验证-响应链路 |
| POST /api/ddl/check + scene_type | ODS/DWD/ADS 场景差异化评分 |
| GET /api/ddl/rules | rules.yaml 加载与返回格式 |
| POST /api/rules/ | 自定义规则创建，重复 ID 冲突 |
| PUT /api/rules/{id}/toggle | 规则状态切换，验证缓存失效 |
| DELETE /api/rules/{id} | 自定义规则删除、内置规则删除拒绝 |
| POST /api/rules/test | Dry Run 模式验证 |
| 权限测试 | 普通用户无法创建/删除规则 |
| 审计日志测试 | delete/disable 规则时日志同步写入（非 BackgroundTasks） |
| 任务拆分测试 | 大库扫描触发 Celery 任务拆分（>=100 表） |

### 9.3 测试数据

**合规 DDL 示例**:

```sql
CREATE TABLE dim_user (
  id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键',
  user_name VARCHAR(128) NOT NULL COMMENT '用户名',
  email VARCHAR(256) COMMENT '邮箱',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT DEFAULT 0 COMMENT '软删除标记'
) COMMENT='用户维度表';
```

**不合规 DDL 示例**:

```sql
CREATE TABLE UserInfo (
  ID INT,
  UserName FLOAT,
  create_date DATE
);
```

预期违规：表名大写（High）、列名大写（High）、使用 FLOAT（Medium）、缺少主键（High）、缺少注释（Medium）、缺少 create_time/update_time（Medium）、缺少 is_deleted（Medium）。

### 9.4 验收标准

- [ ] POST /api/ddl/check 对合规 DDL 返回 score=100, passed=true
- [ ] POST /api/ddl/check 对不合规 DDL 返回正确 violations 列表和评分
- [ ] scene_type=ODS/DWD/ADS 使用不同扣分权重
- [ ] ddl_text 超 64KB 返回 DDL_004
- [ ] 正则解析超时 200ms 降级 AST 并返回 DDL_005
- [ ] 规则 CRUD API 权限校验（普通用户 403）
- [ ] 规则 toggle/delete 审计日志同步写入
- [ ] Seed 幂等性：`is_modified_by_user=TRUE` 的规则不被覆盖
- [ ] RuleCache 在规则变更后正确失效
- [ ] `cd backend && pytest tests/ -x -q` 全通过

### 9.5 Mock 与测试约束

- **`RuleCache`（Redis）**：单元测试中 mock `redis.StrictRedis` 返回预设规则 JSON；集成测试可使用 `fakeredis`。禁止在单元测试中依赖真实 Redis 实例
- **`RuleConfigDatabase._get_db()`**：mock 返回 SQLAlchemy `Session`，避免在 parser/validator 单元测试中触发真实 DB 连接
- **`DDLParser` 双引擎**：分别测试正则路径和 AST 路径。mock `sqlglot.parse()` 验证降级触发条件，不要依赖 sqlglot 版本行为
- **`RulesConfig`（已废弃）**：此类为 v1.0 遗留的 YAML 静态加载器，已被 `DatabaseRulesAdapter` 替代。测试中**不得引用 `RulesConfig`**
- **审计日志**：`delete`/`disable` 操作的审计日志在同一事务内写入，测试需断言 `bi_rule_change_logs` INSERT 与规则变更在同一 `session.commit()` 中

---

## 10. 开放问题

| 编号 | 问题 | 影响范围 | 优先级 | 状态 |
|------|------|----------|--------|------|
| **OI-002** | **【已修复】rules.yaml 静态规则与 bi_rule_configs 数据库规则为两套独立体系。修复方案：明确 rules.yaml 为 Seed 文件，运行时规则统一从数据库加载。** | 架构一致性 | **P0** | ✅ 已修复 |
| **OI-001** | **【已修复】正则解析复杂 DDL 能力有限。修复方案：正则优先 + AST 回退双引擎（sqlglot/sqlparse），当正则提取元数据为空且 SQL 合法时自动降级。** | 解析覆盖率 | **P0** | ✅ 已修复 |
| OI-003 | **【已修复】表级 COMMENT 在纯 SQL 文本解析模式下无法提取。修复方案：增强 Parser 支持 `COMMENT='xxx'` 语法。** | 检查完整性 | P2 | ✅ 已修复 |
| **OI-004** | **【已修复】评分权重硬编码。修复方案：通过 `config_json.scene_weights` 支持 ODS/DWD/ADS 场景化权重配置。** | 灵活性 | **P1** | ✅ 已修复 |
| OI-005 | DDL 检查目前不支持 ALTER TABLE 语句。是否需要扩展支持增量变更检查？ | 功能覆盖 | P2 | 待办 |
| **OI-006** | **【已修复】BackgroundTasks 进程崩溃会丢失审计日志。修复方案：delete/disable 操作在同一 DB 事务内同步写入；一般变更使用 Celery 队列（带重试）。** | 合规审计 | **P1** | ✅ 已修复 |
| **OI-007** | **【已修复】64KB 长度限制不足以防 ReDoS。修复方案：正则匹配单次超时 200ms，超时返回 DDL_005 并尝试 AST 降级。** | 安全 | **P1** | ✅ 已修复 |
| OI-008 | 内置规则种子数据 (DEFAULT_RULES_SEED) 在模块导入时执行写入，若数据库未就绪会静默失败。是否需要改为显式初始化命令？ | 启动可靠性 | P2 | 待办 |
| **OI-009** | **【新增】Seed 幂等性问题：重复部署会覆盖用户已修改的规则。修复方案：添加 `is_modified_by_user` 标记 + UPSERT 逻辑。** | Seed 管理 | **P2** | ✅ 已修复 |
| **OI-010** | **【新增】全库扫描万级表同步阻塞 Worker。修复方案：任务拆分策略，Celery 分布式并发执行单表扫描任务。** | 扫描性能 | **P1** | ✅ 已修复 |
| OI-011 | 前端 DDL 暂存区与 Diff 功能未实现 | 开发体验 | P3 | 待办 |

---

## 11. 开发交付约束

### 11.1 架构约束

- `services/ddl_checker/` 不得 import FastAPI、Request、Response（纯业务层）
- `services/ddl_checker/` 不得 import `app.api.*`（禁止反向依赖）
- `services/rules/models.py` 通过 SQLAlchemy Core 操作 DB，不得使用 raw SQL 字符串插值
- `modules/ddl_check_engine/` 为独立模块，不得 import `backend/` 内部模块
- 规则运行时**必须**从 `bi_rule_configs` 表加载，`rules.yaml` 仅作 Seed 使用
- `functools.lru_cache` 不适用于请求级 DDLValidator 实例，**禁止使用**

### 11.2 强制检查清单

- [ ] 新增/修改的规则检查方法有对应的单元测试
- [ ] 规则 CRUD 操作写入 `bi_rule_change_logs` 审计日志（delete/disable 同步写入）
- [ ] `ddl_text` 入口处校验长度 ≤ 64KB
- [ ] 正则匹配设置 200ms 超时
- [ ] 不使用 `RulesConfig`（已废弃的静态 YAML 加载器）
- [ ] Seed 数据通过 `is_modified_by_user` 保护用户修改

### 11.3 验证命令

```bash
# 后端编译检查
cd backend && python3 -m py_compile services/ddl_checker/parser.py
cd backend && python3 -m py_compile services/ddl_checker/validator.py
cd backend && python3 -m py_compile services/ddl_checker/scanner.py

# 禁止 services/ 依赖 Web 框架
grep -rn "from fastapi\|from starlette" backend/services/ddl_checker/ && echo "FAIL" || echo "PASS"

# 禁止废弃的 RulesConfig 引用
grep -rn "RulesConfig" backend/services/ backend/app/ | grep -v "# DEPRECATED" && echo "FAIL" || echo "PASS"

# 后端测试
cd backend && pytest tests/ -x -q
```

### 11.4 正确 / 错误示范

```python
# ❌ 错误：运行时从 YAML 加载规则
from services.rules.config import RulesConfig
rules = RulesConfig.load()

# ✅ 正确：运行时从数据库加载规则
from services.ddl_checker.cache import RuleCache
rules = RuleCache.get_active_rules(scene_type="ALL", db_type="MySQL")

# ❌ 错误：使用 lru_cache 缓存规则（请求级实例，不生效）
@functools.lru_cache()
def get_rules(): ...

# ✅ 正确：使用 Redis 缓存，TTL=300s
RuleCache.get_or_set(key, loader_fn, ttl=300)

# ❌ 错误：审计日志用 BackgroundTasks（进程崩溃会丢失）
background_tasks.add_task(write_audit_log, ...)

# ✅ 正确：delete/disable 审计在同一事务内同步写入
with db.session.begin():
    db.delete(rule)
    db.create_change_log(rule_id, "delete", old_value, None, operator)
```
