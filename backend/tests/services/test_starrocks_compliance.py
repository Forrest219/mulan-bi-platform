"""
StarRocks 合规检查单元测试 — SPEC 35 §9.1

覆盖范围：
- 连接器 StarRocks 分支（连接串、端口、超时）
- 规则 db_type 过滤（MySQL/StarRocks 隔离）
- 分层命名检查（ODS/DWD/DIM/ADS）
- 字段类型对齐检查（金额/日期/数量/比率）
- 公共字段检查（etl_time/etl_batch_id/src_op）
- 注释检查（表注释/字段注释覆盖率）
- 数据库白名单检查
- 表名通用检查（中文、版本号）
- db_type 隔离（MySQL 扫描不触发 SR 规则）
- 种子规则结构验证
"""
from typing import List, Optional

import pytest
from unittest.mock import patch, MagicMock

from services.ddl_checker.connector import DatabaseConnector
from services.ddl_checker.validator import (
    DatabaseRulesAdapter,
    TableValidator,
    ColumnValidator,
    ViolationLevel,
    Violation,
)
from services.ddl_checker.parser import TableInfo, ColumnInfo, IndexInfo


# ---------------------------------------------------------------------------
# 辅助工厂函数
# ---------------------------------------------------------------------------

def _make_column(name: str, data_type: str, comment: str = "") -> ColumnInfo:
    """快速构造 ColumnInfo"""
    return ColumnInfo(name=name, data_type=data_type, comment=comment)


def _make_table(
    name: str,
    columns: Optional[List[ColumnInfo]] = None,
    comment: str = "",
    database: str = "",
) -> TableInfo:
    """快速构造 TableInfo"""
    if columns is None:
        columns = [_make_column("id", "BIGINT", "主键")]
    return TableInfo(name=name, columns=columns, comment=comment, database=database)


# ---------------------------------------------------------------------------
# 规则 fixtures
# ---------------------------------------------------------------------------

def _sr_layer_naming_rules() -> List[dict]:
    """ODS/DWD/DIM/ADS 分层命名规则"""
    return [
        {
            "rule_id": "RULE_SR_001",
            "name": "ODS 双下划线命名",
            "level": "HIGH",
            "category": "sr_layer_naming",
            "db_type": "StarRocks",
            "suggestion": "表名格式示例: erp__order__sales_order",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ODS",
            "config_json": {
                "pattern": "^[a-z]+__[a-z0-9_]+__[a-z0-9_]+$",
                "databases": ["ods_db", "ods_api", "ods_log"],
            },
        },
        {
            "rule_id": "RULE_SR_002",
            "name": "DWD 业务域+粒度后缀",
            "level": "HIGH",
            "category": "sr_layer_naming",
            "db_type": "StarRocks",
            "suggestion": "粒度后缀: _di(日增量), _df(日全量), _hi(小时增量), _rt(实时)",
            "enabled": True,
            "is_custom": False,
            "scene_type": "DWD",
            "config_json": {
                "pattern": "^(sales|finance|supply|hr|market|risk|ops|product|ai)_.*_(di|df|hi|rt)$",
                "databases": ["dwd"],
            },
        },
        {
            "rule_id": "RULE_SR_003",
            "name": "DIM 无业务域前缀",
            "level": "HIGH",
            "category": "sr_layer_naming",
            "db_type": "StarRocks",
            "suggestion": "DIM 表不应使用业务域前缀",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {
                "forbidden_prefixes": [
                    "sales_", "finance_", "supply_", "hr_",
                    "market_", "risk_", "ops_", "product_", "ai_",
                ],
                "databases": ["dim"],
            },
        },
        {
            "rule_id": "RULE_SR_005",
            "name": "ADS 场景前缀",
            "level": "HIGH",
            "category": "sr_layer_naming",
            "db_type": "StarRocks",
            "suggestion": "表名前缀: board_, report_, api_, ai_, tag_, label_",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {
                "pattern": "^(board|report|api|ai|tag|label)_",
                "databases": ["ads"],
            },
        },
    ]


def _sr_type_alignment_rules() -> List[dict]:
    """字段后缀与类型对齐规则"""
    return [
        {
            "rule_id": "RULE_SR_006",
            "name": "金额字段必须 DECIMAL",
            "level": "HIGH",
            "category": "sr_type_alignment",
            "db_type": "StarRocks",
            "suggestion": "使用 DECIMAL(20,4)，禁止 FLOAT/DOUBLE",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {
                "suffixes": ["_amt", "_amount"],
                "required_type": "DECIMAL",
                "forbidden_types": ["FLOAT", "DOUBLE"],
            },
        },
        {
            "rule_id": "RULE_SR_007",
            "name": "日期字段禁止 VARCHAR",
            "level": "HIGH",
            "category": "sr_type_alignment",
            "db_type": "StarRocks",
            "suggestion": "使用 DATETIME/DATE/TIMESTAMP",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {
                "suffixes": ["_time", "_at", "_dt"],
                "required_types": ["DATETIME", "DATE", "TIMESTAMP"],
                "forbidden_types": ["VARCHAR", "CHAR", "STRING"],
            },
        },
        {
            "rule_id": "RULE_SR_019",
            "name": "数量字段类型",
            "level": "HIGH",
            "category": "sr_type_alignment",
            "db_type": "StarRocks",
            "suggestion": "使用 BIGINT/DECIMAL/INT",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {
                "suffixes": ["_qty", "_cnt"],
                "required_types": ["BIGINT", "DECIMAL", "INT"],
                "forbidden_types": ["FLOAT", "DOUBLE"],
            },
        },
        {
            "rule_id": "RULE_SR_020",
            "name": "比率字段类型",
            "level": "HIGH",
            "category": "sr_type_alignment",
            "db_type": "StarRocks",
            "suggestion": "使用 DECIMAL(10,6)",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {
                "suffixes": ["_rate"],
                "required_type": "DECIMAL",
                "forbidden_types": ["FLOAT", "DOUBLE"],
            },
        },
    ]


