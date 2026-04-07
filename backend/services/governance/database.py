"""数据质量监控 - 数据库访问层

遵循 Spec 15 v1.1：
- bi_quality_scores: Append-Only（每次 INSERT，不 UPSERT）
- bi_quality_results: 90 天保留，PostgreSQL 按月分区
- 规则 CRUD、结果查询、评分聚合

P0 修复：所有 CRUD 方法接受外部传入的 db: Session，移除内部 _session() 闭包。
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import desc, and_, func, text
from sqlalchemy.orm import Session

from .models import QualityRule, QualityResult, QualityScore


class QualityDatabase:
    """质量监控数据库访问层"""

    # ==================== 规则 CRUD ====================

    def create_rule(self, db: Session, **kwargs) -> QualityRule:
        rule = QualityRule(**kwargs)
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return rule

    def get_rule(self, db: Session, rule_id: int) -> Optional[QualityRule]:
        return db.query(QualityRule).filter(QualityRule.id == rule_id).first()

    def list_rules(
        self,
        db: Session,
        datasource_id: int = None,
        table_name: str = None,
        enabled: bool = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        q = db.query(QualityRule)
        if datasource_id is not None:
            q = q.filter(QualityRule.datasource_id == datasource_id)
        if table_name:
            q = q.filter(QualityRule.table_name == table_name)
        if enabled is not None:
            q = q.filter(QualityRule.enabled == enabled)
        total = q.count()
        items = q.order_by(QualityRule.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {"rules": [r.to_dict() for r in items], "total": total, "page": page, "page_size": page_size}

    def update_rule(self, db: Session, rule_id: int, **kwargs) -> bool:
        rule = db.query(QualityRule).filter(QualityRule.id == rule_id).first()
        if not rule:
            return False
        for key, value in kwargs.items():
            if hasattr(rule, key) and value is not None:
                # P0 修复：setattr 需要 3 个参数
                setattr(rule, key, value)
        db.commit()
        return True

    def delete_rule(self, db: Session, rule_id: int) -> bool:
        rule = db.query(QualityRule).filter(QualityRule.id == rule_id).first()
        if not rule:
            return False
        db.delete(rule)
        db.commit()
        return True

    def toggle_rule(self, db: Session, rule_id: int) -> Optional[bool]:
        """切换规则启用状态，返回切换后的 enabled 值"""
        rule = db.query(QualityRule).filter(QualityRule.id == rule_id).first()
        if not rule:
            return None
        rule.enabled = not rule.enabled
        db.commit()
        return rule.enabled

    def get_enabled_rules(self, db: Session, datasource_id: int = None) -> List[QualityRule]:
        """获取所有启用规则，支持按数据源过滤"""
        q = db.query(QualityRule).filter(QualityRule.enabled == True)
        if datasource_id is not None:
            q = q.filter(QualityRule.datasource_id == datasource_id)
        return q.all()

    def rule_exists(
        self,
        db: Session,
        datasource_id: int,
        table_name: str,
        field_name: str,
        rule_type: str,
        exclude_id: int = None,
    ) -> bool:
        """检查同一数据源+表+字段+规则类型是否已存在"""
        q = db.query(QualityRule).filter(
            and_(
                QualityRule.datasource_id == datasource_id,
                QualityRule.table_name == table_name,
                QualityRule.field_name == field_name,
                QualityRule.rule_type == rule_type,
            )
        )
        if exclude_id is not None:
            q = q.filter(QualityRule.id != exclude_id)
        return q.first() is not None

    # ==================== 检测结果 ====================

    def create_result(self, db: Session, **kwargs) -> QualityResult:
        result = QualityResult(**kwargs)
        db.add(result)
        db.commit()
        db.refresh(result)
        return result

    def batch_create_results(self, db: Session, results: List[Dict[str, Any]]) -> int:
        """批量插入检测结果"""
        objs = [QualityResult(**r) for r in results]
        db.bulk_save_objects(objs)
        db.commit()
        return len(objs)

    def list_results(
        self,
        db: Session,
        datasource_id: int = None,
        rule_id: int = None,
        passed: bool = None,
        start_date: datetime = None,
        end_date: datetime = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        q = db.query(QualityResult)
        if datasource_id is not None:
            q = q.filter(QualityResult.datasource_id == datasource_id)
        if rule_id is not None:
            q = q.filter(QualityResult.rule_id == rule_id)
        if passed is not None:
            q = q.filter(QualityResult.passed == passed)
        if start_date:
            q = q.filter(QualityResult.executed_at >= start_date)
        if end_date:
            q = q.filter(QualityResult.executed_at <= end_date)
        total = q.count()
        items = q.order_by(desc(QualityResult.executed_at)).offset((page - 1) * page_size).limit(page_size).all()
        return {"results": [r.to_dict() for r in items], "total": total, "page": page, "page_size": page_size}

    def get_latest_results(self, db: Session, datasource_id: int = None, limit: int = 100) -> List[QualityResult]:
        """获取各规则最新一次检测结果"""
        subq = (
            db.query(
                QualityResult.rule_id,
                func.max(QualityResult.executed_at).label("max_exec"),
            )
            .group_by(QualityResult.rule_id)
            .subquery()
        )
        q = (
            db.query(QualityResult)
            .join(subq, and_(QualityResult.rule_id == subq.c.rule_id, QualityResult.executed_at == subq.c.max_exec))
        )
        if datasource_id is not None:
            q = q.filter(QualityResult.datasource_id == datasource_id)
        return q.limit(limit).all()

    # ==================== 质量评分 ====================

    def append_score(self, db: Session, **kwargs) -> QualityScore:
        """追加评分快照 - Append-Only，每次计算后 INSERT 新记录"""
        score = QualityScore(**kwargs)
        db.add(score)
        db.commit()
        db.refresh(score)
        return score

    def get_latest_scores(
        self,
        db: Session,
        datasource_id: int,
        scope_type: str = None,
        scope_name: str = None,
    ) -> List[QualityScore]:
        """获取最新评分（按 scope_type + scope_name 取最新一条）"""
        filters = [QualityScore.datasource_id == datasource_id]
        if scope_type:
            filters.append(QualityScore.scope_type == scope_type)
        if scope_name:
            filters.append(QualityScore.scope_name == scope_name)

        subq = (
            db.query(
                QualityScore.scope_type,
                QualityScore.scope_name,
                func.max(QualityScore.id).label("max_id"),
            )
            .filter(*filters)
            .group_by(QualityScore.scope_type, QualityScore.scope_name)
            .subquery()
        )
        scores = (
            db.query(QualityScore)
            .join(subq, and_(
                QualityScore.scope_type == subq.c.scope_type,
                QualityScore.scope_name == subq.c.scope_name,
                QualityScore.id == subq.c.max_id,
            ))
            .all()
        )
        return scores

    def get_score_trend(
        self,
        db: Session,
        datasource_id: int,
        scope_type: str = None,
        scope_name: str = None,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """获取评分趋势 - 按日期聚合近 N 天每日最新评分"""
        cutoff = datetime.now() - timedelta(days=days)
        filters = [
            QualityScore.datasource_id == datasource_id,
            QualityScore.calculated_at >= cutoff,
        ]
        if scope_type:
            filters.append(QualityScore.scope_type == scope_type)
        if scope_name:
            filters.append(QualityScore.scope_name == scope_name)

        trend = (
            db.query(
                func.date(QualityScore.calculated_at).label("date"),
                func.max(QualityScore.overall_score).label("overall_score"),
            )
            .filter(*filters)
            .group_by(func.date(QualityScore.calculated_at))
            .order_by(func.date(QualityScore.calculated_at))
            .all()
        )
        return [{"date": str(row.date), "overall_score": row.overall_score} for row in trend]

    def get_health_scan_score(self, db: Session, datasource_id: int) -> Optional[float]:
        """从 bi_health_scan_records 读取最新健康扫描评分（Spec 11 集成）"""
        from services.health_scan.models import HealthScanRecord
        record = (
            db.query(HealthScanRecord)
            .filter(
                HealthScanRecord.datasource_id == datasource_id,
                HealthScanRecord.status == "success",
            )
            .order_by(desc(HealthScanRecord.id))
            .first()
        )
        return record.health_score if record else None

    def get_ddl_compliance_score(self, db: Session, datasource_id: int) -> Optional[float]:
        """从 bi_scan_logs 读取最新 DDL 合规评分（Spec 06 集成）"""
        from services.logs.models import ScanLog
        record = (
            db.query(ScanLog)
            .filter(
                ScanLog.datasource_id == datasource_id,
                ScanLog.status == "completed",
            )
            .order_by(desc(ScanLog.id))
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

    # ==================== 看板聚合 ====================

    def get_dashboard_summary(self, db: Session) -> Dict[str, Any]:
        """质量看板汇总统计"""
        total_ds = db.query(func.count(func.distinct(QualityScore.datasource_id))).scalar() or 0

        latest_subq = (
            db.query(
                QualityScore.datasource_id,
                func.max(QualityScore.id).label("max_id"),
            )
            .group_by(QualityScore.datasource_id)
            .subquery()
        )
        avg_score = (
            db.query(func.avg(QualityScore.overall_score))
            .join(latest_subq, QualityScore.id == latest_subq.c.max_id)
            .scalar()
        ) or 0.0

        total_rules = db.query(func.count(QualityRule.id)).scalar() or 0
        enabled_rules = (
            db.query(func.count(QualityRule.id)).filter(QualityRule.enabled == True).scalar() or 0
        )

        latest_results = self.get_latest_results(db, limit=10000)
        passed_count = sum(1 for r in latest_results if r.passed)
        failed_count = len(latest_results) - passed_count

        return {
            "total_datasources": total_ds,
            "avg_score": round(avg_score, 1),
            "rules_total": total_rules,
            "rules_passed": passed_count,
            "rules_failed": failed_count,
        }

    def get_top_failures(self, db: Session, limit: int = 10) -> List[Dict[str, Any]]:
        """失败规则 TOP N（按连续失败次数排序）"""
        latest_results = self.get_latest_results(db, limit=1000)
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
            rule = self.get_rule(db, f["rule_id"])
            if rule:
                f["rule_name"] = rule.name
                f["severity"] = rule.severity
            ds_result = db.query(QualityResult).filter(QualityResult.rule_id == f["rule_id"]).first()
            if ds_result:
                from services.datasources.models import DataSource
                ds = db.query(DataSource).filter(DataSource.id == f["datasource_id"]).first()
                f["datasource_name"] = ds.name if ds else f["datasource_id"]
        return sorted_failures
