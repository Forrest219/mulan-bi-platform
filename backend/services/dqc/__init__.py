"""DQC — Data Quality Core 服务模块"""

from .rule_engine import (
    seed_sr_rules,
    SrComplianceValidator,
    SrViolation,
    SrTableInfo,
    SR_RULES,
)
