"""seed_starrocks_rules

Revision ID: 20260427_0002
Revises: add_ddl_compliance_fields
Create Date: 2026-04-27 00:02:00.000000

Spec 35 StarRocks 合规批次 B18:
- 向 bi_rule_configs 表 Seed 25 条 StarRocks 规则（RULE_SR_001~025）
- 与 DEFAULT_RULES_SEED 保持一致，确保幂等性
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260427_0002"
down_revision: Union[str, None] = "add_ddl_compliance_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 25 条 StarRocks 规则（与 app/api/rules.py DEFAULT_RULES_SEED 对应）
STARROCKS_RULES_SEED = [
    {
        "rule_id": "RULE_SR_001",
        "name": "ODS 双下划线命名",
        "level": "HIGH",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ODS",
        "description": "ODS 层表名必须使用 {系统}__{模块}__{原表} 格式",
        "suggestion": "表名格式示例: erp__order__sales_order",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "pattern": "^[a-z]+__[a-z0-9_]+__[a-z0-9_]+$",
            "databases": ["ods_db", "ods_api", "ods_log"]
        },
    },
    {
        "rule_id": "RULE_SR_002",
        "name": "DWD 业务域+粒度后缀",
        "level": "HIGH",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "DWD",
        "description": "DWD 层表名必须使用 {业务域}_{含义}_{粒度后缀} 格式",
        "suggestion": "粒度后缀: _di(日增量), _df(日全量), _hi(小时增量), _rt(实时)",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "pattern": "^(sales|finance|supply|hr|market|risk|ops|product|ai)_.*_(di|df|hi|rt)$",
            "databases": ["dwd"]
        },
    },
    {
        "rule_id": "RULE_SR_003",
        "name": "DIM 无业务域前缀",
        "level": "HIGH",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "DIM 层表不应使用业务域前缀，应为通用维度命名",
        "suggestion": "表名格式: dim_xxx，不要带 sales_/finance_ 等业务前缀",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "forbidden_prefixes": ["sales_", "finance_", "supply_", "hr_", "market_", "risk_", "ops_", "product_", "ai_"],
            "databases": ["dim"]
        },
    },
    {
        "rule_id": "RULE_SR_004",
        "name": "DWS 粒度后缀",
        "level": "HIGH",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "DWS 层表名必须包含粒度后缀",
        "suggestion": "表名末尾应为 _1d, _1h, _1m, _rt",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "_(1d|1h|1m|rt)$", "databases": ["dws"]},
    },
    {
        "rule_id": "RULE_SR_005",
        "name": "ADS 场景前缀",
        "level": "HIGH",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "ADS 层表名必须包含场景前缀",
        "suggestion": "表名前缀: board_, report_, api_, ai_, tag_, label_",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "^(board|report|api|ai|tag|label)_", "databases": ["ads"]},
    },
    {
        "rule_id": "RULE_SR_006",
        "name": "金额字段必须 DECIMAL",
        "level": "HIGH",
        "category": "sr_type_alignment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "金额字段（_amt/_amount 后缀）必须使用 DECIMAL 类型",
        "suggestion": "使用 DECIMAL(20,4)，禁止 FLOAT/DOUBLE",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "suffixes": ["_amt", "_amount"],
            "required_type": "DECIMAL",
            "forbidden_types": ["FLOAT", "DOUBLE"]
        },
    },
    {
        "rule_id": "RULE_SR_007",
        "name": "日期字段禁止 VARCHAR",
        "level": "HIGH",
        "category": "sr_type_alignment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "日期时间字段（_time/_at/_dt 后缀）必须使用时间类型",
        "suggestion": "使用 DATETIME/DATE/TIMESTAMP，禁止 VARCHAR/CHAR/STRING",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "suffixes": ["_time", "_at", "_dt"],
            "required_types": ["DATETIME", "DATE", "TIMESTAMP"],
            "forbidden_types": ["VARCHAR", "CHAR", "STRING"]
        },
    },
    {
        "rule_id": "RULE_SR_008",
        "name": "公共字段 etl_time",
        "level": "HIGH",
        "category": "sr_public_fields",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "所有表必须包含 etl_time DATETIME 字段",
        "suggestion": "添加 etl_time DATETIME 字段记录 ETL 处理时间",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"required_fields": [{"name": "etl_time", "type": "DATETIME"}], "databases": "__all__"},
    },
    {
        "rule_id": "RULE_SR_009",
        "name": "公共字段 dt",
        "level": "HIGH",
        "category": "sr_public_fields",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "ODS/DWD/DWS/DM 表必须包含 dt DATE 分区字段",
        "suggestion": "添加 dt DATE 字段作为分区键",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"required_fields": [{"name": "dt", "type": "DATE"}], "databases": ["ods_db", "ods_api", "ods_log", "dwd", "dws", "dm"]},
    },
    {
        "rule_id": "RULE_SR_010",
        "name": "ODS 全套公共字段",
        "level": "HIGH",
        "category": "sr_public_fields",
        "db_type": "StarRocks",
        "scene_type": "ODS",
        "description": "ODS 层表必须包含 etl_batch_id/src_system/src_table/is_deleted 公共字段",
        "suggestion": "添加 ODS 全套公共字段",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "required_fields": [
                {"name": "etl_batch_id", "type": "VARCHAR"},
                {"name": "src_system", "type": "VARCHAR"},
                {"name": "src_table", "type": "VARCHAR"},
                {"name": "is_deleted", "type": "TINYINT"}
            ],
            "databases": ["ods_db", "ods_api", "ods_log"]
        },
    },
    {
        "rule_id": "RULE_SR_011",
        "name": "ODS_DB CDC 字段",
        "level": "HIGH",
        "category": "sr_public_fields",
        "db_type": "StarRocks",
        "scene_type": "ODS",
        "description": "ODS_DB 表必须包含 src_op/src_ts CDC 操作字段",
        "suggestion": "添加 src_op VARCHAR 和 src_ts DATETIME 字段",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "required_fields": [{"name": "src_op", "type": "VARCHAR"}, {"name": "src_ts", "type": "DATETIME"}],
            "databases": ["ods_db"]
        },
    },
    {
        "rule_id": "RULE_SR_012",
        "name": "字段 snake_case",
        "level": "HIGH",
        "category": "sr_field_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "所有字段名必须使用 snake_case 命名",
        "suggestion": "字段名使用小写字母+数字+下划线，长度不超过 40",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "^[a-z][a-z0-9_]*$", "max_length": 40},
    },
    {
        "rule_id": "RULE_SR_013",
        "name": "字段注释覆盖率",
        "level": "HIGH",
        "category": "sr_comment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "所有字段必须有注释，覆盖率 100%",
        "suggestion": "为每个字段添加 COMMENT",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"min_coverage": 1.0},
    },
    {
        "rule_id": "RULE_SR_014",
        "name": "表注释存在",
        "level": "HIGH",
        "category": "sr_comment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "所有表必须包含注释说明用途",
        "suggestion": "使用 COMMENT 说明表的业务含义和数据粒度",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {},
    },
    {
        "rule_id": "RULE_SR_015",
        "name": "禁止额外数据库",
        "level": "HIGH",
        "category": "sr_database_whitelist",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "StarRocks 实例中只允许规划内的数据库",
        "suggestion": "联系管理员确认数据库是否在规划列表中",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "allowed": ["ods_db", "ods_api", "ods_log", "dwd", "dim", "dws", "dm", "ads", "feature", "ai", "sandbox", "tmp", "ops", "meta", "backup", "information_schema", "_statistics_"]
        },
    },
    {
        "rule_id": "RULE_SR_016",
        "name": "Feature 表命名",
        "level": "MEDIUM",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "Feature 层表名必须包含特征粒度后缀",
        "suggestion": "表名格式: xxx_features_1d/1h/rt",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "_features_(1d|1h|rt|[0-9]+[dhm])$", "databases": ["feature"]},
    },
    {
        "rule_id": "RULE_SR_017",
        "name": "AI 表前缀",
        "level": "MEDIUM",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "AI 层表名必须使用 kb/llm/agent/text2sql 前缀",
        "suggestion": "表名前缀: kb_, llm_, agent_, text2sql_",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "^(kb|llm|agent|text2sql)_", "databases": ["ai"]},
    },
    {
        "rule_id": "RULE_SR_018",
        "name": "Backup 命名含日期",
        "level": "MEDIUM",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "Backup 层表名必须包含 8 位日期后缀",
        "suggestion": "表名格式: xxx__yyy_20260101",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "__.*_\\d{8}$", "databases": ["backup"]},
    },
    {
        "rule_id": "RULE_SR_019",
        "name": "数量字段类型",
        "level": "HIGH",
        "category": "sr_type_alignment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "数量字段（_qty/_cnt 后缀）必须使用整数或精确数值类型",
        "suggestion": "使用 BIGINT/DECIMAL/INT，禁止 FLOAT/DOUBLE",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "suffixes": ["_qty", "_cnt"],
            "required_types": ["BIGINT", "DECIMAL", "INT"],
            "forbidden_types": ["FLOAT", "DOUBLE"]
        },
    },
    {
        "rule_id": "RULE_SR_020",
        "name": "比率字段类型",
        "level": "HIGH",
        "category": "sr_type_alignment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "比率字段（_rate 后缀）必须使用 DECIMAL 类型",
        "suggestion": "使用 DECIMAL(10,6)，禁止 FLOAT/DOUBLE",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "suffixes": ["_rate"],
            "required_type": "DECIMAL",
            "forbidden_types": ["FLOAT", "DOUBLE"]
        },
    },
    {
        "rule_id": "RULE_SR_021",
        "name": "无 ods_hive 库",
        "level": "HIGH",
        "category": "sr_database_whitelist",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "StarRocks 实例中不应存在 ods_hive 数据库（ADR-003 迁移要求）",
        "suggestion": "将 ods_hive 数据迁移至 ods_db/ods_api/ods_log",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"forbidden": ["ods_hive"]},
    },
    {
        "rule_id": "RULE_SR_022",
        "name": "表名无中文",
        "level": "HIGH",
        "category": "sr_table_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "表名不允许包含中文字符",
        "suggestion": "表名只使用英文字母、数字、下划线",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern_forbidden": "[\\u4e00-\\u9fff]"},
    },
    {
        "rule_id": "RULE_SR_023",
        "name": "表名无版本号",
        "level": "MEDIUM",
        "category": "sr_table_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "表名不应包含版本号（如 _v2）",
        "suggestion": "使用 DDL 变更管理，不要在表名中加版本号",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern_forbidden": "_v\\d+"},
    },
    {
        "rule_id": "RULE_SR_024",
        "name": "DM 部门前缀",
        "level": "MEDIUM",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "DM 层表名使用宽松 snake_case",
        "suggestion": "表名格式: 部门_主题_含义",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "^[a-z][a-z0-9_]+$", "databases": ["dm"]},
    },
    {
        "rule_id": "RULE_SR_025",
        "name": "视图命名 _vw 后缀",
        "level": "MEDIUM",
        "category": "sr_view_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "所有视图必须以 _vw 后缀命名",
        "suggestion": "视图命名: xxx_vw",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "_vw$"},
    },
]


def upgrade() -> None:
    """Seed 25 条 StarRocks 规则到 bi_rule_configs 表（幂等性 UPSERT）"""
    for rule in STARROCKS_RULES_SEED:
        rule_id = rule["rule_id"]
        config_json = rule.pop("config_json")

        # PostgreSQL UPSERT: ON CONFLICT (rule_id) DO UPDATE SET ...
        # 仅当 is_modified_by_user=FALSE 时覆盖（保留用户修改）
        stmt = postgresql.insert(sa.text("bi_rule_configs")).values(
            rule_id=rule_id,
            name=rule["name"],
            description=rule["description"],
            level=rule["level"],
            category=rule["category"],
            db_type=rule["db_type"],
            suggestion=rule["suggestion"],
            enabled=rule["enabled"],
            is_custom=rule["is_custom"],
            is_modified_by_user=rule["is_modified_by_user"],
            scene_type=rule["scene_type"],
            config_json=postgresql.JSONB.NULL if not config_json else config_json,
        )

        # 构造 ON CONFLICT 子句：rule_id 冲突时，仅更新未标记为用户修改的字段
        stmt = stmt.on_conflict_do_update(
            index_elements=["rule_id"],
            index_where=sa.text("is_modified_by_user = FALSE"),
            set_={
                "name": rule["name"],
                "description": rule["description"],
                "level": rule["level"],
                "category": rule["category"],
                "db_type": rule["db_type"],
                "suggestion": rule["suggestion"],
                "enabled": rule["enabled"],
                "is_custom": rule["is_custom"],
                "scene_type": rule["scene_type"],
                "config_json": postgresql.JSONB.NULL if not config_json else config_json,
            },
        )
        op.execute(stmt)


def downgrade() -> None:
    """删除 StarRocks 规则（仅删除 StarRocks db_type 的内置规则）"""
    op.execute(
        sa.text("DELETE FROM bi_rule_configs WHERE db_type = 'StarRocks' AND is_custom = FALSE")
    )
