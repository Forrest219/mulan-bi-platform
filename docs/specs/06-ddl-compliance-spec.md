# DDL 合规检查技术规格书

| 属性 | 值 |
|------|------|
| 版本 | v1.0 |
| 日期 | 2026-04-03 |
| 状态 | Draft |
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
- 通过可量化的评分体系（0-100）衡量 DDL 规范程度
- 规则可配置，支持内置规则与自定义规则的 CRUD 管理
- 扫描结果可审计，支持历史查询

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
| DDLParser | `backend/services/ddl_checker/parser.py` | SQL 解析，提取 TableInfo |
| DDLValidator | `backend/services/ddl_checker/validator.py` | 规则匹配与违规检测 |
| DDLScanner | `backend/services/ddl_checker/scanner.py` | 全库扫描编排器 |
| RuleConfig Model | `backend/services/rules/models.py` | 规则持久化 ORM |
| DDL Check Engine | `modules/ddl_check_engine/` | 独立可分发的检查引擎模块 |
| 规则配置文件 | `config/rules.yaml` | 静态规则定义 |

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
| config_json | JSONB | NOT NULL, DEFAULT '{}' | 规则扩展参数 |
| created_at | DATETIME | NOT NULL, SERVER_DEFAULT now() | 创建时间 |
| updated_at | DATETIME | NOT NULL, SERVER_DEFAULT now(), ON UPDATE now() | 更新时间 |

#### bi_scan_logs（扫描日志表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO_INCREMENT | 自增主键 |
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
| results | JSONB | NULL | 详细扫描结果 |
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

### 2.3 内存数据模型

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

**响应体**:

```json
{
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
  "executable": true
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| passed | boolean | 是否通过（executable=true 且 score >= 80） |
| score | integer | 合规评分 0-100 |
| summary | object | 按风险级别汇总：High / Medium / Low |
| issues | array | 违规问题列表 |
| executable | boolean | 是否可执行（score >= 60 且无 High 问题） |

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

---

## 4. 业务逻辑

### 4.1 DDL 检查处理流程

```
用户提交 DDL 文本
       |
       v
  DDLParser.parse_create_table(sql)
       |
       |--- 解析失败 ---> 返回 score=0, PARSE_ERROR
       |
       v
  TableInfo (表名、列列表、索引列表)
       |
       v
  DDLValidator.validate_table(table_info)
       |
       |--- 从数据库加载活跃规则（bi_rule_configs 中 enabled=true 的记录）
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
  _calculate_score(violations)
       |
       v
  DDLCheckResponse (score, passed, executable, issues)
```

### 4.2 评分算法

起始分值为 100 分，按违规级别逐项扣分：

| 违规级别 | 映射关系 | 扣分 |
|----------|----------|------|
| High（error） | ViolationLevel.ERROR | -20 分/项 |
| Medium（warning） | ViolationLevel.WARNING | -5 分/项 |
| Low（info） | ViolationLevel.INFO | -1 分/项 |

**边界约束**:
- 最低分: 0
- 最高分: 100

**输入安全约束**:
- `ddl_text` 最大长度限制为 **64KB**（65,536 字节），超长输入直接返回 `DDL_004` 错误
- 此长度限制同时作为 ReDoS 防护的第一道防线

**判定逻辑**:

```python
score = 100 - (high_count * 20) - (medium_count * 5) - (low_count * 1)
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

DDLParser 通过正则表达式解析 CREATE TABLE 语句，支持以下语法元素：

| 元素 | 支持情况 |
|------|----------|
| CREATE TABLE (IF NOT EXISTS) | 支持 |
| 反引号/引号包裹的标识符 | 支持 |
| 列定义（类型、NOT NULL、DEFAULT、COMMENT） | 支持 |
| PRIMARY KEY（内联和独立声明） | 支持 |
| INDEX / KEY | 支持 |
| UNIQUE INDEX / KEY | 支持 |
| FOREIGN KEY | 不支持（跳过） |
| **表级 COMMENT** (`COMMENT='xxx'` 或 `COMMENT="xxx"`) | **支持（新增）** |
| 分区定义 | 不支持 |

### 4.6 数据库连接扫描模式

DDLScanner 支持通过 DatabaseConnector 直连数据库执行全库扫描：

1. `connect_database(db_config)` — 建立数据库连接
2. `scan_all_tables()` — 遍历所有表，读取结构信息并验证
3. `scan_table(table_name)` — 扫描单表
4. `scan_sql(sql)` — 扫描 SQL 文本（不需要数据库连接）
5. 扫描完成后自动记录 bi_scan_logs

---

## 5. 错误码

| 错误码 | HTTP 状态码 | 说明 | 触发场景 |
|--------|------------|------|----------|
| DDL_001 | 400 | DDL 语法无效 | DDLParser 无法解析提交的 SQL 语句 |
| DDL_002 | 404 | 规则不存在 | toggle/delete 操作时找不到指定 rule_id |
| DDL_003 | 400 | 规则配置无效 | 创建自定义规则时参数校验失败 |
| **DDL_004** | **400** | **输入超长** | **ddl_text 超过 64KB 限制（ReDoS 防护）** |
| PARSE_ERROR | 200 | 解析失败 | DDL 检查时解析失败，返回 score=0 |
| 409 | 409 | 规则 ID 冲突 | 创建自定义规则时 rule_id 已存在 |
| 403 | 403 | 操作被拒绝 | 尝试删除内置规则 |

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
- **ReDoS 防护**: 除长度限制外，正则引擎需设置回溯上限（如 `re.MAX_REPEAT` 或超时机制），防止恶意构造的 ReDoS 正则导致 CPU 耗尽
- **rules.yaml 路径**: 硬编码为相对于项目根目录的固定路径，不接受用户输入的文件路径

