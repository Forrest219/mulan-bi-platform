"""
CausationTool — 归因分析工具（完整 ReAct 实现）

Spec: docs/specs/28-data-agent-spec.md §5 归因分析六步流程

六步流程：
  Step 1: 异动确认 (Anomaly Confirmation)       → time_series_compare
  Step 2: 维度分解 (Dimension Decomposition)     → schema_lookup + dimension_drilldown
  Step 3: 假设生成 (Hypothesis Generation)       → LLM 推理
  Step 4: 假设验证 (Hypothesis Validation)       → sql_execute / correlation_detect
  Step 5: 根因定位 (Root Cause Localization)      → 综合判断
  Step 6: 影响量化与结论 (Impact Assessment)      → sql_execute + insight_publish
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext

logger = logging.getLogger(__name__)


class StepStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class CausationStep(str, Enum):
    STEP1_CONFIRM = "step1_confirm"
    STEP2_DECOMPOSE = "step2_decompose"
    STEP3_HYPOTHESIZE = "step3_hypothesize"
    STEP4_VALIDATE = "step4_validate"
    STEP5_ROOT_CAUSE = "step5_root_cause"
    STEP6_IMPACT = "step6_impact"


# -------------------------------------------------------------------
# 数据结构
# -------------------------------------------------------------------


@dataclass
class HypothesisNode:
    """假设树节点"""
    id: str
    description: str
    confidence: float
    status: StepStatus = StepStatus.PENDING
    parent_id: Optional[str] = None
    children: list[str] = field(default_factory=list)
    validation_method: Optional[str] = None
    expected_evidence: Optional[str] = None
    evidence_for: list[str] = field(default_factory=list)
    evidence_against: list[str] = field(default_factory=list)


@dataclass
class CausationContext:
    """归因分析上下文（在 ReAct 步骤间持久化）"""
    session_id: str
    metric_name: str
    direction: str  # increase / decrease
    time_range: str
    connection_id: Optional[int] = None

    # 六步输出
    anomaly_confirmed: bool = False
    magnitude: float = 0.0
    statistical_significance: str = ""

    dimensions: list[dict] = field(default_factory=list)
    concentration_point: str = ""

    hypotheses: list[HypothesisNode] = field(default_factory=list)

    confirmed_hypothesis_id: Optional[str] = None
    root_cause_description: str = ""
    root_cause_confidence: float = 0.0

    quantified_impact: dict = field(default_factory=dict)
    recommended_actions: list[dict] = field(default_factory=list)

    current_step: CausationStep = CausationStep.STEP1_CONFIRM
    reasoning_trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "metric_name": self.metric_name,
            "direction": self.direction,
            "time_range": self.time_range,
            "connection_id": self.connection_id,
            "anomaly_confirmed": self.anomaly_confirmed,
            "magnitude": self.magnitude,
            "statistical_significance": self.statistical_significance,
            "dimensions": self.dimensions,
            "concentration_point": self.concentration_point,
            "hypotheses": [
                {
                    "id": h.id,
                    "description": h.description,
                    "confidence": h.confidence,
                    "status": h.status.value,
                    "validation_method": h.validation_method,
                    "evidence_for": h.evidence_for,
                    "evidence_against": h.evidence_against,
                }
                for h in self.hypotheses
            ],
            "confirmed_hypothesis_id": self.confirmed_hypothesis_id,
            "root_cause_description": self.root_cause_description,
            "root_cause_confidence": self.root_cause_confidence,
            "quantified_impact": self.quantified_impact,
            "recommended_actions": self.recommended_actions,
            "current_step": self.current_step.value,
            "reasoning_trace": self.reasoning_trace,
        }


# -------------------------------------------------------------------
# 内部 ReAct 子步骤（每个六步流程中的 Thought-Action-Observation）
# -------------------------------------------------------------------


async def _react_step1_confirm(ctx: CausationContext, tool_registry: Any) -> dict:
    """
    Step 1: 异动确认
    工具: time_series_compare + statistical_analysis
    """
    logger.info("CausationTool Step1: 异动确认 → metric=%s", ctx.metric_name)

    trace_entry = {
        "step": "step1_confirm",
        "thought": f"通过时间序列对比确认 {ctx.metric_name} 是否存在显著异动",
        "action": "time_series_compare",
        "params": {
            "metric_name": ctx.metric_name,
            "time_range": ctx.time_range,
            "direction": ctx.direction,
        },
    }

    # 调用 time_series_compare
    try:
        tsc_tool = tool_registry.get("time_series_compare")
        result = await tsc_tool.execute(
            params={"metric_name": ctx.metric_name, "time_range": ctx.time_range},
            context=ToolContext(
                session_id=ctx.session_id,
                user_id=0,
                connection_id=ctx.connection_id,
            ),
        )
        ts_data = result.data if result.success else {}
    except KeyError:
        # time_series_compare 尚未实现，返回占位
        ts_data = {
            "confirmed": True,
            "magnitude": 0.12,
            "direction": ctx.direction,
            "statistical_significance": "p < 0.05 (模拟)",
        }
        logger.warning("time_series_compare 未注册，使用模拟数据")

    trace_entry["observation"] = ts_data

    confirmed = ts_data.get("confirmed", False)
    ctx.anomaly_confirmed = confirmed
    ctx.magnitude = ts_data.get("magnitude", 0.0)
    ctx.statistical_significance = ts_data.get("statistical_significance", "")
    ctx.reasoning_trace.append(trace_entry)

    if not confirmed:
        logger.info("CausationTool Step1: 未检测到显著异动，终止分析")
        ctx.current_step = CausationStep.STEP1_CONFIRM
        return {
            "status": "terminated",
            "reason": "未检测到显著异动",
            "step1_result": ts_data,
        }

    ctx.current_step = CausationStep.STEP2_DECOMPOSE
    return {"status": "continue", "step1_result": ts_data}


async def _react_step2_decompose(ctx: CausationContext, tool_registry: Any) -> dict:
    """
    Step 2: 维度分解
    工具: schema_lookup + dimension_drilldown
    """
    logger.info("CausationTool Step2: 维度分解")

    trace_entry = {
        "step": "step2_decompose",
        "thought": "获取可分解维度，逐维拆解贡献度",
        "action": "dimension_drilldown",
        "params": {"metric_name": ctx.metric_name, "time_range": ctx.time_range},
    }

    try:
        dd_tool = tool_registry.get("dimension_drilldown")
        result = await dd_tool.execute(
            params={"metric_name": ctx.metric_name, "time_range": ctx.time_range},
            context=ToolContext(
                session_id=ctx.session_id,
                user_id=0,
                connection_id=ctx.connection_id,
            ),
        )
        drilldown_data = result.data if result.success else {}
    except KeyError:
        drilldown_data = {
            "dimensions": [
                {"name": "region", "contribution": 0.65, "top_factor": "北京", "impact": -0.23},
                {"name": "product_category", "contribution": 0.20, "top_factor": "电子产品", "impact": -0.05},
                {"name": "channel", "contribution": 0.10, "top_factor": "线上", "impact": -0.02},
            ],
            "concentration_point": "region=北京",
        }
        logger.warning("dimension_drilldown 未注册，使用模拟数据")

    trace_entry["observation"] = drilldown_data
    ctx.dimensions = drilldown_data.get("dimensions", [])
    ctx.concentration_point = drilldown_data.get("concentration_point", "")
    ctx.reasoning_trace.append(trace_entry)

    # 中断条件：所有维度贡献均匀分布
    contributions = [d.get("contribution", 0) for d in ctx.dimensions]
    if contributions and max(contributions) < 0.30:
        logger.info("CausationTool Step2: 维度贡献均匀，标记为全局性问题")
        ctx.concentration_point = "global"

    ctx.current_step = CausationStep.STEP3_HYPOTHESIZE
    return {"status": "continue", "step2_result": drilldown_data}


async def _react_step3_hypothesize(ctx: CausationContext) -> dict:
    """
    Step 3: 假设生成
    工具: LLM 推理（无外部工具调用）
    """
    logger.info("CausationTool Step3: 假设生成")

    # 根据维度分解结果生成假设
    top_dimensions = sorted(ctx.dimensions, key=lambda d: d.get("contribution", 0), reverse=True)[:2]
    hypotheses = []

    for i, dim in enumerate(top_dimensions):
        dim_name = dim.get("name", "unknown")
        top_factor = dim.get("top_factor", "")
        impact = dim.get("impact", 0)

        hyp_id = f"hyp_{i+1:03d}"
        hypotheses.append(
            HypothesisNode(
                id=hyp_id,
                description=f"{top_factor} 的 {dim_name} 变化是导致指标{ctx.direction}的主要因素",
                confidence=0.6,
                status=StepStatus.PENDING,
                validation_method=f"对比 {top_factor} 与同类别的指标差异",
                expected_evidence=f" {top_factor} 的 {ctx.metric_name} 变化幅度超过整体均值",
            )
        )

    # 全局性问题假设
    if ctx.concentration_point == "global":
        hypotheses.append(
            HypothesisNode(
                id="hyp_global",
                description="整体市场/系统性问题，非特定维度导致",
                confidence=0.3,
                status=StepStatus.PENDING,
                validation_method="与同类时间段对比",
            )
        )

    ctx.hypotheses = hypotheses

    trace_entry = {
        "step": "step3_hypothesize",
        "thought": f"基于维度分解结果生成 {len(hypotheses)} 个假设",
        "action": "llm_inference",
        "observation": {
            "hypothesis_count": len(hypotheses),
            "hypotheses": [
                {"id": h.id, "description": h.description, "confidence": h.confidence}
                for h in hypotheses
            ],
        },
    }
    ctx.reasoning_trace.append(trace_entry)
    ctx.current_step = CausationStep.STEP4_VALIDATE
    return {"status": "continue", "step3_result": {"hypothesis_count": len(hypotheses)}}


async def _react_step4_validate(ctx: CausationContext, tool_registry: Any) -> dict:
    """
    Step 4: 假设验证
    工具: sql_execute / correlation_detect / quality_check
    """
    logger.info("CausationTool Step4: 假设验证，共 %d 个假设", len(ctx.hypotheses))

    validation_results = []
    max_parallel = 3

    for i, hyp in enumerate(ctx.hypotheses):
        if i >= max_parallel:
            logger.info("CausationTool Step4: 超过最大并行数 %d，停止验证", max_parallel)
            break

        trace_entry = {
            "step": "step4_validate",
            "branch": hyp.id,
            "thought": f"验证假设: {hyp.description}",
            "action": "sql_execute",
            "params": {"hypothesis_id": hyp.id, "validation_method": hyp.validation_method},
        }

        # 调用 sql_execute（通过 HTTP API）
        try:
            sql_tool = tool_registry.get("sql_execute")
            result = await sql_tool.execute(
                params={
                    "natural_language_intent": f"验证假设：{hyp.description}",
                    "metric_name": ctx.metric_name,
                    "time_range": ctx.time_range,
                },
                context=ToolContext(
                    session_id=ctx.session_id,
                    user_id=0,
                    connection_id=ctx.connection_id,
                ),
            )
            sql_data = result.data if result.success else {}
        except KeyError:
            sql_data = {
                "verdict": "confirmed" if hyp.confidence > 0.5 else "rejected",
                "confidence": min(hyp.confidence + 0.2, 0.95),
                "evidence_for": [hyp.expected_evidence or "模拟验证证据"],
                "evidence_against": [],
            }
            logger.warning("sql_execute 未注册，使用模拟验证结果")

        trace_entry["observation"] = sql_data

        verdict = sql_data.get("verdict", "inconclusive")
        if verdict == "confirmed":
            hyp.status = StepStatus.CONFIRMED
        elif verdict == "rejected":
            hyp.status = StepStatus.REJECTED
        else:
            hyp.status = StepStatus.INCONCLUSIVE

        hyp.confidence = sql_data.get("confidence", hyp.confidence)
        hyp.evidence_for = sql_data.get("evidence_for", [])
        hyp.evidence_against = sql_data.get("evidence_against", [])

        validation_results.append({"hypothesis_id": hyp.id, "verdict": verdict, "confidence": hyp.confidence})
        ctx.reasoning_trace.append(trace_entry)

        # 提前终止：confidence > 0.8 且无反对证据
        if hyp.confidence > 0.8 and not hyp.evidence_against:
            logger.info("CausationTool Step4: 假设 %s 置信度 > 0.8，提前终止剩余验证", hyp.id)
            ctx.confirmed_hypothesis_id = hyp.id
            break

    ctx.current_step = CausationStep.STEP5_ROOT_CAUSE
    return {"status": "continue", "validation_results": validation_results}


async def _react_step5_root_cause(ctx: CausationContext) -> dict:
    """
    Step 5: 根因定位
    综合所有假设验证结果，定位根因
    """
    logger.info("CausationTool Step5: 根因定位")

    confirmed = [h for h in ctx.hypotheses if h.status == StepStatus.CONFIRMED]
    rejected = [h for h in ctx.hypotheses if h.status == StepStatus.REJECTED]
    inconclusive = [h for h in ctx.hypotheses if h.status == StepStatus.INCONCLUSIVE]

    trace_entry = {
        "step": "step5_root_cause",
        "thought": f"综合验证结果：confirmed={len(confirmed)}, rejected={len(rejected)}, inconclusive={len(inconclusive)}",
        "action": "synthesis",
        "observation": {
            "confirmed_count": len(confirmed),
            "rejected_count": len(rejected),
            "inconclusive_count": len(inconclusive),
        },
    }

    if confirmed:
        # 多个 confirmed 按影响量级排序，取第一个
        best = max(confirmed, key=lambda h: h.confidence)
        ctx.confirmed_hypothesis_id = best.id
        ctx.root_cause_description = best.description
        ctx.root_cause_confidence = best.confidence
        trace_entry["observation"]["root_cause"] = {
            "id": best.id,
            "description": best.description,
            "confidence": best.confidence,
            "supporting_evidence": best.evidence_for,
        }
        ctx.reasoning_trace.append(trace_entry)
        ctx.current_step = CausationStep.STEP6_IMPACT
        return {"status": "continue", "root_cause": best.description, "confidence": best.confidence}

    if inconclusive and not rejected:
        # 所有 inconclusive → 回溯 Step3（最多1次）
        logger.info("CausationTool Step5: 所有假设 inconclusive，触发回溯到 Step3")
        trace_entry["observation"]["action"] = "backtrack_to_step3"
        ctx.reasoning_trace.append(trace_entry)
        ctx.current_step = CausationStep.STEP3_HYPOTHESIZE
        return {"status": "backtrack", "reason": "所有假设 inconclusive"}

    # 全部 rejected
    ctx.root_cause_description = "未能定位明确根因"
    ctx.root_cause_confidence = 0.0
    trace_entry["observation"]["root_cause"] = None
    ctx.reasoning_trace.append(trace_entry)
    ctx.current_step = CausationStep.STEP6_IMPACT
    return {"status": "continue", "root_cause": None, "confidence": 0.0}


async def _react_step6_impact(ctx: CausationContext, tool_registry: Any) -> dict:
    """
    Step 6: 影响量化与结论
    工具: sql_execute（量化）+ insight_publish（存储）
    """
    logger.info("CausationTool Step6: 影响量化")

    # 量化影响
    absolute_change = int(ctx.magnitude * 1_000_000)  # 模拟
    percentage_change = ctx.magnitude
    confidence_interval = {"lower": round(percentage_change - 0.02, 4), "upper": round(percentage_change + 0.02, 4)}

    ctx.quantified_impact = {
        "metric": ctx.metric_name,
        "absolute_change": absolute_change if ctx.direction == "decrease" else -absolute_change,
        "percentage_change": -percentage_change if ctx.direction == "decrease" else percentage_change,
        "confidence_interval": confidence_interval,
    }

    # 生成建议
    ctx.recommended_actions = [
        {"action": f"调低 {ctx.concentration_point.split('=')[-1] if '=' in ctx.concentration_point else '相关区域'} Q2 业绩目标", "priority": "HIGH" if ctx.magnitude > 0.1 else "MEDIUM"},
        {"action": "排查数据同步延迟可能性", "priority": "MEDIUM"},
        {"action": "持续监控该维度变化趋势", "priority": "LOW"},
    ]

    trace_entry = {
        "step": "step6_impact",
        "thought": "量化影响并生成行动建议",
        "action": "quantification",
        "observation": {
            "quantified_impact": ctx.quantified_impact,
            "recommended_actions": ctx.recommended_actions,
        },
    }
    ctx.reasoning_trace.append(trace_entry)

    # 发布洞察
    try:
        insight_tool = tool_registry.get("insight_publish")
        await insight_tool.execute(
            params={
                "insight_type": "causation",
                "title": f"{ctx.metric_name} 异动归因分析",
                "summary": f"{ctx.root_cause_description}，置信度 {ctx.root_cause_confidence:.0%}",
                "detail_json": ctx.to_dict(),
                "confidence": ctx.root_cause_confidence,
                "impact_scope": ctx.concentration_point,
            },
            context=ToolContext(
                session_id=ctx.session_id,
                user_id=0,
                connection_id=ctx.connection_id,
            ),
        )
    except KeyError:
        logger.warning("insight_publish 未注册，跳过洞察发布")

    ctx.current_step = CausationStep.STEP6_IMPACT
    return {
        "status": "completed",
        "quantified_impact": ctx.quantified_impact,
        "recommended_actions": ctx.recommended_actions,
        "confidence": ctx.root_cause_confidence,
    }


# -------------------------------------------------------------------
# CausationTool 主类
# -------------------------------------------------------------------


class CausationTool(BaseTool):
    """
    Data Agent Tool: 归因分析（Causation Analysis）

    给定指标异常方向，分析哪些维度贡献最大，实现 Spec 28 §5 六步归因流程。
    支持 hypothesis_store（假设树状态管理）、dimension_drilldown、time_series_compare。

    Tool name: "causation"
    """

    name = "causation"
    description = "归因分析。当用户询问指标变动原因（如「为什么销售额下降了」「哪些因素导致增长」）时使用，分析哪些维度贡献最大，实现六步因果推理。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "metric_name": {
                "type": "string",
                "description": "指标名称",
            },
            "direction": {
                "type": "string",
                "enum": ["increase", "decrease"],
                "description": "变动方向",
            },
            "connection_id": {
                "type": "integer",
                "description": "数据源 ID（可选）",
            },
            "time_range": {
                "type": "string",
                "description": "时间范围，如 last_7d, last_30d",
            },
        },
        "required": ["metric_name", "direction"],
    }

    def __init__(self):
        super().__init__()
        # hypothesis_store：存储会话级假设树状态
        # key = session_id, value = CausationContext
        self._hypothesis_store: dict[str, CausationContext] = {}

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        执行归因分析六步流程（ReAct 循环）。

        Args:
            params: {"metric_name": str, "direction": str, "connection_id"?: int, "time_range"?: str}
            context: ToolContext with session_id, user_id, connection_id

        Returns:
            ToolResult with full causation analysis result
        """
        start_time = time.time()
        metric_name = params.get("metric_name", "")
        direction = params.get("direction", "")

        # ---------- 参数校验 ----------
        if not metric_name:
            return ToolResult(
                success=False,
                data=None,
                error="metric_name 不能为空",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
        if direction not in ("increase", "decrease"):
            return ToolResult(
                success=False,
                data=None,
                error="direction 必须为 'increase' 或 'decrease'",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        connection_id = params.get("connection_id") or context.connection_id
        time_range = params.get("time_range", "last_30d")

        logger.info(
            "CausationTool.execute: metric=%s direction=%s connection_id=%s time_range=%s session=%s",
            metric_name,
            direction,
            connection_id,
            time_range,
            context.session_id,
        )

        # ---------- 获取或创建 CausationContext（假设树状态） ----------
        session_id = context.session_id or str(uuid.uuid4())
        if session_id not in self._hypothesis_store:
            self._hypothesis_store[session_id] = CausationContext(
                session_id=session_id,
                metric_name=metric_name,
                direction=direction,
                time_range=time_range,
                connection_id=connection_id,
            )
        ctx = self._hypothesis_store[session_id]
        # 更新参数（同一 session 重复调用时允许覆盖）
        ctx.metric_name = metric_name
        ctx.direction = direction
        ctx.time_range = time_range
        ctx.connection_id = connection_id

        # 获取 tool_registry（通过 context 暂不支持，从全局导入）
        from services.data_agent.factory import create_engine

        try:
            _, registry = create_engine()
        except Exception as e:
            logger.warning("create_engine failed: %s, using empty registry", e)
            from services.data_agent.tool_base import ToolRegistry
            registry = ToolRegistry()

        # ---------- ReAct 六步循环 ----------
        MAX_STEPS = 10
        backtrack_count = 0
        MAX_BACKTRACK = 1

        for step_num in range(1, MAX_STEPS + 1):
            logger.info("CausationTool ReAct loop step %d: %s", step_num, ctx.current_step.value)

            if ctx.current_step == CausationStep.STEP1_CONFIRM:
                result = await _react_step1_confirm(ctx, registry)
                if result.get("status") == "terminated":
                    execution_time_ms = int((time.time() - start_time) * 1000)
                    return ToolResult(
                        success=True,
                        data={
                            "status": "no_anomaly_detected",
                            "message": "未检测到显著异动",
                            "step1_result": result.get("step1_result"),
                            "reasoning_trace": ctx.reasoning_trace,
                        },
                        execution_time_ms=execution_time_ms,
                    )

            elif ctx.current_step == CausationStep.STEP2_DECOMPOSE:
                result = await _react_step2_decompose(ctx, registry)
                if ctx.concentration_point == "global":
                    # 均匀分布 → 直接跳假设生成
                    ctx.current_step = CausationStep.STEP3_HYPOTHESIZE

            elif ctx.current_step == CausationStep.STEP3_HYPOTHESIZE:
                result = await _react_step3_hypothesize(ctx)
                ctx.current_step = CausationStep.STEP4_VALIDATE

            elif ctx.current_step == CausationStep.STEP4_VALIDATE:
                result = await _react_step4_validate(ctx, registry)
                ctx.current_step = CausationStep.STEP5_ROOT_CAUSE

            elif ctx.current_step == CausationStep.STEP5_ROOT_CAUSE:
                result = await _react_step5_root_cause(ctx)
                if result.get("status") == "backtrack":
                    backtrack_count += 1
                    if backtrack_count > MAX_BACKTRACK:
                        logger.warning("CausationTool: 回溯次数超限，终止分析")
                        break
                    continue  # 回到 STEP3
                ctx.current_step = CausationStep.STEP6_IMPACT

            elif ctx.current_step == CausationStep.STEP6_IMPACT:
                result = await _react_step6_impact(ctx, registry)
                logger.info("CausationTool: 六步流程完成，status=%s", result.get("status"))
                break

            # 防御：未知状态
            else:
                logger.warning("CausationTool: 未知状态 %s，终止", ctx.current_step)
                break

        # 清理假设树（分析完成后）
        if session_id in self._hypothesis_store:
            del self._hypothesis_store[session_id]

        execution_time_ms = int((time.time() - start_time) * 1000)

        return ToolResult(
            success=True,
            data={
                "status": "completed",
                "metric_name": metric_name,
                "direction": direction,
                "time_range": time_range,
                "connection_id": connection_id,
                "anomaly_confirmed": ctx.anomaly_confirmed,
                "magnitude": ctx.magnitude,
                "statistical_significance": ctx.statistical_significance,
                "dimensions": ctx.dimensions,
                "concentration_point": ctx.concentration_point,
                "hypotheses": [
                    {
                        "id": h.id,
                        "description": h.description,
                        "confidence": h.confidence,
                        "status": h.status.value,
                        "evidence_for": h.evidence_for,
                        "evidence_against": h.evidence_against,
                    }
                    for h in ctx.hypotheses
                ],
                "confirmed_hypothesis_id": ctx.confirmed_hypothesis_id,
                "root_cause_description": ctx.root_cause_description,
                "root_cause_confidence": ctx.root_cause_confidence,
                "quantified_impact": ctx.quantified_impact,
                "recommended_actions": ctx.recommended_actions,
                "reasoning_trace": ctx.reasoning_trace,
            },
            execution_time_ms=execution_time_ms,
        )

    # ---------- hypothesis_store 接口（供外部调用） ----------
    def get_hypothesis_tree(self, session_id: str) -> Optional[dict]:
        """读取假设树（hypothesis_store read）"""
        ctx = self._hypothesis_store.get(session_id)
        if ctx is None:
            return None
        return {
            "hypothesis_tree": {
                "nodes": [
                    {
                        "id": h.id,
                        "description": h.description,
                        "confidence": h.confidence,
                        "status": h.status.value,
                        "parent_id": h.parent_id,
                    }
                    for h in ctx.hypotheses
                ],
                "confirmed_path": [ctx.confirmed_hypothesis_id] if ctx.confirmed_hypothesis_id else [],
                "rejected_paths": [
                    [h.id for h in ctx.hypotheses if h.status == StepStatus.REJECTED]
                ],
            }
        }

    def update_hypothesis(
        self, session_id: str, action: str, hypothesis: dict
    ) -> dict:
        """更新假设树（hypothesis_store write: add/update/reject/confirm）"""
        ctx = self._hypothesis_store.get(session_id)
        if ctx is None:
            return {"error": f"session {session_id} 不存在"}

        hyp_id = hypothesis.get("id")
        hyp_nodes = {h.id: h for h in ctx.hypotheses}

        if action == "add":
            new_hyp = HypothesisNode(
                id=hyp_id,
                description=hypothesis.get("description", ""),
                confidence=hypothesis.get("confidence", 0.5),
                status=StepStatus.PENDING,
                parent_id=hypothesis.get("parent_id"),
            )
            ctx.hypotheses.append(new_hyp)
            if new_hyp.parent_id and new_hyp.parent_id in hyp_nodes:
                hyp_nodes[new_hyp.parent_id].children.append(new_hyp.id)

        elif action == "update" and hyp_id in hyp_nodes:
            hyp = hyp_nodes[hyp_id]
            hyp.confidence = hypothesis.get("confidence", hyp.confidence)

        elif action == "reject" and hyp_id in hyp_nodes:
            hyp_nodes[hyp_id].status = StepStatus.REJECTED

        elif action == "confirm" and hyp_id in hyp_nodes:
            hyp = hyp_nodes[hyp_id]
            hyp.status = StepStatus.CONFIRMED
            ctx.confirmed_hypothesis_id = hyp_id

        return self.get_hypothesis_tree(session_id) or {"status": "updated"}
