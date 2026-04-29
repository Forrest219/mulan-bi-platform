"""TokenBudget 配置加载器（Spec 12 §18.4）

从 config/token_budget.yaml 加载场景级配置。
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import yaml

logger = logging.getLogger(__name__)

# 默认配置路径
_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "token_budget.yaml"

# 内存缓存（Spec 12 §18.12 红线：运行时禁止重读 YAML）
_config_cache: Optional[Dict[str, Any]] = None


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    加载 token_budget.yaml 配置。

    配置在启动时一次加载，运行时禁止重读（除显式 admin reload）。

    Args:
        config_path: 配置文件路径，默认使用 _DEFAULT_CONFIG_PATH

    Returns:
        配置字典

    Raises:
        TBD_003: YAML 配置缺失或解析失败
    """
    global _config_cache

    if _config_cache is not None:
        return _config_cache

    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning("token_budget.yaml 未找到，使用内置默认配置: %s", path)
        config = _default_config()

    # 配置校验
    _validate_config(config)

    _config_cache = config
    return config


def _validate_config(config: Dict[str, Any]) -> None:
    """启动时配置校验（校验通过才允许启动）"""
    from .errors import TBD_004

    defaults = config.get("defaults", {})
    total = defaults.get("system_reserved", 0) + \
            defaults.get("instruction_reserved", 0) + \
            defaults.get("response_reserved", 0)

    # 不在这里校验 total > budget_total，因为 defaults 不是完整 TokenBudget
    # 完整校验在 registry.get() 时进行

    scenarios = config.get("scenarios", {})
    for scenario_name, providers in scenarios.items():
        for provider_name, budget_config in providers.items():
            s_res = budget_config.get("system_reserved", defaults.get("system_reserved", 200))
            i_res = budget_config.get("instruction_reserved", defaults.get("instruction_reserved", 300))
            r_res = budget_config.get("response_reserved", defaults.get("response_reserved", 512))
            total_budget = budget_config.get("total", 0)

            if s_res + i_res + r_res > total_budget:
                raise TBD_004(
                    message=f"场景 {scenario_name}/{provider_name} 的预留空间超限: "
                            f"system({s_res}) + instruction({i_res}) + response({r_res}) = {s_res+i_res+r_res} > total({total_budget})"
                )


def _default_config() -> Dict[str, Any]:
    """内置默认配置（Spec 12 §18.4 YAML 结构）"""
    return {
        "defaults": {
            "system_reserved": 200,
            "instruction_reserved": 300,
            "response_reserved": 512,
        },
        "scenarios": {
            "semantic_field": {
                "openai": {
                    "model": "gpt-4o",
                    "total": 3000,
                    "response_reserved": 512,
                },
                "anthropic": {
                    "model": "claude-sonnet-4",
                    "total": 4096,
                    "response_reserved": 1024,
                },
                "deepseek": {
                    "model": "deepseek-v3",
                    "total": 8192,
                    "response_reserved": 1024,
                },
            },
            "semantic_ds": {
                "openai": {
                    "model": "gpt-4o",
                    "total": 3000,
                    "response_reserved": 512,
                },
                "anthropic": {
                    "model": "claude-sonnet-4",
                    "total": 4096,
                    "response_reserved": 1024,
                },
                "deepseek": {
                    "model": "deepseek-v3",
                    "total": 8192,
                    "response_reserved": 1024,
                },
            },
            "nlq": {
                "openai": {
                    "model": "gpt-4o",
                    "total": 4096,
                    "response_reserved": 1024,
                },
                "anthropic": {
                    "model": "claude-sonnet-4",
                    "total": 8192,
                    "response_reserved": 2048,
                },
                "deepseek": {
                    "model": "deepseek-v3",
                    "total": 16384,
                    "response_reserved": 2048,
                },
            },
            "agent_step": {
                "openai": {
                    "model": "gpt-4o",
                    "total": 8192,
                    "response_reserved": 2048,
                },
                "anthropic": {
                    "model": "claude-sonnet-4",
                    "total": 16384,
                    "response_reserved": 4096,
                },
                "deepseek": {
                    "model": "deepseek-v3",
                    "total": 32768,
                    "response_reserved": 4096,
                },
            },
            "rag_context": {
                "openai": {
                    "model": "gpt-4o",
                    "total": 6144,
                    "response_reserved": 1024,
                },
                "anthropic": {
                    "model": "claude-sonnet-4",
                    "total": 12288,
                    "response_reserved": 2048,
                },
                "deepseek": {
                    "model": "deepseek-v3",
                    "total": 24576,
                    "response_reserved": 2048,
                },
            },
        },
    }


def clear_config_cache() -> None:
    """清除配置缓存（用于测试或 admin reload）"""
    global _config_cache
    _config_cache = None


def reload_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    显式重载配置（用于 admin reload 场景）。

    Args:
        config_path: 配置文件路径，默认使用 _DEFAULT_CONFIG_PATH

    Returns:
        新加载的配置字典
    """
    clear_config_cache()
    return load_config(config_path)