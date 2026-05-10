"""Data Agent Factory — reusable engine construction

Extracts setup logic from app/api/agent.py into a pure-service helper.
No web framework dependency: only SQLAlchemy + pure Python.
"""

from typing import Any, Tuple

from .engine import ReActEngine
from .tool_base import ToolRegistry


def create_engine() -> Tuple[ReActEngine, ToolRegistry]:
    """Build a fully-configured ReActEngine with all 14 standard tools.

    Returns:
        (engine, registry) tuple.  The registry is returned so callers
        can inspect registered tools if needed.
    """
    from .tools.query_tool import QueryTool
    from .tools.schema_tool import SchemaTool
    from .tools.metrics_tool import MetricsTool
    from .tools.causation_tool import CausationTool
    from .tools.chart_tool import ChartTool
    from .tools.report_generation_tool import ReportGenerationTool
    from .tools.proactive_insight_tool import ProactiveInsightTool
    from .tools.data_comparison_tool import DataComparisonTool
    from .tools.trend_analysis_tool import TrendAnalysisTool
    from .tools.correlation_discovery_tool import CorrelationDiscoveryTool
    from .tools.segmentation_analysis_tool import SegmentationAnalysisTool
    from .tools.funnel_analysis_tool import FunnelAnalysisTool
    from .tools.cohort_analysis_tool import CohortAnalysisTool
    from .tools.root_cause_analysis_tool import RootCauseAnalysisTool
    from services.llm.service import LLMService
    from services.capability import CapabilityWrapper

    registry = ToolRegistry()
    registry.register(QueryTool())
    registry.register(SchemaTool())
    registry.register(MetricsTool())
    registry.register(CausationTool())
    registry.register(ChartTool())
    registry.register(ReportGenerationTool())
    registry.register(ProactiveInsightTool())
    registry.register(DataComparisonTool())
    registry.register(TrendAnalysisTool())
    registry.register(CorrelationDiscoveryTool())
    registry.register(SegmentationAnalysisTool())
    registry.register(FunnelAnalysisTool())
    registry.register(CohortAnalysisTool())
    registry.register(RootCauseAnalysisTool())

    llm_service = LLMService()
    wrapper = CapabilityWrapper()
    engine = ReActEngine(registry=registry, llm_service=llm_service, wrapper=wrapper)

    return engine, registry


async def create_engine_with_skills(db: Any) -> Tuple[ReActEngine, ToolRegistry]:
    """Build a fully-configured ReActEngine and overlay DB skill meta overrides.

    This async variant extends create_engine() by loading active skill versions
    from the database via SkillLoader, so the LLM sees the DB-managed
    descriptions and parameter schemas rather than the static class attributes.

    Gracefully degrades when:
    - the skills module is not yet installed (ImportError in SkillLoader)
    - the DB tables don't exist yet (exception in SkillLoader.load_and_override)

    Args:
        db: SQLAlchemy Session — the caller's synchronous DB session.

    Returns:
        (engine, registry) tuple where engine._active_skill_versions reflects
        DB overrides (or empty dict on graceful degradation).
    """
    from .skill_loader import SkillLoader

    engine, registry = create_engine()

    # 动态加载 DB 技能 meta 覆盖静态工具描述
    _loader = SkillLoader()
    _active_skill_versions = await _loader.load_and_override(registry, db)

    # 将版本映射写回 engine，供工具执行后记录步骤版本
    engine._active_skill_versions = _active_skill_versions

    return engine, registry
