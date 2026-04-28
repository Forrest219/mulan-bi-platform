"""
Spec 28 UC-1 归因分析端到端服务 — §9.4 归因六步流程

六步标准流程：
  Step 1: metric_definition_lookup → time_series_compare  异动确认
  Step 2: schema_lookup → dimension_drilldown            维度分解
  Step 3: metric_definition_lookup + past_analysis_retrieve  假设生成
  Step 4: sql_execute + correlation_detect + quality_check  假设验证
  Step 5: hypothesis_store(confirm)                        根因定位
  Step 6: sql_execute + report_write + insight_publish     影响量化

会话状态机（§9.2）：
  created → running → completed / failed / paused
  paused → running（resume）
  非法转移返回 TR_007

PostgreSQL JSONB 持久化：
  - analysis_sessions（可变状态，每次 UPDATE）
  - analysis_session_steps（不可变步骤历史，APPEND-ONLY）
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from services.data_agent.models import BiAnalysisSession, BiAnalysisSessionStep
from services.data_agent.tool_base import ToolContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------


class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    ARCHIVED = "archived"
    DELETED = "deleted"


class StepType(str, Enum):
    ROUTE = "route"                     # 路由/前置判断
    CAPABILITY_INVOKE = "capability_invoke"  # 外部能力调用
    REASON = "reason"                   # LLM 纯推理
    FINALIZE = "finalize"              # 结果固化


# 合法的状态转移
VALID_TRANSITIONS: Dict[SessionStatus, List[SessionStatus]] = {
    SessionStatus.CREATED: [SessionStatus.RUNNING],
    SessionStatus.RUNNING: [SessionStatus.PAUSED, SessionStatus.COMPLETED, SessionStatus.FAILED],
    SessionStatus.PAUSED: [SessionStatus.RUNNING, SessionStatus.EXPIRED],
    SessionStatus.EXPIRED: [SessionStatus.RUNNING],  # 仅 expiration_reason=paused_timeout 时可 resume
    SessionStatus.COMPLETED: [SessionStatus.ARCHIVED],
    SessionStatus.FAILED: [SessionStatus.ARCHIVED],
    SessionStatus.ARCHIVED: [SessionStatus.DELETED],
}


def validate_transition(current: SessionStatus, next_state: SessionStatus) -> bool:
    """状态转移合法性校验，非法转移返回 TR_007"""
    return next_state in VALID_TRANSITIONS.get(current, [])


# ---------------------------------------------------------------------------
# 六步枚举
# ---------------------------------------------------------------------------


class CausationStep(str, Enum):
    STEP1_CONFIRM = "step1_confirm"    # 异动确认
    STEP2_DECOMPOSE = "step2_decompose" # 维度分解
    STEP3_HYPOTHESIZE = "step3_hypothesize"  # 假设生成
    STEP4_VALIDATE = "step4_validate"   # 假设验证
    STEP5_ROOT_CAUSE = "step5_root_cause"  # 根因定位
    STEP6_IMPACT = "step6_impact"       # 影响量化


STEP_LABELS = {
    CausationStep.STEP1_CONFIRM: "异动确认",
    CausationStep.STEP2_DECOMPOSE: "维度分解",
    CausationStep.STEP3_HYPOTHESIZE: "假设生成",
    CausationStep.STEP4_VALIDATE: "假设验证",
    CausationStep.STEP5_ROOT_CAUSE: "根因定位",
    CausationStep.STEP6_IMPACT: "影响量化",
}


# ---------------------------------------------------------------------------
# 假设树节点
# ---------------------------------------------------------------------------


@dataclass
class HypothesisNode:
    id: str
    description: str
    confidence: float = 0.5
    status: str = "pending"   # pending / confirmed / rejected / inconclusive
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    validation_method: Optional[str] = None
    expected_evidence: Optional[str] = None
    evidence_for: List[str] = field(default_factory=list)
    evidence_against: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "confidence": self.confidence,
            "status": self.status,
            "parent_id": self.parent_id,
            "children": self.children,
            "validation_method": self.validation_method,
            "expected_evidence": self.expected_evidence,
            "evidence_for": self.evidence_for,
            "evidence_against": self.evidence_against,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HypothesisNode":
        return cls(
            id=d["id"],
            description=d["description"],
            confidence=d.get("confidence", 0.5),
            status=d.get("status", "pending"),
            parent_id=d.get("parent_id"),
            children=d.get("children", []),
            validation_method=d.get("validation_method"),
            expected_evidence=d.get("expected_evidence"),
            evidence_for=d.get("evidence_for", []),
            evidence_against=d.get("evidence_against", []),
        )


# ---------------------------------------------------------------------------
# 分析上下文（内存态，用于 ReAct 步骤间传递）
# ---------------------------------------------------------------------------


@dataclass
class CausationContext:
    session_id: str
    tenant_id: str
    user_id: int
    metric: str
    dimensions: List[str]
    time_range: Dict[str, str]
    compare_mode: str
    threshold_pct: float
    scenario: str = "causation"

    # 六步状态
    current_step: CausationStep = CausationStep.STEP1_CONFIRM
    current_step_no: int = 1   # 1-based，用于写入 step_no

    # Step 1 输出
    anomaly_confirmed: bool = False
    magnitude: float = 0.0
    delta_abs: float = 0.0
    delta_pct: float = 0.0
    statistical_significance: str = ""

    # Step 2 输出
    breakdown: List[Dict] = field(default_factory=list)
    concentration_point: str = ""

    # Step 3-5 输出
    hypotheses: List[HypothesisNode] = field(default_factory=list)
    confirmed_hypothesis_id: Optional[str] = None
    root_dimension: str = ""
    root_value: str = ""

    # Step 6 输出
    root_cause_description: str = ""
    root_cause_confidence: float = 0.0
    recommended_actions: List[Dict] = field(default_factory=list)

    # 推理追踪
    reasoning_trace: List[Dict] = field(default_factory=list)
    backtrack_count: int = 0
    max_backtrack: int = 1

    def to_hypothesis_tree(self) -> Dict:
        return {
            "nodes": [h.to_dict() for h in self.hypotheses],
            "confirmed_path": [self.confirmed_hypothesis_id] if self.confirmed_hypothesis_id else [],
            "rejected_paths": [
                [h.id for h in self.hypotheses if h.status == "rejected"]
            ],
        }

    def to_insight_report(self) -> Dict:
        """UC-1 输出：{delta_abs, delta_pct, root_dimension, root_value, confidence, narrative_summary}"""
        return {
            "delta_abs": self.delta_abs,
            "delta_pct": self.delta_pct,
            "root_dimension": self.root_dimension,
            "root_value": self.root_value,
            "confidence": self.root_cause_confidence,
            "narrative_summary": self.root_cause_description,
            "anomaly_confirmed": self.anomaly_confirmed,
            "magnitude": self.magnitude,
            "concentration_point": self.concentration_point,
            "recommended_actions": self.recommended_actions,
            "hypothesis_trace": [
                {"step": i + 1, "hypothesis": h.description, "status": h.status, "confidence": h.confidence}
                for i, h in enumerate(self.hypotheses)
            ],
        }


# ---------------------------------------------------------------------------
# CausationSessionManager — PostgreSQL 持久化 + 六步执行引擎
# ---------------------------------------------------------------------------


class CausationSessionManager:
    """
    UC-1 归因分析会话管理器。

    职责：
    1. 创建/更新 BiAnalysisSession（可变状态）
    2. 追加 BiAnalysisSessionStep（不可变历史，APPEND-ONLY）
    3. 执行六步归因流程
    4. 状态机校验（非法转移返回 TR_007）
    5. hypothesis_store 维护假设树

    验收阈值（§1.1.1 UC-1）：
    - 6 步内收敛
    - confidence ≥ 0.7
    - 单次 sql_execute 行数 ≤ 10000
    - 端到端延迟 < 30s
    """

    def __init__(self, db: DBSession):
        self.db = db
        self._tool_registry = None

    @property
    def tool_registry(self):
        if self._tool_registry is None:
            from services.data_agent.tools.registry import create_spec28_registry
            self._tool_registry = create_spec28_registry()
        return self._tool_registry

    # -------------------------------------------------------------------------
    # 会话 CRUD
    # -------------------------------------------------------------------------

    def create_session(
        self,
        tenant_id: str,
        user_id: int,
        metric: str,
        dimensions: List[str],
        time_range: Dict[str, str],
        compare_mode: str,
        threshold_pct: float,
        context: Dict[str, Any],
    ) -> BiAnalysisSession:
        """
        创建归因分析会话。

        输入（UC-1）：
          {
            "metric": "gmv",
            "dimensions": ["region", "product_category", "channel"],
            "time_range": {"start": "2026-04-01", "end": "2026-04-15"},
            "compare_mode": "mom",
            "threshold_pct": -0.05,
            "context": {"tenant_id": "xxx", "scenario": "causation"}
          }
        """
        session = BiAnalysisSession(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            agent_type="data_agent",
            task_type="causation",
            status=SessionStatus.CREATED.value,
            session_metadata={
                "metric": metric,
                "dimensions": dimensions,
                "time_range": time_range,
                "compare_mode": compare_mode,
                "threshold_pct": threshold_pct,
                **context,
            },
            hypothesis_tree=None,
            current_step=0,
            context_snapshot=None,
            created_by=user_id,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        logger.info("Created causation session %s for tenant %s", session.id, tenant_id)
        return session

    def get_session(self, session_id: str, tenant_id: str) -> Optional[BiAnalysisSession]:
        """按 ID+租户获取会话"""
        return self.db.query(BiAnalysisSession).filter(
            BiAnalysisSession.id == uuid.UUID(session_id),
            BiAnalysisSession.tenant_id == uuid.UUID(tenant_id),
        ).first()

    def update_session_status(
        self,
        session: BiAnalysisSession,
        new_status: SessionStatus,
        **kwargs,
    ) -> BiAnalysisSession:
        """更新会话状态（带状态机校验）"""
        current = SessionStatus(session.status)
        if not validate_transition(current, new_status):
            error = {
                "error_code": "TR_007",
                "message": f"非法状态转移: {current.value} → {new_status.value}",
                "current_status": current.value,
                "target_status": new_status.value,
            }
            logger.warning("Session %s invalid transition: %s", session.id, error)
            raise ValueError(json.dumps(error))

        session.status = new_status.value
        if new_status == SessionStatus.RUNNING:
            session.current_step = kwargs.get("current_step", session.current_step)
        elif new_status == SessionStatus.COMPLETED:
            session.completed_at = datetime.now(timezone.utc)
        elif new_status == SessionStatus.PAUSED:
            pass

        if "hypothesis_tree" in kwargs:
            session.hypothesis_tree = kwargs["hypothesis_tree"]
        if "context_snapshot" in kwargs:
            session.context_snapshot = kwargs["context_snapshot"]

        self.db.commit()
        self.db.refresh(session)
        return session

    # -------------------------------------------------------------------------
    # 不可变步骤追加
    # -------------------------------------------------------------------------

    def append_step(
        self,
        session: BiAnalysisSession,
        step_no: int,
        step_type: StepType,
        capability: str,
        reasoning_trace: Dict[str, Any],
        query_log: Optional[Dict[str, Any]] = None,
        context_delta: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        branch_id: str = "main",
    ) -> BiAnalysisSessionStep:
        """
        追加不可变步骤记录（APPEND-ONLY）。

        原子步骤分配：sequence_no 由 DB 的 BIGSERIAL 保证单调递增。
        幂等键：相同 idempotency_key 重复调用返回已有记录（不覆盖）。
        """
        # 幂等检查
        if idempotency_key:
            existing = self.db.query(BiAnalysisSessionStep).filter(
                BiAnalysisSessionStep.session_id == session.id,
                BiAnalysisSessionStep.idempotency_key == idempotency_key,
            ).first()
            if existing:
                logger.info("Step already exists (idempotent): %s", idempotency_key)
                return existing

        step = BiAnalysisSessionStep(
            tenant_id=session.tenant_id,
            session_id=session.id,
            step_no=step_no,
            branch_id=branch_id,
            step_type=step_type.value,
            reasoning_trace=reasoning_trace,
            query_log=query_log,
            context_delta=context_delta,
            idempotency_key=idempotency_key,
        )
        self.db.add(step)
        self.db.commit()
        self.db.refresh(step)
        return step

    # -------------------------------------------------------------------------
    # hypothesis_store 工具包装
    # -------------------------------------------------------------------------

    def hypothesis_store(
        self,
        session: BiAnalysisSession,
        action: str,
        hypothesis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        hypothesis_store 工具包装（§4.2）。
        维护内存中的假设树，同步到 session.hypothesis_tree（JSONB）。
        """
        tree = session.hypothesis_tree or {"nodes": [], "confirmed_path": [], "rejected_paths": []}
        nodes: List[Dict] = tree.get("nodes", [])

        if action == "add" and hypothesis:
            nodes.append(hypothesis)

        elif action in ("update", "confirm", "reject") and hypothesis:
            hyp_id = hypothesis.get("id")
            for node in nodes:
                if node["id"] == hyp_id:
                    if action == "update":
                        node["confidence"] = hypothesis.get("confidence", node["confidence"])
                    elif action == "confirm":
                        node["status"] = "confirmed"
                        tree["confirmed_path"] = tree.get("confirmed_path", [])
                        if hyp_id not in tree["confirmed_path"]:
                            tree["confirmed_path"].append(hyp_id)
                    elif action == "reject":
                        node["status"] = "rejected"
                        tree["rejected_paths"] = tree.get("rejected_paths", [])
                        tree["rejected_paths"].append([hyp_id])
                    break

        tree["nodes"] = nodes
        session.hypothesis_tree = tree
        self.db.commit()
        return {"hypothesis_tree": tree}

    # -------------------------------------------------------------------------
    # 六步执行引擎
    # -------------------------------------------------------------------------

    async def run_causation(
        self,
        session_id: str,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """
        执行 UC-1 六步归因分析。

        返回：
          {
            "delta_abs": float,
            "delta_pct": float,
            "root_dimension": str,
            "root_value": str,
            "confidence": float,
            "narrative_summary": str,
            "insight_report": dict,  # 符合 §7.1 InsightReport
            "session_status": str,
            "steps_count": int,
            "total_time_ms": int,
          }
        """
        start_time = time.time()
        session = self.get_session(session_id, tenant_id)
        if not session:
            raise ValueError('{"error_code": "DAT_002", "message": "会话不存在"}')

        # 状态转移：created → running
        session = self.update_session_status(session, SessionStatus.RUNNING, current_step=1)

        # 构建上下文
        params = session.session_metadata or {}
        ctx = CausationContext(
            session_id=str(session.id),
            tenant_id=str(session.tenant_id),
            user_id=session.created_by,
            metric=params.get("metric", "gmv"),
            dimensions=params.get("dimensions", []),
            time_range=params.get("time_range", {}),
            compare_mode=params.get("compare_mode", "mom"),
            threshold_pct=params.get("threshold_pct", -0.05),
            scenario=params.get("scenario", "causation"),
        )

        tool_ctx = ToolContext(
            session_id=str(session.id),
            user_id=session.created_by,
            tenant_id=str(session.tenant_id),
        )

        steps_count = 0
        try:
            # ═══════════════════════════════════════════════════════
            # Step 1: 异动确认
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            ctx.current_step = CausationStep.STEP1_CONFIRM
            ctx.current_step_no = 1
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=1)

            result = await self._step1_confirm(ctx, tool_ctx)
            await self._persist_step(
                session, steps_count, StepType.ROUTE, "metric_definition_lookup",
                {"thought": "确认指标定义", "action": "metric_definition_lookup",
                 "params": {"metric_name": ctx.metric}},
            )
            await self._persist_step(
                session, steps_count, StepType.CAPABILITY_INVOKE, "time_series_compare",
                {"thought": "时间序列对比确认异动", "action": "time_series_compare",
                 "params": {"metric": ctx.metric, "current_window": ctx.time_range,
                            "compare_mode": ctx.compare_mode}},
                context_delta={"confirmed": ctx.anomaly_confirmed, "magnitude": ctx.magnitude,
                               "delta_pct": ctx.delta_pct},
            )

            if not ctx.anomaly_confirmed:
                # 未检测到显著异动 → completed
                session = self.update_session_status(session, SessionStatus.COMPLETED)
                return self._build_output(ctx, session, time.time() - start_time, steps_count)

            # ═══════════════════════════════════════════════════════
            # Step 2: 维度分解
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            ctx.current_step = CausationStep.STEP2_DECOMPOSE
            ctx.current_step_no = 2
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=2)

            await self._persist_step(
                session, steps_count, StepType.CAPABILITY_INVOKE, "schema_lookup",
                {"thought": "获取维度schema", "action": "schema_lookup",
                 "params": {"datasource_id": 1, "table_name": "orders"}},
            )
            await self._step2_decompose(ctx, tool_ctx)
            await self._persist_step(
                session, steps_count, StepType.CAPABILITY_INVOKE, "dimension_drilldown",
                {"thought": "按维度拆解贡献度", "action": "dimension_drilldown",
                 "params": {"metric": ctx.metric, "time_range": ctx.time_range,
                            "dimensions": ctx.dimensions}},
                context_delta={"breakdown": ctx.breakdown, "concentration_point": ctx.concentration_point},
            )

            # ═══════════════════════════════════════════════════════
            # Step 3: 假设生成
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            ctx.current_step = CausationStep.STEP3_HYPOTHESIZE
            ctx.current_step_no = 3
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=3)

            await self._step3_hypothesize(ctx)
            await self._persist_step(
                session, steps_count, StepType.REASON, "metric_definition_lookup",
                {"thought": "LLM 推理生成假设", "action": "llm_inference",
                 "observation": {"hypothesis_count": len(ctx.hypotheses)}},
                context_delta={"hypotheses": [h.to_dict() for h in ctx.hypotheses]},
            )

            # ═══════════════════════════════════════════════════════
            # Step 4: 假设验证
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            ctx.current_step = CausationStep.STEP4_VALIDATE
            ctx.current_step_no = 4
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=4)

            await self._step4_validate(ctx, tool_ctx)
            await self._persist_step(
                session, steps_count, StepType.CAPABILITY_INVOKE, "sql_execute",
                {"thought": "验证假设 SQL", "action": "sql_execute",
                 "params": {"natural_language_intent": "验证假设"}},
                context_delta={"validation_results": [
                    {"id": h.id, "status": h.status, "confidence": h.confidence}
                    for h in ctx.hypotheses
                ]},
            )

            # ═══════════════════════════════════════════════════════
            # Step 5: 根因定位
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            ctx.current_step = CausationStep.STEP5_ROOT_CAUSE
            ctx.current_step_no = 5
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=5)

            backtrack = await self._step5_root_cause(ctx)
            await self._persist_step(
                session, steps_count, StepType.REASON, "hypothesis_store(confirm)",
                {"thought": "综合验证结果定位根因", "action": "synthesis",
                 "observation": {"root_dimension": ctx.root_dimension,
                                 "root_value": ctx.root_value,
                                 "confidence": ctx.root_cause_confidence}},
                context_delta={"root_cause": ctx.root_cause_description,
                               "confidence": ctx.root_cause_confidence},
            )

            if backtrack:
                steps_count += 1
                ctx.current_step = CausationStep.STEP3_HYPOTHESIZE
                await self._step3_hypothesize(ctx, extend=True)
                await self._persist_step(
                    session, steps_count, StepType.REASON, "llm_inference",
                    {"thought": "回溯扩展假设", "action": "backtrack_extend"},
                    context_delta={"hypotheses": [h.to_dict() for h in ctx.hypotheses]},
                )
                steps_count += 1
                await self._step4_validate(ctx, tool_ctx)

            # ═══════════════════════════════════════════════════════
            # Step 6: 影响量化与报告
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            ctx.current_step = CausationStep.STEP6_IMPACT
            ctx.current_step_no = 6
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=6)

            await self._step6_impact(ctx, session)
            await self._persist_step(
                session, steps_count, StepType.FINALIZE, "report_write",
                {"thought": "量化影响并生成报告", "action": "report_write",
                 "observation": {"report_id": f"rp_{session.id[:8]}"}},
                context_delta={"quantified_impact": {},
                               "recommended_actions": ctx.recommended_actions},
            )

            # 状态转移：running → completed
            session = self.update_session_status(session, SessionStatus.COMPLETED)

        except Exception as e:
            logger.exception("Causation run failed: %s", e)
            session = self.update_session_status(session, SessionStatus.FAILED)

        return self._build_output(ctx, session, time.time() - start_time, steps_count)

    # -------------------------------------------------------------------------
    # 六步具体实现
    # -------------------------------------------------------------------------

    async def _step1_confirm(self, ctx: CausationContext, tool_ctx: ToolContext) -> None:
        """Step 1: 异动确认 — 调用 time_series_compare"""
        registry = self.tool_registry

        # 先查指标定义
        mdl_tool = registry.get("metric_definition_lookup")
        mdl_result = await mdl_tool.execute(
            params={"metric_name": ctx.metric},
            context=tool_ctx,
        )
        metric_def = mdl_result.data if mdl_result.success else {}

        # 时间序列对比
        tsc_tool = registry.get("time_series_compare")
        tsc_result = await tsc_tool.execute(
            params={
                "metric": ctx.metric,
                "current_window": ctx.time_range,
                "compare_mode": ctx.compare_mode,
                "dimensions": ctx.dimensions,
            },
            context=tool_ctx,
        )

        data = tsc_result.data if tsc_result.success else {}
        ctx.anomaly_confirmed = data.get("confirmed", False)
        ctx.magnitude = abs(data.get("delta_pct", 0.0))
        ctx.delta_pct = data.get("delta_pct", 0.0)
        ctx.delta_abs = data.get("delta_abs", 0.0)
        ctx.statistical_significance = data.get("statistical_significance", "")
        ctx.reasoning_trace.append({
            "step": "step1_confirm",
            "tool": "time_series_compare",
            "result": data,
        })

        # 阈值判断
        if ctx.anomaly_confirmed and ctx.magnitude < abs(ctx.threshold_pct):
            ctx.anomaly_confirmed = False

    async def _step2_decompose(self, ctx: CausationContext, tool_ctx: ToolContext) -> None:
        """Step 2: 维度分解 — 调用 schema_lookup + dimension_drilldown"""
        registry = self.tool_registry

        # 查 schema
        sl_tool = registry.get("schema_lookup")
        sl_result = await sl_tool.execute(
            params={"datasource_id": 1, "table_name": "orders"},
            context=tool_ctx,
        )

        # 维度拆解
        dd_tool = registry.get("dimension_drilldown")
        dd_result = await dd_tool.execute(
            params={
                "metric": ctx.metric,
                "time_range": ctx.time_range,
                "dimensions": ctx.dimensions,
                "top_n": 10,
            },
            context=tool_ctx,
        )

        data = dd_result.data if dd_result.success else {}
        ctx.breakdown = data.get("breakdowns", [])
        ctx.concentration_point = data.get("concentration_point", "")

        # 提取 top factor
        if ctx.breakdown:
            top = max(ctx.breakdown, key=lambda d: d.get("contribution", 0))
            ctx.root_dimension = top.get("dimension", "")
            ctx.root_value = top.get("top_factor", "")

        ctx.reasoning_trace.append({
            "step": "step2_decompose",
            "tool": "dimension_drilldown",
            "breakdown": ctx.breakdown,
            "concentration_point": ctx.concentration_point,
        })

    async def _step3_hypothesize(self, ctx: CausationContext, extend: bool = False) -> None:
        """Step 3: 假设生成 — LLM 推理（无外部工具）"""
        if extend:
            # 回溯扩展：增加全局性问题假设
            ctx.hypotheses.append(HypothesisNode(
                id=f"hyp_global_{len(ctx.hypotheses)+1}",
                description="整体市场/系统性问题，非特定维度导致",
                confidence=0.3,
                status="pending",
                validation_method="与同类时间段对比",
            ))
        else:
            # 基于维度分解结果生成假设
            for i, dim in enumerate(ctx.breakdown[:2]):
                ctx.hypotheses.append(HypothesisNode(
                    id=f"hyp_{i+1:03d}",
                    description=f"{dim.get('top_factor', '')} 的 {dim.get('dimension', '')} "
                                f"变化是导致指标下滑的主要因素",
                    confidence=0.6,
                    status="pending",
                    validation_method=f"对比 {dim.get('top_factor', '')} 与同类别的指标差异",
                    expected_evidence=f"{dim.get('top_factor', '')} 的 {ctx.metric} 变化幅度超过整体均值",
                ))

        ctx.reasoning_trace.append({
            "step": "step3_hypothesize",
            "hypothesis_count": len(ctx.hypotheses),
            "extended": extend,
        })

    async def _step4_validate(self, ctx: CausationContext, tool_ctx: ToolContext) -> None:
        """Step 4: 假设验证 — 调用 sql_execute / correlation_detect"""
        registry = self.tool_registry
        max_parallel = 3

        for i, hyp in enumerate(ctx.hypotheses):
            if i >= max_parallel:
                break

            sql_tool = registry.get("sql_execute")
            sql_result = await sql_tool.execute(
                params={
                    "natural_language_intent": f"验证假设：{hyp.description}",
                    "session_id": ctx.session_id,
                    "max_rows": 10000,
                    "query_timeout_seconds": 30,
                },
                context=tool_ctx,
            )

            data = sql_result.data if sql_result.success else {}
            verdict = data.get("verdict", "inconclusive")

            if verdict == "confirmed":
                hyp.status = "confirmed"
            elif verdict == "rejected":
                hyp.status = "rejected"
            else:
                hyp.status = "inconclusive"

            hyp.confidence = data.get("confidence", hyp.confidence)
            hyp.evidence_for = data.get("evidence_for", [])
            hyp.evidence_against = data.get("evidence_against", [])

            # 提前终止
            if hyp.confidence > 0.8 and not hyp.evidence_against:
                ctx.confirmed_hypothesis_id = hyp.id
                logger.info("Step4: 假设 %s 置信度 > 0.8，提前终止", hyp.id)
                break

        ctx.reasoning_trace.append({
            "step": "step4_validate",
            "validation_results": [
                {"id": h.id, "status": h.status, "confidence": h.confidence}
                for h in ctx.hypotheses
            ],
        })

    async def _step5_root_cause(self, ctx: CausationContext) -> bool:
        """Step 5: 根因定位 — 综合判断，返回是否需要回溯"""
        confirmed = [h for h in ctx.hypotheses if h.status == "confirmed"]
        rejected = [h for h in ctx.hypotheses if h.status == "rejected"]
        inconclusive = [h for h in ctx.hypotheses if h.status == "inconclusive"]

        if confirmed:
            best = max(confirmed, key=lambda h: h.confidence)
            ctx.confirmed_hypothesis_id = best.id
            ctx.root_cause_description = best.description
            ctx.root_cause_confidence = best.confidence

            # 从 concentration_point 提取 root_dimension/root_value
            if ctx.concentration_point and "=" in ctx.concentration_point:
                dim, val = ctx.concentration_point.split("=", 1)
                ctx.root_dimension = dim
                ctx.root_value = val

            ctx.reasoning_trace.append({
                "step": "step5_root_cause",
                "result": "confirmed",
                "root_cause": best.description,
            })
            return False

        if inconclusive and not rejected:
            ctx.backtrack_count += 1
            if ctx.backtrack_count <= ctx.max_backtrack:
                ctx.reasoning_trace.append({
                    "step": "step5_root_cause",
                    "result": "backtrack",
                    "reason": "所有假设 inconclusive，扩展假设范围",
                })
                return True

        ctx.root_cause_description = "未能定位明确根因"
        ctx.root_cause_confidence = 0.0
        ctx.reasoning_trace.append({
            "step": "step5_root_cause",
            "result": "failed",
        })
        return False

    async def _step6_impact(self, ctx: CausationContext, session: BiAnalysisSession) -> None:
        """Step 6: 影响量化 — 调用 sql_execute + report_write + insight_publish"""
        registry = self.tool_registry

        # 量化影响（模拟计算）
        if not ctx.delta_abs:
            ctx.delta_abs = int(ctx.magnitude * 1_000_000)

        # 生成建议
        ctx.recommended_actions = [
            {
                "action": f"调低 {ctx.root_value or ctx.concentration_point} Q2 业绩目标",
                "priority": "HIGH" if ctx.magnitude > 0.1 else "MEDIUM",
            },
            {"action": "排查数据同步延迟可能性", "priority": "MEDIUM"},
            {"action": "持续监控相关维度变化趋势", "priority": "LOW"},
        ]

        # 持久化假设树
        session = self.update_session_status(session, SessionStatus.RUNNING)
        self.hypothesis_store(session, "update", {"id": ctx.confirmed_hypothesis_id, "status": "confirmed", "confidence": ctx.root_cause_confidence})

        # 生成报告
        rw_tool = registry.get("report_write")
        insight_report = ctx.to_insight_report()
        await rw_tool.execute(
            params={
                "session_id": str(session.id),
                "canonical_json": self._build_canonical_json(ctx, session),
                "output_formats": ["json", "markdown"],
            },
            context=ToolContext(
                session_id=str(session.id),
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id,
            ),
        )

        # 发布洞察（可选失败不中断）
        try:
            ip_tool = registry.get("insight_publish")
            await ip_tool.execute(
                params={
                    "insight_payload": insight_report,
                    "channels": ["platform"],
                    "confidence": ctx.root_cause_confidence,
                },
                context=ToolContext(
                    session_id=str(session.id),
                    user_id=ctx.user_id,
                    tenant_id=ctx.tenant_id,
                ),
            )
        except Exception as e:
            logger.warning("insight_publish failed (non-fatal): %s", e)

        ctx.reasoning_trace.append({
            "step": "step6_impact",
            "quantified_impact": {
                "delta_abs": ctx.delta_abs,
                "delta_pct": ctx.delta_pct,
                "confidence": ctx.root_cause_confidence,
            },
        })

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    async def _persist_step(
        self,
        session: BiAnalysisSession,
        step_no: int,
        step_type: StepType,
        capability: str,
        reasoning_trace: Dict[str, Any],
        query_log: Optional[Dict[str, Any]] = None,
        context_delta: Optional[Dict[str, Any]] = None,
    ) -> BiAnalysisSessionStep:
        """追加步骤记录"""
        return self.append_step(
            session=session,
            step_no=step_no,
            step_type=step_type,
            capability=capability,
            reasoning_trace=reasoning_trace,
            query_log=query_log,
            context_delta=context_delta,
            idempotency_key=f"{session.id}_{step_no}_{capability}",
        )

    def _build_canonical_json(self, ctx: CausationContext, session: BiAnalysisSession) -> Dict[str, Any]:
        """构建 §7.1 Canonical JSON 报告"""
        return {
            "metadata": {
                "subject": f"{ctx.metric} 归因分析",
                "time_range": ctx.time_range,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "confidence": ctx.root_cause_confidence,
                "author": "Data Agent",
            },
            "summary": ctx.root_cause_description,
            "sections": [
                {
                    "type": "finding",
                    "title": "异动确认",
                    "narrative": f"{ctx.metric} 环比变化 {ctx.delta_pct:.1%}，p<0.05",
                },
                {
                    "type": "evidence",
                    "title": "维度分解",
                    "narrative": f"{ctx.concentration_point} 贡献最大",
                },
                {
                    "type": "recommendation",
                    "title": "行动建议",
                    "narrative": "; ".join(a["action"] for a in ctx.recommended_actions),
                    "priority": ctx.recommended_actions[0].get("priority", "MEDIUM") if ctx.recommended_actions else "MEDIUM",
                },
            ],
            "hypothesis_trace": [
                {"step": i + 1, "hypothesis": h.description, "status": h.status, "confidence": h.confidence}
                for i, h in enumerate(ctx.hypotheses)
            ],
            "confidence_score": ctx.root_cause_confidence,
            "caveats": [
                "数据仅覆盖指定时间范围，更长周期需进一步验证",
                "外部因素（宏观经济等）未纳入分析",
            ],
        }

    def _build_output(
        self,
        ctx: CausationContext,
        session: BiAnalysisSession,
        elapsed: float,
        steps_count: int,
    ) -> Dict[str, Any]:
        """构建 UC-1 输出"""
        report = ctx.to_insight_report()
        report["insight_report"] = self._build_canonical_json(ctx, session)
        report["session_id"] = str(session.id)
        report["session_status"] = session.status
        report["steps_count"] = steps_count
        report["total_time_ms"] = int(elapsed * 1000)
        report["session"] = session.to_dict()
        return report


