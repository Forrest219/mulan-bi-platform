"""DDL 规范验证模块 — 运行时从数据库加载规则"""
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

from .parser import TableInfo, ColumnInfo
from .cache import RuleCache


class ViolationLevel(Enum):
    """违规级别"""
    ERROR = "error"      # 严重违规 (High)
    WARNING = "warning"  # 警告 (Medium)
    INFO = "info"        # 提示 (Low)


@dataclass
class Violation:
    """违规项"""
    level: ViolationLevel
    rule_name: str
    message: str
    table_name: str = ""
    column_name: str = ""
    suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "rule_name": self.rule_name,
            "message": self.message,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "suggestion": self.suggestion,
        }


# 默认扣分权重
DEFAULT_WEIGHTS = {"high": -20, "medium": -5, "low": -1}


class DatabaseRulesAdapter:
    """
    数据库规则适配器 — 从 bi_rule_configs 表加载运行时规则（带 Redis 缓存）

    替代原来的 rules.yaml + RulesConfig 组合，
    确保 DDL 检查使用与规则管理 API 同一数据源。
    """

    # 规则分类名到规则 ID 前缀的映射（与 rules.py 中 DEFAULT_RULES_SEED 对应）
    RULE_CATEGORY_MAP = {
        "table_naming": "RULE_001",
        "column_naming": "RULE_008",
        "data_type": "RULE_003",
        "timestamp": "RULE_004",
        "timestamp_update": "RULE_005",
        "primary_key": "RULE_006",
        "index": "RULE_007",
        "table_comment": "RULE_010",
        "column_comment": "RULE_002",
        "soft_delete": "RULE_009",
    }

    def __init__(self, scene_type: str = "ALL", db_type: str = "MySQL"):
        self.scene_type = scene_type
        self.db_type = db_type
        self._rules_cache: Optional[List[Dict[str, Any]]] = None

    def _load_rules(self) -> List[Dict[str, Any]]:
        """
        从 Redis 缓存加载规则，未命中则从数据库加载并写入缓存。

        缓存键: ddl:rules:{scene_type}:{db_type}
        TTL: 300 秒
        """
        # 尝试从 Redis 缓存读取
        cached = RuleCache.get(self.scene_type, self.db_type)
        if cached is not None:
            self._rules_cache = cached
            return cached

        # 缓存未命中，从数据库加载
        from services.rules.models import RuleConfigDatabase

        db = RuleConfigDatabase()
        all_rules = db.get_all()

        # 按 rule_id 建立索引，仅保留启用的规则
        enabled_rules = [r for r in all_rules if r.enabled]
        # 按 db_type 过滤：仅加载当前数据库类型和通用规则
        enabled_rules = [r for r in enabled_rules
                         if r.db_type.lower() in (self.db_type.lower(), "all")]
        # B14: 按 scene_type 过滤：仅加载当前场景和 ALL 场景的规则
        enabled_rules = [r for r in enabled_rules
                         if r.scene_type in (self.scene_type, "ALL")]

        # 转换为 dict 列表（避免 ORM 对象序列化问题）
        rules_list = []
        for r in enabled_rules:
            rules_list.append({
                "rule_id": r.rule_id,
                "name": r.name,
                "description": r.description,
                "level": r.level,
                "category": r.category,
                "db_type": r.db_type,
                "suggestion": r.suggestion,
                "enabled": r.enabled,
                "is_custom": r.is_custom,
                "scene_type": r.scene_type,
                "config_json": r.config_json or {},
            })

        # 写入 Redis 缓存
        RuleCache.set(rules_list, self.scene_type, self.db_type)

        self._rules_cache = rules_list
        return rules_list

    def get_enabled_rules(self) -> List[Dict[str, Any]]:
        """获取所有已启用的规则（dict 列表）"""
        return self._load_rules()

    def _find_rule_by_category(self, category: str) -> Optional[Dict[str, Any]]:
        """根据分类查找匹配的规则"""
        rules = self._load_rules()
        rule_id = self.RULE_CATEGORY_MAP.get(category)
        if not rule_id:
            return None
        for rule in rules:
            if rule["rule_id"] == rule_id:
                return rule
        return None

    def is_rule_enabled(self, category: str) -> bool:
        """检查某分类规则是否启用"""
        rule = self._find_rule_by_category(category)
        if rule is None:
            return True  # 未知分类默认启用
        return rule.get("enabled", True)

    def get_rule_config(self, category: str) -> Dict[str, Any]:
        """获取某分类规则的配置"""
        rule = self._find_rule_by_category(category)
        if rule is None:
            return {"enabled": True, "config_json": {}}

        return {
            "enabled": rule.get("enabled", True),
            "description": rule.get("description", ""),
            "suggestion": rule.get("suggestion", ""),
            "level": rule.get("level", "MEDIUM"),
            "config_json": rule.get("config_json", {}),
        }

    def get_scene_weights(self) -> Dict[str, int]:
        """
        获取当前场景的扣分权重。

        从 config_json.scene_weights[{scene_type}] 读取，
        若无配置则返回 DEFAULT_WEIGHTS。
        """
        # 从任意规则中获取全局 scene_weights 配置
        rules = self._load_rules()
        for rule in rules:
            scene_weights = rule.get("config_json", {}).get("scene_weights", {})
            if self.scene_type in scene_weights:
                return scene_weights[self.scene_type]
        return DEFAULT_WEIGHTS

    def get_rules_for(self, db_type: str) -> list:
        """
        按 db_type 过滤规则，返回仅包含指定 db_type 和通用规则的列表。
        
        Raises:
            ValueError: 当 db_type 不在支持列表中时，抛出 SR_ADAPT_001 错误码
        """
        if db_type.lower() not in ("mysql", "postgresql", "starrocks", "all"):
            raise ValueError(
                f"SR_ADAPT_001: connection 类型与请求 db_type 不匹配 "
                f"(db_type='{db_type}', supported=['mysql','postgresql','starrocks','all'])"
            )
        rules = self._load_rules()
        # 过滤：仅保留匹配的 db_type 和通用规则
        filtered = [r for r in rules if r["db_type"].lower() in (db_type.lower(), "all")]
        return filtered

    def _find_sr_rules_by_category(self, category: str) -> List[Dict[str, Any]]:
        """查找指定 category 的所有 StarRocks 规则"""
        rules = self._load_rules()
        return [r for r in rules if r["category"] == category]


