"""Data Agent connection resolution regressions."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.agent import _validate_connection_access
from services.datasources.models import DataSource
from services.tableau.models import TableauConnection


pytestmark = pytest.mark.skip_db


def _has_active_true_filter(criteria):
    for criterion in criteria:
        left = getattr(criterion, "left", None)
        right = getattr(criterion, "right", None)
        if getattr(left, "key", None) == "is_active" and (
            getattr(right, "value", None) is True or right.__class__.__name__ == "True_"
        ):
            return True
    return False


class _ConnectionQuery:
    def __init__(self, model):
        self.model = model
        self.criteria = []

    def filter(self, *criteria):
        self.criteria.extend(criteria)
        return self

    def first(self):
        if self.model is TableauConnection:
            if _has_active_true_filter(self.criteria):
                return None
            return MagicMock(id=1, is_active=False)
        if self.model is DataSource:
            raise AssertionError(
                "inactive tableau_connections.id=1 must not fall back to bi_data_sources.id=1"
            )
        return None


def test_inactive_tableau_connection_id_does_not_fallback_to_datasource_id():
    """回归：停用的 tableau_connections.id=1 不能被当作 bi_data_sources.id=1。"""
    db = MagicMock()
    db.query.side_effect = lambda model: _ConnectionQuery(model)

    with pytest.raises(HTTPException) as exc:
        _validate_connection_access(
            connection_id=1,
            current_user={"id": 1, "role": "admin"},
            db=db,
        )

    assert exc.value.status_code == 404
