"""规则配置 API — 持久化到 PostgreSQL
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.dependencies import get_current_user, require_roles
from services.ddl_checker.cache import RuleCache
from services.logs.logger import logger as audit_logger
from services.rules.models import RuleConfigDatabase

logger = logging.getLogger(__name__)
router = APIRouter()

# 默认规则种子数据（首次启动写入数据库）
DEFAULT_RULES_SEED = [
    {"rule_id": "RULE_001", "name": "表命名规范", "level": "HIGH", "category": "Naming", "display_group": "naming", "db_type": "MySQL",
     "description": "表名必须以小写字母开头，支持小写字母、数字、下划线",
     "suggestion": "表名格式：dim_xxx, fact_xxx, ods_xxx"},
    {"rule_id": "RULE_002", "name": "字段必须有注释", "level": "HIGH", "category": "Structure", "display_group": "comment", "db_type": "MySQL",
     "description": "所有字段必须包含 COMMENT 注释说明",
     "suggestion": "为每个字段添加清晰的 COMMENT 说明"},
    {"rule_id": "RULE_003", "name": "金额字段类型", "level": "MEDIUM", "category": "Type", "display_group": "field", "db_type": "MySQL",
     "description": "金额相关字段必须使用 DECIMAL 类型，避免精度问题",
     "suggestion": "使用 DECIMAL(18,2) 等明确精度"},
    {"rule_id": "RULE_004", "name": "必须包含 create_time", "level": "HIGH", "category": "Audit", "display_group": "schema", "db_type": "MySQL",
     "description": "表必须包含 create_time 字段记录创建时间",
     "suggestion": "添加 create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"},
    {"rule_id": "RULE_005", "name": "必须包含 update_time", "level": "HIGH", "category": "Audit", "display_group": "schema", "db_type": "MySQL",
     "description": "表必须包含 update_time 字段记录更新时间",
     "suggestion": "添加 update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"},
    {"rule_id": "RULE_006", "name": "主键规范", "level": "HIGH", "category": "Structure", "display_group": "schema", "db_type": "MySQL",
     "description": "表必须包含主键",
     "suggestion": "使用 BIGINT AUTO_INCREMENT 作为主键"},
    {"rule_id": "RULE_007", "name": "索引数量限制", "level": "MEDIUM", "category": "Index", "display_group": "performance", "db_type": "MySQL",
     "description": "单表索引数量不超过 10 个",
     "suggestion": "保留必要的索引，删除冗余索引"},
    {"rule_id": "RULE_008", "name": "字段命名规范", "level": "MEDIUM", "category": "Naming", "display_group": "naming", "db_type": "MySQL",
     "description": "字段名必须以小写字母开头，支持小写字母、数字、下划线",
     "suggestion": "使用下划线分隔：user_name, create_time"},
    {"rule_id": "RULE_009", "name": "软删除字段", "level": "LOW", "category": "Audit", "display_group": "schema", "db_type": "MySQL",
     "description": "业务表建议包含 is_deleted 字段支持软删除",
     "suggestion": "添加 is_deleted TINYINT(1) DEFAULT 0"},
    {"rule_id": "RULE_010", "name": "表注释规范", "level": "MEDIUM", "category": "Structure", "display_group": "comment", "db_type": "MySQL",
     "description": "表必须包含 COMMENT 注释说明表用途",
     "suggestion": "使用 COMMENT='表用途说明'"},
    {"rule_id": "RULE_011", "name": "SQL Server 主键规范", "level": "HIGH", "category": "Structure", "display_group": "schema", "db_type": "SQL Server",
     "description": "SQL Server 表必须包含主键",
     "suggestion": "使用 INT IDENTITY(1,1) 或 BIGINT IDENTITY 作为主键"},
    {"rule_id": "RULE_012", "name": "SQL Server 注释规范", "level": "MEDIUM", "category": "Structure", "display_group": "comment", "db_type": "SQL Server",
     "description": "SQL Server 表和字段使用 EXTENDED PROPERTY 存储注释",
     "suggestion": "使用 sp_addextendedproperty 存储注释"},
    # StarRocks 数仓合规规则 (RULE_SR_001 ~ RULE_SR_025)
    {"rule_id": "RULE_SR_001", "name": "ODS 双下划线命名", "level": "HIGH", "category": "sr_layer_naming", "display_group": "naming", "db_type": "StarRocks",
     "scene_type": "ODS",
     "description": "ODS 层表名必须使用 {系统}__{模块}__{原表} 格式",
     "suggestion": "表名格式示例: erp__order__sales_order",
     "config_json": {"pattern": "^[a-z]+__[a-z0-9_]+__[a-z0-9_]+$", "databases": ["ods_db", "ods_api", "ods_log"]}},
    {"rule_id": "RULE_SR_002", "name": "DWD 业务域+粒度后缀", "level": "HIGH", "category": "sr_layer_naming", "display_group": "naming", "db_type": "StarRocks",
     "scene_type": "DWD",
     "description": "DWD 层表名必须使用 {业务域}_{含义}_{粒度后缀} 格式",
     "suggestion": "粒度后缀: _di(日增量), _df(日全量), _hi(小时增量), _rt(实时)",
     "config_json": {"pattern": "^(sales|finance|supply|hr|market|risk|ops|product|ai)_.*_(di|df|hi|rt)$", "databases": ["dwd"]}},
    {"rule_id": "RULE_SR_003", "name": "DIM 无业务域前缀", "level": "HIGH", "category": "sr_layer_naming", "display_group": "naming", "db_type": "StarRocks",
     "description": "DIM 层表不应使用业务域前缀，应为通用维度命名",
     "suggestion": "表名格式: dim_xxx，不要带 sales_/finance_ 等业务前缀",
     "config_json": {"forbidden_prefixes": ["sales_", "finance_", "supply_", "hr_", "market_", "risk_", "ops_", "product_", "ai_"], "databases": ["dim"]}},
    {"rule_id": "RULE_SR_004", "name": "DWS 粒度后缀", "level": "HIGH", "category": "sr_layer_naming", "display_group": "naming", "db_type": "StarRocks",
     "description": "DWS 层表名必须包含粒度后缀",
     "suggestion": "表名末尾应为 _1d, _1h, _1m, _rt",
     "config_json": {"pattern": "_(1d|1h|1m|rt)$", "databases": ["dws"]}},
    {"rule_id": "RULE_SR_005", "name": "ADS 场景前缀", "level": "HIGH", "category": "sr_layer_naming", "display_group": "naming", "db_type": "StarRocks",
     "description": "ADS 层表名必须包含场景前缀",
     "suggestion": "表名前缀: board_, report_, api_, ai_, tag_, label_",
     "config_json": {"pattern": "^(board|report|api|ai|tag|label)_", "databases": ["ads"]}},
    {"rule_id": "RULE_SR_006", "name": "金额字段必须 DECIMAL", "level": "HIGH", "category": "sr_type_alignment", "display_group": "field", "db_type": "StarRocks",
     "description": "金额字段（_amt/_amount 后缀）必须使用 DECIMAL 类型",
     "suggestion": "使用 DECIMAL(20,4)，禁止 FLOAT/DOUBLE",
     "config_json": {"suffixes": ["_amt", "_amount"], "required_type": "DECIMAL", "forbidden_types": ["FLOAT", "DOUBLE"]}},
    {"rule_id": "RULE_SR_007", "name": "日期字段禁止 VARCHAR", "level": "HIGH", "category": "sr_type_alignment", "display_group": "field", "db_type": "StarRocks",
     "description": "日期时间字段（_time/_at/_dt 后缀）必须使用时间类型",
     "suggestion": "使用 DATETIME/DATE/TIMESTAMP，禁止 VARCHAR/CHAR/STRING",
     "config_json": {"suffixes": ["_time", "_at", "_dt"], "required_types": ["DATETIME", "DATE", "TIMESTAMP"], "forbidden_types": ["VARCHAR", "CHAR", "STRING"]}},
    {"rule_id": "RULE_SR_008", "name": "公共字段 etl_time", "level": "HIGH", "category": "sr_public_fields", "display_group": "field", "db_type": "StarRocks",
     "description": "所有表必须包含 etl_time DATETIME 字段",
     "suggestion": "添加 etl_time DATETIME 字段记录 ETL 处理时间",
     "config_json": {"required_fields": [{"name": "etl_time", "type": "DATETIME"}], "databases": "__all__"}},
    {"rule_id": "RULE_SR_009", "name": "公共字段 dt", "level": "HIGH", "category": "sr_public_fields", "display_group": "field", "db_type": "StarRocks",
     "description": "ODS/DWD/DWS/DM 表必须包含 dt DATE 分区字段",
     "suggestion": "添加 dt DATE 字段作为分区键",
     "config_json": {"required_fields": [{"name": "dt", "type": "DATE"}], "databases": ["ods_db", "ods_api", "ods_log", "dwd", "dws", "dm"]}},
    {"rule_id": "RULE_SR_010", "name": "ODS 全套公共字段", "level": "HIGH", "category": "sr_public_fields", "display_group": "field", "db_type": "StarRocks",
     "scene_type": "ODS",
     "description": "ODS 层表必须包含 etl_batch_id/src_system/src_table/is_deleted 公共字段",
     "suggestion": "添加 ODS 全套公共字段",
     "config_json": {"required_fields": [{"name": "etl_batch_id", "type": "VARCHAR"}, {"name": "src_system", "type": "VARCHAR"}, {"name": "src_table", "type": "VARCHAR"}, {"name": "is_deleted", "type": "TINYINT"}], "databases": ["ods_db", "ods_api", "ods_log"]}},
    {"rule_id": "RULE_SR_011", "name": "ODS_DB CDC 字段", "level": "HIGH", "category": "sr_public_fields", "display_group": "field", "db_type": "StarRocks",
     "scene_type": "ODS",
     "description": "ODS_DB 表必须包含 src_op/src_ts CDC 操作字段",
     "suggestion": "添加 src_op VARCHAR 和 src_ts DATETIME 字段",
     "config_json": {"required_fields": [{"name": "src_op", "type": "VARCHAR"}, {"name": "src_ts", "type": "DATETIME"}], "databases": ["ods_db"]}},
    {"rule_id": "RULE_SR_012", "name": "字段 snake_case", "level": "HIGH", "category": "sr_field_naming", "display_group": "naming", "db_type": "StarRocks",
     "description": "所有字段名必须使用 snake_case 命名",
     "suggestion": "字段名使用小写字母+数字+下划线，长度不超过 40",
     "config_json": {"pattern": "^[a-z][a-z0-9_]*$", "max_length": 40}},
    {"rule_id": "RULE_SR_013", "name": "字段注释覆盖率", "level": "HIGH", "category": "sr_comment", "display_group": "comment", "db_type": "StarRocks",
     "description": "所有字段必须有注释，覆盖率 100%",
     "suggestion": "为每个字段添加 COMMENT",
     "config_json": {"min_coverage": 1.0}},
    {"rule_id": "RULE_SR_014", "name": "表注释存在", "level": "HIGH", "category": "sr_comment", "display_group": "comment", "db_type": "StarRocks",
     "description": "所有表必须包含注释说明用途",
     "suggestion": "使用 COMMENT 说明表的业务含义和数据粒度"},
    {"rule_id": "RULE_SR_015", "name": "禁止额外数据库", "level": "HIGH", "category": "sr_database_whitelist", "display_group": "schema", "db_type": "StarRocks",
     "description": "StarRocks 实例中只允许规划内的数据库",
     "suggestion": "联系管理员确认数据库是否在规划列表中",
     "config_json": {"allowed": ["ods_db", "ods_api", "ods_log", "dwd", "dim", "dws", "dm", "ads", "feature", "ai", "sandbox", "tmp", "ops", "meta", "backup", "information_schema", "_statistics_"]}},
    {"rule_id": "RULE_SR_016", "name": "Feature 表命名", "level": "MEDIUM", "category": "sr_layer_naming", "display_group": "naming", "db_type": "StarRocks",
     "description": "Feature 层表名必须包含特征粒度后缀",
     "suggestion": "表名格式: xxx_features_1d/1h/rt",
     "config_json": {"pattern": "_features_(1d|1h|rt|[0-9]+[dhm])$", "databases": ["feature"]}},
    {"rule_id": "RULE_SR_017", "name": "AI 表前缀", "level": "MEDIUM", "category": "sr_layer_naming", "display_group": "naming", "db_type": "StarRocks",
     "description": "AI 层表名必须使用 kb/llm/agent/text2sql 前缀",
     "suggestion": "表名前缀: kb_, llm_, agent_, text2sql_",
     "config_json": {"pattern": "^(kb|llm|agent|text2sql)_", "databases": ["ai"]}},
    {"rule_id": "RULE_SR_018", "name": "Backup 命名含日期", "level": "MEDIUM", "category": "sr_layer_naming", "display_group": "naming", "db_type": "StarRocks",
     "description": "Backup 层表名必须包含 8 位日期后缀",
     "suggestion": "表名格式: xxx__yyy_20260101",
     "config_json": {"pattern": "__.*_\\d{8}$", "databases": ["backup"]}},
    {"rule_id": "RULE_SR_019", "name": "数量字段类型", "level": "HIGH", "category": "sr_type_alignment", "display_group": "field", "db_type": "StarRocks",
     "description": "数量字段（_qty/_cnt 后缀）必须使用整数或精确数值类型",
     "suggestion": "使用 BIGINT/DECIMAL/INT，禁止 FLOAT/DOUBLE",
     "config_json": {"suffixes": ["_qty", "_cnt"], "required_types": ["BIGINT", "DECIMAL", "INT"], "forbidden_types": ["FLOAT", "DOUBLE"]}},
    {"rule_id": "RULE_SR_020", "name": "比率字段类型", "level": "HIGH", "category": "sr_type_alignment", "display_group": "field", "db_type": "StarRocks",
     "description": "比率字段（_rate 后缀）必须使用 DECIMAL 类型",
     "suggestion": "使用 DECIMAL(10,6)，禁止 FLOAT/DOUBLE",
     "config_json": {"suffixes": ["_rate"], "required_type": "DECIMAL", "forbidden_types": ["FLOAT", "DOUBLE"]}},
    {"rule_id": "RULE_SR_021", "name": "无 ods_hive 库", "level": "HIGH", "category": "sr_database_whitelist", "display_group": "schema", "db_type": "StarRocks",
     "description": "StarRocks 实例中不应存在 ods_hive 数据库（ADR-003 迁移要求）",
     "suggestion": "将 ods_hive 数据迁移至 ods_db/ods_api/ods_log",
     "config_json": {"forbidden": ["ods_hive"]}},
    {"rule_id": "RULE_SR_022", "name": "表名无中文", "level": "HIGH", "category": "sr_table_naming", "display_group": "naming", "db_type": "StarRocks",
     "description": "表名不允许包含中文字符",
     "suggestion": "表名只使用英文字母、数字、下划线",
     "config_json": {"pattern_forbidden": "[\\u4e00-\\u9fff]"}},
    {"rule_id": "RULE_SR_023", "name": "表名无版本号", "level": "MEDIUM", "category": "sr_table_naming", "display_group": "naming", "db_type": "StarRocks",
     "description": "表名不应包含版本号（如 _v2）",
     "suggestion": "使用 DDL 变更管理，不要在表名中加版本号",
     "config_json": {"pattern_forbidden": "_v\\d+"}},
    {"rule_id": "RULE_SR_024", "name": "DM 部门前缀", "level": "MEDIUM", "category": "sr_layer_naming", "display_group": "naming", "db_type": "StarRocks",
     "description": "DM 层表名使用宽松 snake_case",
     "suggestion": "表名格式: 部门_主题_含义",
     "config_json": {"pattern": "^[a-z][a-z0-9_]+$", "databases": ["dm"]}},
    {"rule_id": "RULE_SR_025", "name": "视图命名 _vw 后缀", "level": "MEDIUM", "category": "sr_view_naming", "display_group": "naming", "db_type": "StarRocks",
     "description": "所有视图必须以 _vw 后缀命名",
     "suggestion": "视图命名: xxx_vw",
     "config_json": {"pattern": "_vw$"}},
    {"rule_id": "SR-SCH-001", "name": "主键表必须显式声明 PRIMARY KEY", "level": "critical", "category": "sr_schema", "display_group": "schema", "db_type": "StarRocks",
     "description": "StarRocks 主键表必须显式声明 PRIMARY KEY，否则 KEYS_TYPE='PRIMARY_KEYS' 但无 PRIMARY KEY 子句",
     "suggestion": "ALTER TABLE 重建并显式声明 PRIMARY KEY",
     "config_json": {"trigger": "KEYS_TYPE='PRIMARY_KEYS' but DDL has no PRIMARY KEY"}},
    {"rule_id": "SR-SCH-002", "name": "大宽表必须使用列存模型", "level": "high", "category": "sr_schema", "display_group": "schema", "db_type": "StarRocks",
     "description": "列数 >= 200 的大宽表必须使用 DUPLICATE/PRIMARY/AGG 模型，避免 aggregation 模型写入放大",
     "suggestion": "将表模型改为 DUPLICATE 或 PRIMARY",
     "config_json": {"min_columns": 200, "model": "DUPLICATE/PRIMARY/AGG"}},
    {"rule_id": "SR-SCH-003", "name": "时间字段必须使用 DATETIME", "level": "high", "category": "sr_schema", "display_group": "schema", "db_type": "StarRocks",
     "description": "时间相关字段（_time/_at/_dt 后缀）必须使用 DATETIME/DATE 类型，禁止 VARCHAR/CHAR/STRING",
     "suggestion": "将时间字段类型改为 DATETIME",
     "config_json": {"suffixes": ["_time", "_at", "_dt"], "forbidden": ["VARCHAR", "CHAR", "STRING"]}},
    {"rule_id": "SR-SCH-004", "name": "分区列必须为 DATE/DATETIME/INT", "level": "critical", "category": "sr_schema", "display_group": "schema", "db_type": "StarRocks",
     "description": "分区列仅允许 DATE、DATETIME、INT、BIGINT 类型，禁止 STRING 等其他类型",
     "suggestion": "将分区列类型改为 DATE/DATETIME/INT/BIGINT",
     "config_json": {"allowed": ["DATE", "DATETIME", "INT", "BIGINT"]}},
    {"rule_id": "SR-SCH-005", "name": "主键长度 <= 128 字节", "level": "high", "category": "sr_schema", "display_group": "schema", "db_type": "StarRocks",
     "description": "主键列的总字节长度不得超过 128 字节，否则写入失败",
     "suggestion": "精简主键列组合，确保总字节数 <= 128",
     "config_json": {"max_bytes": 128}},
    {"rule_id": "SR-SCH-006", "name": "表名/列名长度 <= 64", "level": "medium", "category": "sr_schema", "display_group": "schema", "db_type": "StarRocks",
     "description": "表名和列名字符数不得超过 64",
     "suggestion": "缩短表名/列名到 64 字符以内",
     "config_json": {"max_length": 64}},
    {"rule_id": "SR-SCH-007", "name": "字符集统一 utf8mb4", "level": "medium", "category": "sr_schema", "display_group": "schema", "db_type": "StarRocks",
     "description": "所有表必须使用 utf8mb4 字符集，禁止 latin1/gbk 等其他字符集",
     "suggestion": "ALTER TABLE CONVERT TO CHARACTER SET utf8mb4",
     "config_json": {"required_charset": "utf8mb4"}},
    {"rule_id": "SR-SCH-008", "name": "禁止 BLOB 字段", "level": "high", "category": "sr_schema", "display_group": "schema", "db_type": "StarRocks",
     "description": "禁止使用 BLOB、MEDIUMBLOB、LONGBLOB 类型，StarRocks 列存不适合大对象存储",
     "suggestion": "将 BLOB 字段改为 VARCHAR 或迁移至专用对象存储",
     "config_json": {"forbidden_types": ["BLOB", "MEDIUMBLOB", "LONGBLOB"]}},
    {"rule_id": "SR-PART-001", "name": "单表分区数 <= 1000", "level": "high", "category": "sr_partition", "display_group": "storage", "db_type": "StarRocks",
     "description": "单表分区数不得超过 1000，否则元数据压力过大",
     "suggestion": "合并分区或降低分区粒度",
     "config_json": {"max": 1000}},
    {"rule_id": "SR-PART-002", "name": "单分区数据量 1-10GB", "level": "medium", "category": "sr_partition", "display_group": "storage", "db_type": "StarRocks",
     "description": "单个分区数据量应在 1GB~10GB 之间，过小造成资源浪费，过大影响查询性能",
     "suggestion": "调整分区策略，确保单分区数据量在 1-10GB",
     "config_json": {"min_gb": 1, "max_gb": 10}},
    {"rule_id": "SR-PART-003", "name": "分桶数与数据量匹配", "level": "high", "category": "sr_partition", "display_group": "storage", "db_type": "StarRocks",
     "description": "分桶数应与数据量匹配，范围 1~256，过少导致并行度不足，过多造成资源浪费",
     "suggestion": "根据数据量调整分桶数，保持 1~256 范围",
     "config_json": {"min_buckets": 1, "max_buckets": 256}},
    {"rule_id": "SR-PART-004", "name": "分桶列必须高基数", "level": "high", "category": "sr_partition", "display_group": "storage", "db_type": "StarRocks",
     "description": "分桶列基数比应 >= 0.1，即不同值数/总行数 >= 10%，低基数导致数据倾斜",
     "suggestion": "选择高基数字段作为分桶列",
     "config_json": {"min_cardinality_ratio": 0.1}},
    {"rule_id": "SR-BUCK-005", "name": "分桶列禁止可空", "level": "critical", "category": "sr_partition", "display_group": "storage", "db_type": "StarRocks",
     "description": "分桶列不允许为 NULL 或可空，否则导致数据倾斜和查询错误",
     "suggestion": "将分桶列设为 NOT NULL",
     "config_json": {"bucket_col_nullable": False}},
    {"rule_id": "SR-PART-006", "name": "大表必须按时间分区", "level": "high", "category": "sr_partition", "display_group": "storage", "db_type": "StarRocks",
     "description": "超过 100GB 的表必须按时间字段分区，便于冷热数据分离和过期清理",
     "suggestion": "添加时间分区键",
     "config_json": {"min_size_gb": 100}},
    {"rule_id": "SR-REP-001", "name": "生产环境副本数=3", "level": "critical", "category": "sr_replica", "display_group": "storage", "db_type": "StarRocks",
     "description": "生产环境（prod）表副本数必须为 3，保证高可用",
     "suggestion": "修改表副本数为 3",
     "config_json": {"env": "prod", "required_replicas": 3}},
    {"rule_id": "SR-REP-002", "name": "测试环境副本数>=2", "level": "high", "category": "sr_replica", "display_group": "storage", "db_type": "StarRocks",
     "description": "测试/预发环境表副本数至少为 2",
     "suggestion": "修改表副本数 >= 2",
     "config_json": {"envs": ["test", "staging"], "min_replicas": 2}},
    {"rule_id": "SR-REP-003", "name": "副本均衡度 <= 0.1", "level": "medium", "category": "sr_replica", "display_group": "storage", "db_type": "StarRocks",
     "description": "各 BE 节点副本数差异系数应 <= 0.1，过高导致负载不均",
     "suggestion": "执行 ALTER SYSTEM BALANCE 重新均衡",
     "config_json": {"max_imbalance": 0.1}},
    {"rule_id": "SR-REP-004", "name": "colocate group 副本布局一致", "level": "high", "category": "sr_replica", "display_group": "storage", "db_type": "StarRocks",
     "description": "Colocate 表的副本分布必须一致，所有副本必须在同一组 BE 上",
     "suggestion": "检查 colocate group 配置，确保副本布局一致",
     "config_json": {}},
    {"rule_id": "SR-PERF-001", "name": "单表 Tablet 数 <= 30000", "level": "high", "category": "sr_perf", "display_group": "performance", "db_type": "StarRocks",
     "description": "单表 Tablet 数不得超过 30000，过多导致元数据内存压力和查询调度开销",
     "suggestion": "增加分桶数或合并小分区，减少 Tablet 总数",
     "config_json": {"max_tablets": 30000}},
    {"rule_id": "SR-PERF-002", "name": "单 Tablet 大小 <= 5GB", "level": "high", "category": "sr_perf", "display_group": "performance", "db_type": "StarRocks",
     "description": "单个 Tablet 大小不得超过 5GB，过大影响 Compaction 效率和查询并行度",
     "suggestion": "增加分桶数或调整分区粒度，控制 Tablet 大小",
     "config_json": {"max_tablet_size_gb": 5}},
    {"rule_id": "SR-PERF-003", "name": "Compaction 累计 < 100", "level": "high", "category": "sr_perf", "display_group": "performance", "db_type": "StarRocks",
     "description": "单表累计 Compaction Score 不得超过 100，过高表明写入压力过大或 Compaction 滞后",
     "suggestion": "降低写入速率或增加 Compaction 资源",
     "config_json": {"max_compaction_score": 100}},
    {"rule_id": "SR-PERF-004", "name": "慢查询比例 < 5%", "level": "medium", "category": "sr_perf", "display_group": "performance", "db_type": "StarRocks",
     "description": "慢查询（>5s）比例不得超过 5%，过高表明存在性能瓶颈",
     "suggestion": "分析慢查询原因，优化查询或表结构",
     "config_json": {"max_slow_query_ratio": 0.05}},
    {"rule_id": "SR-META-001", "name": "表必须有 COMMENT", "level": "high", "category": "sr_meta", "display_group": "schema", "db_type": "StarRocks",
     "description": "所有表必须包含 COMMENT 说明表用途",
     "suggestion": "添加表级 COMMENT",
     "config_json": {}},
    {"rule_id": "SR-META-002", "name": "关键列必须有 COMMENT", "level": "high", "category": "sr_meta", "display_group": "schema", "db_type": "StarRocks",
     "description": "主键列、分区列、分桶列必须包含 COMMENT 说明",
     "suggestion": "为关键列添加 COMMENT",
     "config_json": {"key_columns": ["主键列", "分区列", "分桶列"]}},
    {"rule_id": "SR-META-003", "name": "表 owner 必须设置", "level": "medium", "category": "sr_meta", "display_group": "schema", "db_type": "StarRocks",
     "description": "表必须设置 owner，便于问题追踪和责任落实",
     "suggestion": "通过 ALTER TABLE SET PROPERTY 设置 owner",
     "config_json": {}}

]

# 初始化 seed（幂等性：已修改的规则不会被覆盖）
try:
    _rule_db = RuleConfigDatabase()
    _rule_db.seed_defaults(DEFAULT_RULES_SEED)
except Exception as e:
    logger.warning("规则 seed 失败（数据库可能未就绪）: %s", e)


class ValidationRule(BaseModel):
    """DDL 验证规则模型"""

    id: str
    name: str
    level: str
    category: str
    display_group: Optional[str] = None
    description: str
    suggestion: str
    db_type: str
    scene_type: str = "ALL"
    built_in: bool = True
    status: str = "enabled"


class DryRunRequest(BaseModel):
    """Dry Run 请求"""

    rule: dict
    ddl_text: str
    db_type: str = "mysql"


@router.get("/")
async def get_rules(
    request: Request,
    category: Optional[str] = None,
    level: Optional[str] = None,
    db_type: Optional[str] = None,
    scene_type: Optional[str] = None,
    status: Optional[str] = None
):
    """获取规则列表"""
    get_current_user(request)
    rule_db = RuleConfigDatabase()
    all_rules = rule_db.get_all()

    rules = [r.to_dict() for r in all_rules]

    if category and category != "ALL":
        rules = [r for r in rules if r["category"] == category]
    if level and level != "ALL":
        rules = [r for r in rules if r["level"] == level]
    if db_type and db_type != "ALL":
        rules = [r for r in rules if r["db_type"] == db_type]
    if scene_type and scene_type != "ALL":
        rules = [r for r in rules if r.get("scene_type") == scene_type]
    if status and status != "ALL":
        rules = [r for r in rules if r["status"] == status]

    enabled_count = sum(1 for r in rules if r["status"] == "enabled")
    disabled_count = sum(1 for r in rules if r["status"] == "disabled")

    return {
        "rules": rules,
        "total": len(rules),
        "enabled_count": enabled_count,
        "disabled_count": disabled_count
    }


@router.put("/{rule_id}/toggle")
async def toggle_rule(
    rule_id: str,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """切换规则启用/禁用状态。

    关键变更（disable）使用同一 DB 事务同步写入审计日志。
    B15: 用户修改规则时标记 is_modified_by_user=True，防止 seed 覆盖。
    """
    rule_db = RuleConfigDatabase()

    rule = rule_db.get_by_rule_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail={"code": "DDL_002", "message": "规则不存在"})

    operator = current_user.get("username", "unknown")
    operator_id = current_user.get("id")

    old_snapshot = rule.to_dict()
    old_enabled = rule.enabled
    new_enabled = not rule.enabled

    # 切换状态
    rule_db.toggle(rule_id, new_enabled)
    # B15: 用户修改后标记为已修改，防止 seed 覆盖
    rule_db.mark_modified(rule_id)
    new_status = "enabled" if new_enabled else "disabled"

    # 失效缓存
    RuleCache.invalidate()

    # 关键变更（disable）同步写入审计日志，确保可靠性
    if not new_enabled:
        try:
            audit_logger.log_rule_change(
                rule_section=rule_id,
                change_type="toggle",
                operator=operator,
                operator_id=operator_id,
                old_value={"enabled": old_enabled},
                new_value={"enabled": new_enabled},
                description=f"规则 {rule_id} 状态切换: {old_enabled} -> {new_enabled}"
            )
        except Exception as e:
            logger.error("关键规则变更审计日志写入失败: %s", e)
            raise HTTPException(status_code=500, detail={"code": "DDL_500", "message": "审计日志写入失败"})
    else:
        # 一般变更可用异步
        try:
            audit_logger.log_rule_change(
                rule_section=rule_id,
                change_type="toggle",
                operator=operator,
                operator_id=operator_id,
                old_value={"enabled": old_enabled},
                new_value={"enabled": new_enabled},
                description=f"规则 {rule_id} 状态切换: {old_enabled} -> {new_enabled}"
            )
        except Exception as e:
            logger.warning("规则变更审计日志写入失败: %s", e)

    return {
        "rule_id": rule_id,
        "status": new_status,
        "message": f"规则已{'启用' if new_enabled else '禁用'}"
    }


@router.post("/")
async def create_custom_rule(
    rule: ValidationRule,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """创建自定义规则"""
    rule_db = RuleConfigDatabase()

    existing = rule_db.get_by_rule_id(rule.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"规则 ID '{rule.id}' 已存在")

    # 获取操作人信息
    operator = current_user.get("username", "unknown")
    operator_id = current_user.get("id")

    new_rule = rule_db.create_rule(
        rule_id=rule.id,
        name=rule.name,
        level=rule.level,
        category=rule.category,
        display_group=rule.display_group or "other",
        description=rule.description,
        suggestion=rule.suggestion,
        db_type=rule.db_type,
        scene_type=rule.scene_type,
        is_custom=True,
        enabled=True,
        is_modified_by_user=True,  # 标记为用户创建的规则
    )

    # 失效缓存
    RuleCache.invalidate()

    # 异步写入审计日志
    try:
        audit_logger.log_rule_change(
            rule_section=new_rule.rule_id,
            change_type="create",
            operator=operator,
            operator_id=operator_id,
            old_value=None,
            new_value=new_rule.to_dict(),
            description=f"创建自定义规则 {new_rule.rule_id}"
        )
    except Exception as e:
        logger.warning("规则变更审计日志写入失败: %s", e)

    return {"rule": new_rule.to_dict(), "message": "自定义规则创建成功"}


class UpdateRuleRequest(BaseModel):
    """规则更新请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    level: Optional[str] = None
    category: Optional[str] = None
    display_group: Optional[str] = None
    suggestion: Optional[str] = None
    scene_type: Optional[str] = None
    config_json: Optional[dict] = None


