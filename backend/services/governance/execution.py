"""规则执行编排

遵循 Spec 15 v1.1 §5 质量评分模型：
- 按数据源分组执行质量规则
- 调用 RuleExecutor 执行检测
- 计算并持久化质量评分（Append-Only）
"""
from typing import List, Optional

from services.governance.models import QualityResult, QualityScore, QualityRule
from services.governance.executor import RuleExecutor
from services.governance.scorer import calculate_quality_score
from app.core.database import SessionLocal


class QualityExecutionService:
    """质量规则执行编排服务"""

    def execute_rules(
        self,
        datasource_id: int = None,
        rule_ids: List[int] = None,
    ) -> dict:
        """
        执行指定规则，返回执行结果。

        1. 加载规则（按 datasource_id 和/或 rule_ids 过滤）
        2. 按 datasource_id 分组
        3. 对每个数据源建立连接
        4. 执行每条规则
        5. 写入 bi_quality_results
        6. 触发评分计算

        Args:
            datasource_id: 数据源 ID（可选）
            rule_ids: 规则 ID 列表（可选）

        Returns:
            dict: 包含执行摘要
        """
        from app.models import BiDataSource
        from datetime import datetime

        session = SessionLocal()
        results = []

        try:
            # 构建查询
            query = session.query(QualityRule).filter(QualityRule.enabled == True)
            if datasource_id is not None:
                query = query.filter(QualityRule.datasource_id == datasource_id)
            if rule_ids:
                query = query.filter(QualityRule.id.in_(rule_ids))

            rules = query.all()

            # 按数据源分组
            rules_by_ds = {}
            for rule in rules:
                if rule.datasource_id not in rules_by_ds:
                    rules_by_ds[rule.datasource_id] = []
                rules_by_ds[rule.datasource_id].append(rule)

            # 执行每个数据源的规则
            for ds_id, ds_rules in rules_by_ds.items():
                # 获取数据源连接信息
                ds = session.query(BiDataSource).filter(BiDataSource.id == ds_id).first()
                if not ds:
                    continue

                conn_info = ds.decrypt()
                executor = RuleExecutor(datasource_conn_info=conn_info)

                for rule in ds_rules:
                    exec_result = executor.execute_rule(
                        rule_type=rule.rule_type,
                        table_name=rule.table_name,
                        column_name=rule.field_name,
                        threshold=rule.threshold,
                        operator=rule.operator,
                        field_name=rule.field_name,
                    )

                    # 写入结果
                    quality_result = QualityResult(
                        rule_id=rule.id,
                        datasource_id=rule.datasource_id,
                        table_name=rule.table_name,
                        field_name=rule.field_name,
                        rule_type=rule.rule_type,
                        executed_at=datetime.utcnow(),
                        passed=exec_result.get("passed", False),
                        actual_value=exec_result.get("actual_value"),
                        expected_value=exec_result.get("expected"),
                        detail_json=exec_result.get("detail"),
                        execution_time_ms=exec_result.get("execution_time_ms"),
                        error_message=exec_result.get("error"),
                    )
                    session.add(quality_result)
                    results.append(exec_result)

            session.commit()

            return {
                "executed_count": len(results),
                "passed_count": sum(1 for r in results if r.get("passed")),
                "failed_count": sum(1 for r in results if not r.get("passed")),
                "results": results,
            }

        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def execute_single_rule(self, rule_id: int) -> dict:
        """执行单条规则

        Args:
            rule_id: 规则 ID

        Returns:
            dict: 执行结果
        """
        from app.models import BiDataSource
        from datetime import datetime

        session = SessionLocal()

        try:
            rule = session.query(QualityRule).filter(QualityRule.id == rule_id).first()
            if not rule:
                raise ValueError(f"Rule {rule_id} not found")

            ds = session.query(BiDataSource).filter(BiDataSource.id == rule.datasource_id).first()
            if not ds:
                raise ValueError(f"DataSource {rule.datasource_id} not found")

            conn_info = ds.decrypt()
            executor = RuleExecutor(datasource_conn_info=conn_info)

            exec_result = executor.execute_rule(
                rule_type=rule.rule_type,
                table_name=rule.table_name,
                column_name=rule.field_name,
                threshold=rule.threshold,
                operator=rule.operator,
                field_name=rule.field_name,
            )

            # 写入结果
            quality_result = QualityResult(
                rule_id=rule.id,
                datasource_id=rule.datasource_id,
                table_name=rule.table_name,
                field_name=rule.field_name,
                rule_type=rule.rule_type,
                executed_at=datetime.utcnow(),
                passed=exec_result.get("passed", False),
                actual_value=exec_result.get("actual_value"),
                expected_value=exec_result.get("expected"),
                detail_json=exec_result.get("detail"),
                execution_time_ms=exec_result.get("execution_time_ms"),
                error_message=exec_result.get("error"),
            )
            session.add(quality_result)
            session.commit()

            return exec_result

        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def calculate_and_persist_score(
        self,
        datasource_id: int,
        scope_type: str = "datasource",
        scope_name: str = None,
    ) -> QualityScore:
        """
        计算并持久化质量评分。

        ⚠️ Append-Only：只 INSERT，不 UPDATE/UPSERT

        1. 查询最近规则检测结果
        2. 查询 Spec 11 健康扫描最新评分（可选）
        3. 查询 Spec 06 DDL 合规最新评分（可选）
        4. 调用 calculate_quality_score()
        5. INSERT bi_quality_scores（新记录）

        Args:
            datasource_id: 数据源 ID
            scope_type: 评分范围类型（datasource/table/field）
            scope_name: 评分范围名称

        Returns:
            QualityScore: 新创建的质量评分记录
        """
        from datetime import datetime, timedelta

        if scope_name is None:
            scope_name = str(datasource_id)

        session = SessionLocal()

        try:
            # 1. 查询最近 24 小时内的规则检测结果
            cutoff_time = datetime.utcnow() - timedelta(hours=24)
            rule_results = (
                session.query(QualityResult)
                .filter(
                    QualityResult.datasource_id == datasource_id,
                    QualityResult.executed_at >= cutoff_time,
                )
                .all()
            )

            # 2. 查询健康扫描评分（Spec 11）- 后续集成
            health_scan_score = None
            # TODO: 集成 Spec 11 健康扫描评分
            # health_scan = session.query(BiHealthScanScore).filter(
            #     BiHealthScanScore.datasource_id == datasource_id
            # ).order_by(BiHealthScanScore.calculated_at.desc()).first()
            # if health_scan:
            #     health_scan_score = health_scan.overall_score

            # 3. 查询 DDL 合规评分（Spec 06）- 后续集成
            ddl_compliance_score = None
            # TODO: 集成 Spec 06 DDL 合规评分
            # ddl_score = session.query(BiDdlComplianceScore).filter(
            #     BiDdlComplianceScore.datasource_id == datasource_id
            # ).order_by(BiDdlComplianceScore.calculated_at.desc()).first()
            # if ddl_score:
            #     ddl_compliance_score = ddl_score.compliance_score

            # 4. 调用评分计算
            score_data = calculate_quality_score(
                rule_results=rule_results,
                health_scan_score=health_scan_score,
                ddl_compliance_score=ddl_compliance_score,
            )

            # 5. 创建新评分记录（Append-Only）
            quality_score = QualityScore(
                datasource_id=datasource_id,
                scope_type=scope_type,
                scope_name=scope_name,
                overall_score=score_data["overall_score"],
                completeness_score=score_data["completeness_score"],
                consistency_score=score_data["consistency_score"],
                uniqueness_score=score_data["uniqueness_score"],
                timeliness_score=score_data["timeliness_score"],
                conformity_score=score_data["conformity_score"],
                health_scan_score=score_data.get("health_scan_score"),
                ddl_compliance_score=score_data.get("ddl_compliance_score"),
                detail_json={
                    "rule_result_count": len(rule_results),
                    "health_scan_score": health_scan_score,
                    "ddl_compliance_score": ddl_compliance_score,
                },
                calculated_at=datetime.utcnow(),
            )

            session.add(quality_score)
            session.commit()
            session.refresh(quality_score)

            return quality_score

        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
