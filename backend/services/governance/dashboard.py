"""质量看板服务

遵循 Spec 15 v1.1 §5 看板 API：
- 数据源评分排名
- 五维雷达图
- 近30天趋势
- 失败规则 TOP 10
"""
from typing import List, Dict, Any, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from services.governance.models import QualityScore, QualityRule, QualityResult
from services.datasources.models import DataSource


class QualityDashboardService:
    """质量看板数据聚合"""

    def __init__(self):
        self.db = SessionLocal()

    def close(self):
        """关闭数据库会话"""
        self.db.close()

    def get_dashboard(self) -> dict:
        """
        聚合看板数据：
        1. 所有数据源平均分
        2. 各数据源评分排名
        3. 规则通过率统计
        4. TOP 失败规则
        """
        try:
            summary = self._get_summary()
            datasource_scores = self._get_datasource_scores()
            top_failures = self._get_top_failures(limit=10)

            return {
                "summary": summary,
                "datasource_scores": datasource_scores,
                "top_failures": top_failures,
            }
        finally:
            self.db.close()

    def _get_summary(self) -> Dict[str, Any]:
        """获取汇总统计"""
        # 数据源总数
        total_ds = self.db.query(func.count(func.distinct(QualityScore.datasource_id))).scalar() or 0

        # 平均评分
        latest_subq = (
            self.db.query(
                QualityScore.datasource_id,
                func.max(QualityScore.id).label("max_id"),
            )
            .group_by(QualityScore.datasource_id)
            .subquery()
        )
        avg_score = (
            self.db.query(func.avg(QualityScore.overall_score))
            .join(latest_subq, QualityScore.id == latest_subq.c.max_id)
            .scalar()
        ) or 0.0

        # 规则统计
        total_rules = self.db.query(func.count(QualityRule.id)).scalar() or 0
        enabled_rules = (
            self.db.query(func.count(QualityRule.id))
            .filter(QualityRule.enabled == True)
            .scalar()
            or 0
        )

        # 最新检测结果通过率
        latest_results = self._get_latest_results(limit=10000)
        passed_count = sum(1 for r in latest_results if r.passed)
        failed_count = len(latest_results) - passed_count

        return {
            "total_datasources": total_ds,
            "avg_score": round(avg_score, 1),
            "rules_total": total_rules,
            "rules_passed": passed_count,
            "rules_failed": failed_count,
        }

    def _get_latest_results(self, limit: int = 100) -> List[QualityResult]:
        """获取各规则最新一次检测结果"""
        subq = (
            self.db.query(
                QualityResult.rule_id,
                func.max(QualityResult.executed_at).label("max_exec"),
            )
            .group_by(QualityResult.rule_id)
            .subquery()
        )
        results = (
            self.db.query(QualityResult)
            .join(
                subq,
                (QualityResult.rule_id == subq.c.rule_id)
                & (QualityResult.executed_at == subq.c.max_exec),
            )
            .limit(limit)
            .all()
        )
        return results

    def _get_datasource_scores(self) -> List[Dict[str, Any]]:
        """获取各数据源最新评分及趋势"""
        # 各数据源最新评分
        latest_subq = (
            self.db.query(
                QualityScore.datasource_id,
                func.max(QualityScore.id).label("max_id"),
            )
            .group_by(QualityScore.datasource_id)
            .subquery()
        )
        latest_scores = (
            self.db.query(QualityScore)
            .join(latest_subq, QualityScore.id == latest_subq.c.max_id)
            .all()
        )

        datasource_scores = []
        for sc in latest_scores:
            ds = self.db.query(DataSource).filter(DataSource.id == sc.datasource_id).first()

            # 计算7天趋势
            trend = self._get_score_trend(sc.datasource_id, days=7)
            trend_direction = "stable"
            if len(trend) >= 2:
                if trend[-1]["overall_score"] > trend[0]["overall_score"]:
                    trend_direction = "up"
                elif trend[-1]["overall_score"] < trend[0]["overall_score"]:
                    trend_direction = "down"

            datasource_scores.append({
                "datasource_id": sc.datasource_id,
                "datasource_name": ds.name if ds else f"数据源{sc.datasource_id}",
                "overall_score": sc.overall_score,
                "completeness_score": sc.completeness_score,
                "consistency_score": sc.consistency_score,
                "uniqueness_score": sc.uniqueness_score,
                "timeliness_score": sc.timeliness_score,
                "conformity_score": sc.conformity_score,
                "trend": trend_direction,
            })

        # 按评分降序排列
        datasource_scores.sort(key=lambda x: -x["overall_score"])
        return datasource_scores

    def _get_score_trend(self, datasource_id: int, days: int = 30) -> List[Dict[str, Any]]:
        """获取评分趋势"""
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(days=days)
        trend = (
            self.db.query(
                func.date(QualityScore.calculated_at).label("date"),
                func.max(QualityScore.overall_score).label("overall_score"),
            )
            .filter(
                QualityScore.datasource_id == datasource_id,
                QualityScore.calculated_at >= cutoff,
            )
            .group_by(func.date(QualityScore.calculated_at))
            .order_by(func.date(QualityScore.calculated_at))
            .all()
        )
        return [{"date": str(row.date), "overall_score": row.overall_score} for row in trend]

    def _get_top_failures(self, limit: int = 10) -> List[Dict[str, Any]]:
        """失败规则 TOP N"""
        latest_results = self._get_latest_results(limit=1000)
        failures = [r for r in latest_results if not r.passed]

        from collections import defaultdict

        rule_failure_count: Dict[int, int] = defaultdict(int)
        rule_info: Dict[int, Dict[str, Any]] = {}

        for r in failures:
            rule_failure_count[r.rule_id] += 1
            if r.rule_id not in rule_info:
                rule_info[r.rule_id] = {
                    "rule_id": r.rule_id,
                    "table_name": r.table_name,
                    "field_name": r.field_name,
                    "datasource_id": r.datasource_id,
                }

        sorted_failures = sorted(
            [{"consecutive_failures": rule_failure_count[k], **rule_info[k]} for k in rule_failure_count],
            key=lambda x: -x["consecutive_failures"],
        )[:limit]

        for f in sorted_failures:
            rule = self.db.query(QualityRule).filter(QualityRule.id == f["rule_id"]).first()
            if rule:
                f["rule_name"] = rule.name
                f["severity"] = rule.severity

            ds = self.db.query(DataSource).filter(DataSource.id == f["datasource_id"]).first()
            f["datasource_name"] = ds.name if ds else f"数据源{f['datasource_id']}"

        return sorted_failures

    def get_radar_data(self, datasource_id: int) -> Dict[str, Any]:
        """获取五维雷达图数据"""
        latest_subq = (
            self.db.query(
                QualityScore.datasource_id,
                func.max(QualityScore.id).label("max_id"),
            )
            .filter(QualityScore.datasource_id == datasource_id)
            .group_by(QualityScore.datasource_id)
            .subquery()
        )
        score = (
            self.db.query(QualityScore)
            .join(latest_subq, QualityScore.id == latest_subq.c.max_id)
            .first()
        )

        if not score:
            return {
                "dimensions": [
                    {"name": "完整性", "score": 0},
                    {"name": "一致性", "score": 0},
                    {"name": "唯一性", "score": 0},
                    {"name": "时效性", "score": 0},
                    {"name": "格式规范", "score": 0},
                ]
            }

        return {
            "dimensions": [
                {"name": "完整性", "score": score.completeness_score or 0},
                {"name": "一致性", "score": score.consistency_score or 0},
                {"name": "唯一性", "score": score.uniqueness_score or 0},
                {"name": "时效性", "score": score.timeliness_score or 0},
                {"name": "格式规范", "score": score.conformity_score or 0},
            ]
        }