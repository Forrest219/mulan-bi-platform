"""TokenBudget 统一控制器（Spec 12 §18 — v1.3 新增）

提供跨场景的 Token 预算统一管理：
- 场景级配置（semantic_field, semantic_ds, nlq, agent_step, rag_context）
- tiktoken 精确计算（全局缓存编码器）
- 统一截断策略接口（Policy）
- 超限异常 + 错误码（TBD_001~TBD_006）
- 计费埋点接口（Meter）
- 短熔断（防 LLM 抖动放大）

架构红线：
1. 本模块不得 import app/api 或 services/llm/service（防循环依赖）
2. tiktoken 编码器必须全局缓存
3. meter.record 内部禁止抛异常
"""

from .budget import TokenBudget, BudgetReport, BudgetEnforcer, BudgetRegistry
from .counter import TokenCounter, clear_encoder_cache
from .policies import Policy, PriorityDropPolicy, FIFODropPolicy, SummarizePolicy, BudgetItem
from .meter import Meter, LogMeter, BiCapabilityInvocationsMeter
from .errors import (
    TBDError,
    BudgetExceeded,
    TBD_001,
    TBD_002,
    TBD_003,
    TBD_004,
    TBD_005,
    TBD_006,
)
from .config import load_config, clear_config_cache, reload_config

# 便捷函数
from .budget import get_registry, clear_registry

__all__ = [
    # Core types
    "TokenBudget",
    "BudgetReport",
    "BudgetItem",
    "BudgetEnforcer",
    "BudgetRegistry",
    # Counter
    "TokenCounter",
    "clear_encoder_cache",
    # Policies
    "Policy",
    "PriorityDropPolicy",
    "FIFODropPolicy",
    "SummarizePolicy",
    # Meter
    "Meter",
    "LogMeter",
    "BiCapabilityInvocationsMeter",
    # Errors
    "TBDError",
    "BudgetExceeded",
    "TBD_001",
    "TBD_002",
    "TBD_003",
    "TBD_004",
    "TBD_005",
    "TBD_006",
    # Config
    "load_config",
    "clear_config_cache",
    "reload_config",
    "get_registry",
    "clear_registry",
]
