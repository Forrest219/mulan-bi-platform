"""DQC 规则建议器

职责：
- 基于表 profiling 结果自动生成规则草稿
- LLM 辅助生成更精确的规则建议
- 写入 bi_dqc_quality_rules（is_system_suggested=True）
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .constants import (
    ALL_DIMENSIONS,
    DIMENSION_RULE_COMPATIBILITY,
    RULE_TYPE_TO_DIMENSION,
    RuleType,
)
from .database import DqcDatabase
from .models import DqcMonitoredAsset, DqcQualityRule, DqcRuleResult

logger = logging.getLogger(__name__)

# 基于 profiling 结果的自动规则建议模板
AUTO_RULE_TEMPLATES = {
    "null_rate": {
        "dimension": "completeness",
        "rule_type": "null_rate",
        "default_threshold": {"max_rate": 0.05},
        "condition": lambda col: col.get("null_rate", 0) > 0,
    },
    "uniqueness": {
        "dimension": "uniqueness",
        "rule_type": "uniqueness",
        "default_threshold": {"max_duplicate_rate": 0.01},
        "condition": lambda col: col.get("distinct_count", 0) is not None,
    },
    "freshness": {
        "dimension": "timeliness",
        "rule_type": "freshness",
        "default_threshold": {"max_age_hours": 24},
        "condition": lambda col: "timestamp" in col.get("data_type", "").lower(),
    },
}

RULE_SUGGESTION_PROMPT = """你是一个数据质量专家。请基于以下表结构信息建议质量监控规则。

## 表信息
- Schema: {schema_name}
- 表名: {table_name}
- 行数: {row_count}
- 字段信息:
{columns_info}

## 已有规则
{existing_rules}

## 任务
请分析这个表的特征，推荐适合的质量监控规则。每个规则应包含：
1. 规则名称（name）
2. 维度（dimension）：completeness/accuracy/timeliness/validity/uniqueness/consistency
3. 规则类型（rule_type）
4. 规则配置（rule_config）
5. 严重级别（severity）：HIGH/MEDIUM/LOW

请用 JSON 格式返回规则数组：
{{
  "suggested_rules": [
    {{
      "name": "规则名称",
      "dimension": "维度",
      "rule_type": "规则类型",
      "rule_config": {{"配置": "值"}},
      "severity": "HIGH/MEDIUM/LOW"
    }}
  ]
}}

