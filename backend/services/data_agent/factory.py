"""Data Agent Factory — reusable engine construction

Extracts setup logic from app/api/agent.py into a pure-service helper.
No web framework dependency: only SQLAlchemy + pure Python.
"""

from typing import Tuple

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