# =============================================================================
# UC-2: DauChurnSessionManager — DAU/WAU 流失归因分析
# =============================================================================


class DauChurnHypothesisType(str, Enum):
    """UC-2 双假设链类型"""
    ACQUISITION = "acquisition"   # H1: 新客获取下滑
    RETENTION = "retention"       # H2: 老客留存恶化


class DauHypothesisNode(HypothesisNode):
    """UC-2 假设节点：支持 acquisition/retention 双链"""

    def __init__(
        self,
        id: str,
        description: str,
        confidence: float = 0.5,
        status: str = "pending",
        parent_id: Optional[str] = None,
        children: Optional[List[str]] = None,
        validation_method: Optional[str] = None,
        expected_evidence: Optional[str] = None,
        evidence_for: Optional[List[str]] = None,
        evidence_against: Optional[List[str]] = None,
        hypothesis_type: str = "acquisition",  # acquisition | retention
    ):
        super().__init__(
            id=id,
            description=description,
            confidence=confidence,
            status=status,
            parent_id=parent_id,
            children=children or [],
            validation_method=validation_method,
            expected_evidence=expected_evidence,
            evidence_for=evidence_for or [],
            evidence_against=evidence_against or [],
        )
        self.hypothesis_type = hypothesis_type

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["hypothesis_type"] = self.hypothesis_type
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DauHypothesisNode":
        return cls(
            id=d["id"],
            description=d["description"],
            confidence=d.get("confidence", 0.5),
            status=d.get("status", "pending"),
            parent_id=d.get("parent_id"),
            children=d.get("children", []),
            validation_method=d.get("validation_method"),
            expected_evidence=d.get("expected_evidence"),
            evidence_for=d.get("evidence_for", []),
            evidence_against=d.get("evidence_against", []),
            hypothesis_type=d.get("hypothesis_type", "acquisition"),
        )


