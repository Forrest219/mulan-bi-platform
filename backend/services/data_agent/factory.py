"""Data Agent Factory — reusable engine construction

Extracts setup logic from app/api/agent.py into a pure-service helper.
No web framework dependency: only SQLAlchemy + pure Python.
"""

from typing import Tuple

from .engine import ReActEngine
from .tool_base import ToolRegistry


def create_engine() -> Tuple[ReActEngine, ToolRegistry]:
    """Build a fully-configured ReActEngine with all standard tools.

    Returns:
        (engine, registry) tuple.  The registry is returned so callers
        can inspect registered tools if needed.
    """
    from .tools.query_tool import QueryTool
    from .tools.schema_tool import SchemaTool
    from .tools.metrics_tool import MetricsTool
    from services.llm.service import LLMService

    registry = ToolRegistry()
    registry.register(QueryTool())
    registry.register(SchemaTool())
    registry.register(MetricsTool())

    llm_service = LLMService()
    engine = ReActEngine(registry=registry, llm_service=llm_service)

    return engine, registry
