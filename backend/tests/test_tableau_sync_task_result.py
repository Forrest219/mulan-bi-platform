"""Tableau sync task result payload regressions."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from services.tasks.tableau_tasks import sync_connection_task


class FakeSession:
    def rollback(self):
        return None


class FakeRedis:
    def set(self, *args, **kwargs):
        return True

    def delete(self, *args, **kwargs):
        return 1


class FakeTableauDatabase:
    def __init__(self, session):
        self.session = session

    def get_connection(self, conn_id):
        return SimpleNamespace(
            id=conn_id,
            token_encrypted="encrypted-token",
            connection_type="mcp",
            server_url="https://tableau.example.com",
            site="default",
            token_name="token-name",
            api_version="3.21",
        )

    def create_sync_log(self, conn_id, trigger_type="manual"):
        return SimpleNamespace(id=14, connection_id=conn_id, trigger_type=trigger_type)

    def set_sync_status(self, *args, **kwargs):
        return None

    def finish_sync_log(self, *args, **kwargs):
        return True

    def update_connection_health(self, *args, **kwargs):
        return None

    def increment_sync_failures(self, *args, **kwargs):
        return None

    def reset_sync_failures(self, *args, **kwargs):
        return None


class FakeCrypto:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail

    def decrypt(self, value):
        if self.should_fail:
            raise ValueError("bad token")
        return "plain-token"


class FakeService:
    connect_result = True
    sync_error = None

    def __init__(self, *args, **kwargs):
        pass

    def connect(self):
        return self.connect_result

    def sync_all_assets(self, *args, **kwargs):
        if self.sync_error:
            raise self.sync_error
        return {"status": "success", "total": 3, "deleted": 1, "duration_sec": 2}

    def disconnect(self):
        return None


@contextmanager
def fake_db_context():
    yield FakeSession()


@pytest.fixture(autouse=True)
def _patch_task_dependencies(monkeypatch):
    import redis
    import app.core.database as database
    import app.core.crypto as crypto
    import services.tableau.models as tableau_models
    import services.tableau.sync_service as sync_service

    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: FakeRedis())
    monkeypatch.setattr(database, "get_db_context", fake_db_context)
    monkeypatch.setattr(tableau_models, "TableauDatabase", FakeTableauDatabase)
    monkeypatch.setattr(crypto, "get_tableau_crypto", lambda: FakeCrypto())
    monkeypatch.setattr(sync_service, "TableauRestSyncService", FakeService)
    monkeypatch.setattr(sync_service, "TableauSyncService", FakeService)
    monkeypatch.setattr("services.tasks.tableau_tasks._update_sync_task", lambda *args, **kwargs: None)

    FakeService.connect_result = True
    FakeService.sync_error = None
    sync_connection_task.request.retries = 0


def test_sync_connection_task_success_result_contains_sync_log_and_connection_id():
    result = sync_connection_task.run(4, trigger_type="manual")

    assert result["status"] == "success"
    assert result["sync_log_id"] == 14
    assert result["connection_id"] == 4


def test_sync_connection_task_token_failure_result_contains_sync_log_and_connection_id(monkeypatch):
    import app.core.crypto as crypto

    monkeypatch.setattr(crypto, "get_tableau_crypto", lambda: FakeCrypto(should_fail=True))

    result = sync_connection_task.run(4, trigger_type="manual")

    assert result["status"] == "error"
    assert "Token 解密失败" in result["message"]
    assert result["sync_log_id"] == 14
    assert result["connection_id"] == 4


def test_sync_connection_task_connection_failure_after_retries_contains_ids():
    FakeService.connect_result = False
    sync_connection_task.request.retries = sync_connection_task.max_retries

    result = sync_connection_task.run(4, trigger_type="manual")

    assert result["status"] == "error"
    assert result["message"] == "连接失败"
    assert result["sync_log_id"] == 14
    assert result["connection_id"] == 4


def test_sync_connection_task_sync_exception_after_retries_contains_ids():
    FakeService.sync_error = RuntimeError("sync exploded")
    sync_connection_task.request.retries = sync_connection_task.max_retries

    result = sync_connection_task.run(4, trigger_type="manual")

    assert result["status"] == "error"
    assert result["message"] == "sync exploded"
    assert result["sync_log_id"] == 14
    assert result["connection_id"] == 4
