"""
integration/ 子目录 conftest — 覆盖根 conftest 的 autouse 数据库 setup。

本目录下的集成测试全部使用 mock，不需要真实数据库连接。
通过重新定义 session-scoped setup_database fixture 来跳过 alembic 迁移。
"""
import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """覆盖根 conftest 的 setup_database — integration 测试不需要真实数据库"""
    yield
