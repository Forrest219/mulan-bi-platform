import pytest

from app.core.errors import MulanError
from services.data_explorer.connector import PreviewObjectNotAllowedError
from services.data_explorer.service import data_explorer_service, map_connector_error
from services.data_explorer.table_ref import encode_table_ref
from services.datasources.models import DataSource

pytestmark = pytest.mark.skip_db


class FakeQuery:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.value


class FakeDb:
    def __init__(self, datasource, owner=None):
        self.datasource = datasource
        self.owner = owner

    def query(self, model):
        if model.__name__ == "DataSource":
            return FakeQuery(self.datasource)
        return FakeQuery(self.owner)


class FakeConnector:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.closed = False
        self.list_columns_calls = []
        self.list_tables_calls = []

    def list_schemas(self):
        return ["openclaw_db", "empty_schema"]

    def list_tables(self, schema=None, include_views=True):
        self.list_tables_calls.append((schema, include_views))
        if schema == "openclaw_db":
            return [
                {"schema": schema, "name": "orders", "object_type": "table"},
                {"schema": schema, "name": "customers", "object_type": "table"},
                {"schema": schema, "name": "sales_view", "object_type": "view"},
            ]
        return []

    def list_columns(self, schema, table):
        self.list_columns_calls.append((schema, table))
        if self.fail:
            raise PreviewObjectNotAllowedError("preview 对象不存在或不允许访问")
        return [{"name": "id", "data_type": "BIGINT"}]

    def close(self):
        self.closed = True


def _datasource(**overrides):
    defaults = {
        "id": 7,
        "name": "Orders DB",
        "db_type": "mysql",
        "host": "localhost",
        "port": 3306,
        "database_name": "demo",
        "username": "readonly",
        "password_encrypted": "",
        "owner_id": 42,
        "is_active": True,
    }
    defaults.update(overrides)
    return DataSource(**defaults)


def test_connector_error_code_maps_to_standard_http_status():
    error = map_connector_error(PreviewObjectNotAllowedError("blocked"))

    assert error.error_code == "DEX_009"
    assert error.status_code == 400


def test_list_schemas_returns_real_table_and_view_counts(monkeypatch):
    connector = FakeConnector()
    monkeypatch.setattr("services.data_explorer.service._connector_for", lambda connection: connector)

    response = data_explorer_service.list_schemas(
        7,
        {"id": 42, "role": "analyst"},
        FakeDb(_datasource()),
    )

    openclaw = next(item for item in response.items if item.name == "openclaw_db")
    empty = next(item for item in response.items if item.name == "empty_schema")
    assert openclaw.table_count == 2
    assert openclaw.view_count == 1
    assert empty.table_count == 0
    assert empty.view_count == 0
    assert connector.list_tables_calls == [("openclaw_db", True), ("empty_schema", True)]
    assert connector.closed is True


def test_get_permissions_validates_table_ref_object_and_closes_connector(monkeypatch):
    connector = FakeConnector()
    monkeypatch.setattr("services.data_explorer.service._connector_for", lambda connection: connector)

    response = data_explorer_service.get_permissions(
        7,
        encode_table_ref("analytics", "orders"),
        {"id": 42, "role": "analyst"},
        FakeDb(_datasource()),
    )

    assert connector.list_columns_calls == [("analytics", "orders")]
    assert connector.closed is True
    assert response.resource_id == "dbtable:7.analytics.orders"
    assert response.current_user.is_owner is True
    assert response.effective_actions.grant is False


def test_get_permissions_rejects_missing_target_object_and_closes_connector(monkeypatch):
    connector = FakeConnector(fail=True)
    monkeypatch.setattr("services.data_explorer.service._connector_for", lambda connection: connector)

    with pytest.raises(MulanError) as exc:
        data_explorer_service.get_permissions(
            7,
            encode_table_ref("analytics", "missing_orders"),
            {"id": 42, "role": "analyst"},
            FakeDb(_datasource()),
        )

    assert exc.value.error_code == "DEX_009"
    assert connector.closed is True


def test_analyst_cannot_access_other_owner_connection():
    with pytest.raises(MulanError) as exc:
        data_explorer_service.get_permissions(
            7,
            encode_table_ref("analytics", "orders"),
            {"id": 99, "role": "analyst"},
            FakeDb(_datasource(owner_id=42)),
        )

    assert exc.value.error_code == "DEX_005"
    assert exc.value.status_code == 403


def test_inactive_connection_returns_dex_003():
    with pytest.raises(MulanError) as exc:
        data_explorer_service.get_permissions(
            7,
            encode_table_ref("analytics", "orders"),
            {"id": 42, "role": "admin"},
            FakeDb(_datasource(is_active=False)),
        )

    assert exc.value.error_code == "DEX_003"
    assert exc.value.status_code == 400


def test_unsupported_connection_returns_dex_004():
    with pytest.raises(MulanError) as exc:
        data_explorer_service.get_permissions(
            7,
            encode_table_ref("analytics", "orders"),
            {"id": 42, "role": "admin"},
            FakeDb(_datasource(db_type="hive")),
        )

    assert exc.value.error_code == "DEX_004"
    assert exc.value.status_code == 422
