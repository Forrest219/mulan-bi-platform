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

    def validate(self, table: TableInfo) -> List[Violation]:
        """验证表"""
        violations = []

        violations.extend(self._check_naming(table))
        violations.extend(self._check_comment(table))
        violations.extend(self._check_primary_key(table))
        violations.extend(self._check_timestamp_fields(table))
        violations.extend(self._check_soft_delete(table))
        violations.extend(self._check_indexes(table))

        # StarRocks 专属检查（仅当存在 sr_* 类型规则时执行）
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
                    rule_name=rule["rule_id"],
                    message=f"表 '{table_name}' (库: {db_name}) 不符合命名规范: {rule['name']}",
                    table_name=table_name,
                    suggestion=rule.get("suggestion", f"表名应匹配模式: {pattern}"),
                ))

            if forbidden_prefixes:
                for prefix in forbidden_prefixes:
                    if table_name.startswith(prefix):
                        violations.append(Violation(
                            level=level,
                            rule_name=rule["rule_id"],
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
                        rule_name=rule["rule_id"],
                        message=f"表 '{table.name}' (库: {db_name}) 缺少公共字段 '{field['name']}'",
                        table_name=table.name,
                        suggestion=rule.get("suggestion", f"添加 {field['name']} {field_type} 字段"),
                    ))
                elif field_type and field_type not in column_types.get(field_name, ""):
                    violations.append(Violation(
                        level=ViolationLevel.WARNING,
                        rule_name=rule["rule_id"],
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
                    rule_name=rule["rule_id"],
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
                        rule_name=rule["rule_id"],
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
                        rule_name=rule["rule_id"],
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
                        rule_name=rule["rule_id"],
                        message=f"字段 '{col.name}' 不符合 snake_case 命名规范",
                        table_name=table.name,
                        column_name=col.name,
                        suggestion=rule.get("suggestion", "字段名使用小写字母+下划线"),
                    ))
                if len(col.name) > max_length:
                    violations.append(Violation(
                        level=ViolationLevel.WARNING,
                        rule_name=rule["rule_id"],
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
                        rule_name=rule["rule_id"],
                        message=f"检测到禁止的数据库 '{db_name}': {rule['name']}",
                        suggestion=rule.get("suggestion", f"删除或迁移数据库 '{db_name}'"),
                    ))

                if allowed and db_name.lower() not in [a.lower() for a in allowed]:
                    violations.append(Violation(
                        level=level,
                        rule_name=rule["rule_id"],
                        message=f"数据库 '{db_name}' 不在允许列表中: {rule['name']}",
                        suggestion=rule.get("suggestion", "联系管理员确认此数据库是否合规"),
                    ))

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
                    rule_name=rule["rule_id"],
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
                        rule_name=rule["rule_id"],
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
                    rule_name=rule["rule_id"],
                    message=f"字段 '{column.name}' 类型 {col_type} 不符合要求，{rule['name']}",
                    table_name=table.name,
                    column_name=column.name,
                    suggestion=rule.get("suggestion", f"应使用 {', '.join(required_types)} 类型"),
                ))

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
