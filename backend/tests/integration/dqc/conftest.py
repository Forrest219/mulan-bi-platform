"""DQC 集成测试共用 fixture

集成测试需要真实的 PostgreSQL（含 DQC 表）+ 真实的目标数据库。
运行前置条件：
- DATABASE_URL 指向已完成 alembic upgrade head 的测试库
- 目标数据库 fixture 由各测试用例自行准备（或使用 H2-like 的内嵌 db）

若环境不满足，各测试通过 pytest.skip 自动跳过，不阻塞主线。
"""
import json
import os
from pathlib import Path

import pytest


FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "dqc"


def _load_fixture(name: str):
    path = FIXTURE_DIR / name
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


@pytest.fixture
def sample_assets():
    return _load_fixture("assets.json") or []


@pytest.fixture
def sample_rules():
    return _load_fixture("rules.json") or []


@pytest.fixture
def sample_results_p0():
    return _load_fixture("results_p0.json") or []


@pytest.fixture
def sample_profile():
    return _load_fixture("profile_sample.json") or {}


def _target_db_available() -> bool:
    """判断是否存在可用的目标测试数据库（由 CI 环境变量开关控制）"""
    return os.environ.get("DQC_INTEGRATION_ENABLED") == "1"


@pytest.fixture
def require_integration_env():
    if not _target_db_available():
        pytest.skip("DQC integration tests require DQC_INTEGRATION_ENABLED=1 + real DBs")