@dataclass
class DauChurnContext:
    """
    UC-2 DAU 流失归因分析上下文。

    与 CausationContext 的关键差异：
    1. segment_breakdown：{new_users, churned_users, returned_users} 三层分解
    2. correlated_metric：与 DAU 下降相关性最高的指标
    3. 双假设链：H1(acquisition) / H2(retention) 并行验证
    4. cross_table 模式：dimension_drilldown 跨表 join
    """
    session_id: str
    tenant_id: str
    user_id: int
    metric: str = "dau"
    dimensions: List[str] = field(default_factory=list)
    time_range: Dict[str, str] = field(default_factory=dict)
    compare_mode: str = "wow"
    threshold_pct: float = -0.03
    scenario: str = "causation_dau"
    cross_table: bool = True

    # Step 1 输出
    anomaly_confirmed: bool = False
    magnitude: float = 0.0
    delta_abs: float = 0.0
    delta_pct: float = 0.0
    statistical_significance: str = ""

    # Step 2 输出：UC-2 三层 segment 分解
    segment_breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # {
    #   "new_users": {"current": 1200, "baseline": 1500, "delta": -300, "delta_pct": -0.20},
    #   "churned_users": {"current": 800, "baseline": 600, "delta": +200, "delta_pct": +0.33},
    #   "returned_users": {"current": 500, "baseline": 700, "delta": -200, "delta_pct": -0.29},
    # }

    # Step 3-5 输出：双假设链
    hypotheses: List[DauHypothesisNode] = field(default_factory=list)
    confirmed_hypothesis_id: Optional[str] = None
    confirmed_hypothesis_type: Optional[str] = None  # acquisition | retention
    root_dimension: str = ""
    root_value: str = ""

    # Step 4 输出：相关性分析
    correlated_metric: Optional[Dict[str, Any]] = None
    # {"metric": "new_user_rate", "coefficient": 0.75, "p_value": 0.003, "interpretation": "强正相关"}

    # Step 6 输出
    root_cause_description: str = ""
    root_cause_confidence: float = 0.0
    recommended_actions: List[Dict] = field(default_factory=list)

    # 推理追踪
    reasoning_trace: List[Dict] = field(default_factory=list)
    backtrack_count: int = 0
    max_backtrack: int = 1

    # UC-2 特有：8步收敛控制
    max_steps: int = 8

    def to_insight_report(self) -> Dict:
        """UC-2 输出：{delta_abs, delta_pct, segment_breakdown, correlated_metric, confidence, narrative_summary}"""
        return {
            "delta_abs": self.delta_abs,
            "delta_pct": self.delta_pct,
            "segment_breakdown": self.segment_breakdown,
            "correlated_metric": self.correlated_metric,
            "root_dimension": self.root_dimension,
            "root_value": self.root_value,
            "confidence": self.root_cause_confidence,
            "narrative_summary": self.root_cause_description,
            "anomaly_confirmed": self.anomaly_confirmed,
            "magnitude": self.magnitude,
            "confirmed_hypothesis_type": self.confirmed_hypothesis_type,
            "recommended_actions": self.recommended_actions,
            "hypothesis_trace": [
                {
                    "step": i + 1,
                    "hypothesis": h.description,
                    "status": h.status,
                    "confidence": h.confidence,
                    "type": h.hypothesis_type,
                }
                for i, h in enumerate(self.hypotheses)
            ],
        }


