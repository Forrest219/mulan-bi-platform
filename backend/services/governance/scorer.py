"""数据质量监控 - 评分计算器

遵循 Spec 15 v1.1 §5 质量评分模型：
- 三输入源整合：质量规则检测(50%) + 健康扫描(30%) + DDL合规(20%)
- 五维度评分：完整性(30%) / 一致性(25%) / 唯一性(20%) / 时效性(15%) / 格式规范(10%)
- 按严重级别加权：HIGH=3.0 / MEDIUM=2.0 / LOW=1.0
"""
from typing import List, Dict, Any, Optional

from .models import QualityResult


# 维度 -> 规则类型映射
DIMENSION_RULES = {
    "completeness": ["null_rate", "not_null", "row_count"],
    "consistency": ["referential", "cross_field", "value_range"],
    "uniqueness": ["duplicate_rate", "unique_count"],
    "timeliness": ["freshness", "latency"],
    "conformity": ["format_regex", "enum_check"],
}

# 维度权重
DIMENSION_WEIGHTS = {
    "completeness": 0.30,
    "consistency": 0.25,
    "uniqueness": 0.20,
    "timeliness": 0.15,
    "conformity": 0.10,
}

# 严重级别权重
SEVERITY_WEIGHTS = {"HIGH": 3.0, "MEDIUM": 2.0, "LOW": 1.0}

# 综合评分权重
RULE_SCORE_WEIGHT = 0.50
HEALTH_SCAN_WEIGHT = 0.30
DDL_COMPLIANCE_WEIGHT = 0.20


def calculate_dimension_score(results: List[QualityResult], rule_types: List[str]) -> float:
    """计算单个维度的评分

    Args:
        results: 该维度下所有规则的最新检测结果
        rule_types: 该维度对应的规则类型列表

    Returns:
        float: 维度评分 0.0 ~ 100.0，无规则时默认 100.0
    """
    dimension_results = [r for r in results if r.rule_type in rule_types]
    if not dimension_results:
        return 100.0  # 无规则时默认满分

    total_weight = 0.0
    weighted_pass = 0.0

    for r in dimension_results:
        severity = getattr(r, "severity", "MEDIUM")
        severity = severity if severity in SEVERITY_WEIGHTS else "MEDIUM"
        w = SEVERITY_WEIGHTS.get(severity, 1.0)
        total_weight += w
        if r.passed:
            weighted_pass += w

    if total_weight == 0:
        return 100.0
    return (weighted_pass / total_weight) * 100.0


def calculate_quality_score(
    rule_results: List[QualityResult],
    health_scan_score: Optional[float],
    ddl_compliance_score: Optional[float],
) -> Dict[str, Any]:
    """计算综合质量评分

    整合三大输入源：
    1. 质量规则检测（50%）
    2. 健康扫描（30%）
    3. DDL 合规（20%）

    Args:
        rule_results: 质量规则的最新检测结果列表
        health_scan_score: 健康扫描评分（0-100），None 表示无数据
        ddl_compliance_score: DDL 合规评分（0-100），None 表示无数据

    Returns:
        dict: 包含 overall_score 和各维度评分的字典
    """
    # 维度评分
    completeness = calculate_dimension_score(rule_results, DIMENSION_RULES["completeness"])
    consistency = calculate_dimension_score(rule_results, DIMENSION_RULES["consistency"])
    uniqueness = calculate_dimension_score(rule_results, DIMENSION_RULES["uniqueness"])
    timeliness = calculate_dimension_score(rule_results, DIMENSION_RULES["timeliness"])
    conformity = calculate_dimension_score(rule_results, DIMENSION_RULES["conformity"])

    # 规则维度加权
    rule_score = (
        completeness * DIMENSION_WEIGHTS["completeness"]
        + consistency * DIMENSION_WEIGHTS["consistency"]
        + uniqueness * DIMENSION_WEIGHTS["uniqueness"]
        + timeliness * DIMENSION_WEIGHTS["timeliness"]
        + conformity * DIMENSION_WEIGHTS["conformity"]
    )

    # 综合评分（整合健康扫描 + DDL 合规）
    components = [(rule_score, RULE_SCORE_WEIGHT)]
    remaining_weight = RULE_SCORE_WEIGHT

    if health_scan_score is not None:
        components.append((health_scan_score, HEALTH_SCAN_WEIGHT))
        remaining_weight -= HEALTH_SCAN_WEIGHT

    if ddl_compliance_score is not None:
        components.append((ddl_compliance_score, DDL_COMPLIANCE_WEIGHT))
        remaining_weight -= DDL_COMPLIANCE_WEIGHT

    # 未集成的输入源权重回归到规则评分
    if remaining_weight > 0:
        components[0] = (rule_score, components[0][1] + remaining_weight)

    overall = sum(score * weight for score, weight in components)
    overall = max(0.0, min(100.0, overall))

    return {
        "overall_score": round(overall, 1),
        "completeness_score": round(completeness, 1),
        "consistency_score": round(consistency, 1),
        "uniqueness_score": round(uniqueness, 1),
        "timeliness_score": round(timeliness, 1),
        "conformity_score": round(conformity, 1),
        "health_scan_score": health_scan_score,
        "ddl_compliance_score": ddl_compliance_score,
    }


def get_score_grade(score: float) -> Dict[str, str]:
    """根据评分返回等级描述

    | 等级 | 分数范围 | 颜色 |
    | 优秀 | >= 90 | 绿色 |
    | 良好 | >= 75 | 蓝色 |
    | 一般 | >= 60 | 黄色 |
    | 较差 | < 60 | 红色 |
    """
    if score >= 90:
        return {"grade": "优秀", "color": "green"}
    elif score >= 75:
        return {"grade": "良好", "color": "blue"}
    elif score >= 60:
        return {"grade": "一般", "color": "yellow"}
    else:
        return {"grade": "较差", "color": "red"}


# ==================== Spec 11 & Spec 06 集成 ====================


def get_latest_health_scan_score(datasource_id: int) -> Optional[float]:
    """
    从 bi_health_scan_records 读取最新健康扫描评分（Spec 11）

    Args:
        datasource_id: 数据源 ID

    Returns:
        float: 健康扫描评分（0-100），无数据时返回 None
    """
    from app.core.database import SessionLocal
    from services.health_scan.models import HealthScanRecord

    db = SessionLocal()
    try:
        record = (
            db.query(HealthScanRecord)
            .filter(
                HealthScanRecord.datasource_id == datasource_id,
                HealthScanRecord.status == "success",
            )
            .order_by(HealthScanRecord.id.desc())
            .first()
        )
        return record.health_score if record else None
    finally:
        db.close()


def get_latest_ddl_compliance_score(datasource_id: int) -> Optional[float]:
    """
    从 bi_scan_logs 读取最新 DDL 合规评分（Spec 06）

    评分公式：100 - (error_count * 20 + warning_count * 5 + info_count * 1)

    Args:
        datasource_id: 数据源 ID

    Returns:
        float: DDL 合规评分（0-100），无数据时返回 None
    """
    from app.core.database import SessionLocal
    from services.logs.models import ScanLog

    db = SessionLocal()
    try:
        record = (
            db.query(ScanLog)
            .filter(
                ScanLog.datasource_id == datasource_id,
                ScanLog.status == "completed",
            )
            .order_by(ScanLog.id.desc())
            .first()
        )
        if not record:
            return None
        ddl_score = max(
            0.0,
            100.0
            - (record.error_count or 0) * 20
            - (record.warning_count or 0) * 5
            - (record.info_count or 0) * 1,
        )
        return round(ddl_score, 1)
    finally:
        db.close()
