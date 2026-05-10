"""
Spec §3.5: STATIC_SKILL_KEYS 必须与 ToolRegistry 注册的工具名集合保持一致。

此测试防止 factory.py 新增/删除工具后 whitelist 悄悄漂移。
"""

from services.data_agent.factory import create_engine
from services.skills.service import STATIC_SKILL_KEYS


def test_whitelist_matches_registry():
    _, registry = create_engine()
    registry_keys = frozenset(registry.list_tool_names())
    assert STATIC_SKILL_KEYS == registry_keys, (
        f"STATIC_SKILL_KEYS 与 ToolRegistry 不一致\n"
        f"  仅在白名单: {STATIC_SKILL_KEYS - registry_keys}\n"
        f"  仅在 registry: {registry_keys - STATIC_SKILL_KEYS}"
    )