只返回 JSON。
"""


@dataclass
class SuggestedRule:
    """建议的规则"""
    name: str
    dimension: str
    rule_type: str
    rule_config: Dict[str, Any]
    severity: str
    reason: str


class DqcRuleSuggester:
    """DQC 规则建议器"""

    def __init__(self, dao: Optional[DqcDatabase] = None):
        self.dao = dao or DqcDatabase()

    def suggest_rules_from_profile(
        self,
        db: Session,
        asset: DqcMonitoredAsset,
        max_rules: int = 5,
    ) -> List[SuggestedRule]:
        """基于 profiling 结果自动生成规则建议"""
        profile = asset.profile_json
        if not profile:
            return []

        suggestions: List[SuggestedRule] = []
        existing_rules = self.dao.list_rules_by_asset(db, asset.id, is_active=True)
        existing_rule_types = {r.rule_type for r in existing_rules}

        # 1. 基于字段特征的自动规则
        columns = profile.get("columns", [])
        for col in columns:
            col_name = col.get("name", "")
            data_type = col.get("data_type", "").lower()
            null_rate = col.get("null_rate", 0)
            distinct_count = col.get("distinct_count")
            is_timestamp = "timestamp" in data_type or "date" in data_type

            # 空值率规则
            if null_rate > 0 and "null_rate" not in existing_rule_types:
                suggestions.append(
                    SuggestedRule(
                        name=f"{col_name} 空值率监控",
                        dimension="completeness",
                        rule_type="null_rate",
                        rule_config={"column": col_name, "max_rate": min(0.05, null_rate * 2)},
                        severity="HIGH" if null_rate > 0.1 else "MEDIUM",
                        reason=f"当前空值率: {null_rate:.2%}",
                    )
                )
                existing_rule_types.add("null_rate")

            # 唯一性规则（候选主键）
            candidate_id_cols = profile.get("candidate_id_columns", [])
            if col_name in candidate_id_cols and "uniqueness" not in existing_rule_types:
                suggestions.append(
                    SuggestedRule(
                        name=f"{col_name} 唯一性监控",
                        dimension="uniqueness",
                        rule_type="uniqueness",
                        rule_config={"columns": [col_name], "max_duplicate_rate": 0},
                        severity="HIGH",
                        reason="候选主键列",
                    )
                )
                existing_rule_types.add("uniqueness")

            # 新鲜度规则（时间戳列）
            if is_timestamp and "freshness" not in existing_rule_types:
                suggestions.append(
                    SuggestedRule(
                        name=f"{col_name} 数据新鲜度监控",
                        dimension="timeliness",
                        rule_type="freshness",
                        rule_config={"column": col_name, "max_age_hours": 24},
                        severity="MEDIUM",
                        reason=f"时间戳列: {data_type}",
                    )
                )
                existing_rule_types.add("freshness")

            # 值域规则（数值列）
            min_val = col.get("min_value")
            max_val = col.get("max_value")
            if min_val is not None and max_val is not None:
                if isinstance(min_val, (int, float)) and isinstance(max_val, (int, float)):
                    if max_val - min_val > 0 and "range_check" not in existing_rule_types:
                        suggestions.append(
                            SuggestedRule(
                                name=f"{col_name} 值域监控",
                                dimension="validity",
                                rule_type="range_check",
                                rule_config={
                                    "column": col_name,
                                    "min": min_val,
                                    "max": max_val,
                                    "check_mode": "min_max_all",
                                },
                                severity="LOW",
                                reason=f"值域: [{min_val}, {max_val}]",
                            )
                        )
                        existing_rule_types.add("range_check")

            if len(suggestions) >= max_rules:
                break

        # 2. 表级规则
        row_count = profile.get("row_count", 0)
        if row_count > 0 and "volume_anomaly" not in existing_rule_types:
            suggestions.append(
                SuggestedRule(
                    name="表行数异常监控",
                    dimension="completeness",
                    rule_type="volume_anomaly",
                    rule_config={
                        "direction": "both",
                        "threshold_pct": 0.20,
                        "comparison_window": "1d",
                        "min_row_count": max(1000, row_count * 0.1),
                    },
                    severity="MEDIUM",
                    reason=f"当前行数: {row_count}",
                )
            )

        return suggestions[:max_rules]

    def suggest_rules_with_llm(
        self,
        db: Session,
        asset: DqcMonitoredAsset,
        max_rules: int = 5,
    ) -> List[SuggestedRule]:
        """使用 LLM 基于表结构生成规则建议"""
        profile = asset.profile_json
        if not profile:
            return self.suggest_rules_from_profile(db, asset, max_rules)

        # 构建字段信息
        columns_info = []
        for col in profile.get("columns", [])[:20]:  # 限制字段数量
            col_desc = (
                f"- {col.get('name')}: {col.get('data_type')}, "
                f"空值率={col.get('null_rate', 0):.2%}, "
                f"唯一值数={col.get('distinct_count', 'N/A')}"
            )
            columns_info.append(col_desc)

        existing_rules = self.dao.list_rules_by_asset(db, asset.id, is_active=True)
        existing_rules_desc = []
        for r in existing_rules:
            existing_rules_desc.append(f"- {r.name} ({r.rule_type})")

        prompt = RULE_SUGGESTION_PROMPT.format(
            schema_name=asset.schema_name,
            table_name=asset.table_name,
            row_count=profile.get("row_count", 0),
            columns_info="\n".join(columns_info) or "无",
            existing_rules="\n".join(existing_rules_desc) or "无",
        )

        # 调用 LLM
        llm_result = self._call_llm(prompt)

        suggestions = []
        for rule_data in llm_result.get("suggested_rules", []):
            suggestions.append(
                SuggestedRule(
                    name=rule_data.get("name", ""),
                    dimension=rule_data.get("dimension", ""),
                    rule_type=rule_data.get("rule_type", ""),
                    rule_config=rule_data.get("rule_config", {}),
                    severity=rule_data.get("severity", "MEDIUM"),
                    reason="LLM 推荐",
                )
            )

        return suggestions[:max_rules]

    def _call_llm(self, prompt: str) -> Dict[str, Any]:
        """调用 LLM 服务"""
        import asyncio
        from services.llm.service import LLMService

        async def _async_call():
            service = LLMService()
            result = await service.complete_for_semantic(
                prompt=prompt,
                system="你是一个数据质量专家，专注于推荐质量监控规则。",
                timeout=30,
                purpose="default",
            )
            return result

        from services.common.async_compat import run_async_safely

        result = run_async_safely(_async_call())

        if "error" in result:
            logger.warning("llm rule suggestion failed: %s", result["error"])
            return {"suggested_rules": []}

        content = result.get("content", "")
        return self._parse_llm_response(content)

    def _parse_llm_response(self, content: str) -> Dict[str, Any]:
        """解析 LLM 响应"""
        import re

        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            return {"suggested_rules": []}

        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            return {"suggested_rules": []}

    def create_suggested_rules(
        self,
        db: Session,
        asset_id: int,
        suggestions: List[SuggestedRule],
        created_by: int,
    ) -> List[DqcQualityRule]:
        """将建议的规则写入数据库（is_system_suggested=True）"""
        rules = []
        for suggestion in suggestions:
            # 验证规则类型和维度兼容性
            if suggestion.dimension not in ALL_DIMENSIONS:
                continue
            allowed = DIMENSION_RULE_COMPATIBILITY.get(suggestion.dimension, set())
            if suggestion.rule_type not in allowed:
                continue

            # 检查是否已存在同名规则
            if self.dao.rule_name_exists(db, asset_id, suggestion.name):
                continue

            rule = self.dao.create_rule(
                db,
                asset_id=asset_id,
                name=suggestion.name,
                dimension=suggestion.dimension,
                rule_type=suggestion.rule_type,
                rule_config=suggestion.rule_config,
                is_active=False,  # 建议规则默认不启用
                is_system_suggested=True,
                created_by=created_by,
            )
            rules.append(rule)

        db.commit()
        return rules


def suggest_and_create_rules(
    db: Session,
    asset_id: int,
    created_by: int,
    use_llm: bool = False,
    max_rules: int = 5,
) -> List[DqcQualityRule]:
    """便捷函数：建议并创建规则"""
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        return []

    suggester = DqcRuleSuggester(dao)

    if use_llm:
        suggestions = suggester.suggest_rules_with_llm(db, asset, max_rules)
    else:
        suggestions = suggester.suggest_rules_from_profile(db, asset, max_rules)

    return suggester.create_suggested_rules(db, asset_id, suggestions, created_by)