class RulesConfig:
    """
    规则配置 — 兼容旧接口
    已废弃，仅用于向后兼容 Scanner 等旧模块。
    实际 DDL 检查应使用 DatabaseRulesAdapter。
    """

    def __init__(self, config_path: str):
        # 忽略 config_path，从数据库加载
        self._db_adapter = DatabaseRulesAdapter()
        self.config: Dict[str, Any] = {}
        self._load_from_db()

    def _load_from_db(self):
        """从数据库加载规则配置"""
        rules = self._db_adapter.get_enabled_rules()
        for rule in rules:
            # 旧版 YAML 格式: {section: {key: value}}
            # 兼容：将 rule.category 作为 section
            if rule.category not in self.config:
                self.config[rule.category] = {}
            self.config[rule.category].setdefault("rules", []).append(rule.to_dict())

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.config.get(section, {}).get(key, default)

    def is_enabled(self, section: str) -> bool:
        """检查规则是否启用"""
        return self.config.get(section, {}).get("enabled", True)


class TableValidator:
    """表级验证器"""

    def __init__(self, rules: DatabaseRulesAdapter):
        self.rules = rules
        self.connector = None  # SQL connector for StarRocks live queries

    def set_connector(self, connector):
        """注入数据库连接器（用于 StarRocks 引擎检查的 SQL 查询）"""
        self.connector = connector

    def _show_partitions(self, db: str, tbl: str) -> list:
        """查询 StarRocks 分区信息"""
        if not self.connector:
            return []
        try:
            return self.connector.show_partitions(db, tbl)
        except Exception:
            return []

    def _show_tablets(self, db: str, tbl: str) -> list:
        """查询 StarRocks Tablet 信息"""
        if not self.connector:
            return []
        try:
            return self.connector.show_tablets(db, tbl)
        except Exception:
            return []

    def validate(self, table: TableInfo) -> List[Violation]:
        """验证表"""
        violations = []

        # §4.10 契约：StarRocks 巡检时 TableInfo.database 缺失则 abort
        if self.rules.db_type.lower() == "starrocks" and not table.database:
            raise RuntimeError(
                f"SR_ADAPT_002: TableInfo.database 注入缺失，scan abort "
                f"(table='{table.name}')"
            )

        violations.extend(self._check_naming(table))
        violations.extend(self._check_comment(table))
        violations.extend(self._check_primary_key(table))
        violations.extend(self._check_timestamp_fields(table))
        violations.extend(self._check_soft_delete(table))
        violations.extend(self._check_indexes(table))

        # StarRocks 专属检查（§2.2 命名/类型规则，对应 RULE_SR_001~025）
        if self.rules._find_sr_rules_by_category("sr_layer_naming"):
            violations.extend(self._check_sr_layer_naming(table))
        if self.rules._find_sr_rules_by_category("sr_public_fields"):
            violations.extend(self._check_sr_public_fields(table))
        if self.rules._find_sr_rules_by_category("sr_table_naming"):
            violations.extend(self._check_sr_table_naming(table))
        if self.rules._find_sr_rules_by_category("sr_comment"):
            violations.extend(self._check_sr_comment(table))
        if self.rules._find_sr_rules_by_category("sr_field_naming"):
            violations.extend(self._check_sr_field_naming(table))
        if self.rules._find_sr_rules_by_category("sr_view_naming"):
            violations.extend(self._check_sr_view_naming(table))

        # StarRocks 引擎检查（§2.4 规则，对应 SR-SCH-*/SR-PART-*/SR-REP-*/SR-PERF-*/SR-META-*）
        if self.rules._find_sr_rules_by_category("sr_schema"):
            violations.extend(self._check_sr_schema_rules(table))
        if self.rules._find_sr_rules_by_category("sr_partition"):
            violations.extend(self._check_sr_partition_rules(table))
        if self.rules._find_sr_rules_by_category("sr_replica"):
            violations.extend(self._check_sr_replica_rules(table))
        if self.rules._find_sr_rules_by_category("sr_perf"):
            violations.extend(self._check_sr_perf_rules(table))
        if self.rules._find_sr_rules_by_category("sr_meta"):
            violations.extend(self._check_sr_meta_rules(table))

        return violations

    def _check_naming(self, table: TableInfo) -> List[Violation]:
        """检查表命名规范"""
        violations = []
        if not self.rules.is_rule_enabled("table_naming"):
            return violations

        config = self.rules.get_rule_config("table_naming")
        pattern = config.get("config_json", {}).get("pattern", r"^[a-z][a-z0-9_]*$")
        max_length = config.get("config_json", {}).get("max_length", 64)
        prefix_whitelist = config.get("config_json", {}).get("prefix_whitelist", [])

        table_name = table.name

        # 检查长度
        if len(table_name) > max_length:
            violations.append(Violation(
                level=ViolationLevel.ERROR,
                rule_name="table_naming",
                message=f"表名 '{table_name}' 长度超过 {max_length} 字符",
                table_name=table_name,
                suggestion=config.get("suggestion", f"将表名控制在 {max_length} 字符以内")
            ))

        # 检查命名模式
        if not re.match(pattern, table_name):
            violations.append(Violation(
                level=ViolationLevel.ERROR,
                rule_name="table_naming",
                message=f"表名 '{table_name}' 不符合命名规范",
                table_name=table_name,
                suggestion=config.get("suggestion", "表名必须以小写字母开头，支持小写字母、数字、下划线")
            ))

        # 检查前缀
        if prefix_whitelist and not any(table_name.startswith(p) for p in prefix_whitelist):
            violations.append(Violation(
                level=ViolationLevel.WARNING,
                rule_name="table_naming",
                message=f"表名 '{table_name}' 不使用标准前缀",
                table_name=table_name,
                suggestion=f"建议使用以下前缀之一: {', '.join(prefix_whitelist)}"
            ))

        return violations

    def _check_comment(self, table: TableInfo) -> List[Violation]:
        """检查表注释"""
        violations = []
        if not self.rules.is_rule_enabled("table_comment"):
            return violations

        config = self.rules.get_rule_config("table_comment")
        require = config.get("config_json", {}).get("require_table_comment", True)

        if require and not table.comment:
            violations.append(Violation(
                level=ViolationLevel.WARNING,
                rule_name="table_comment",
                message=f"表 '{table.name}' 缺少注释",
                table_name=table.name,
                suggestion=config.get("suggestion", "为表添加注释说明其用途")
            ))

        return violations

    def _check_primary_key(self, table: TableInfo) -> List[Violation]:
        """检查主键"""
        violations = []
        if not self.rules.is_rule_enabled("primary_key"):
            return violations

        config = self.rules.get_rule_config("primary_key")
        pk_columns = table.get_primary_key_columns()

        if config.get("config_json", {}).get("require_primary_key", True) and not pk_columns:
            violations.append(Violation(
                level=ViolationLevel.ERROR,
                rule_name="primary_key",
                message=f"表 '{table.name}' 缺少主键",
                table_name=table.name,
                suggestion=config.get("suggestion", "为表添加主键，建议使用 id 字段")
            ))

        return violations

    def _check_timestamp_fields(self, table: TableInfo) -> List[Violation]:
        """检查时间戳字段"""
        violations = []
        if not self.rules.is_rule_enabled("timestamp"):
            return violations

        config = self.rules.get_rule_config("timestamp")
        column_names = table.get_column_names()

        if config.get("config_json", {}).get("require_create_time", True):
            if "create_time" not in column_names:
                violations.append(Violation(
                    level=ViolationLevel.WARNING,
                    rule_name="create_time",
                    message=f"表 '{table.name}' 缺少 create_time 字段",
                    table_name=table.name,
                    suggestion=config.get("suggestion", "添加 create_time DATETIME 字段记录创建时间")
                ))

        if config.get("config_json", {}).get("require_update_time", True):
            if "update_time" not in column_names:
                violations.append(Violation(
                    level=ViolationLevel.WARNING,
                    rule_name="update_time",
                    message=f"表 '{table.name}' 缺少 update_time 字段",
                    table_name=table.name,
                    suggestion=config.get("suggestion", "添加 update_time DATETIME 字段记录更新时间")
                ))

        return violations

    def _check_soft_delete(self, table: TableInfo) -> List[Violation]:
        """检查软删除字段"""
        violations = []
        if not self.rules.is_rule_enabled("soft_delete"):
            return violations

        config = self.rules.get_rule_config("soft_delete")
        column_names = table.get_column_names()

        if config.get("config_json", {}).get("require_is_deleted", True):
            if "is_deleted" not in column_names:
                violations.append(Violation(
                    level=ViolationLevel.WARNING,
                    rule_name="soft_delete",
                    message=f"表 '{table.name}' 缺少 is_deleted 字段",
                    table_name=table.name,
                    suggestion=config.get("suggestion", "添加 is_deleted TINYINT 字段支持软删除")
                ))

        return violations

    def _check_indexes(self, table: TableInfo) -> List[Violation]:
        """检查索引"""
        violations = []
        if not self.rules.is_rule_enabled("index"):
            return violations

        config = self.rules.get_rule_config("index")
        max_count = config.get("config_json", {}).get("max_index_count_per_table", 10)

        if len(table.indexes) > max_count:
            violations.append(Violation(
                level=ViolationLevel.WARNING,
                rule_name="index_count",
                message=f"表 '{table.name}' 索引数量 ({len(table.indexes)}) 超过限制 ({max_count})",
                table_name=table.name,
                suggestion=f"减少索引数量，保留必要的索引"
            ))

        return violations

    def _check_sr_layer_naming(self, table: TableInfo) -> List[Violation]:
        """SR-001~005, 016~018, 024: 分层命名合规检查"""
        violations = []
        db_name = table.database.lower()
        table_name = table.name

        sr_rules = self.rules._find_sr_rules_by_category("sr_layer_naming")
        for rule in sr_rules:
            cfg = rule.get("config_json", {})
            databases = cfg.get("databases", [])

            # 检查当前数据库是否在规则适用范围内
            if databases and db_name not in [d.lower() for d in databases]:
                continue

            pattern = cfg.get("pattern")
            forbidden_prefixes = cfg.get("forbidden_prefixes", [])

            level = ViolationLevel.ERROR if rule["level"] == "HIGH" else ViolationLevel.WARNING

            if pattern and not re.match(pattern, table_name):
                violations.append(Violation(
                    level=level,
                    rule_name=rule["category"],
                    message=f"表 '{table_name}' (库: {db_name}) 不符合命名规范: {rule['name']}",
                    table_name=table_name,
                    suggestion=rule.get("suggestion", f"表名应匹配模式: {pattern}"),
                ))

            if forbidden_prefixes:
                for prefix in forbidden_prefixes:
                    if table_name.startswith(prefix):
                        violations.append(Violation(
                            level=level,
                            rule_name=rule["category"],
                            message=f"表 '{table_name}' (库: {db_name}) 使用了禁止的前缀 '{prefix}': {rule['name']}",
                            table_name=table_name,
                            suggestion=rule.get("suggestion", f"DIM 表不应使用业务域前缀"),
                        ))

        return violations

    def _check_sr_public_fields(self, table: TableInfo) -> List[Violation]:
        """SR-008~011: 公共字段检查"""
        violations = []
        db_name = table.database.lower()
        column_names = [c.name.lower() for c in table.columns]
        column_types = {c.name.lower(): c.data_type.upper() for c in table.columns}

        sr_rules = self.rules._find_sr_rules_by_category("sr_public_fields")
        for rule in sr_rules:
            cfg = rule.get("config_json", {})
            databases = cfg.get("databases", "__all__")
            required_fields = cfg.get("required_fields", [])

            # 检查当前数据库是否在规则适用范围内
            if databases != "__all__":
                if db_name not in [d.lower() for d in databases]:
                    continue

            level = ViolationLevel.ERROR if rule["level"] == "HIGH" else ViolationLevel.WARNING

            for field in required_fields:
                field_name = field["name"].lower()
                field_type = field.get("type", "").upper()

                if field_name not in column_names:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"表 '{table.name}' (库: {db_name}) 缺少公共字段 '{field['name']}'",
                        table_name=table.name,
                        suggestion=rule.get("suggestion", f"添加 {field['name']} {field_type} 字段"),
                    ))
                elif field_type and field_type not in column_types.get(field_name, ""):
                    violations.append(Violation(
                        level=ViolationLevel.WARNING,
                        rule_name=rule["category"],
                        message=f"表 '{table.name}' 公共字段 '{field['name']}' 类型不匹配，期望含 {field_type}，实际为 {column_types.get(field_name)}",
                        table_name=table.name,
                        column_name=field["name"],
                        suggestion=f"将 {field['name']} 类型改为 {field_type}",
                    ))

        return violations

    def _check_sr_table_naming(self, table: TableInfo) -> List[Violation]:
        """SR-022, 023: 表名通用检查（中文、版本号）"""
        violations = []
        table_name = table.name

        sr_rules = self.rules._find_sr_rules_by_category("sr_table_naming")
        for rule in sr_rules:
            cfg = rule.get("config_json", {})
            pattern_forbidden = cfg.get("pattern_forbidden")

            if not pattern_forbidden:
                continue

            level = ViolationLevel.ERROR if rule["level"] == "HIGH" else ViolationLevel.WARNING

            if re.search(pattern_forbidden, table_name):
                violations.append(Violation(
                    level=level,
                    rule_name=rule["category"],
                    message=f"表 '{table_name}' 命名不合规: {rule['name']}",
                    table_name=table_name,
                    suggestion=rule.get("suggestion", ""),
                ))

        return violations

    def _check_sr_comment(self, table: TableInfo) -> List[Violation]:
        """SR-013, 014: 注释检查"""
        violations = []

        # SR-014: 表注释存在
        sr_rules_comment = self.rules._find_sr_rules_by_category("sr_comment")
        for rule in sr_rules_comment:
            cfg = rule.get("config_json", {})
            level = ViolationLevel.ERROR if rule["level"] == "HIGH" else ViolationLevel.WARNING

            if rule["rule_id"] == "RULE_SR_014":
                if not table.comment:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"表 '{table.name}' 缺少表注释",
                        table_name=table.name,
                        suggestion=rule.get("suggestion", "为表添加 COMMENT"),
                    ))

            elif rule["rule_id"] == "RULE_SR_013":
                min_coverage = cfg.get("min_coverage", 1.0)
                total_cols = len(table.columns)
                if total_cols == 0:
                    continue
                commented_cols = sum(1 for c in table.columns if c.comment)
                coverage = commented_cols / total_cols

                if coverage < min_coverage:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"表 '{table.name}' 字段注释覆盖率 {coverage:.0%}，要求 {min_coverage:.0%}",
                        table_name=table.name,
                        suggestion=rule.get("suggestion", "为所有字段添加注释"),
                    ))

        return violations

    def _check_sr_field_naming(self, table: TableInfo) -> List[Violation]:
        """SR-012: 字段 snake_case 检查"""
        violations = []

        sr_rules = self.rules._find_sr_rules_by_category("sr_field_naming")
        for rule in sr_rules:
            cfg = rule.get("config_json", {})
            pattern = cfg.get("pattern", r"^[a-z][a-z0-9_]*$")
            max_length = cfg.get("max_length", 40)
            level = ViolationLevel.ERROR if rule["level"] == "HIGH" else ViolationLevel.WARNING

            for col in table.columns:
                if not re.match(pattern, col.name):
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"字段 '{col.name}' 不符合 snake_case 命名规范",
                        table_name=table.name,
                        column_name=col.name,
                        suggestion=rule.get("suggestion", "字段名使用小写字母+下划线"),
                    ))
                if len(col.name) > max_length:
                    violations.append(Violation(
                        level=ViolationLevel.WARNING,
                        rule_name=rule["category"],
                        message=f"字段 '{col.name}' 长度 {len(col.name)} 超过限制 {max_length}",
                        table_name=table.name,
                        column_name=col.name,
                        suggestion=f"字段名长度不超过 {max_length} 字符",
                    ))

        return violations

    def _check_sr_database_whitelist(self, databases: list) -> List[Violation]:
        """SR-015, 021: 数据库白名单检查（scan 级别，非逐表）"""
        violations = []

        sr_rules = self.rules._find_sr_rules_by_category("sr_database_whitelist")
        for rule in sr_rules:
            cfg = rule.get("config_json", {})
            allowed = cfg.get("allowed", [])
            forbidden = cfg.get("forbidden", [])
            level = ViolationLevel.ERROR if rule["level"] == "HIGH" else ViolationLevel.WARNING

            for db_name in databases:
                if forbidden and db_name.lower() in [f.lower() for f in forbidden]:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"检测到禁止的数据库 '{db_name}': {rule['name']}",
                        suggestion=rule.get("suggestion", f"删除或迁移数据库 '{db_name}'"),
                    ))

                if allowed and db_name.lower() not in [a.lower() for a in allowed]:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"数据库 '{db_name}' 不在允许列表中: {rule['name']}",
                        suggestion=rule.get("suggestion", "联系管理员确认此数据库是否合规"),
                    ))

        return violations



    # ============================================================
    # StarRocks 引擎检查方法 SR-SCH-*/SR-PART-*/SR-REP-*/SR-PERF-*/SR-META-*
    # ============================================================

    def _check_sr_schema_rules(self, table: "TableInfo") -> List["Violation"]:
        """SR-SCH-001~008: Schema 合规性检查（主键声明、列存模型、时间字段类型、分区列类型、主键长度、表名列名字符集、BLOB）"""
        from .parser import TableInfo
        violations = []

        # 查找 sr_schema 规则
        sr_rules = self.rules._find_sr_rules_by_category("sr_schema")
        if not sr_rules:
            return violations

        # SR-SCH-001: 主键表必须显式声明 PRIMARY KEY
        # SR-SCH-002: 大宽表必须使用列存模型
        # SR-SCH-003: 时间字段必须使用 DATETIME (在 _check_sr_type_alignment 中已覆盖)
        # SR-SCH-004: 分区列必须为 DATE/DATETIME/INT/BIGINT
        # SR-SCH-005: 主键长度 <= 128 字节
        # SR-SCH-006: 表名/列名长度 <= 64
        # SR-SCH-007: 字符集统一 utf8mb4
        # SR-SCH-008: 禁止 BLOB 字段 (在 _check_sr_type_alignment 中已覆盖)

        for rule in sr_rules:
            cfg = rule.get("config_json", {})
            level = ViolationLevel.ERROR if rule["level"] == "critical" else (
                ViolationLevel.WARNING if rule["level"] == "high" else ViolationLevel.INFO)
            rule_id = rule["rule_id"]

            if rule_id == "SR-SCH-001":
                # 检查主键表是否有 PRIMARY KEY
                pk_cols = table.get_primary_key_columns()
                if not pk_cols:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"表 '{table.name}' 是主键表但缺少 PRIMARY KEY 声明",
                        table_name=table.name,
                        suggestion=rule.get("suggestion", "添加 PRIMARY KEY 声明"),
                    ))

            elif rule_id == "SR-SCH-002":
                # 大宽表检查：列数 >= min_columns
                min_cols = cfg.get("min_columns", 200)
                if len(table.columns) >= min_cols:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"表 '{table.name}' 列数 {len(table.columns)} >= {min_cols}，需使用列存模型",
                        table_name=table.name,
                        suggestion=rule.get("suggestion", "改用 DUPLICATE/PRIMARY/AGG 模型"),
                    ))

            elif rule_id == "SR-SCH-004":
                # 分区列类型检查
                allowed = [t.upper() for t in cfg.get("allowed", ["DATE", "DATETIME", "INT", "BIGINT"])]
                # 需要通过 connector 查询分区列信息，此处做静态检查
                pass  # 动态检查需要 SQL 查询

            elif rule_id == "SR-SCH-005":
                # 主键长度检查（字节）
                max_bytes = cfg.get("max_bytes", 128)
                pk_cols = table.get_primary_key_columns()
                pk_bytes = sum(len(c.name.encode('utf-8')) for c in table.columns if c.name in pk_cols)
                if pk_bytes > max_bytes:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"表 '{table.name}' 主键总字节数 {pk_bytes} 超过限制 {max_bytes}",
                        table_name=table.name,
                        suggestion=rule.get("suggestion", "精简主键列组合"),
                    ))

            elif rule_id == "SR-SCH-006":
                # 表名/列名长度检查
                max_len = cfg.get("max_length", 64)
                if len(table.name) > max_len:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"表名 '{table.name}' 长度 {len(table.name)} 超过限制 {max_len}",
                        table_name=table.name,
                        suggestion=rule.get("suggestion", "表名控制在 64 字符以内"),
                    ))
                for col in table.columns:
                    if len(col.name) > max_len:
                        violations.append(Violation(
                            level=level,
                            rule_name=rule["category"],
                            message=f"列名 '{col.name}' 长度 {len(col.name)} 超过限制 {max_len}",
                            table_name=table.name,
                            column_name=col.name,
                            suggestion=rule.get("suggestion", "列名控制在 64 字符以内"),
                        ))

            elif rule_id == "SR-SCH-007":
                # 字符集检查（需要通过 connector 查询）
                pass  # 动态检查需要 SQL 查询

            elif rule_id == "SR-SCH-008":
                # BLOB 类型检查
                forbidden = [t.upper() for t in cfg.get("forbidden_types", ["BLOB", "MEDIUMBLOB", "LONGBLOB"])]
                for col in table.columns:
                    col_type = col.data_type.upper()
                    if any(ft in col_type for ft in forbidden):
                        violations.append(Violation(
                            level=level,
                            rule_name=rule["category"],
                            message=f"列 '{col.name}' 使用了禁止的类型 {col.data_type}",
                            table_name=table.name,
                            column_name=col.name,
                            suggestion=rule.get("suggestion", "将 BLOB 改为 VARCHAR 或迁移至对象存储"),
                        ))

        return violations

    def _check_sr_partition_rules(self, table: "TableInfo") -> List["Violation"]:
        """SR-PART-001/002/003/004/006 + SR-BUCK-005: 分区分桶合规性检查"""
        from .parser import TableInfo
        violations = []

        sr_rules = self.rules._find_sr_rules_by_category("sr_partition")
        if not sr_rules:
            return violations

        # SR-PART-001: 单表分区数 <= 1000
        # SR-PART-002: 单分区数据量 1-10GB
        # SR-PART-003: 分桶数与数据量匹配 (1~256)
        # SR-PART-004: 分桶列必须高基数 (基数比 >= 0.1)
        # SR-BUCK-005: 分桶列禁止可空
        # SR-PART-006: 大表必须按时间分区 (>= 100GB)

        if not self.connector:
            return violations

        partitions = self._show_partitions(table.database, table.name)

        for rule in sr_rules:
            cfg = rule.get("config_json", {})
            level = ViolationLevel.ERROR if rule["level"] == "critical" else (
                ViolationLevel.WARNING if rule["level"] == "high" else ViolationLevel.INFO)
            rule_id = rule["rule_id"]

            if rule_id == "SR-PART-001":
                # 单表分区数 <= 1000
                max_partitions = cfg.get("max_partitions", 1000)
                partition_count = len(partitions)
                if partition_count > max_partitions:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"表 '{table.name}' 分区数 {partition_count} 超过上限 {max_partitions}",
                        table_name=table.name,
                        suggestion=rule.get("suggestion", f"减少分区数至 {max_partitions} 以内"),
                    ))

            elif rule_id == "SR-PART-002":
                # 单分区数据量 1-10GB
                min_size_gb = cfg.get("min_size_gb", 1)
                max_size_gb = cfg.get("max_size_gb", 10)
                for p in partitions:
                    # data_size 在 StarRocks 中以 KB 为单位
                    data_size_kb = int(p.get("DataSize", 0) or 0)
                    data_size_gb = data_size_kb / (1024 * 1024)
                    if data_size_gb > 0:
                        if data_size_gb < min_size_gb:
                            violations.append(Violation(
                                level=level,
                                rule_name=rule["category"],
                                message=f"表 '{table.name}' 分区 '{p.get('PartitionName', '')}' 数据量 {data_size_gb:.2f}GB 小于下限 {min_size_gb}GB",
                                table_name=table.name,
                                suggestion=rule.get("suggestion", "合并过小分区"),
                            ))
                        elif data_size_gb > max_size_gb:
                            violations.append(Violation(
                                level=level,
                                rule_name=rule["category"],
                                message=f"表 '{table.name}' 分区 '{p.get('PartitionName', '')}' 数据量 {data_size_gb:.2f}GB 超过上限 {max_size_gb}GB",
                                table_name=table.name,
                                suggestion=rule.get("suggestion", "拆分过大分区"),
                            ))

            elif rule_id == "SR-BUCK-005":
                # 分桶列禁止可空 - 需要查询表结构获取分桶列
                try:
                    with self.connector.engine.connect() as conn:
                        from sqlalchemy import text
                        result = conn.execute(
                            text("SHOW CREATE TABLE `:db`.`:tbl`"),
                            {"db": table.database, "tbl": table.name}
                        )
                        create_stmt = result.fetchone()[0] if result.fetchone() else ""
                        # 解析分桶列并检查是否可空 (需要通过 information_schema 查询)
                        # 简化实现：通过 information_schema.COLUMNS 查询
                        col_result = conn.execute(
                            text("""
                                SELECT COLUMN_NAME, IS_NULLABLE
                                FROM information_schema.COLUMNS
                                WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :tbl
                            """),
                            {"db": table.database, "tbl": table.name}
                        )
                        columns_info = {row[0]: row[1] for row in col_result.fetchall()}
                        # 尝试从 create statement 中提取分桶列
                        import re
                        bucket_match = re.search(r"DISTRIBUTED BY\s+\(([^)]+)\)", create_stmt, re.IGNORECASE)
                        if bucket_match:
                            bucket_cols = [c.strip() for c in bucket_match.group(1).split(",")]
                            for col in bucket_cols:
                                if col in columns_info and columns_info[col].upper() == "YES":
                                    violations.append(Violation(
                                        level=level,
                                        rule_name=rule["category"],
                                        message=f"表 '{table.name}' 分桶列 '{col}' 允许为空 (SR-BUCK-005)",
                                        table_name=table.name,
                                        column_name=col,
                                        suggestion=rule.get("suggestion", "分桶列不允许可空"),
                                    ))
                except Exception:
                    pass  # 无法获取表结构时跳过

            # SR-PART-003/004/006 暂未实现，保留 stub
            elif rule_id in ("SR-PART-003", "SR-PART-004", "SR-PART-006"):
                pass  # Stub

        return violations

    def _check_sr_replica_rules(self, table: "TableInfo") -> List["Violation"]:
        """SR-REP-001/002/003/004: 副本与一致性检查（需要调用 connector 执行 SHOW PARTITIONS）"""
        from .parser import TableInfo
        violations = []

        sr_rules = self.rules._find_sr_rules_by_category("sr_replica")
        if not sr_rules:
            return violations

        # SR-REP-001: 生产环境副本数=3
        # SR-REP-002: 测试环境副本数>=2
        # SR-REP-003: 副本均衡度 <= 0.1
        # SR-REP-004: colocate group 副本布局一致

        # 这些规则需要通过 connector 执行 SHOW PARTITIONS 查询
        # connector 通过 set_connector 注入
        if not self.connector:
            return violations

        try:
            db_name = table.database
            tbl_name = table.name

            # 查询分区信息
            with self.connector.engine.connect() as conn:
                from sqlalchemy import text
                result = conn.execute(
                    text("SHOW PARTITIONS FROM :db.:tbl"),
                    {"db": db_name, "tbl": tbl_name}
                )
                partitions = result.fetchall()

            for rule in sr_rules:
                cfg = rule.get("config_json", {})
                level = ViolationLevel.ERROR if rule["level"] == "critical" else ViolationLevel.WARNING
                rule_id = rule["rule_id"]

                if rule_id == "SR-REP-001":
                    required = cfg.get("required_replicas", 3)
                    for p in partitions:
                        # 分区信息包含副本数字段
                        if len(p) > 3:
                            replicas = int(p[3]) if p[3] else 0
                            if replicas != required:
                                violations.append(Violation(
                                    level=level,
                                    rule_name=rule["category"],
                                    message=f"表 '{tbl_name}' 分区副本数 {replicas} != {required}",
                                    table_name=tbl_name,
                                    suggestion=rule.get("suggestion", f"修改表副本数为 {required}"),
                                ))

                elif rule_id == "SR-REP-002":
                    min_rep = cfg.get("min_replicas", 2)
                    for p in partitions:
                        if len(p) > 3:
                            replicas = int(p[3]) if p[3] else 0
                            if replicas < min_rep:
                                violations.append(Violation(
                                    level=level,
                                    rule_name=rule["category"],
                                    message=f"表 '{tbl_name}' 分区副本数 {replicas} < {min_rep}",
                                    table_name=tbl_name,
                                    suggestion=rule.get("suggestion", f"修改表副本数 >= {min_rep}"),
                                ))

        except Exception:
            # 无法获取分区信息，跳过动态检查
            pass

        return violations

    def _check_sr_perf_rules(self, table: "TableInfo") -> List["Violation"]:
        """SR-PERF-001/002/003/004: 性能相关检查（Tablet 数、Tablet 大小、Compaction Score、慢查询比例）"""
        from .parser import TableInfo
        violations = []

        sr_rules = self.rules._find_sr_rules_by_category("sr_perf")
        if not sr_rules:
            return violations

        # SR-PERF-001: 单表 Tablet 数 <= 30000
        # SR-PERF-002: 单 Tablet 大小 <= 5GB
        # SR-PERF-003: Compaction 累计 < 100
        # SR-PERF-004: 慢查询比例 < 5%

        if not self.connector:
            return violations

        tablets = self._show_tablets(table.database, table.name)

        for rule in sr_rules:
            cfg = rule.get("config_json", {})
            level = ViolationLevel.WARNING
            rule_id = rule["rule_id"]

            try:
                if rule_id == "SR-PERF-001":
                    # 单表 Tablet 数 <= 30000
                    max_tablets = cfg.get("max_tablets", 30000)
                    tablet_count = len(tablets)
                    if tablet_count > max_tablets:
                        violations.append(Violation(
                            level=level,
                            rule_name=rule["category"],
                            message=f"表 '{table.name}' Tablet 数 {tablet_count} 超过上限 {max_tablets}",
                            table_name=table.name,
                            suggestion=rule.get("suggestion", f"减少 Tablet 数至 {max_tablets} 以内"),
                        ))

                elif rule_id == "SR-PERF-002":
                    # 单 Tablet 大小 <= 5GB
                    max_size_gb = cfg.get("max_tablet_size_gb", 5)
                    for tablet in tablets:
                        # Size 在 StarRocks 中可能以 KB 或 MB 为单位
                        size_str = tablet.get("Size", tablet.get("DataSize", "0"))
                        try:
                            size_kb = int(size_str) if size_str else 0
                        except (ValueError, TypeError):
                            size_kb = 0
                        size_gb = size_kb / (1024 * 1024)
                        if size_gb > max_size_gb:
                            violations.append(Violation(
                                level=level,
                                rule_name=rule["category"],
                                message=f"表 '{table.name}' Tablet {tablet.get('TabletId', '')} 大小 {size_gb:.2f}GB 超过上限 {max_size_gb}GB",
                                table_name=table.name,
                                suggestion=rule.get("suggestion", "Tablet 过大会影响查询性能"),
                            ))

                elif rule_id == "SR-PERF-003":
                    # Compaction 累计 < 100 (通过 SHOW TABLETS 获取 compaction score)
                    max_compaction_score = cfg.get("max_compaction_score", 100)
                    for tablet in tablets:
                        compaction_score = int(tablet.get("CompactionScore", tablet.get("Compaction_Score", 0)) or 0)
                        if compaction_score > max_compaction_score:
                            violations.append(Violation(
                                level=level,
                                rule_name=rule["category"],
                                message=f"表 '{table.name}' Tablet {tablet.get('TabletId', '')} Compaction Score {compaction_score} 超过上限 {max_compaction_score}",
                                table_name=table.name,
                                suggestion=rule.get("suggestion", "Compaction Score 过高会影响写入性能"),
                            ))

                elif rule_id == "SR-PERF-004":
                    # 慢查询比例 < 5% (需要 query history，此处 stub)
                    # SR-PERF-004 需要通过 information_schema 或 query 统计获取
                    # 暂时跳过，待 query history 接口就绪
                    pass

            except Exception:
                # 无法获取性能指标，跳过
                pass

        return violations

    def _check_sr_meta_rules(self, table: "TableInfo") -> List["Violation"]:
        """SR-META-001/002/003: 元数据合规性检查（表 COMMENT、关键列 COMMENT、表 owner）"""
        from .parser import TableInfo
        violations = []

        sr_rules = self.rules._find_sr_rules_by_category("sr_meta")
        if not sr_rules:
            return violations

        for rule in sr_rules:
            cfg = rule.get("config_json", {})
            level = ViolationLevel.WARNING
            rule_id = rule["rule_id"]

            if rule_id == "SR-META-001":
                # 表必须有 COMMENT
                if not table.comment:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"表 '{table.name}' 缺少 COMMENT",
                        table_name=table.name,
                        suggestion=rule.get("suggestion", "为表添加 COMMENT"),
                    ))

            elif rule_id == "SR-META-002":
                # 关键列必须有 COMMENT
                key_cols = cfg.get("key_columns", [])
                pk_cols = set(table.get_primary_key_columns())
                # 分区列和分桶列需要通过 connector 查询
                for col in table.columns:
                    if col.name in pk_cols or col.is_primary_key:
                        if not col.comment:
                            violations.append(Violation(
                                level=level,
                                rule_name=rule["category"],
                                message=f"主键列 '{col.name}' 缺少 COMMENT",
                                table_name=table.name,
                                column_name=col.name,
                                suggestion=rule.get("suggestion", "为主键列添加 COMMENT"),
                            ))

            elif rule_id == "SR-META-003":
                # 表 owner 必须设置（需要通过 connector 查询）
                if not self.connector:
                    continue
                try:
                    with self.connector.engine.connect() as conn:
                        from sqlalchemy import text
                        result = conn.execute(
                            text("SHOW TABLE :tbl PROPERTIES"),
                            {"tbl": table.name}
                        )
                        # 解析 owner
                        pass
                except Exception:
                    pass

        return violations

    def _check_sr_view_naming(self, table: TableInfo) -> List[Violation]:
        """SR-025: 视图命名 _vw 后缀检查"""
        violations = []

        sr_rules = self.rules._find_sr_rules_by_category("sr_view_naming")
        for rule in sr_rules:
            cfg = rule.get("config_json", {})
            pattern = cfg.get("pattern")
            level = ViolationLevel.ERROR if rule["level"] == "HIGH" else ViolationLevel.WARNING

            if pattern and not re.search(pattern, table.name):
                violations.append(Violation(
                    level=level,
                    rule_name=rule["category"],
                    message=f"视图 '{table.name}' 缺少 _vw 后缀",
                    table_name=table.name,
                    suggestion=rule.get("suggestion", "视图命名应以 _vw 结尾"),
                ))

        return violations


