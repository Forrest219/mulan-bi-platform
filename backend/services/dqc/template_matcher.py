"""DQC 模板匹配器

读取 asset.profile_json 和 template.match_condition，
判断模板是否适用于该资产，生成规则实例。
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .database import DqcDatabase
from .models import DqcMonitoredAsset, DqcQualityRule, DqcRuleTemplate

logger = logging.getLogger(__name__)


class TemplateMatcher:
    """遍历 enabled 模板，按 match_condition 匹配列特征，实例化规则。"""

    def __init__(self, dao: Optional[DqcDatabase] = None):
        self.dao = dao or DqcDatabase()

    def match_and_instantiate(
        self,
        db: Session,
        asset: DqcMonitoredAsset,
        created_by: int,
    ) -> List[DqcQualityRule]:
        """对一个资产匹配所有 enabled 模板，创建派生规则。"""
        profile = asset.profile_json or {}

        templates = self.dao.list_templates(db, enabled=True)
        existing_rules = self.dao.list_rules_by_asset(db, asset.id)
        existing_template_ids = {r.template_id for r in existing_rules if r.template_id}

        created_rules: List[DqcQualityRule] = []

        for tmpl in templates:
            if tmpl.id in existing_template_ids:
                continue

            matched_columns = self._match_template(tmpl, profile)
            if matched_columns is None:
                continue

            rules = self._instantiate(db, asset, tmpl, matched_columns, created_by)
            created_rules.extend(rules)

        db.flush()
        return created_rules

    def _match_template(
        self, tmpl: DqcRuleTemplate, profile: Dict[str, Any]
    ) -> Optional[List[Dict[str, Any]]]:
        """判断模板是否匹配。返回匹配的列列表，table 级返回空列表，不匹配返回 None。"""
        condition = tmpl.match_condition or {}
        scope = condition.get("scope", "table")

        if scope == "table":
            return []

        if scope == "column":
            col_filter = condition.get("column_filter", {})
            columns = profile.get("columns", [])
            matched = []
            for col in columns:
                if self._column_matches(col, col_filter, profile):
                    matched.append(col)
            return matched if matched else None

        return None

    def _column_matches(
        self, col: Dict[str, Any], col_filter: Dict[str, Any], profile: Dict[str, Any]
    ) -> bool:
        if col_filter.get("has_nulls"):
            if col.get("null_rate", 0) <= 0:
                return False

        if col_filter.get("is_candidate_id"):
            candidates = profile.get("candidate_id_columns", [])
            if col.get("name") not in candidates:
                return False

        data_type_contains = col_filter.get("data_type_contains")
        if data_type_contains:
            data_type = col.get("data_type", "").lower()
            if not any(kw in data_type for kw in data_type_contains):
                return False

        if col_filter.get("has_numeric_range"):
            min_val = col.get("min_value")
            max_val = col.get("max_value")
            if min_val is None or max_val is None:
                return False
            if not (isinstance(min_val, (int, float)) and isinstance(max_val, (int, float))):
                return False
            if max_val - min_val <= 0:
                return False

        return True

    def _instantiate(
        self,
        db: Session,
        asset: DqcMonitoredAsset,
        tmpl: DqcRuleTemplate,
        matched_columns: List[Dict[str, Any]],
        created_by: int,
    ) -> List[DqcQualityRule]:
        rules: List[DqcQualityRule] = []
        scope = (tmpl.match_condition or {}).get("scope", "table")

        if scope == "table":
            rule_config = dict(tmpl.default_config or {})
            name = tmpl.name
            if self.dao.rule_name_exists(db, asset.id, name):
                return []
            rule = self.dao.create_rule(
                db,
                asset_id=asset.id,
                name=name,
                dimension=tmpl.dimension,
                rule_type=tmpl.rule_type,
                rule_config=rule_config,
                is_active=True,
                is_system_suggested=True,
                template_id=tmpl.id,
                is_modified_by_user=False,
                created_by=created_by,
            )
            rules.append(rule)
        else:
            for col in matched_columns[:3]:
                col_name = col.get("name", "unknown")
                name = f"{col_name} {tmpl.name}"
                if self.dao.rule_name_exists(db, asset.id, name):
                    continue

                rule_config = dict(tmpl.default_config or {})
                if tmpl.rule_type == "range_check":
                    rule_config["column"] = col_name
                    rule_config.setdefault("min", col.get("min_value"))
                    rule_config.setdefault("max", col.get("max_value"))
                elif tmpl.rule_type == "uniqueness":
                    rule_config["columns"] = [col_name]
                else:
                    rule_config["column"] = col_name

                rule = self.dao.create_rule(
                    db,
                    asset_id=asset.id,
                    name=name,
                    dimension=tmpl.dimension,
                    rule_type=tmpl.rule_type,
                    rule_config=rule_config,
                    is_active=True,
                    is_system_suggested=True,
                    template_id=tmpl.id,
                    is_modified_by_user=False,
                    created_by=created_by,
                )
                rules.append(rule)

        return rules
