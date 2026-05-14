"""Base contract for Data Agent semantic operators."""

from __future__ import annotations

from typing import Any, Protocol

from services.data_agent.query_plan import OperatorResult, QueryPlanContext, QueryPlanStep, ResultShape


class SemanticOperator(Protocol):
    name: str
    version: str
    output_shape: ResultShape

    def match(self, ctx: QueryPlanContext) -> float:
        """Return confidence 0..1. Registry selects the highest above threshold."""

    def build_steps(self, ctx: QueryPlanContext) -> list[QueryPlanStep]:
        """Build Tableau VizQL steps with aggregation/filter/sort pushed down."""

    def reduce(self, ctx: QueryPlanContext, step_results: dict[str, dict[str, Any]]) -> OperatorResult:
        """Convert pushed-down step results into a deterministic structured result."""


class BaseSemanticOperator:
    name = "base"
    version = "0.1.0"
    output_shape: ResultShape = "operator_summary"

    def match(self, ctx: QueryPlanContext) -> float:
        return 0.0

    def build_steps(self, ctx: QueryPlanContext) -> list[QueryPlanStep]:
        raise NotImplementedError

    def reduce(self, ctx: QueryPlanContext, step_results: dict[str, dict[str, Any]]) -> OperatorResult:
        raise NotImplementedError


def require_fields(ctx: QueryPlanContext, *names: str) -> None:
    missing = [name for name in names if not getattr(ctx, name)]
    if missing:
        raise ValueError(f"missing required query context fields: {', '.join(missing)}")
