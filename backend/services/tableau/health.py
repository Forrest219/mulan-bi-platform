"""Tableau 资产健康评分引擎"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


# 健康检查项及权重
HEALTH_CHECKS = [
    {"key": "has_description", "label": "有描述信息", "weight": 20},
    {"key": "has_owner", "label": "有所有者", "weight": 15},
    {"key": "has_datasource_link", "label": "有关联数据源", "weight": 15},
    {"key": "fields_have_captions", "label": "字段有中文名", "weight": 20},
    {"key": "is_certified", "label": "已认证", "weight": 10},
    {"key": "naming_convention", "label": "命名规范", "weight": 10},
    {"key": "not_stale", "label": "近期有更新", "weight": 10},
]


def get_health_level(score: float) -> str:
    if score >= 80:
        return "excellent"
    elif score >= 60:
        return "good"
    elif score >= 40:
        return "warning"
    return "poor"


def compute_asset_health(
    asset: Dict[str, Any],
    datasources: List[Any],
    fields: List[Any],
) -> Dict[str, Any]:
    """
    计算单个资产的健康评分。

    Args:
        asset: 资产 dict (from to_dict())
        datasources: 关联数据源列表
        fields: 数据源字段列表

    Returns:
        {score, level, checks: [{key, label, weight, passed, detail}]}
    """
    checks = []
    total_score = 0.0

    # 1. has_description
    has_desc = bool(asset.get("description") and asset["description"].strip())
    checks.append({
        "key": "has_description",
        "label": "有描述信息",
        "weight": 20,
        "passed": has_desc,
        "detail": "已填写描述" if has_desc else "缺少描述，建议补充报表用途说明",
    })
    if has_desc:
        total_score += 20

    # 2. has_owner
    has_owner = bool(asset.get("owner_name") and asset["owner_name"].strip())
    checks.append({
        "key": "has_owner",
        "label": "有所有者",
        "weight": 15,
        "passed": has_owner,
        "detail": f"所有者: {asset.get('owner_name', '')}" if has_owner else "缺少所有者信息",
    })
    if has_owner:
        total_score += 15

    # 3. has_datasource_link
    has_ds = len(datasources) > 0
    checks.append({
        "key": "has_datasource_link",
        "label": "有关联数据源",
        "weight": 15,
        "passed": has_ds,
        "detail": f"关联 {len(datasources)} 个数据源" if has_ds else "未关联数据源",
    })
    if has_ds:
        total_score += 15

    # 4. fields_have_captions (仅对有字段的资产检查)
    if fields:
        captioned = sum(1 for f in fields if getattr(f, 'field_caption', None) or getattr(f, 'ai_caption', None))
        ratio = captioned / len(fields) if fields else 0
        passed = ratio >= 0.5
        checks.append({
            "key": "fields_have_captions",
            "label": "字段有中文名",
            "weight": 20,
            "passed": passed,
            "detail": f"{captioned}/{len(fields)} 个字段有中文名 ({ratio:.0%})" if fields else "无字段数据",
        })
        if passed:
            total_score += 20 * min(1.0, ratio)
    else:
        checks.append({
            "key": "fields_have_captions",
            "label": "字段有中文名",
            "weight": 20,
            "passed": True,
            "detail": "无字段数据，跳过检查",
        })
        total_score += 20

    # 5. is_certified
    certified = bool(asset.get("is_certified"))
    checks.append({
        "key": "is_certified",
        "label": "已认证",
        "weight": 10,
        "passed": certified,
        "detail": "已通过认证" if certified else "未认证，建议完善元数据后申请认证",
    })
    if certified:
        total_score += 10

    # 6. naming_convention (简单检查：名称不含特殊字符，不以数字开头)
    name = asset.get("name", "")
    name_ok = bool(name) and not name[0].isdigit() and not any(c in name for c in ['@', '#', '$', '!'])
    checks.append({
        "key": "naming_convention",
        "label": "命名规范",
        "weight": 10,
        "passed": name_ok,
        "detail": "命名符合规范" if name_ok else "命名不规范，避免特殊字符或数字开头",
    })
    if name_ok:
        total_score += 10

    # 7. not_stale (90 天内有更新)
    updated_str = asset.get("updated_on_server")
    if updated_str:
        try:
            updated_dt = datetime.strptime(updated_str, "%Y-%m-%d %H:%M:%S")
            is_fresh = (datetime.now() - updated_dt) < timedelta(days=90)
        except (ValueError, TypeError):
            is_fresh = False
    else:
        is_fresh = False
    checks.append({
        "key": "not_stale",
        "label": "近期有更新",
        "weight": 10,
        "passed": is_fresh,
        "detail": f"最近更新: {updated_str}" if is_fresh else "超过 90 天未更新，建议确认是否仍在使用",
    })
    if is_fresh:
        total_score += 10

    score = round(total_score, 1)
    return {
        "score": score,
        "level": get_health_level(score),
        "checks": checks,
    }