def _sr_public_fields_rules() -> List[dict]:
    """公共字段规则"""
    return [
        {
            "rule_id": "RULE_SR_008",
            "name": "公共字段 etl_time",
            "level": "HIGH",
            "category": "sr_public_fields",
            "db_type": "StarRocks",
            "suggestion": "添加 etl_time DATETIME 字段",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {
                "required_fields": [{"name": "etl_time", "type": "DATETIME"}],
                "databases": "__all__",
            },
        },
        {
            "rule_id": "RULE_SR_010",
            "name": "ODS 全套公共字段",
            "level": "HIGH",
            "category": "sr_public_fields",
            "db_type": "StarRocks",
            "suggestion": "添加 ODS 全套公共字段",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ODS",
            "config_json": {
                "required_fields": [
                    {"name": "etl_batch_id", "type": "VARCHAR"},
                    {"name": "src_system", "type": "VARCHAR"},
                    {"name": "src_table", "type": "VARCHAR"},
                    {"name": "is_deleted", "type": "TINYINT"},
                ],
                "databases": ["ods_db", "ods_api", "ods_log"],
            },
        },
        {
            "rule_id": "RULE_SR_011",
            "name": "ODS_DB CDC 字段",
            "level": "HIGH",
            "category": "sr_public_fields",
            "db_type": "StarRocks",
            "suggestion": "添加 src_op VARCHAR 和 src_ts DATETIME 字段",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ODS",
            "config_json": {
                "required_fields": [
                    {"name": "src_op", "type": "VARCHAR"},
                    {"name": "src_ts", "type": "DATETIME"},
                ],
                "databases": ["ods_db"],
            },
        },
    ]


def _sr_comment_rules() -> List[dict]:
    """注释检查规则"""
    return [
        {
            "rule_id": "RULE_SR_013",
            "name": "字段注释覆盖率",
            "level": "HIGH",
            "category": "sr_comment",
            "db_type": "StarRocks",
            "suggestion": "为每个字段添加 COMMENT",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {"min_coverage": 1.0},
        },
        {
            "rule_id": "RULE_SR_014",
            "name": "表注释存在",
            "level": "HIGH",
            "category": "sr_comment",
            "db_type": "StarRocks",
            "suggestion": "使用 COMMENT 说明表的业务含义和数据粒度",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {},
        },
    ]


def _sr_database_whitelist_rules() -> List[dict]:
    """数据库白名单规则"""
    return [
        {
            "rule_id": "RULE_SR_015",
            "name": "禁止额外数据库",
            "level": "HIGH",
            "category": "sr_database_whitelist",
            "db_type": "StarRocks",
            "suggestion": "联系管理员确认数据库是否在规划列表中",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {
                "allowed": [
                    "ods_db", "ods_api", "ods_log", "dwd", "dim",
                    "dws", "dm", "ads", "feature", "ai", "sandbox",
                    "tmp", "ops", "meta", "backup",
                    "information_schema", "_statistics_",
                ],
            },
        },
        {
            "rule_id": "RULE_SR_021",
            "name": "无 ods_hive 库",
            "level": "HIGH",
            "category": "sr_database_whitelist",
            "db_type": "StarRocks",
            "suggestion": "将 ods_hive 数据迁移至 ods_db/ods_api/ods_log",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {"forbidden": ["ods_hive"]},
        },
    ]


def _sr_table_naming_rules() -> List[dict]:
    """表名通用检查规则（中文、版本号）"""
    return [
        {
            "rule_id": "RULE_SR_022",
            "name": "表名无中文",
            "level": "HIGH",
            "category": "sr_table_naming",
            "db_type": "StarRocks",
            "suggestion": "表名只使用英文字母、数字、下划线",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {"pattern_forbidden": "[\\u4e00-\\u9fff]"},
        },
        {
            "rule_id": "RULE_SR_023",
            "name": "表名无版本号",
            "level": "MEDIUM",
            "category": "sr_table_naming",
            "db_type": "StarRocks",
            "suggestion": "使用 DDL 变更管理，不要在表名中加版本号",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {"pattern_forbidden": "_v\\d+"},
        },
    ]


def _make_adapter(rules: List[dict]) -> DatabaseRulesAdapter:
    """构造一个带预置规则缓存的 DatabaseRulesAdapter（跳过 DB/Redis）"""
    adapter = DatabaseRulesAdapter(scene_type="ALL", db_type="StarRocks")
    adapter._rules_cache = rules
    adapter._load_rules = lambda: rules
    return adapter


def _mysql_only_rules() -> List[dict]:
    """仅含 MySQL 规则的列表"""
    return [
        {
            "rule_id": "RULE_001",
            "name": "表命名规范",
            "level": "HIGH",
            "category": "table_naming",
            "db_type": "MySQL",
            "suggestion": "表名格式: dim_xxx, fact_xxx",
            "enabled": True,
            "is_custom": False,
            "scene_type": "ALL",
            "config_json": {"pattern": "^[a-z][a-z0-9_]*$", "max_length": 64},
        },
    ]


# ===========================================================================
# 1. 连接器测试
# ===========================================================================