class ColumnValidator:
    """列级验证器"""

    def __init__(self, rules: DatabaseRulesAdapter):
        self.rules = rules

    def validate(self, table: TableInfo) -> List[Violation]:
        """验证表的所有列"""
        violations = []

        for column in table.columns:
            violations.extend(self._validate_column(table, column))

        return violations

    def _validate_column(self, table: TableInfo, column: ColumnInfo) -> List[Violation]:
        """验证单个列"""
        violations = []

        violations.extend(self._check_naming(table, column))
        violations.extend(self._check_data_type(table, column))
        violations.extend(self._check_comment(table, column))

        # StarRocks 专属检查
        if self.rules._find_sr_rules_by_category("sr_type_alignment"):
            violations.extend(self._check_sr_type_alignment(table, column))

        return violations

    def _check_naming(self, table: TableInfo, column: ColumnInfo) -> List[Violation]:
        """检查列命名"""
        violations = []
        if not self.rules.is_rule_enabled("column_naming"):
            return violations

        config = self.rules.get_rule_config("column_naming")
        pattern = config.get("config_json", {}).get("pattern", r"^[a-z][a-z0-9_]*$")
        max_length = config.get("config_json", {}).get("max_length", 64)
        reserved_words = config.get("config_json", {}).get("reserved_words", [])

        col_name = column.name
        if col_name is None:
            col_name = ""

        # 检查长度
        if len(col_name) > max_length:
            violations.append(Violation(
                level=ViolationLevel.ERROR,
                rule_name="column_naming",
                message=f"列名 '{col_name}' 长度超过 {max_length} 字符",
                table_name=table.name,
                column_name=col_name,
                suggestion=f"将列名控制在 {max_length} 字符以内"
            ))

        # 检查命名模式
        if not re.match(pattern, col_name):
            violations.append(Violation(
                level=ViolationLevel.ERROR,
                rule_name="column_naming",
                message=f"列名 '{col_name}' 不符合命名规范",
                table_name=table.name,
                column_name=col_name,
                suggestion=config.get("suggestion", "列名必须以小写字母开头，支持小写字母、数字、下划线")
            ))

        # 检查保留字
        if col_name.lower() in [w.lower() for w in reserved_words]:
            violations.append(Violation(
                level=ViolationLevel.INFO,
                rule_name="column_naming",
                message=f"列名 '{col_name}' 是保留字",
                table_name=table.name,
                column_name=col_name,
                suggestion="考虑使用更明确的列名"
            ))

        return violations

    def _check_data_type(self, table: TableInfo, column: ColumnInfo) -> List[Violation]:
        """检查数据类型"""
        violations = []
        if not self.rules.is_rule_enabled("data_type"):
            return violations

        config = self.rules.get_rule_config("data_type")
        deprecated_types = config.get("config_json", {}).get("deprecated_types", [])
        recommended_types = config.get("config_json", {}).get("recommended_types", [])

        # 防御性检查：确保 data_type 不为 None
        if column.data_type is None:
            return violations

        # 检查是否是不推荐类型
        for dep_type in deprecated_types:
            if column.data_type.upper() == dep_type.upper():
                violations.append(Violation(
                    level=ViolationLevel.WARNING,
                    rule_name="data_type",
                    message=f"列 '{column.name}' 使用不推荐的数据类型 {column.data_type}",
                    table_name=table.name,
                    column_name=column.name,
                    suggestion=config.get("suggestion", f"建议使用 {', '.join(recommended_types)} 之一")
                ))

        return violations

    def _check_comment(self, table: TableInfo, column: ColumnInfo) -> List[Violation]:
        """检查列注释"""
        violations = []
        if not self.rules.is_rule_enabled("column_comment"):
            return violations

        config = self.rules.get_rule_config("column_comment")
        require = config.get("config_json", {}).get("require_column_comment", True)

        if require and not column.comment:
            violations.append(Violation(
                level=ViolationLevel.WARNING,
                rule_name="column_comment",
                message=f"列 '{column.name}' 缺少注释",
                table_name=table.name,
                column_name=column.name,
                suggestion=config.get("suggestion", "为列添加注释说明其含义")
            ))

        return violations

    def _check_sr_type_alignment(self, table: TableInfo, column: ColumnInfo) -> List[Violation]:
        """SR-006, 007, 019, 020: 字段后缀与类型对齐检查"""
        violations = []

        sr_rules = self.rules._find_sr_rules_by_category("sr_type_alignment")
        for rule in sr_rules:
            cfg = rule.get("config_json", {})
            suffixes = cfg.get("suffixes", [])
            required_type = cfg.get("required_type")
            required_types = cfg.get("required_types", [])
            forbidden_types = cfg.get("forbidden_types", [])
            level = ViolationLevel.ERROR if rule["level"] == "HIGH" else ViolationLevel.WARNING

            if required_type:
                required_types = [required_type]

            col_name = column.name.lower()
            col_type = column.data_type.upper()

            # 检查列名是否匹配后缀
            matched = any(col_name.endswith(s) for s in suffixes)
            if not matched:
                continue

            # 检查禁止的类型
            for ft in forbidden_types:
                if ft.upper() in col_type:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["category"],
                        message=f"字段 '{column.name}' 使用了禁止的类型 {col_type}，{rule['name']}",
                        table_name=table.name,
                        column_name=column.name,
                        suggestion=rule.get("suggestion", f"应使用 {', '.join(required_types)} 类型"),
                    ))
                    break

            # 检查是否使用了要求的类型
            if required_types and not any(rt.upper() in col_type for rt in required_types):
                violations.append(Violation(
                    level=level,
                    rule_name=rule["category"],
                    message=f"字段 '{column.name}' 类型 {col_type} 不符合要求，{rule['name']}",
                    table_name=table.name,
                    column_name=column.name,
                    suggestion=rule.get("suggestion", f"应使用 {', '.join(required_types)} 类型"),
                ))


        # SR-SCH-003: 时间字段禁止 VARCHAR（扩展检查）
        # SR-SCH-008: 禁止 BLOB（扩展检查）已在主逻辑覆盖
        # 额外检查：时间字段后缀但使用 VARCHAR
        sr_schema_rules = self.rules._find_sr_rules_by_category("sr_schema")
        for rule in sr_schema_rules:
            if rule["rule_id"] != "SR-SCH-003":
                continue
            cfg = rule.get("config_json", {})
            suffixes = cfg.get("suffixes", ["_time", "_at", "_dt"])
            forbidden = cfg.get("forbidden", ["VARCHAR", "CHAR", "STRING"])
            col_name_lower = column.name.lower()
            col_type_upper = column.data_type.upper()
            if any(col_name_lower.endswith(s) for s in suffixes):
                for ft in forbidden:
                    if ft.upper() in col_type_upper:
                        level = ViolationLevel.WARNING
                        violations.append(Violation(
                            level=level,
                            rule_name=rule["category"],
                            message=f"时间字段 '{column.name}' 使用了禁止的类型 {column.data_type}，SR-SCH-003",
                            table_name=table.name,
                            column_name=column.name,
                            suggestion=rule.get("suggestion", "将时间字段改为 DATETIME 类型"),
                        ))
                        break
        return violations


