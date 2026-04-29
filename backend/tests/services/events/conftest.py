"""
tests/services/events/ 子目录的 conftest
覆盖 session-level setup_database，不连接真实 DB。

纯单元测试不需要数据库，只需环境变量。
"""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")
os.environ.setdefault("FERNET_MASTER_KEY", "dW5kZWZpbmVkLWZlcm5ldC1tYXN0ZXIta2V5LTI1Ng==")


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """单元测试不需要真实 DB，跳过建表和用户初始化。"""
    yield