@router.put("/{rule_id}")
async def update_rule(
    rule_id: str,
    body: UpdateRuleRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """更新规则字段。内置规则和自定义规则均可更新。"""
    rule_db = RuleConfigDatabase()

    rule = rule_db.get_by_rule_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail={"code": "DDL_002", "message": "规则不存在"})

    operator = current_user.get("username", "unknown")
    operator_id = current_user.get("id")
    old_snapshot = rule.to_dict()

    update_fields = body.model_dump(exclude_none=True)
    if not update_fields:
        raise HTTPException(status_code=400, detail={"code": "DDL_004", "message": "未提供更新字段"})

    updated_rule = rule_db.update_rule(rule_id, **update_fields)

    RuleCache.invalidate()

    try:
        audit_logger.log_rule_change(
            rule_section=rule_id,
            change_type="update",
            operator=operator,
            operator_id=operator_id,
            old_value=old_snapshot,
            new_value=updated_rule.to_dict(),
            description=f"更新规则 {rule_id}"
        )
    except Exception as e:
        logger.warning("规则变更审计日志写入失败: %s", e)

    return {"rule": updated_rule.to_dict(), "message": "规则更新成功"}


@router.delete("/{rule_id}")
async def delete_custom_rule(
    rule_id: str,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """删除自定义规则。

    删除操作使用同步 DB 事务写入审计日志，确保可靠性。
    """
    rule_db = RuleConfigDatabase()

    rule = rule_db.get_by_rule_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail={"code": "DDL_002", "message": "规则不存在"})
    if not rule.is_custom:
        raise HTTPException(status_code=403, detail={"code": "DDL_403", "message": "无法删除内置规则"})

    operator = current_user.get("username", "unknown")
    operator_id = current_user.get("id")

    old_snapshot = rule.to_dict()

    # 删除规则
    rule_db.delete(rule_id)

    # 失效缓存
    RuleCache.invalidate()

    # 同步写入审计日志（关键操作，必须确保成功）
    try:
        audit_logger.log_rule_change(
            rule_section=rule_id,
            change_type="delete",
            operator=operator,
            operator_id=operator_id,
            old_value=old_snapshot,
            new_value=None,
            description=f"删除自定义规则 {rule_id}"
        )
    except Exception as e:
        logger.error("关键规则删除审计日志写入失败: %s", e)
        raise HTTPException(status_code=500, detail={"code": "DDL_500", "message": "审计日志写入失败"})

    return {"message": "规则删除成功"}


