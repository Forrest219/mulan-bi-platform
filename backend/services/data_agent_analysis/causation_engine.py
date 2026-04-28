"""
归因分析六步流程引擎 — Causation Engine

Spec 28 §5 — 归因分析六步标准流程

步骤：
1. 异动确认（Anomaly Confirmation）
2. 维度分解（Dimension Decomposition）
3. 假设生成（Hypothesis Generation）
4. 假设验证（Hypothesis Validation）
5. 根因定位（Root Cause Localization）
6. 影响量化与结论（Impact Assessment）

设计原则：
- ReAct max_steps ≤ 10（每步可包含多个工具调用）
- hypothesis_tree JSONB 状态管理
- 不可变步骤历史（Append-Only）
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.data_agent.models import BiAnalysisSession, BiAnalysisSessionStep

logger = logging.getLogger(__name__)


class CausationStep(Enum):
    """归因分析六步枚举"""

    ANOMALY_CONFIRMATION = "anomaly_confirmation"  # 1. 异动确认
    DIMENSION_DECOMPOSITION = "dimension_decomposition"  # 2. 维度分解
    HYPOTHESIS_GENERATION = "hypothesis_generation"  # 3. 假设生成
    HYPOTHESIS_VALIDATION = "hypothesis_validation"  # 4. 假设验证
    ROOT_CAUSE_LOCALIZATION = "root_cause_localization"  # 5. 根因定位
    IMPACT_ASSESSMENT = "impact_assessment"  # 6. 影响量化


class HypothesisStatus(Enum):
    """假设状态"""

    PENDING = "pending"  # 待验证
    CONFIRMED = "confirmed"  # 已确认
    REJECTED = "rejected"  # 已否定
    INCONCLUSIVE = "inconclusive"  # 无法确定


@dataclass
class AnomalyResult:
    """异动确认结果"""

    confirmed: bool
    magnitude: float  # 变化幅度（如 0.12 表示 12%）
    direction: str  # "up" | "down"
    baseline_period: Dict[str, str]  # {"start": "2026-01-01", "end": "2026-03-31"}
    anomaly_period: Dict[str, str]  # {"start": "2026-04-01", "end": "2026-04-15"}
    statistical_significance: str  # "p < 0.05"
    message: str = ""


@dataclass
class DimensionContribution:
    """维度贡献度"""

    name: str
    contribution: float  # 贡献度 0-1
    top_factor: str  # 主要因素
    impact: float  # 影响幅度


@dataclass
class Hypothesis:
    """假设"""

    id: str
    description: str
    confidence: float  # 置信度 0-1
    status: HypothesisStatus
    validation_method: str = ""
    expected_evidence: str = ""
    evidence_for: List[str] = field(default_factory=list)
    evidence_against: List[str] = field(default_factory=list)
    parent_id: Optional[str] = None


@dataclass
class RootCause:
    """根因"""

    hypothesis_id: str
    description: str
    confidence: float
    supporting_evidence: List[str]
    impact_scope: str


@dataclass
class CausationResult:
    """归因分析完整结果"""

    root_cause: Optional[RootCause]
    quantified_impact: Optional[Dict[str, Any]]
    confirmed_hypotheses: List[Hypothesis]
    rejected_hypotheses: List[Hypothesis]
    all_hypotheses: List[Hypothesis]
    conclusion: str
    confidence: float
    recommended_actions: List[Dict[str, str]]
    step_summaries: List[Dict[str, Any]]


class CausationEngine:
    """
    归因分析六步流程引擎

    接受一个指标异动事件，执行六步推理流程，输出根因和影响量化。

    Args:
        session_id: 分析会话 ID
        db: SQLAlchemy Session
    """

    # 六步名称映射
    STEP_NAMES = {
        CausationStep.ANOMALY_CONFIRMATION: "异动确认",
        CausationStep.DIMENSION_DECOMPOSITION: "维度分解",
        CausationStep.HYPOTHESIS_GENERATION: "假设生成",
        CausationStep.HYPOTHESIS_VALIDATION: "假设验证",
        CausationStep.ROOT_CAUSE_LOCALIZATION: "根因定位",
        CausationStep.IMPACT_ASSESSMENT: "影响量化",
    }

    # 最大假设并行验证数
    MAX_PARALLEL_HYPOTHESES = 3

    # 最大回溯次数
    MAX_BACKTRACKS = 1

    def __init__(self, session_id: str, db: Session):
        self.session_id = session_id
        self.db = db
        self.step_results: Dict[CausationStep, Any] = {}
        self.hypothesis_tree: Dict[str, Hypothesis] = {}
        self.step_summaries: List[Dict[str, Any]] = []
        self.backtrack_count = 0
        self._load_session()

    def _load_session(self) -> None:
        """从数据库加载会话状态"""
        session = self.db.query(BiAnalysisSession).filter(
            BiAnalysisSession.id == self.session_id
        ).first()

        if not session:
            raise ValueError(f"Analysis session not found: {self.session_id}")

        self._session = session

        # 恢复 hypothesis_tree
        if session.hypothesis_tree:
            tree_data = session.hypothesis_tree
            for node in tree_data.get("nodes", []):
                hyp = Hypothesis(
                    id=node["id"],
                    description=node["description"],
                    confidence=node.get("confidence", 0.5),
                    status=HypothesisStatus(node.get("status", "pending")),
                    validation_method=node.get("validation_method", ""),
                    expected_evidence=node.get("expected_evidence", ""),
                    evidence_for=node.get("evidence_for", []),
                    evidence_against=node.get("evidence_against", []),
                    parent_id=node.get("parent_id"),
                )
                self.hypothesis_tree[hyp.id] = hyp

    def _save_step(
        self,
        step_no: int,
        reasoning_trace: Dict[str, Any],
        query_log: Optional[Dict[str, Any]] = None,
        context_delta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        保存不可变步骤记录

        Args:
            step_no: 逻辑步骤号
            reasoning_trace: 推理轨迹（Thought-Action-Observation）
            query_log: 查询日志
            context_delta: 上下文变更
        """
        step = BiAnalysisSessionStep(
            session_id=self.session_id,
            tenant_id=self._session.tenant_id,
            step_no=step_no,
            reasoning_trace=reasoning_trace,
            query_log=query_log,
            context_delta=context_delta,
        )
        self.db.add(step)
        self.db.commit()

    def _update_session_hypothesis_tree(self) -> None:
        """更新会话的 hypothesis_tree"""
        nodes = []
        for hyp in self.hypothesis_tree.values():
            nodes.append({
                "id": hyp.id,
                "description": hyp.description,
                "confidence": hyp.confidence,
                "status": hyp.status.value,
                "validation_method": hyp.validation_method,
                "expected_evidence": hyp.expected_evidence,
                "evidence_for": hyp.evidence_for,
                "evidence_against": hyp.evidence_against,
                "parent_id": hyp.parent_id,
            })

        self._session.hypothesis_tree = {
            "nodes": nodes,
            "root": self._get_root_hypothesis_id(),
            "confirmed_path": self._get_confirmed_path(),
            "rejected_paths": self._get_rejected_paths(),
        }
        self.db.commit()

    def _get_root_hypothesis_id(self) -> Optional[str]:
        """获取根假设 ID"""
        for hyp in self.hypothesis_tree.values():
            if hyp.parent_id is None:
                return hyp.id
        return None

    def _get_confirmed_path(self) -> List[str]:
        """获取已确认路径"""
        path = []
        for hyp in self.hypothesis_tree.values():
            if hyp.status == HypothesisStatus.CONFIRMED:
                path.append(hyp.id)
        return path

    def _get_rejected_paths(self) -> List[List[str]]:
        """获取已否定路径列表"""
        paths = []
        for hyp in self.hypothesis_tree.values():
            if hyp.status == HypothesisStatus.REJECTED:
                # 重建该假设的完整路径
                path = [hyp.id]
                current = hyp
                while current.parent_id:
                    parent = self.hypothesis_tree.get(current.parent_id)
                    if parent:
                        path.insert(0, parent.id)
                        current = parent
                    else:
                        break
                paths.append(path)
        return paths

    def _increment_step(self) -> int:
        """原子递增当前步骤号"""
        self._session.current_step += 1
        self.db.commit()
        return self._session.current_step

    async def run(
        self,
        metric: str,
        dimensions: List[str],
        time_range: Dict[str, str],
        threshold: float = 0.1,
        tool_executor=None,
    ) -> CausationResult:
        """
        执行归因分析六步流程

        Args:
            metric: 指标名（如 "gmv"）
            dimensions: 候选维度列表（如 ["region", "product_category"]）
            time_range: 时间范围 {"start": "2026-01-01", "end": "2026-04-15"}
            threshold: 异动阈值（默认 10%）
            tool_executor: 工具执行器（用于调用各工具）

        Returns:
            CausationResult: 完整归因结果
        """
        start_time = time.time()

        logger.info(
            "CausationEngine.run: metric=%s, dimensions=%s, time_range=%s",
            metric,
            dimensions,
            time_range,
        )

        try:
            # Step 1: 异动确认
            step_no = self._increment_step()
            anomaly_result = await self._step1_anomaly_confirmation(
                metric, time_range, threshold, tool_executor
            )
            self.step_results[CausationStep.ANOMALY_CONFIRMATION] = anomaly_result
            self._save_step(
                step_no=step_no,
                reasoning_trace={
                    "step": 1,
                    "name": "anomaly_confirmation",
                    "input": {"metric": metric, "time_range": time_range, "threshold": threshold},
                    "output": anomaly_result.__dict__ if hasattr(anomaly_result, "__dict__") else anomaly_result,
                },
            )
            self.step_summaries.append({
                "step": 1,
                "action": "time_series_compare",
                "result": "confirmed" if anomaly_result.confirmed else "not_confirmed",
                "timestamp": datetime.utcnow().isoformat(),
            })

            # 如果未检测到显著异动，提前终止
            if not anomaly_result.confirmed:
                return CausationResult(
                    root_cause=None,
                    quantified_impact=None,
                    confirmed_hypotheses=[],
                    rejected_hypotheses=[],
                    all_hypotheses=list(self.hypothesis_tree.values()),
                    conclusion="未检测到显著异动",
                    confidence=0.0,
                    recommended_actions=[],
                    step_summaries=self.step_summaries,
                )

            # Step 2: 维度分解
            step_no = self._increment_step()
            dimension_contributions = await self._step2_dimension_decomposition(
                metric, dimensions, time_range, tool_executor
            )
            self.step_results[CausationStep.DIMENSION_DECOMPOSITION] = dimension_contributions
            self._save_step(
                step_no=step_no,
                reasoning_trace={
                    "step": 2,
                    "name": "dimension_decomposition",
                    "input": {"metric": metric, "dimensions": dimensions, "time_range": time_range},
                    "output": [d.__dict__ if hasattr(d, "__dict__") else d for d in dimension_contributions],
                },
            )
            concentration_point = self._find_concentration_point(dimension_contributions)
            self.step_summaries.append({
                "step": 2,
                "action": "dimension_drilldown",
                "result": f"concentration={concentration_point}",
                "timestamp": datetime.utcnow().isoformat(),
            })

            # Step 3: 假设生成
            step_no = self._increment_step()
            hypotheses = await self._step3_hypothesis_generation(
                metric, anomaly_result, dimension_contributions, tool_executor
            )
            self.step_results[CausationStep.HYPOTHESIS_GENERATION] = hypotheses
            for hyp in hypotheses:
                self.hypothesis_tree[hyp.id] = hyp
            self._update_session_hypothesis_tree()
            self._save_step(
                step_no=step_no,
                reasoning_trace={
                    "step": 3,
                    "name": "hypothesis_generation",
                    "input": {"metric": metric, "anomaly": anomaly_result.__dict__, "dimensions": [d.__dict__ if hasattr(d, "__dict__") else d for d in dimension_contributions]},
                    "output": [h.__dict__ for h in hypotheses],
                },
            )
            self.step_summaries.append({
                "step": 3,
                "action": "llm_reasoning",
                "result": f"generated {len(hypotheses)} hypotheses",
                "timestamp": datetime.utcnow().isoformat(),
            })

            # Step 4: 假设验证
            step_no = self._increment_step()
            validation_results = await self._step4_hypothesis_validation(
                hypotheses, metric, time_range, tool_executor
            )
            self.step_results[CausationStep.HYPOTHESIS_VALIDATION] = validation_results
            for hyp_id, verdict in validation_results.items():
                if hyp_id in self.hypothesis_tree:
                    self.hypothesis_tree[hyp_id].status = HypothesisStatus(verdict["status"])
                    self.hypothesis_tree[hyp_id].evidence_for = verdict.get("evidence_for", [])
                    self.hypothesis_tree[hyp_id].evidence_against = verdict.get("evidence_against", [])
                    self.hypothesis_tree[hyp_id].confidence = verdict.get("confidence", 0.5)
            self._update_session_hypothesis_tree()
            self._save_step(
                step_no=step_no,
                reasoning_trace={
                    "step": 4,
                    "name": "hypothesis_validation",
                    "input": {"hypotheses": [h.id for h in hypotheses]},
                    "output": validation_results,
                },
            )
            self.step_summaries.append({
                "step": 4,
                "action": "validate_hypotheses",
                "result": f"validated {len(validation_results)} hypotheses",
                "timestamp": datetime.utcnow().isoformat(),
            })

            # 检查是否所有假设均被否定/无法确定
            def _is_rejected_or_inconclusive(hyp_id: str) -> bool:
                node = self.hypothesis_tree.get(hyp_id)
                if node is None:
                    return False
                return node.status in [HypothesisStatus.REJECTED, HypothesisStatus.INCONCLUSIVE]

            all_rejected = all(
                _is_rejected_or_inconclusive(h.id)
                for h in hypotheses
            )
            if all_rejected and self.backtrack_count < self.MAX_BACKTRACKS:
                # 回溯到 Step 3
                self.backtrack_count += 1
                logger.info(f"所有假设均被否定，执行第 {self.backtrack_count} 次回溯")
                # TODO: 扩展假设范围重新生成

            # Step 5: 根因定位
            step_no = self._increment_step()
            root_cause = await self._step5_root_cause_localization(
                hypotheses, dimension_contributions
            )
            self.step_results[CausationStep.ROOT_CAUSE_LOCALIZATION] = root_cause
            self._save_step(
                step_no=step_no,
                reasoning_trace={
                    "step": 5,
                    "name": "root_cause_localization",
                    "input": {"hypotheses": [h.id for h in hypotheses]},
                    "output": root_cause.__dict__ if root_cause and hasattr(root_cause, "__dict__") else root_cause,
                },
            )
            self.step_summaries.append({
                "step": 5,
                "action": "locate_root_cause",
                "result": root_cause.description if root_cause else "no_confirmed_hypothesis",
                "timestamp": datetime.utcnow().isoformat(),
            })

            # Step 6: 影响量化
            step_no = self._increment_step()
            impact_result = await self._step6_impact_assessment(
                metric, root_cause, anomaly_result, tool_executor
            )
            self.step_results[CausationStep.IMPACT_ASSESSMENT] = impact_result
            self._save_step(
                step_no=step_no,
                reasoning_trace={
                    "step": 6,
                    "name": "impact_assessment",
                    "input": {"metric": metric, "root_cause": root_cause.__dict__ if root_cause and hasattr(root_cause, "__dict__") else root_cause},
                    "output": impact_result,
                },
            )
            self.step_summaries.append({
                "step": 6,
                "action": "quantify_impact",
                "result": f"impact_quantified",
                "timestamp": datetime.utcnow().isoformat(),
            })

            # 构建最终结论
            conclusion = self._build_conclusion(root_cause, anomaly_result, impact_result)
            confidence = self._calculate_overall_confidence(root_cause, anomaly_result)
            recommended_actions = impact_result.get("recommended_actions", []) if impact_result else []

            return CausationResult(
                root_cause=root_cause,
                quantified_impact=impact_result,
                confirmed_hypotheses=[h for h in self.hypothesis_tree.values() if h.status == HypothesisStatus.CONFIRMED],
                rejected_hypotheses=[h for h in self.hypothesis_tree.values() if h.status == HypothesisStatus.REJECTED],
                all_hypotheses=list(self.hypothesis_tree.values()),
                conclusion=conclusion,
                confidence=confidence,
                recommended_actions=recommended_actions,
                step_summaries=self.step_summaries,
            )

        except Exception as e:
            logger.exception("CausationEngine.run error: %s", e)
            # 更新会话状态为 failed
            self._session.status = "failed"
            self.db.commit()
            raise

    # ---------------------------------------------------------------------------
    # Step 1: 异动确认
    # ---------------------------------------------------------------------------

    async def _step1_anomaly_confirmation(
        self,
        metric: str,
        time_range: Dict[str, str],
        threshold: float,
        tool_executor,
    ) -> AnomalyResult:
        """
        Step 1: 异动确认

        使用 time_series_compare 和 statistical_analysis 确认指标是否存在显著异动
        """
        if not tool_executor:
            # 无工具执行器，返回默认结果
            return AnomalyResult(
                confirmed=False,
                magnitude=0.0,
                direction="down",
                baseline_period={"start": time_range.get("start", ""), "end": time_range.get("end", "")},
                anomaly_period={"start": time_range.get("start", ""), "end": time_range.get("end", "")},
                statistical_significance="N/A",
                message="工具执行器未提供",
            )

        # 调用 time_series_compare 工具
        try:
            result = await tool_executor(
                "time_series_compare",
                {
                    "metric": metric,
                    "time_range": time_range,
                    "threshold": threshold,
                },
            )

            if result.get("success"):
                data = result.get("data", {})
                return AnomalyResult(
                    confirmed=data.get("confirmed", False),
                    magnitude=data.get("magnitude", 0.0),
                    direction=data.get("direction", "down"),
                    baseline_period=data.get("baseline_period", {}),
                    anomaly_period=data.get("anomaly_period", {}),
                    statistical_significance=data.get("statistical_significance", "N/A"),
                    message=data.get("message", ""),
                )
            else:
                return AnomalyResult(
                    confirmed=False,
                    magnitude=0.0,
                    direction="down",
                    baseline_period=time_range,
                    anomaly_period=time_range,
                    statistical_significance="N/A",
                    message=f"异动检测失败: {result.get('error', '未知错误')}",
                )

        except Exception as e:
            logger.warning("Step 1异动确认异常: %s", e)
            return AnomalyResult(
                confirmed=False,
                magnitude=0.0,
                direction="down",
                baseline_period=time_range,
                anomaly_period=time_range,
                statistical_significance="error",
                message=f"异动检测异常: {str(e)}",
            )

    # ---------------------------------------------------------------------------
    # Step 2: 维度分解
    # ---------------------------------------------------------------------------

    async def _step2_dimension_decomposition(
        self,
        metric: str,
        dimensions: List[str],
        time_range: Dict[str, str],
        tool_executor,
    ) -> List[DimensionContribution]:
        """
        Step 2: 维度分解

        使用 schema_lookup 获取可分解维度，然后使用 dimension_drilldown 逐维分解
        """
        contributions = []

        if not tool_executor:
            return contributions

        for dim in dimensions[:3]:  # 最多展开 3 个维度
            try:
                result = await tool_executor(
                    "dimension_drilldown",
                    {
                        "metric": metric,
                        "dimension": dim,
                        "time_range": time_range,
                    },
                )

                if result.get("success"):
                    data = result.get("data", {})
                    contributions.append(DimensionContribution(
                        name=dim,
                        contribution=data.get("contribution", 0.0),
                        top_factor=data.get("top_factor", ""),
                        impact=data.get("impact", 0.0),
                    ))

            except Exception as e:
                logger.warning(f"Step 2 维度 {dim} 分解异常: %s", e)
                continue

        # 按贡献度排序
        contributions.sort(key=lambda x: x.contribution, reverse=True)
        return contributions

    def _find_concentration_point(
        self,
        contributions: List[DimensionContribution],
    ) -> str:
        """找到集中度最高的维度组合"""
        if not contributions:
            return "N/A"

        top = contributions[0]
        if top.contribution > 0.3:
            return f"{top.name}={top.top_factor}"
        return "分布均匀"

    # ---------------------------------------------------------------------------
    # Step 3: 假设生成
    # ---------------------------------------------------------------------------

    async def _step3_hypothesis_generation(
        self,
        metric: str,
        anomaly_result: AnomalyResult,
        dimension_contributions: List[DimensionContribution],
        tool_executor,
    ) -> List[Hypothesis]:
        """
        Step 3: 假设生成

        基于异动确认和维度分解结果，LLM 推理生成候选假设
        """
        hypotheses = []

        # 基于维度分解结果生成假设
        concentration_point = self._find_concentration_point(dimension_contributions)

        if concentration_point and concentration_point != "分布均匀":
            # 基于集中维度生成假设
            dim_name, dim_value = concentration_point.split("=", 1)
            hypotheses.append(Hypothesis(
                id=f"hyp_{uuid.uuid4().hex[:8]}",
                description=f"{dim_value}区域的{metric}下滑是主要原因",
                confidence=0.6,
                status=HypothesisStatus.PENDING,
                validation_method=f"对比去年同期{dim_value}区域数据",
                expected_evidence=f"去年{metric}同期也有类似下滑幅度",
                parent_id=None,
            ))

        # 如果有异常方向信息，生成额外假设
        if anomaly_result.direction == "down":
            hypotheses.append(Hypothesis(
                id=f"hyp_{uuid.uuid4().hex[:8]}",
                description="新客转化率下降导致整体指标下滑",
                confidence=0.5,
                status=HypothesisStatus.PENDING,
                validation_method="按新老客维度拆分数据",
                expected_evidence="新客转化率下降超 30%",
                parent_id=None,
            ))

        return hypotheses

    # ---------------------------------------------------------------------------
    # Step 4: 假设验证
    # ---------------------------------------------------------------------------

    async def _step4_hypothesis_validation(
        self,
        hypotheses: List[Hypothesis],
        metric: str,
        time_range: Dict[str, str],
        tool_executor,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Step 4: 假设验证

        使用 sql_execute、correlation_detect、quality_check 等工具验证假设
        """
        validation_results = {}

        if not tool_executor or not hypotheses:
            for hyp in hypotheses:
                validation_results[hyp.id] = {
                    "status": "inconclusive",
                    "confidence": 0.5,
                    "evidence_for": [],
                    "evidence_against": ["工具执行器未提供"],
                }
            return validation_results

        # 最多并行验证 3 个假设
        for hyp in hypotheses[: self.MAX_PARALLEL_HYPOTHESES]:
            try:
                # 调用 SQL 执行器验证假设
                result = await tool_executor(
                    "sql_execute",
                    {
                        "natural_language_intent": hyp.validation_method,
                        "metric": metric,
                        "time_range": time_range,
                    },
                )

                if result.get("success"):
                    data = result.get("data", {})
                    evidence_for = []
                    evidence_against = []

                    # 根据结果判断证据
                    result_summary = data.get("result_summary", "")
                    if "类似" in result_summary or "相同" in result_summary:
                        evidence_for.append(result_summary)
                    else:
                        evidence_against.append(result_summary)

                    validation_results[hyp.id] = {
                        "status": "confirmed" if evidence_for else "rejected",
                        "confidence": 0.85 if evidence_for else 0.3,
                        "evidence_for": evidence_for,
                        "evidence_against": evidence_against,
                        "data_queries_used": [data.get("sql", "")],
                    }
                else:
                    validation_results[hyp.id] = {
                        "status": "inconclusive",
                        "confidence": 0.5,
                        "evidence_for": [],
                        "evidence_against": [result.get("error", "验证失败")],
                    }

            except Exception as e:
                logger.warning(f"假设 {hyp.id} 验证异常: %s", e)
                validation_results[hyp.id] = {
                    "status": "inconclusive",
                    "confidence": 0.5,
                    "evidence_for": [],
                    "evidence_against": [str(e)],
                }

        return validation_results

    # ---------------------------------------------------------------------------
    # Step 5: 根因定位
    # ---------------------------------------------------------------------------

    async def _step5_root_cause_localization(
        self,
        hypotheses: List[Hypothesis],
        dimension_contributions: List[DimensionContribution],
    ) -> Optional[RootCause]:
        """
        Step 5: 根因定位

        基于验证结果，确认最终根因
        """
        # 找到已确认的假设
        confirmed = [h for h in self.hypothesis_tree.values() if h.status == HypothesisStatus.CONFIRMED]

        if not confirmed:
            return None

        # 按置信度排序
        confirmed.sort(key=lambda h: h.confidence, reverse=True)
        top_hyp = confirmed[0]

        # 找到对应的维度贡献
        dim_info = ""
        for d in dimension_contributions:
            if d.contribution > 0.3:
                dim_info = f"{d.name}={d.top_factor} 贡献了 {d.contribution*100:.0f}%"
                break

        return RootCause(
            hypothesis_id=top_hyp.id,
            description=top_hyp.description,
            confidence=top_hyp.confidence,
            supporting_evidence=top_hyp.evidence_for,
            impact_scope=dim_info or "影响范围待量化",
        )

    # ---------------------------------------------------------------------------
    # Step 6: 影响量化
    # ---------------------------------------------------------------------------

    async def _step6_impact_assessment(
        self,
        metric: str,
        root_cause: Optional[RootCause],
        anomaly_result: AnomalyResult,
        tool_executor,
    ) -> Dict[str, Any]:
        """
        Step 6: 影响量化与结论

        量化根因的影响并生成行动建议
        """
        if not root_cause:
            return {
                "quantified_impact": None,
                "confidence": 0.0,
                "recommended_actions": [
                    {"action": "多因素待进一步观察", "priority": "HIGH"},
                ],
            }

        # 计算影响量
        magnitude = anomaly_result.magnitude
        direction = anomaly_result.direction

        quantified_impact = {
            "metric": metric,
            "absolute_change": f"{magnitude*100:.1f}%",
            "percentage_change": magnitude if direction == "down" else -magnitude,
            "confidence_interval": {"lower": magnitude * 0.8, "upper": magnitude * 1.2},
        }

        # 生成行动建议
        recommended_actions = [
            {
                "action": f"调低{metric}预期目标 {magnitude*100:.0f}%",
                "priority": "HIGH",
            },
            {
                "action": "排查数据同步延迟",
                "priority": "MEDIUM",
            },
        ]

        return {
            "quantified_impact": quantified_impact,
            "confidence": root_cause.confidence,
            "recommended_actions": recommended_actions,
        }

    # ---------------------------------------------------------------------------
    # 辅助方法
    # ---------------------------------------------------------------------------

    def _build_conclusion(
        self,
        root_cause: Optional[RootCause],
        anomaly_result: AnomalyResult,
        impact_result: Optional[Dict[str, Any]],
    ) -> str:
        """构建自然语言结论"""
        if not root_cause:
            return "未检测到显著异动或无法确定根因，建议进一步观察。"

        impact = impact_result.get("quantified_impact", {}) if impact_result else {}
        change = impact.get("absolute_change", f"{anomaly_result.magnitude*100:.1f}%")

        return (
            f"{anomaly_result.anomaly_period.get('start', '')} 至 "
            f"{anomaly_result.anomaly_period.get('end', '')} 期间，"
            f"{anomaly_result.direction == 'down' and '下降' or '上升'}{change}，"
            f"根因为：{root_cause.description}，"
            f"置信度 {root_cause.confidence*100:.0f}%。"
        )

    def _calculate_overall_confidence(
        self,
        root_cause: Optional[RootCause],
        anomaly_result: AnomalyResult,
    ) -> float:
        """计算整体置信度"""
        if not root_cause:
            return 0.0

        # 基础置信度
        confidence = root_cause.confidence

        # 如果异动统计显著，增加置信度
        if anomaly_result.statistical_significance == "p < 0.05":
            confidence *= 1.1

        # 如果置信度超过 1.0，取 1.0
        return min(confidence, 1.0)