class TestStarRocksConnector:
    """StarRocks 连接器测试"""

    def test_build_connection_string_starrocks(self):
        """StarRocks 使用 mysql+pymysql:// 协议，默认端口 9030"""
        connector = DatabaseConnector({
            "db_type": "starrocks",
            "host": "sr-host",
            "user": "root",
            "password": "pw",
            "database": "ods_db",
        })
        conn_str = connector._build_connection_string()
        assert conn_str == "mysql+pymysql://root:pw@sr-host:9030/ods_db"

    def test_build_connection_string_starrocks_custom_port(self):
        """自定义端口覆盖默认 9030"""
        connector = DatabaseConnector({
            "db_type": "starrocks",
            "host": "sr-host",
            "port": 19030,
            "user": "root",
            "password": "pw",
            "database": "dwd",
        })
        conn_str = connector._build_connection_string()
        assert "19030" in conn_str
        assert "9030" not in conn_str.replace("19030", "")

    def test_build_connection_string_mysql_default_port(self):
        """MySQL 默认端口 3306，确认与 StarRocks 互不干扰"""
        connector = DatabaseConnector({
            "db_type": "mysql",
            "host": "mysql-host",
            "user": "root",
            "password": "pw",
            "database": "test_db",
        })
        conn_str = connector._build_connection_string()
        assert ":3306/" in conn_str

    def test_connect_timeout_starrocks(self):
        """StarRocks 连接应设置 connect_timeout=10"""
        connector = DatabaseConnector({
            "db_type": "starrocks",
            "host": "sr-host",
            "user": "root",
            "password": "pw",
            "database": "ods_db",
        })
        # 拦截 create_engine 验证 connect_args
        with patch("services.ddl_checker.connector.create_engine") as mock_ce, \
             patch("services.ddl_checker.connector.inspect"):
            mock_ce.return_value = MagicMock()
            connector.connect()
            _, kwargs = mock_ce.call_args
            assert kwargs["connect_args"]["connect_timeout"] == 10

    def test_connect_timeout_mysql(self):
        """MySQL 连接也应设置 connect_timeout=10"""
        connector = DatabaseConnector({
            "db_type": "mysql",
            "host": "mysql-host",
            "user": "root",
            "password": "pw",
            "database": "db",
        })
        with patch("services.ddl_checker.connector.create_engine") as mock_ce, \
             patch("services.ddl_checker.connector.inspect"):
            mock_ce.return_value = MagicMock()
            connector.connect()
            _, kwargs = mock_ce.call_args
            assert kwargs["connect_args"]["connect_timeout"] == 10

    def test_get_table_comment_supports_starrocks(self):
        """get_table_comment 在 db_type='starrocks' 时走 information_schema 路径"""
        connector = DatabaseConnector({"db_type": "starrocks"})
        # 使用 starrocks 的 db_type，方法应尝试 information_schema 查询
        # 未连接时会抛出 RuntimeError
        with pytest.raises(RuntimeError, match="请先连接数据库"):
            connector.get_table_comment("some_table")


# ===========================================================================
# 2. 规则加载 / db_type 过滤测试
# ===========================================================================