@router.post("/test")
async def test_rule(
    body: DryRunRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """Dry Run：测试新规则对指定 DDL 的拦截效果（不保存规则）。

    用于管理员在修改规则配置后，预验证规则是否按预期拦截/放行。
    """

    from services.ddl_checker.parser import DDLParser

    rule = body.rule
    ddl_text = body.ddl_text
    db_type = body.db_type

    # 解析 DDL
    parser = DDLParser()
    try:
        table_info, parse_mode = parser.parse_create_table(ddl_text)
    except Exception as e:
        return {
            "code": "DDL_006",
            "message": f"Dry Run 失败: {str(e)}",
            "trace_id": "",
            "data": {
                "rule_id": rule.get("rule_id", "TEST"),
                "ddl_text": ddl_text,
                "hit": False,
                "violations": []
            }
        }

    if not table_info:
        return {
            "code": "DDL_001",
            "message": "无法解析 DDL 语句",
            "trace_id": "",
            "data": {
                "rule_id": rule.get("rule_id", "TEST"),
                "ddl_text": ddl_text,
                "hit": False,
                "violations": []
            }
        }

    # 临时应用规则进行测试
    # 注意：这里仅做简化验证，实际实现可能需要更复杂的规则引擎
    violations = []

    # 简单检查：按规则中的 pattern 进行正则匹配
    import re
    pattern = rule.get("pattern", "")
    check_target = rule.get("check_target", "table_name")

    if pattern:
        try:
            if check_target == "table_name":
                target_value = table_info.name
                if not re.match(pattern, target_value):
                    violations.append({
                        "level": rule.get("level", "HIGH"),
                        "message": f"表名 '{target_value}' 不符合正则 {pattern}",
                        "suggestion": rule.get("suggestion", "")
                    })
        except re.error:
            return {
                "code": "DDL_006",
                "message": f"规则正则表达式无效: {pattern}",
                "trace_id": "",
                "data": {
                    "rule_id": rule.get("rule_id", "TEST"),
                    "ddl_text": ddl_text,
                    "hit": False,
                    "violations": []
                }
            }

    return {
        "code": "DDL_000",
        "message": "Dry Run 完成",
        "trace_id": "",
        "data": {
            "rule_id": rule.get("rule_id", "TEST"),
            "ddl_text": ddl_text,
            "hit": len(violations) > 0,
            "violations": violations
        }
    }
