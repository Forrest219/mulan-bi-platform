"""TokenBudget 错误码（Spec 12 §18.8）

TBD_001~TBD_006
"""
from typing import Optional


class TBDError(Exception):
    """TokenBudget 模块错误基类"""

    code: str = "TBD_000"
    http_status: int = 500
    message: str = "TokenBudget 未知错误"

    def __init__(self, message: Optional[str] = None, details: Optional[dict] = None):
        self.message = message or self.message
        self.details = details or {}
        super().__init__(f"[{self.code}] {self.message}")


class BudgetExceeded(TBDError):
    """上下文超 budget（error 模式）"""

    code = "TBD_001"
    http_status = 422
    message = "上下文超 budget"


class TBD_001(BudgetExceeded):
    """上下文超 budget（error 模式）"""

    code = "TBD_001"
    http_status = 422
    message = "上下文超 budget，触发 error 模式异常"


class TBD_002(TBDError):
    """tiktoken 编码器不支持该 model"""

    code = "TBD_002"
    http_status = 500
    message = "tiktoken 编码器不支持该 model"


class TBD_003(TBDError):
    """YAML 配置缺失 scenario"""

    code = "TBD_003"
    http_status = 500
    message = "YAML 配置缺失 scenario"


class TBD_004(TBDError):
    """配置校验失败：system_reserved + instruction_reserved + response_reserved > total"""

    code = "TBD_004"
    http_status = 422
    message = "Token 预算配置校验失败：预留空间超过总预算"


class TBD_005(TBDError):
    """熔断打开（60 秒内连续 5 次 fit 失败）"""

    code = "TBD_005"
    http_status = 503
    message = "TokenBudget 熔断打开，请稍后重试"


class TBD_006(TBDError):
    """meter.record 失败（仅日志，不回滚业务）"""

    code = "TBD_006"
    http_status = 500
    message = "计费埋点失败"