### 6.3 数据库连接安全

- DatabaseConnector 连接信息不通过 API 暴露
- 数据库连接凭据应通过环境变量或加密配置注入
- 扫描操作仅执行 SELECT 级别的元数据查询

### 6.4 审计

- 规则变更操作应记录到 bi_rule_change_logs，包含操作人、操作类型、变更前后快照
- 扫描操作记录到 bi_scan_logs，包含结果和耗时

---

## 7. 集成点

### 7.1 内部集成

| 集成目标 | 方式 | 说明 |
|----------|------|------|
| 认证模块 | FastAPI Depends | 通过 get_current_user / require_roles 依赖注入 |
| PostgreSQL | SQLAlchemy ORM | bi_rule_configs / bi_scan_logs / bi_rule_change_logs 表操作 |
| rules.yaml | 文件读取 | **仅在初始化时读取一次**作为内置规则种子数据；**运行时规则从数据库加载** |
| 前端 DDL 检查页面 | REST API | /api/ddl/check 接口 |
| 前端规则管理页面 | REST API | /api/rules/ CRUD 接口 |

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
| DDLParser | 边界处理 | 空字符串、无效 SQL、仅含注释的 SQL、嵌套括号 |
| TableValidator | 表命名规则 | 合规表名、大写表名、超长表名、数字开头、前缀白名单 |
| TableValidator | 主键规则 | 有主键、无主键、复合主键 |
| TableValidator | 时间戳规则 | 有 create_time/update_time、缺失其一、缺失全部 |
| ColumnValidator | 列命名规则 | 合规列名、驼峰命名、保留字 |
| ColumnValidator | 数据类型规则 | 推荐类型、不推荐类型（FLOAT, DOUBLE） |
| ColumnValidator | 注释规则 | 有注释、无注释 |
| 评分算法 | 分值计算 | 零违规(100分)、全 High(0分)、混合违规、边界值 |
| 判定逻辑 | executable/passed | 各组合条件下的判定结果 |

### 9.2 集成测试

| 测试范围 | 测试目标 |
|----------|----------|
| POST /api/ddl/check | 端到端检查流程，验证请求-解析-验证-响应链路 |
| GET /api/ddl/rules | rules.yaml 加载与返回格式 |
| POST /api/rules/ | 自定义规则创建，重复 ID 冲突 |
| PUT /api/rules/{id}/toggle | 规则状态切换 |
| DELETE /api/rules/{id} | 自定义规则删除、内置规则删除拒绝 |
| 权限测试 | 普通用户无法创建/删除规则 |

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

---

## 10. 开放问题

| 编号 | 问题 | 影响范围 | 优先级 | 状态 |
|------|------|----------|--------|------|
| **OI-002** | **【已修复】rules.yaml 静态规则与 bi_rule_configs 数据库规则为两套独立体系。修复方案：明确 rules.yaml 为 Seed 文件，运行时规则统一从数据库加载。** | 架构一致性 | **P0** | ✅ 已修复 |
| OI-001 | 当前 DDLParser 基于正则表达式实现，对复杂 DDL（分区表、存储过程内嵌 DDL）解析能力有限。是否需要引入 SQL AST 解析器（如 sqlparse / sqlglot）？ | 解析覆盖率 | P2 | 待办 |
| OI-003 | **【已修复】表级 COMMENT 在纯 SQL 文本解析模式下无法提取。修复方案：增强 Parser 支持 `COMMENT='xxx'` 语法。** | 检查完整性 | P2 | ✅ 已修复 |
| OI-004 | 当前评分权重（High=-20, Medium=-5, Low=-1）为硬编码。是否需要支持管理员自定义扣分权重？ | 灵活性 | P3 | 待办 |
| OI-005 | DDL 检查目前不支持 ALTER TABLE 语句。是否需要扩展支持增量变更检查？ | 功能覆盖 | P2 | 待办 |
| **OI-006** | **【已修复】规则变更审计表 bi_rule_change_logs 在当前代码中尚未实现写入逻辑。修复方案：在所有规则变更 API 的后置操作中显式加入异步写入步骤。** | 合规审计 | **P1** | ✅ 已修复 |
| **OI-007** | **【已修复】ddl_text 输入缺少长度限制，大文本可能导致正则引擎性能问题（ReDoS 风险）。修复方案：API 入口强制限制 64KB，增加 ReDoS 正则回溯上限。** | 安全 | **P1** | ✅ 已修复 |
| OI-008 | 内置规则种子数据 (DEFAULT_RULES_SEED) 在模块导入时执行写入，若数据库未就绪会静默失败。是否需要改为显式初始化命令？ | 启动可靠性 | P2 | 待办 |