class DDLValidator:
    """
    DDL 验证器 — 整合表级和列级验证

    运行时从数据库（bi_rule_configs）加载规则，支持场景化评分。
    """

    def __init__(self, scene_type: str = "ALL", db_type: str = "MySQL"):
        """
        初始化验证器

        Args:
            scene_type: 业务场景（ODS/DWD/ADS/ALL），用于差异化评分
            db_type: 数据库类型（MySQL/SQL Server）
        """
        self.scene_type = scene_type
        self.db_type = db_type
        self._db_adapter = DatabaseRulesAdapter(scene_type=scene_type, db_type=db_type)
        self.table_validator = TableValidator(self._db_adapter)
        self.column_validator = ColumnValidator(self._db_adapter)

    def validate_table(self, table: TableInfo) -> List[Violation]:
        """验证单个表"""
        violations = []
        violations.extend(self.table_validator.validate(table))
        violations.extend(self.column_validator.validate(table))
        return violations

    def validate_tables(self, tables: List[TableInfo]) -> Dict[str, List[Violation]]:
        """验证多个表"""
        results = {}
        for table in tables:
            results[table.name] = self.validate_table(table)
        return results

    def calculate_score(self, violations: List[Violation]) -> tuple:
        """
        计算评分（支持场景化权重）。

        Returns:
            tuple: (score, summary_dict)
        """
        weights = self._db_adapter.get_scene_weights()
        high_penalty = weights.get("high", -20)
        medium_penalty = weights.get("medium", -5)
        low_penalty = weights.get("low", -1)

        high_count = sum(1 for v in violations if v.level == ViolationLevel.ERROR)
        medium_count = sum(1 for v in violations if v.level == ViolationLevel.WARNING)
        low_count = sum(1 for v in violations if v.level == ViolationLevel.INFO)

        score = 100 + (high_count * high_penalty) + (medium_count * medium_penalty) + (low_count * low_penalty)
        score = max(0, min(100, score))
        summary = {"High": high_count, "Medium": medium_count, "Low": low_count}

        return score, summary
