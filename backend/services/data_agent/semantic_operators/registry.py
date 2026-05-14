"""Semantic operator registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from services.data_agent.query_plan import QueryPlanContext
from services.data_agent.semantic_operators.all_period_condition import AllPeriodConditionOperator
from services.data_agent.semantic_operators.base import SemanticOperator
from services.data_agent.semantic_operators.contribution_share import ContributionShareOperator
from services.data_agent.semantic_operators.customer_record import CustomerRecordOperator
from services.data_agent.semantic_operators.ranking import RankingOperator
from services.data_agent.semantic_operators.root_cause import RootCauseOperator
from services.data_agent.semantic_operators.set_difference import SetDifferenceOperator
from services.data_agent.semantic_operators.trend_condition import TrendConditionOperator


@dataclass(slots=True)
class OperatorMatch:
    operator: SemanticOperator
    confidence: float


class SemanticOperatorRegistry:
    def __init__(self, operators: Iterable[SemanticOperator] | None = None, threshold: float = 0.6):
        self.threshold = threshold
        self._operators: dict[str, SemanticOperator] = {}
        for operator in operators or []:
            self.register(operator)

    def register(self, operator: SemanticOperator) -> None:
        if operator.name in self._operators:
            raise ValueError(f"semantic operator already registered: {operator.name}")
        self._operators[operator.name] = operator

    def get(self, name: str) -> SemanticOperator:
        return self._operators[name]

    def list_names(self) -> list[str]:
        return list(self._operators.keys())

    def match(self, ctx: QueryPlanContext) -> OperatorMatch | None:
        if ctx.operator_hint and ctx.operator_hint in self._operators:
            return OperatorMatch(operator=self._operators[ctx.operator_hint], confidence=1.0)
        best: OperatorMatch | None = None
        for operator in self._operators.values():
            confidence = operator.match(ctx)
            if best is None or confidence > best.confidence:
                best = OperatorMatch(operator=operator, confidence=confidence)
        if best and best.confidence >= self.threshold:
            return best
        return None


def default_registry() -> SemanticOperatorRegistry:
    return SemanticOperatorRegistry(
        operators=[
            SetDifferenceOperator(),
            CustomerRecordOperator(),
            TrendConditionOperator(),
            AllPeriodConditionOperator(),
            RootCauseOperator(),
            ContributionShareOperator(),
            RankingOperator(),
        ],
        threshold=0.6,
    )