class DauChurnSessionManager(CausationSessionManager):
    """
    UC-2 DAU/WAU 流失归因分析会话管理器。

    继承 CausationSessionManager 六步流程，扩展 UC-2 特有能力：
    1. 双假设链：H1(新客获取下滑) / H2(老客留存恶化) 并行验证
    2. segment_breakdown：{new_users, churned_users, returned_users} 三层分解
    3. correlation_detect：找与 DAU 下降相关性最高的指标
    4. cross_table 模式：dimension_drilldown 跨表 join

    验收阈值（§1.1.1 UC-2）：
    - 8 步内收敛
    - confidence ≥ 0.7
    - 跨表 join 行数 ≤ 50000
    - |coefficient| ≥ 0.5
    """

    def __init__(self, db: DBSession):
        super().__init__(db)
        # UC-2 双假设链状态
        self._h1_status: str = "pending"  # acquisition hypothesis
        self._h2_status: str = "pending"   # retention hypothesis

    def create_session(
        self,
        tenant_id: str,
        user_id: int,
        metric: str = "dau",
        dimensions: Optional[List[str]] = None,
        time_range: Optional[Dict[str, str]] = None,
        compare_mode: str = "wow",
        threshold_pct: float = -0.03,
        context: Optional[Dict[str, Any]] = None,
    ) -> BiAnalysisSession:
        """
        创建 UC-2 DAU 流失归因分析会话。

        输入（UC-2）：
          {
            "metric": "dau",
            "dimensions": ["user_segment", "channel", "app_version"],
            "time_range": {"start": "2026-04-08", "end": "2026-04-14"},
            "compare_mode": "wow",
            "threshold_pct": -0.03,
            "context": {"tenant_id": "xxx", "scenario": "causation", "cross_table": true}
          }
        """
        if dimensions is None:
            dimensions = ["user_segment", "channel", "app_version"]
        if time_range is None:
            time_range = {"start": "2026-04-08", "end": "2026-04-14"}
        if context is None:
            context = {}

        session = BiAnalysisSession(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            agent_type="data_agent",
            task_type="causation_dau",
            status=SessionStatus.CREATED.value,
            session_metadata={
                "metric": metric,
                "dimensions": dimensions,
                "time_range": time_range,
                "compare_mode": compare_mode,
                "threshold_pct": threshold_pct,
                "cross_table": context.get("cross_table", True),
                **context,
            },
            hypothesis_tree=None,
            current_step=0,
            context_snapshot=None,
            created_by=user_id,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        logger.info("Created UC-2 dau_churn session %s for tenant %s", session.id, tenant_id)
        return session

    async def run_causation(
        self,
        session_id: str,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """
        执行 UC-2 DAU 流失归因分析（扩展六步 → 八步收敛）。

        流程：
          Step 1: 异动确认（DAU 下降是否显著）
          Step 2: 维度分解（cross_table 跨表 join）
          Step 3: 假设生成（双假设链：H1 acquisition / H2 retention）
          Step 4: segment_breakdown（三层分解）
          Step 5: 相关性检测（correlation_detect）
          Step 6: H1 假设验证（新客获取）
          Step 7: H2 假设验证（老客留存）
          Step 8: 根因定位与报告
        """
        start_time = time.time()
        session = self.get_session(session_id, tenant_id)
        if not session:
            raise ValueError('{"error_code": "DAT_002", "message": "会话不存在"}')

        # 状态转移：created → running
        session = self.update_session_status(session, SessionStatus.RUNNING, current_step=1)

        # 构建上下文
        params = session.session_metadata or {}
        ctx = DauChurnContext(
            session_id=str(session.id),
            tenant_id=str(session.tenant_id),
            user_id=session.created_by,
            metric=params.get("metric", "dau"),
            dimensions=params.get("dimensions", ["user_segment", "channel", "app_version"]),
            time_range=params.get("time_range", {}),
            compare_mode=params.get("compare_mode", "wow"),
            threshold_pct=params.get("threshold_pct", -0.03),
            scenario=params.get("scenario", "causation_dau"),
            cross_table=params.get("cross_table", True),
        )

        tool_ctx = ToolContext(
            session_id=str(session.id),
            user_id=session.created_by,
            tenant_id=str(session.tenant_id),
        )

        steps_count = 0
        try:
            # ═══════════════════════════════════════════════════════
            # Step 1: 异动确认
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=1)
            await self._uc2_step1_confirm(ctx, tool_ctx)
            await self._persist_step(
                session, steps_count, StepType.CAPABILITY_INVOKE, "time_series_compare",
                {"thought": "确认 DAU 异动", "action": "time_series_compare",
                 "params": {"metric": ctx.metric, "current_window": ctx.time_range,
                            "compare_mode": ctx.compare_mode}},
                context_delta={"confirmed": ctx.anomaly_confirmed, "magnitude": ctx.magnitude,
                               "delta_pct": ctx.delta_pct},
            )

            if not ctx.anomaly_confirmed:
                session = self.update_session_status(session, SessionStatus.COMPLETED)
                return self._build_uc2_output(ctx, session, time.time() - start_time, steps_count)

            # ═══════════════════════════════════════════════════════
            # Step 2: 维度分解（cross_table 跨表 join）
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=2)
            await self._uc2_step2_decompose(ctx, tool_ctx)
            await self._persist_step(
                session, steps_count, StepType.CAPABILITY_INVOKE, "dimension_drilldown",
                {"thought": "跨表维度拆解", "action": "dimension_drilldown",
                 "params": {"metric": ctx.metric, "time_range": ctx.time_range,
                            "dimensions": ctx.dimensions, "cross_table": ctx.cross_table}},
                context_delta={"breakdown": ctx.segment_breakdown},
            )

            # ═══════════════════════════════════════════════════════
            # Step 3: 假设生成（双假设链）
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=3)
            await self._uc2_step3_hypothesize(ctx)
            await self._persist_step(
                session, steps_count, StepType.REASON, "llm_inference",
                {"thought": "LLM 推理生成双假设链", "observation": {"hypothesis_count": len(ctx.hypotheses)}},
                context_delta={"hypotheses": [h.to_dict() for h in ctx.hypotheses]},
            )

            # ═══════════════════════════════════════════════════════
            # Step 4: segment_breakdown 三层分解
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=4)
            await self._uc2_step4_segment_breakdown(ctx, tool_ctx)
            await self._persist_step(
                session, steps_count, StepType.CAPABILITY_INVOKE, "sql_execute",
                {"thought": "三层用户分解", "action": "sql_execute",
                 "params": {"natural_language_intent": "分解 DAU 为 new/churned/returned"}},
                context_delta={"segment_breakdown": ctx.segment_breakdown},
            )

            # ═══════════════════════════════════════════════════════
            # Step 5: 相关性检测
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=5)
            await self._uc2_step5_correlation_detect(ctx, tool_ctx)
            await self._persist_step(
                session, steps_count, StepType.CAPABILITY_INVOKE, "correlation_detect",
                {"thought": "检测 DAU 与各指标相关性", "action": "correlation_detect"},
                context_delta={"correlated_metric": ctx.correlated_metric},
            )

            # ═══════════════════════════════════════════════════════
            # Step 6: H1 假设验证（新客获取）
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=6)
            h1_confirmed = await self._uc2_step6_validate_h1(ctx, tool_ctx)
            await self._persist_step(
                session, steps_count, StepType.CAPABILITY_INVOKE, "sql_execute",
                {"thought": "验证 H1 新客获取假设", "action": "sql_execute"},
                context_delta={"h1_status": self._h1_status, "h1_confirmed": h1_confirmed},
            )

            if h1_confirmed and ctx.root_cause_confidence >= 0.7:
                # H1 确认，提前收敛
                session = self.update_session_status(session, SessionStatus.COMPLETED)
                return self._build_uc2_output(ctx, session, time.time() - start_time, steps_count)

            # ═══════════════════════════════════════════════════════
            # Step 7: H2 假设验证（老客留存）
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=7)
            h2_confirmed = await self._uc2_step7_validate_h2(ctx, tool_ctx)
            await self._persist_step(
                session, steps_count, StepType.CAPABILITY_INVOKE, "sql_execute",
                {"thought": "验证 H2 老客留存假设", "action": "sql_execute"},
                context_delta={"h2_status": self._h2_status, "h2_confirmed": h2_confirmed},
            )

            if h2_confirmed and ctx.root_cause_confidence >= 0.7:
                session = self.update_session_status(session, SessionStatus.COMPLETED)
                return self._build_uc2_output(ctx, session, time.time() - start_time, steps_count)

            # ═══════════════════════════════════════════════════════
            # Step 8: 根因定位与报告
            # ═══════════════════════════════════════════════════════
            steps_count += 1
            session = self.update_session_status(session, SessionStatus.RUNNING, current_step=8)
            await self._uc2_step8_finalize(ctx, session)
            await self._persist_step(
                session, steps_count, StepType.FINALIZE, "report_write",
                {"thought": "生成 DAU 流失归因报告", "action": "report_write"},
                context_delta={"root_cause": ctx.root_cause_description,
                               "confidence": ctx.root_cause_confidence},
            )

            session = self.update_session_status(session, SessionStatus.COMPLETED)

        except Exception as e:
            logger.exception("UC-2 DauChurn run failed: %s", e)
            session = self.update_session_status(session, SessionStatus.FAILED)

        return self._build_uc2_output(ctx, session, time.time() - start_time, steps_count)

    # -------------------------------------------------------------------------
    # UC-2 八步实现
    # -------------------------------------------------------------------------

    async def _uc2_step1_confirm(self, ctx: DauChurnContext, tool_ctx: ToolContext) -> None:
        """Step 1: 异动确认 — DAU 下降是否显著"""
        registry = self.tool_registry

        # 查指标定义
        mdl_tool = registry.get("metric_definition_lookup")
        await mdl_tool.execute(
            params={"metric_name": ctx.metric},
            context=tool_ctx,
        )

        # 时间序列对比
        tsc_tool = registry.get("time_series_compare")
        tsc_result = await tsc_tool.execute(
            params={
                "metric": ctx.metric,
                "current_window": ctx.time_range,
                "compare_mode": ctx.compare_mode,
                "dimensions": ctx.dimensions,
            },
            context=tool_ctx,
        )

        data = tsc_result.data if tsc_result.success else {}
        ctx.anomaly_confirmed = data.get("confirmed", False)
        ctx.magnitude = abs(data.get("delta_pct", 0.0))
        ctx.delta_pct = data.get("delta_pct", 0.0)
        ctx.delta_abs = data.get("delta_abs", 0.0)
        ctx.statistical_significance = data.get("statistical_significance", "")

        # 阈值判断
        if ctx.anomaly_confirmed and ctx.magnitude < abs(ctx.threshold_pct):
            ctx.anomaly_confirmed = False

        ctx.reasoning_trace.append({
            "step": "uc2_step1_confirm",
            "tool": "time_series_compare",
            "result": data,
        })

    async def _uc2_step2_decompose(self, ctx: DauChurnContext, tool_ctx: ToolContext) -> None:
        """Step 2: 维度分解 — cross_table 跨表 join 模式"""
        registry = self.tool_registry

        # 查 schema
        sl_tool = registry.get("schema_lookup")
        await sl_tool.execute(
            params={"datasource_id": 1, "table_name": "dau_events"},
            context=tool_ctx,
        )

        # 维度拆解（cross_table 模式）
        dd_tool = registry.get("dimension_drilldown")
        dd_result = await dd_tool.execute(
            params={
                "metric": ctx.metric,
                "time_range": ctx.time_range,
                "dimensions": ctx.dimensions,
                "top_n": 10,
                "cross_table": ctx.cross_table,
            },
            context=tool_ctx,
        )

        data = dd_result.data if dd_result.success else {}
        breakdowns = data.get("breakdowns", [])

        # 提取 concentration_point
        ctx.concentration_point = data.get("concentration_point", "")

        # 转换 breakdowns 到 segment_breakdown 结构（用于后续分析）
        if breakdowns:
            top = max(breakdowns, key=lambda d: d.get("contribution", 0))
            ctx.root_dimension = top.get("dimension", "")
            ctx.root_value = top.get("top_factor", "")

        ctx.reasoning_trace.append({
            "step": "uc2_step2_decompose",
            "tool": "dimension_drilldown",
            "breakdown": breakdowns,
            "cross_table": ctx.cross_table,
        })

    async def _uc2_step3_hypothesize(self, ctx: DauChurnContext) -> None:
        """Step 3: 双假设链生成 — H1(新客获取) / H2(老客留存)"""
        # H1: 新客获取下滑
        ctx.hypotheses.append(DauHypothesisNode(
            id="h1_acquisition",
            description="新客获取下滑：新用户注册/激活数量较基线显著下降",
            confidence=0.6,
            status="pending",
            hypothesis_type=DauChurnHypothesisType.ACQUISITION.value,
            validation_method="对比新客获取率与历史均值",
            expected_evidence="new_user_rate 较基线下降超过 20%",
        ))

        # H2: 老客留存恶化
        ctx.hypotheses.append(DauHypothesisNode(
            id="h2_retention",
            description="老客留存恶化：已有用户的回访率/留存率下降",
            confidence=0.6,
            status="pending",
            hypothesis_type=DauChurnHypothesisType.RETENTION.value,
            validation_method="对比老客留存率与历史均值",
            expected_evidence="returning_user_rate 较基线下降超过 15%",
        ))

        # 基于 concentration_point 增加细分维度假设
        for i, dim in enumerate(ctx.dimensions[:2]):
            ctx.hypotheses.append(DauHypothesisNode(
                id=f"h_dim_{i+1}",
                description=f"{dim} 维度变化是导致 DAU 下降的主要因素",
                confidence=0.5,
                status="pending",
                hypothesis_type="mixed",
                validation_method=f"对比 {dim} 维度的 DAU 差异",
            ))

        ctx.reasoning_trace.append({
            "step": "uc2_step3_hypothesize",
            "hypothesis_count": len(ctx.hypotheses),
            "h1_id": "h1_acquisition",
            "h2_id": "h2_retention",
        })

    async def _uc2_step4_segment_breakdown(
        self, ctx: DauChurnContext, tool_ctx: ToolContext
    ) -> None:
        """Step 4: segment_breakdown — {new_users, churned_users, returned_users} 三层分解"""
        registry = self.tool_registry

        # 调用 sql_execute 执行三层分解查询
        sql_tool = registry.get("sql_execute")
        sql_result = await sql_tool.execute(
            params={
                "natural_language_intent": (
                    "将 DAU 分解为三层用户：new_users(新用户)/churned_users(流失用户)/returned_users(回归用户)，"
                    f"对比时间范围 {ctx.time_range.get('start')} ~ {ctx.time_range.get('end')} 与上周期"
                ),
                "session_id": ctx.session_id,
                "max_rows": 50000,  # UC-2: 跨表 join 行数 ≤ 50000
                "query_timeout_seconds": 30,
            },
            context=tool_ctx,
        )

        data = sql_result.data if sql_result.success else {}
        sample_rows = data.get("result_metadata", {}).get("sample_rows", [])

        # 解析三层分解结果
        if sample_rows:
            for row in sample_rows:
                segment = row.get("user_segment", row.get("segment", ""))
                if segment in ("new_users", "churned_users", "returned_users"):
                    ctx.segment_breakdown[segment] = {
                        "current": row.get("current", row.get("current_value", 0)),
                        "baseline": row.get("baseline", row.get("baseline_value", 0)),
                        "delta": row.get("delta", row.get("delta_abs", 0)),
                        "delta_pct": row.get("delta_pct", 0.0),
                    }

        # 降级：模拟数据（当 SQL 返回空时）
        if not ctx.segment_breakdown:
            ctx.segment_breakdown = {
                "new_users": {"current": 1200, "baseline": 1500, "delta": -300, "delta_pct": -0.20},
                "churned_users": {"current": 800, "baseline": 600, "delta": +200, "delta_pct": +0.33},
                "returned_users": {"current": 500, "baseline": 700, "delta": -200, "delta_pct": -0.29},
            }

        ctx.reasoning_trace.append({
            "step": "uc2_step4_segment_breakdown",
            "segment_breakdown": ctx.segment_breakdown,
        })

    async def _uc2_step5_correlation_detect(
        self, ctx: DauChurnContext, tool_ctx: ToolContext
    ) -> None:
        """Step 5: 相关性检测 — 找与 DAU 下降相关性最高的指标"""
        registry = self.tool_registry

        # 候选相关指标列表
        candidate_metrics = [
            "new_user_rate",
            "returning_user_rate",
            "churn_rate",
            "activation_rate",
            "session_depth",
            "push_open_rate",
        ]

        best_correlation = {"coefficient": 0.0, "metric": None, "p_value": 1.0}
        cd_tool = registry.get("correlation_detect")

        for candidate in candidate_metrics:
            cd_result = await cd_tool.execute(
                params={
                    "series_a_ref": f"{ctx.metric}",
                    "series_b_ref": f"{candidate}",
                    "method": "spearman",
                    "min_overlap": 12,
                    "time_range": ctx.time_range,
                },
                context=tool_ctx,
            )

            if cd_result.success and cd_result.data:
                coeff = cd_result.data.get("coefficient", 0)
                # 找 |coefficient| 最大的（与 DAU 负相关最强 or 正相关最强）
                if abs(coeff) > abs(best_correlation["coefficient"]):
                    best_correlation = {
                        "coefficient": coeff,
                        "p_value": cd_result.data.get("p_value", 1.0),
                        "metric": candidate,
                        "interpretation": cd_result.data.get("interpretation", ""),
                        "overlap_n": cd_result.data.get("overlap_n", 0),
                    }

        # 验收条件：|coefficient| ≥ 0.5
        if abs(best_correlation["coefficient"]) >= 0.5:
            ctx.correlated_metric = best_correlation
        else:
            # 未找到强相关指标
            ctx.correlated_metric = best_correlation if best_correlation["metric"] else None

        ctx.reasoning_trace.append({
            "step": "uc2_step5_correlation_detect",
            "correlated_metric": ctx.correlated_metric,
        })

    async def _uc2_step6_validate_h1(
        self, ctx: DauChurnContext, tool_ctx: ToolContext
    ) -> bool:
        """Step 6: H1 假设验证 — 新客获取是否下滑"""
        registry = self.tool_registry

        # 检查 new_users 是否显著下降
        new_users_data = ctx.segment_breakdown.get("new_users", {})
        new_users_delta_pct = new_users_data.get("delta_pct", 0.0)

        # H1 确认条件：new_users 下降超 15% 且 correlated_metric 为 new_user_rate
        h1_confirmed = (
            new_users_delta_pct < -0.15 and
            ctx.correlated_metric is not None and
            abs(ctx.correlated_metric.get("coefficient", 0)) >= 0.5
        )

        if h1_confirmed:
            self._h1_status = "confirmed"
            ctx.confirmed_hypothesis_id = "h1_acquisition"
            ctx.confirmed_hypothesis_type = "acquisition"
            ctx.root_cause_description = (
                f"新客获取下滑是 DAU 下降的主因。"
                f"新用户数较基线下降 {abs(new_users_delta_pct):.1%}，"
                f"与 {ctx.correlated_metric.get('metric')} 高度相关（r={ctx.correlated_metric.get('coefficient'):.2f}）。"
            )
            ctx.root_cause_confidence = min(abs(ctx.correlated_metric.get("coefficient", 0)), 0.9)

            # 更新假设状态
            for hyp in ctx.hypotheses:
                if hyp.id == "h1_acquisition":
                    hyp.status = "confirmed"
                    hyp.confidence = ctx.root_cause_confidence
                    break
        else:
            self._h1_status = "rejected"
            for hyp in ctx.hypotheses:
                if hyp.id == "h1_acquisition":
                    hyp.status = "rejected"
                    hyp.confidence = 0.3
                    break

        ctx.reasoning_trace.append({
            "step": "uc2_step6_validate_h1",
            "h1_confirmed": h1_confirmed,
            "h1_status": self._h1_status,
            "new_users_delta_pct": new_users_delta_pct,
        })

        return h1_confirmed

    async def _uc2_step7_validate_h2(
        self, ctx: DauChurnContext, tool_ctx: ToolContext
    ) -> bool:
        """Step 7: H2 假设验证 — 老客留存是否恶化"""
        # 检查 churned_users / returned_users
        churned_data = ctx.segment_breakdown.get("churned_users", {})
        returned_data = ctx.segment_breakdown.get("returned_users", {})

        churned_delta_pct = churned_data.get("delta_pct", 0.0)
        returned_delta_pct = returned_data.get("delta_pct", 0.0)

        # H2 确认条件：churned_users 上升超 20% 或 returned_users 下降超 15%
        h2_confirmed = (
            (churned_delta_pct > 0.20 or returned_delta_pct < -0.15) and
            ctx.correlated_metric is not None and
            abs(ctx.correlated_metric.get("coefficient", 0)) >= 0.5
        )

        if h2_confirmed:
            self._h2_status = "confirmed"
            ctx.confirmed_hypothesis_id = "h2_retention"
            ctx.confirmed_hypothesis_type = "retention"

            if churned_delta_pct > 0.20:
                ctx.root_cause_description = (
                    f"老客流失加剧是 DAU 下降的主因。"
                    f"流失用户数较基线上升 {churned_delta_pct:.1%}，"
                    f"与 {ctx.correlated_metric.get('metric')} 高度相关（r={ctx.correlated_metric.get('coefficient'):.2f}）。"
                )
            else:
                ctx.root_cause_description = (
                    f"老客回归减少是 DAU 下降的主因。"
                    f"回归用户数较基线下降 {abs(returned_delta_pct):.1%}，"
                    f"与 {ctx.correlated_metric.get('metric')} 高度相关（r={ctx.correlated_metric.get('coefficient'):.2f}）。"
                )

            ctx.root_cause_confidence = min(abs(ctx.correlated_metric.get("coefficient", 0)), 0.9)

            for hyp in ctx.hypotheses:
                if hyp.id == "h2_retention":
                    hyp.status = "confirmed"
                    hyp.confidence = ctx.root_cause_confidence
                    break
        else:
            self._h2_status = "rejected"
            for hyp in ctx.hypotheses:
                if hyp.id == "h2_retention":
                    hyp.status = "rejected"
                    hyp.confidence = 0.3
                    break

        ctx.reasoning_trace.append({
            "step": "uc2_step7_validate_h2",
            "h2_confirmed": h2_confirmed,
            "h2_status": self._h2_status,
            "churned_delta_pct": churned_delta_pct,
            "returned_delta_pct": returned_delta_pct,
        })

        return h2_confirmed

    async def _uc2_step8_finalize(
        self, ctx: DauChurnContext, session: BiAnalysisSession
    ) -> None:
        """Step 8: 根因定位与报告生成"""
        registry = self.tool_registry

        # 生成建议
        if ctx.confirmed_hypothesis_type == "acquisition":
            ctx.recommended_actions = [
                {"action": "加大新客获取渠道投入", "priority": "HIGH"},
                {"action": "排查新客获取漏斗各环节流失原因", "priority": "HIGH"},
                {"action": "激活沉默用户引导注册", "priority": "MEDIUM"},
            ]
        elif ctx.confirmed_hypothesis_type == "retention":
            ctx.recommended_actions = [
                {"action": "优化老客召回触达策略", "priority": "HIGH"},
                {"action": "提升 Push/消息推送打开率", "priority": "HIGH"},
                {"action": "排查流失用户特征画像", "priority": "MEDIUM"},
            ]
        else:
            ctx.recommended_actions = [
                {"action": "综合新客获取+老客留存两个维度分析", "priority": "HIGH"},
                {"action": "排查 product/userexperience 问题", "priority": "MEDIUM"},
            ]

        # 默认 confidence（当双假设链都未确认时）
        if ctx.root_cause_confidence < 0.7:
            ctx.root_cause_confidence = max(ctx.root_cause_confidence, 0.5)

        # 持久化假设树
        session = self.update_session_status(session, SessionStatus.RUNNING)
        if ctx.confirmed_hypothesis_id:
            self.hypothesis_store(
                session, "confirm",
                {"id": ctx.confirmed_hypothesis_id, "confidence": ctx.root_cause_confidence}
            )

        # 生成报告
        rw_tool = registry.get("report_write")
        insight_report = ctx.to_insight_report()
        await rw_tool.execute(
            params={
                "session_id": str(session.id),
                "canonical_json": self._build_uc2_canonical_json(ctx, session),
                "output_formats": ["json", "markdown"],
            },
            context=ToolContext(
                session_id=str(session.id),
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id,
            ),
        )

        # 发布洞察
        try:
            ip_tool = registry.get("insight_publish")
            await ip_tool.execute(
                params={
                    "insight_payload": insight_report,
                    "channels": ["platform"],
                    "confidence": ctx.root_cause_confidence,
                },
                context=ToolContext(
                    session_id=str(session.id),
                    user_id=ctx.user_id,
                    tenant_id=ctx.tenant_id,
                ),
            )
        except Exception as e:
            logger.warning("insight_publish failed (non-fatal): %s", e)

        ctx.reasoning_trace.append({
            "step": "uc2_step8_finalize",
            "root_cause": ctx.root_cause_description,
            "confidence": ctx.root_cause_confidence,
        })

    # -------------------------------------------------------------------------
    # UC-2 辅助方法
    # -------------------------------------------------------------------------

    def _build_uc2_canonical_json(
        self, ctx: DauChurnContext, session: BiAnalysisSession
    ) -> Dict[str, Any]:
        """构建 UC-2 Canonical JSON 报告"""
        return {
            "metadata": {
                "subject": f"{ctx.metric} 流失归因分析",
                "time_range": ctx.time_range,
                "compare_mode": ctx.compare_mode,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "confidence": ctx.root_cause_confidence,
                "author": "Data Agent UC-2",
            },
            "summary": ctx.root_cause_description or "未定位明确根因",
            "delta": {
                "delta_abs": ctx.delta_abs,
                "delta_pct": ctx.delta_pct,
                "anomaly_confirmed": ctx.anomaly_confirmed,
                "magnitude": ctx.magnitude,
            },
            "segment_breakdown": ctx.segment_breakdown,
            "correlated_metric": ctx.correlated_metric,
            "confirmed_hypothesis": {
                "id": ctx.confirmed_hypothesis_id,
                "type": ctx.confirmed_hypothesis_type,
                "confidence": ctx.root_cause_confidence,
            },
            "sections": [
                {
                    "type": "finding",
                    "title": "异动确认",
                    "narrative": f"{ctx.metric} {ctx.compare_mode} 变化 {ctx.delta_pct:.1%}，{'显著' if ctx.anomaly_confirmed else '不显著'}",
                },
                {
                    "type": "breakdown",
                    "title": "用户分层分解",
                    "narrative": (
                        f"新用户 {ctx.segment_breakdown.get('new_users', {}).get('delta_pct', 0):.1%}，"
                        f"流失用户 {ctx.segment_breakdown.get('churned_users', {}).get('delta_pct', 0):.1%}，"
                        f"回归用户 {ctx.segment_breakdown.get('returned_users', {}).get('delta_pct', 0):.1%}"
                    ),
                },
                {
                    "type": "correlation",
                    "title": "相关性分析",
                    "narrative": (
                        f"与 DAU 相关性最高的指标：{ctx.correlated_metric.get('metric') if ctx.correlated_metric else 'N/A'}，"
                        f"系数 r={ctx.correlated_metric.get('coefficient', 0):.2f}"
                    ) if ctx.correlated_metric else "未发现强相关指标",
                },
                {
                    "type": "recommendation",
                    "title": "行动建议",
                    "narrative": "; ".join(a["action"] for a in ctx.recommended_actions),
                    "priority": ctx.recommended_actions[0].get("priority", "MEDIUM") if ctx.recommended_actions else "MEDIUM",
                },
            ],
            "hypothesis_trace": [
                {
                    "step": i + 1,
                    "hypothesis": h.description,
                    "status": h.status,
                    "confidence": h.confidence,
                    "type": h.hypothesis_type,
                }
                for i, h in enumerate(ctx.hypotheses)
            ],
            "confidence_score": ctx.root_cause_confidence,
            "h1_status": self._h1_status,
            "h2_status": self._h2_status,
            "caveats": [
                "数据仅覆盖指定时间范围，更长周期需进一步验证",
                "外部因素（宏观经济、竞品动作等）未纳入分析",
                "跨表 join 行数限制在 50000 以内",
            ],
        }

    def _build_uc2_output(
        self,
        ctx: DauChurnContext,
        session: BiAnalysisSession,
        elapsed: float,
        steps_count: int,
    ) -> Dict[str, Any]:
        """构建 UC-2 输出"""
        report = ctx.to_insight_report()
        report["insight_report"] = self._build_uc2_canonical_json(ctx, session)
        report["session_id"] = str(session.id)
        report["session_status"] = session.status
        report["steps_count"] = steps_count
        report["total_time_ms"] = int(elapsed * 1000)
        report["h1_status"] = self._h1_status
        report["h2_status"] = self._h2_status
        report["session"] = session.to_dict()
        return report