class TestDbTypeFiltering:
    """db_type 过滤测试"""

    def test_load_rules_filters_by_db_type_mysql(self):
        """MySQL 适配器只加载 MySQL 和 all 类型的规则，不加载 StarRocks"""
        mixed_rules = _mysql_only_rules() + _sr_layer_naming_rules()

        # _load_rules 需要从 DB 加载，这里直接测试过滤逻辑
        adapter = DatabaseRulesAdapter(scene_type="ALL", db_type="MySQL")
        # 模拟 DB 返回所有规则
        mock_rule_objects = []
        for r in mixed_rules:
            mock_obj = MagicMock()
            mock_obj.enabled = r["enabled"]
            mock_obj.db_type = r["db_type"]
            mock_obj.rule_id = r["rule_id"]
            mock_obj.name = r["name"]
            mock_obj.description = r.get("description", "")
            mock_obj.level = r["level"]
            mock_obj.category = r["category"]
            mock_obj.suggestion = r["suggestion"]
            mock_obj.is_custom = r["is_custom"]
            mock_obj.scene_type = r["scene_type"]
            mock_obj.config_json = r.get("config_json", {})
            mock_rule_objects.append(mock_obj)

        with patch("services.ddl_checker.validator.RuleCache") as mock_cache:
            mock_cache.get.return_value = None
            mock_cache.set.return_value = True

            with patch("services.rules.models.RuleConfigDatabase") as mock_db_cls:
                mock_db = MagicMock()
                mock_db.get_all.return_value = mock_rule_objects
                mock_db_cls.return_value = mock_db

                loaded = adapter._load_rules()

        # MySQL adapter 不应包含 StarRocks 规则
        sr_rules = [r for r in loaded if r["db_type"] == "StarRocks"]
        assert len(sr_rules) == 0
        mysql_rules = [r for r in loaded if r["db_type"] == "MySQL"]
        assert len(mysql_rules) >= 1

    def test_load_rules_starrocks_loads_sr_rules(self):
        """StarRocks 适配器加载 StarRocks 和 all 类型规则"""
        mixed_rules = _mysql_only_rules() + _sr_layer_naming_rules()

        adapter = DatabaseRulesAdapter(scene_type="ALL", db_type="StarRocks")
        mock_rule_objects = []
        for r in mixed_rules:
            mock_obj = MagicMock()
            mock_obj.enabled = r["enabled"]
            mock_obj.db_type = r["db_type"]
            mock_obj.rule_id = r["rule_id"]
            mock_obj.name = r["name"]
            mock_obj.description = r.get("description", "")
            mock_obj.level = r["level"]
            mock_obj.category = r["category"]
            mock_obj.suggestion = r["suggestion"]
            mock_obj.is_custom = r["is_custom"]
            mock_obj.scene_type = r["scene_type"]
            mock_obj.config_json = r.get("config_json", {})
            mock_rule_objects.append(mock_obj)

        with patch("services.ddl_checker.validator.RuleCache") as mock_cache:
            mock_cache.get.return_value = None
            mock_cache.set.return_value = True

            with patch("services.rules.models.RuleConfigDatabase") as mock_db_cls:
                mock_db = MagicMock()
                mock_db.get_all.return_value = mock_rule_objects
                mock_db_cls.return_value = mock_db

                loaded = adapter._load_rules()

        sr_rules = [r for r in loaded if r["db_type"] == "StarRocks"]
        assert len(sr_rules) >= 1
        # MySQL 专属规则不应出现
        mysql_only = [r for r in loaded if r["db_type"] == "MySQL"]
        assert len(mysql_only) == 0

    def test_load_rules_includes_all_type(self):
        """db_type='all' 的规则对任何数据库类型都会加载"""
        rules_with_all = [
            {
                "rule_id": "RULE_UNIVERSAL_001",
                "name": "通用规则",
                "level": "MEDIUM",
                "category": "general",
                "db_type": "all",
                "suggestion": "通用建议",
                "enabled": True,
                "is_custom": False,
                "scene_type": "ALL",
                "config_json": {},
            },
        ]
        adapter = DatabaseRulesAdapter(scene_type="ALL", db_type="StarRocks")
        mock_objs = []
        for r in rules_with_all:
            obj = MagicMock()
            obj.enabled = True
            obj.db_type = r["db_type"]
            obj.rule_id = r["rule_id"]
            obj.name = r["name"]
            obj.description = ""
            obj.level = r["level"]
            obj.category = r["category"]
            obj.suggestion = r["suggestion"]
            obj.is_custom = False
            obj.scene_type = r["scene_type"]
            obj.config_json = r["config_json"]
            mock_objs.append(obj)

        with patch("services.ddl_checker.validator.RuleCache") as mock_cache:
            mock_cache.get.return_value = None
            mock_cache.set.return_value = True
            with patch("services.rules.models.RuleConfigDatabase") as mock_db_cls:
                mock_db = MagicMock()
                mock_db.get_all.return_value = mock_objs
                mock_db_cls.return_value = mock_db
                loaded = adapter._load_rules()

        assert len(loaded) == 1
        assert loaded[0]["rule_id"] == "RULE_UNIVERSAL_001"

    def test_find_sr_rules_by_category(self):
        """_find_sr_rules_by_category 返回匹配 category 的规则列表"""
        adapter = _make_adapter(_sr_layer_naming_rules())
        found = adapter._find_sr_rules_by_category("sr_layer_naming")
        assert len(found) == 4
        # 不存在的 category 返回空列表
        assert len(adapter._find_sr_rules_by_category("sr_nonexistent")) == 0


# ===========================================================================
# 3. StarRocks 分层命名检查
# ===========================================================================


