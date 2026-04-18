"""
tests/evals/conftest.py

Evals 专用 conftest：
- 设置最小必要的环境变量（避免模块 import 时因缺少 env 而崩溃）
- 不依赖真实数据库连接
- 覆盖父级 conftest 的 setup_database autouse fixture（通过同名 fixture 空实现）
"""
import os
import sys
from pathlib import Path

# 设置最小环境变量（必须在任何 app 模块 import 之前）
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")

# 确保 backend 根目录在 sys.path 中
_BACKEND_ROOT = str(Path(__file__).parent.parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """
    覆盖父级 conftest 中的 setup_database fixture。
    evals 测试不需要真实数据库，此处为空实现。
    """
    yield