class TestSrLayerNaming:
    """SR-001~005: 分层命名合规检查"""

    def test_ods_table_without_double_underscore_fails(self):
        """SR-001: ODS 表不含双下划线 → HIGH 违规"""
        adapter = _make_adapter(_sr_layer_naming_rules())
        validator = TableValidator(adapter)
        # ods_db 库中的不合规表名
        table = _make_table("bad_ods_table", database="ods_db")
        violations = validator._check_sr_layer_naming(table)
        assert len(violations) >= 1
        assert any(v.rule_name == "RULE_SR_001" for v in violations)
        assert any(v.level == ViolationLevel.ERROR for v in violations)

    def test_ods_table_with_correct_naming_passes(self):
        """SR-001: erp__order__sales_order → 无违规"""
        adapter = _make_adapter(_sr_layer_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("erp__order__sales_order", database="ods_db")
        violations = validator._check_sr_layer_naming(table)
        sr001 = [v for v in violations if v.rule_name == "RULE_SR_001"]
        assert len(sr001) == 0

    def test_dwd_table_without_granularity_suffix_fails(self):
        """SR-002: DWD 表不含 _di/_df/_hi/_rt 后缀 → HIGH 违规"""
        adapter = _make_adapter(_sr_layer_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("sales_order_detail", database="dwd")
        violations = validator._check_sr_layer_naming(table)
        assert any(v.rule_name == "RULE_SR_002" for v in violations)

    def test_dwd_table_with_correct_naming_passes(self):
        """SR-002: sales_order_detail_di → 无违规"""
        adapter = _make_adapter(_sr_layer_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("sales_order_detail_di", database="dwd")
        violations = validator._check_sr_layer_naming(table)
        sr002 = [v for v in violations if v.rule_name == "RULE_SR_002"]
        assert len(sr002) == 0

    def test_dim_table_with_business_prefix_fails(self):
        """SR-003: DIM 表以 sales_ 开头 → HIGH 违规"""
        adapter = _make_adapter(_sr_layer_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("sales_region", database="dim")
        violations = validator._check_sr_layer_naming(table)
        assert any(v.rule_name == "RULE_SR_003" for v in violations)

    def test_dim_table_without_business_prefix_passes(self):
        """SR-003: dim_region → 无违规（无禁止前缀）"""
        adapter = _make_adapter(_sr_layer_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("dim_region", database="dim")
        violations = validator._check_sr_layer_naming(table)
        sr003 = [v for v in violations if v.rule_name == "RULE_SR_003"]
        assert len(sr003) == 0

    def test_ads_table_without_scene_prefix_fails(self):
        """SR-005: ADS 表不含 board_/report_/... 前缀 → HIGH 违规"""
        adapter = _make_adapter(_sr_layer_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("user_summary_daily", database="ads")
        violations = validator._check_sr_layer_naming(table)
        assert any(v.rule_name == "RULE_SR_005" for v in violations)

    def test_ads_table_with_scene_prefix_passes(self):
        """SR-005: report_user_summary → 无违规"""
        adapter = _make_adapter(_sr_layer_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("report_user_summary", database="ads")
        violations = validator._check_sr_layer_naming(table)
        sr005 = [v for v in violations if v.rule_name == "RULE_SR_005"]
        assert len(sr005) == 0

    def test_non_matching_database_skipped(self):
        """规则不适用于非目标数据库时不触发"""
        adapter = _make_adapter(_sr_layer_naming_rules())
        validator = TableValidator(adapter)
        # 该表在 dws 库，ODS 规则不应触发
        table = _make_table("bad_table", database="dws")
        violations = validator._check_sr_layer_naming(table)
        sr001 = [v for v in violations if v.rule_name == "RULE_SR_001"]
        assert len(sr001) == 0


# ===========================================================================
# 4. 字段类型对齐检查
# ===========================================================================


class TestSrTypeAlignment:
    """SR-006, 007, 019, 020: 字段后缀与类型对齐检查"""

    def test_amount_field_with_float_fails(self):
        """SR-006: _amt 字段使用 FLOAT → HIGH 违规"""
        adapter = _make_adapter(_sr_type_alignment_rules())
        validator = ColumnValidator(adapter)
        table = _make_table("test_table", columns=[
            _make_column("order_amt", "FLOAT"),
        ])
        violations = validator._check_sr_type_alignment(table, table.columns[0])
        assert len(violations) >= 1
        assert any(v.rule_name == "RULE_SR_006" for v in violations)
        assert any(v.level == ViolationLevel.ERROR for v in violations)

    def test_amount_field_with_decimal_passes(self):
        """SR-006: _amt 字段使用 DECIMAL(20,4) → 无违规"""
        adapter = _make_adapter(_sr_type_alignment_rules())
        validator = ColumnValidator(adapter)
        table = _make_table("test_table", columns=[
            _make_column("order_amt", "DECIMAL(20,4)"),
        ])
        violations = validator._check_sr_type_alignment(table, table.columns[0])
        sr006 = [v for v in violations if v.rule_name == "RULE_SR_006"]
        assert len(sr006) == 0

    def test_date_field_with_varchar_fails(self):
        """SR-007: _time 字段使用 VARCHAR → HIGH 违规"""
        adapter = _make_adapter(_sr_type_alignment_rules())
        validator = ColumnValidator(adapter)
        table = _make_table("test_table", columns=[
            _make_column("create_time", "VARCHAR(20)"),
        ])
        violations = validator._check_sr_type_alignment(table, table.columns[0])
        assert any(v.rule_name == "RULE_SR_007" for v in violations)

    def test_date_field_with_datetime_passes(self):
        """SR-007: _time 字段使用 DATETIME → 无违规"""
        adapter = _make_adapter(_sr_type_alignment_rules())
        validator = ColumnValidator(adapter)
        table = _make_table("test_table", columns=[
            _make_column("create_time", "DATETIME"),
        ])
        violations = validator._check_sr_type_alignment(table, table.columns[0])
        sr007 = [v for v in violations if v.rule_name == "RULE_SR_007"]
        assert len(sr007) == 0

    def test_qty_field_with_float_fails(self):
        """SR-019: _qty 字段使用 FLOAT → HIGH 违规"""
        adapter = _make_adapter(_sr_type_alignment_rules())
        validator = ColumnValidator(adapter)
        table = _make_table("test_table", columns=[
            _make_column("order_qty", "FLOAT"),
        ])
        violations = validator._check_sr_type_alignment(table, table.columns[0])
        assert any(v.rule_name == "RULE_SR_019" for v in violations)

    def test_qty_field_with_bigint_passes(self):
        """SR-019: _qty 字段使用 BIGINT → 无违规"""
        adapter = _make_adapter(_sr_type_alignment_rules())
        validator = ColumnValidator(adapter)
        table = _make_table("test_table", columns=[
            _make_column("order_qty", "BIGINT"),
        ])
        violations = validator._check_sr_type_alignment(table, table.columns[0])
        sr019 = [v for v in violations if v.rule_name == "RULE_SR_019"]
        assert len(sr019) == 0

    def test_rate_field_with_decimal_passes(self):
        """SR-020: _rate 字段使用 DECIMAL → 无违规"""
        adapter = _make_adapter(_sr_type_alignment_rules())
        validator = ColumnValidator(adapter)
        table = _make_table("test_table", columns=[
            _make_column("tax_rate", "DECIMAL(10,6)"),
        ])
        violations = validator._check_sr_type_alignment(table, table.columns[0])
        sr020 = [v for v in violations if v.rule_name == "RULE_SR_020"]
        assert len(sr020) == 0

    def test_rate_field_with_double_fails(self):
        """SR-020: _rate 字段使用 DOUBLE → HIGH 违规"""
        adapter = _make_adapter(_sr_type_alignment_rules())
        validator = ColumnValidator(adapter)
        table = _make_table("test_table", columns=[
            _make_column("tax_rate", "DOUBLE"),
        ])
        violations = validator._check_sr_type_alignment(table, table.columns[0])
        assert any(v.rule_name == "RULE_SR_020" for v in violations)

    def test_non_matching_suffix_not_checked(self):
        """不匹配任何后缀的字段不触发类型对齐检查"""
        adapter = _make_adapter(_sr_type_alignment_rules())
        validator = ColumnValidator(adapter)
        table = _make_table("test_table", columns=[
            _make_column("user_name", "VARCHAR(100)"),
        ])
        violations = validator._check_sr_type_alignment(table, table.columns[0])
        assert len(violations) == 0


# ===========================================================================
# 5. 公共字段检查
# ===========================================================================


class TestSrPublicFields:
    """SR-008~011: 公共字段检查"""

    def test_ods_table_missing_etl_time_fails(self):
        """SR-008: ODS 表缺少 etl_time → HIGH 违规"""
        adapter = _make_adapter(_sr_public_fields_rules())
        validator = TableValidator(adapter)
        table = _make_table(
            "erp__order__sales",
            columns=[_make_column("id", "BIGINT")],
            database="ods_db",
        )
        violations = validator._check_sr_public_fields(table)
        assert any(v.rule_name == "RULE_SR_008" for v in violations)

    def test_ods_table_with_etl_time_passes(self):
        """SR-008: ODS 表包含 etl_time → 该规则无违规"""
        adapter = _make_adapter(_sr_public_fields_rules())
        validator = TableValidator(adapter)
        table = _make_table(
            "erp__order__sales",
            columns=[
                _make_column("id", "BIGINT"),
                _make_column("etl_time", "DATETIME"),
            ],
            database="ods_db",
        )
        violations = validator._check_sr_public_fields(table)
        sr008 = [v for v in violations if v.rule_name == "RULE_SR_008"]
        # etl_time 存在且类型匹配，无违规
        missing_etl = [v for v in sr008 if "etl_time" in v.message and "缺少" in v.message]
        assert len(missing_etl) == 0

    def test_ods_table_missing_etl_batch_id_fails(self):
        """SR-010: ODS 表缺少 etl_batch_id → HIGH 违规"""
        adapter = _make_adapter(_sr_public_fields_rules())
        validator = TableValidator(adapter)
        table = _make_table(
            "erp__order__sales",
            columns=[
                _make_column("id", "BIGINT"),
                _make_column("etl_time", "DATETIME"),
            ],
            database="ods_db",
        )
        violations = validator._check_sr_public_fields(table)
        assert any(
            v.rule_name == "RULE_SR_010" and "etl_batch_id" in v.message
            for v in violations
        )

    def test_ods_db_table_missing_src_op_fails(self):
        """SR-011: ods_db 表缺少 src_op → HIGH 违规"""
        adapter = _make_adapter(_sr_public_fields_rules())
        validator = TableValidator(adapter)
        table = _make_table(
            "erp__order__sales",
            columns=[_make_column("id", "BIGINT")],
            database="ods_db",
        )
        violations = validator._check_sr_public_fields(table)
        assert any(
            v.rule_name == "RULE_SR_011" and "src_op" in v.message
            for v in violations
        )

    def test_non_ods_db_table_no_src_op_check(self):
        """SR-011: 非 ods_db 库不检查 src_op"""
        adapter = _make_adapter(_sr_public_fields_rules())
        validator = TableValidator(adapter)
        table = _make_table(
            "some_table",
            columns=[_make_column("id", "BIGINT")],
            database="dwd",
        )
        violations = validator._check_sr_public_fields(table)
        sr011 = [v for v in violations if v.rule_name == "RULE_SR_011"]
        assert len(sr011) == 0


# ===========================================================================
# 6. 注释检查
# ===========================================================================


class TestSrComment:
    """SR-013, 014: 注释检查"""

    def test_table_without_comment_fails(self):
        """SR-014: 表无注释 → HIGH 违规"""
        adapter = _make_adapter(_sr_comment_rules())
        validator = TableValidator(adapter)
        table = _make_table("test_table", comment="")
        violations = validator._check_sr_comment(table)
        assert any(v.rule_name == "RULE_SR_014" for v in violations)
        assert any(v.level == ViolationLevel.ERROR for v in violations)

    def test_table_with_comment_passes(self):
        """SR-014: 表有注释 → 无违规"""
        adapter = _make_adapter(_sr_comment_rules())
        validator = TableValidator(adapter)
        table = _make_table("test_table", comment="订单明细表")
        violations = validator._check_sr_comment(table)
        sr014 = [v for v in violations if v.rule_name == "RULE_SR_014"]
        assert len(sr014) == 0

    def test_zero_column_comment_coverage_fails(self):
        """SR-013: 字段注释覆盖率 0% → HIGH 违规"""
        adapter = _make_adapter(_sr_comment_rules())
        validator = TableValidator(adapter)
        table = _make_table(
            "test_table",
            columns=[
                _make_column("id", "BIGINT", comment=""),
                _make_column("name", "VARCHAR(100)", comment=""),
            ],
            comment="有表注释",
        )
        violations = validator._check_sr_comment(table)
        assert any(v.rule_name == "RULE_SR_013" for v in violations)

    def test_full_column_comment_coverage_passes(self):
        """SR-013: 字段注释覆盖率 100% → 无违规"""
        adapter = _make_adapter(_sr_comment_rules())
        validator = TableValidator(adapter)
        table = _make_table(
            "test_table",
            columns=[
                _make_column("id", "BIGINT", comment="主键"),
                _make_column("name", "VARCHAR(100)", comment="名称"),
            ],
            comment="测试表",
        )
        violations = validator._check_sr_comment(table)
        sr013 = [v for v in violations if v.rule_name == "RULE_SR_013"]
        assert len(sr013) == 0


# ===========================================================================
# 7. 数据库白名单检查
# ===========================================================================


class TestSrDatabaseWhitelist:
    """SR-015, 021: 数据库白名单检查"""

    def test_ods_hive_database_fails(self):
        """SR-021: ods_hive 数据库 → HIGH 违规"""
        adapter = _make_adapter(_sr_database_whitelist_rules())
        validator = TableValidator(adapter)
        violations = validator._check_sr_database_whitelist(["ods_hive"])
        assert any(v.rule_name == "RULE_SR_021" for v in violations)
        assert any(v.level == ViolationLevel.ERROR for v in violations)

    def test_unknown_database_fails(self):
        """SR-015: 未知数据库不在白名单 → HIGH 违规"""
        adapter = _make_adapter(_sr_database_whitelist_rules())
        validator = TableValidator(adapter)
        violations = validator._check_sr_database_whitelist(["unknown_db_xyz"])
        assert any(v.rule_name == "RULE_SR_015" for v in violations)

    def test_whitelisted_database_passes(self):
        """合规数据库不触发白名单违规"""
        adapter = _make_adapter(_sr_database_whitelist_rules())
        validator = TableValidator(adapter)
        violations = validator._check_sr_database_whitelist(["ods_db", "dwd", "ads"])
        sr015_forbidden = [
            v for v in violations
            if v.rule_name == "RULE_SR_015" and "不在允许列表" in v.message
        ]
        assert len(sr015_forbidden) == 0


# ===========================================================================
# 8. 表名通用检查（中文、版本号）
# ===========================================================================


class TestSrTableNaming:
    """SR-022, 023: 表名通用检查"""

    def test_chinese_table_name_fails(self):
        """SR-022: 表名含中文字符 → HIGH 违规"""
        adapter = _make_adapter(_sr_table_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("订单表")
        violations = validator._check_sr_table_naming(table)
        assert any(v.rule_name == "RULE_SR_022" for v in violations)
        assert any(v.level == ViolationLevel.ERROR for v in violations)

    def test_english_table_name_passes(self):
        """SR-022: 纯英文表名 → 无违规"""
        adapter = _make_adapter(_sr_table_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("order_detail")
        violations = validator._check_sr_table_naming(table)
        sr022 = [v for v in violations if v.rule_name == "RULE_SR_022"]
        assert len(sr022) == 0

    def test_versioned_table_name_fails(self):
        """SR-023: 表名含 _v2 → MEDIUM 违规"""
        adapter = _make_adapter(_sr_table_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("order_detail_v2")
        violations = validator._check_sr_table_naming(table)
        assert any(v.rule_name == "RULE_SR_023" for v in violations)
        sr023 = [v for v in violations if v.rule_name == "RULE_SR_023"]
        assert all(v.level == ViolationLevel.WARNING for v in sr023)

    def test_table_name_without_version_passes(self):
        """SR-023: 表名不含版本号 → 无违规"""
        adapter = _make_adapter(_sr_table_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("order_detail")
        violations = validator._check_sr_table_naming(table)
        sr023 = [v for v in violations if v.rule_name == "RULE_SR_023"]
        assert len(sr023) == 0


# ===========================================================================
# 9. db_type 隔离测试（MySQL 扫描不触发 SR 规则）
# ===========================================================================


class TestDbTypeIsolation:
    """MySQL 扫描不应触发 sr_* 违规"""

    def test_mysql_scan_no_sr_violations(self):
        """MySQL db_type 扫描应产生零 sr_* 违规"""
        # MySQL adapter 仅含 MySQL 规则
        adapter = _make_adapter(_mysql_only_rules())
        table_validator = TableValidator(adapter)
        column_validator = ColumnValidator(adapter)

        # 构造一个不合规的 ODS 表（若加载了 SR 规则会触发多条违规）
        table = _make_table(
            "bad_ods_table",
            columns=[
                _make_column("order_amt", "FLOAT"),
                _make_column("create_time", "VARCHAR(20)"),
            ],
            database="ods_db",
            comment="",
        )

        table_violations = table_validator.validate(table)
        column_violations = column_validator.validate(table)

        all_violations = table_violations + column_violations
        sr_violations = [v for v in all_violations if v.rule_name.startswith("RULE_SR_")]
        assert len(sr_violations) == 0

    def test_starrocks_adapter_triggers_sr_rules(self):
        """StarRocks adapter 应能触发 sr_* 规则"""
        all_sr_rules = (
            _sr_layer_naming_rules()
            + _sr_type_alignment_rules()
            + _sr_comment_rules()
            + _sr_table_naming_rules()
        )
        adapter = _make_adapter(all_sr_rules)
        table_validator = TableValidator(adapter)
        column_validator = ColumnValidator(adapter)

        # 构造一个不合规的 ODS 表
        table = _make_table(
            "bad_ods_table",
            columns=[
                _make_column("order_amt", "FLOAT", comment=""),
            ],
            database="ods_db",
            comment="",
        )

        table_violations = table_validator.validate(table)
        column_violations = column_validator.validate(table)

        all_violations = table_violations + column_violations
        sr_violations = [v for v in all_violations if v.rule_name.startswith("RULE_SR_")]
        assert len(sr_violations) >= 1


# ===========================================================================
# 10. 种子规则结构验证
# ===========================================================================


class TestSeedRules:
    """DEFAULT_RULES_SEED 结构验证"""

    @pytest.fixture(autouse=True)
    def _load_seed(self):
        """安全导入 DEFAULT_RULES_SEED（跳过 seed_defaults DB 调用）

        DEFAULT_RULES_SEED 在 app.api.rules 模块顶层定义（line 18），
        seed_defaults() 调用在 try/except 中（line 162），即使 DB 不可用也不会阻止导入。
        此处 patch RuleConfigDatabase 确保不会真正连接数据库。
        """
        with patch("app.api.rules.RuleConfigDatabase"):
            from app.api.rules import DEFAULT_RULES_SEED
            self.seed = DEFAULT_RULES_SEED

    def test_all_25_sr_rules_present(self):
        """DEFAULT_RULES_SEED 包含 RULE_SR_001 到 RULE_SR_025 共 25 条"""
        sr_rules = [r for r in self.seed if r["rule_id"].startswith("RULE_SR_")]
        sr_ids = {r["rule_id"] for r in sr_rules}

        expected_ids = {f"RULE_SR_{i:03d}" for i in range(1, 26)}
        assert sr_ids == expected_ids, f"缺失规则: {expected_ids - sr_ids}, 多余规则: {sr_ids - expected_ids}"

    def test_all_sr_rules_have_starrocks_db_type(self):
        """所有 RULE_SR_* 规则的 db_type 为 'StarRocks'"""
        sr_rules = [r for r in self.seed if r["rule_id"].startswith("RULE_SR_")]
        for rule in sr_rules:
            assert rule["db_type"] == "StarRocks", \
                f"规则 {rule['rule_id']} 的 db_type 应为 'StarRocks'，实际为 '{rule['db_type']}'"

    def test_all_sr_rules_have_sr_category_prefix(self):
        """所有 RULE_SR_* 规则的 category 以 'sr_' 开头"""
        sr_rules = [r for r in self.seed if r["rule_id"].startswith("RULE_SR_")]
        for rule in sr_rules:
            assert rule["category"].startswith("sr_"), \
                f"规则 {rule['rule_id']} 的 category '{rule['category']}' 应以 'sr_' 开头"

    def test_sr_rules_have_required_fields(self):
        """所有 SR 规则都包含必要的字段"""
        required_keys = {"rule_id", "name", "level", "category", "db_type", "suggestion", "description"}
        sr_rules = [r for r in self.seed if r["rule_id"].startswith("RULE_SR_")]
        for rule in sr_rules:
            missing = required_keys - set(rule.keys())
            assert not missing, f"规则 {rule['rule_id']} 缺少字段: {missing}"

    def test_mysql_rules_not_in_sr_category(self):
        """MySQL 规则不应使用 sr_ 前缀的 category"""
        mysql_rules = [r for r in self.seed if r["db_type"] == "MySQL"]
        for rule in mysql_rules:
            assert not rule["category"].startswith("sr_"), \
                f"MySQL 规则 {rule['rule_id']} 不应使用 sr_ category"


# ===========================================================================
# 11. 整合 validate() 入口测试
# ===========================================================================


class TestValidateEntryPoint:
    """验证 validate() 主入口正确分发 sr_* 检查"""

    def test_table_validate_dispatches_sr_checks(self):
        """TableValidator.validate() 在有 sr_* 规则时调用 sr 检查方法"""
        all_sr_rules = (
            _sr_layer_naming_rules()
            + _sr_comment_rules()
            + _sr_table_naming_rules()
        )
        adapter = _make_adapter(all_sr_rules)
        validator = TableValidator(adapter)

        table = _make_table(
            "bad_table",
            columns=[_make_column("id", "BIGINT", comment="")],
            database="ods_db",
            comment="",
        )
        violations = validator.validate(table)

        # 应包含来自 sr_* 检查的违规
        sr_violations = [v for v in violations if v.rule_name.startswith("RULE_SR_")]
        assert len(sr_violations) >= 1

    def test_column_validate_dispatches_sr_type_check(self):
        """ColumnValidator.validate() 在有 sr_type_alignment 规则时调用类型对齐检查"""
        adapter = _make_adapter(_sr_type_alignment_rules())
        validator = ColumnValidator(adapter)

        table = _make_table(
            "test_table",
            columns=[_make_column("order_amt", "FLOAT", comment="金额")],
        )
        violations = validator.validate(table)
        sr_violations = [v for v in violations if v.rule_name.startswith("RULE_SR_")]
        assert len(sr_violations) >= 1

    def test_empty_rules_no_sr_violations(self):
        """空规则列表 → validate 不产生 sr_* 违规"""
        adapter = _make_adapter([])
        table_validator = TableValidator(adapter)
        column_validator = ColumnValidator(adapter)

        table = _make_table(
            "bad_table",
            columns=[_make_column("order_amt", "FLOAT")],
            database="ods_db",
            comment="",
        )
        t_violations = table_validator.validate(table)
        c_violations = column_validator.validate(table)

        all_v = t_violations + c_violations
        sr_v = [v for v in all_v if v.rule_name.startswith("RULE_SR_")]
        assert len(sr_v) == 0


# ===========================================================================
# 12. 视图命名检查
# ===========================================================================


class TestSrViewNaming:
    """SR-025: 视图命名检查"""

    def _view_naming_rules(self) -> List[dict]:
        return [
            {
                "rule_id": "RULE_SR_025",
                "name": "视图命名 _vw 后缀",
                "level": "MEDIUM",
                "category": "sr_view_naming",
                "db_type": "StarRocks",
                "suggestion": "视图命名: xxx_vw",
                "enabled": True,
                "is_custom": False,
                "scene_type": "ALL",
                "config_json": {"pattern": "_vw$"},
            },
        ]

    def test_view_without_vw_suffix_fails(self):
        """SR-025: 视图无 _vw 后缀 → MEDIUM 违规"""
        adapter = _make_adapter(self._view_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("user_summary")
        violations = validator._check_sr_view_naming(table)
        assert any(v.rule_name == "RULE_SR_025" for v in violations)

    def test_view_with_vw_suffix_passes(self):
        """SR-025: 视图有 _vw 后缀 → 无违规"""
        adapter = _make_adapter(self._view_naming_rules())
        validator = TableValidator(adapter)
        table = _make_table("user_summary_vw")
        violations = validator._check_sr_view_naming(table)
        assert len(violations) == 0
