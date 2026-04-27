"""Capability Cost Meter — 成本计量

对应 spec §5 & §8 — 记录：
- input_tokens, output_tokens, latency_ms, cached (bool)
- 写入 bi_capability_invocations 表的 llm_tokens_in / llm_tokens_out / latency_ms 字段
- Per-user, per-capability, per-day 聚合可通过查询审计表计算
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CostRecord:
    """单次调用的成本记录"""
    trace_id: str
    principal_id: int
    principal_role: str
    capability: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cached: bool = False
    error_code: Optional[str] = None


class CostMeter:
    """
    成本计量器。

    计量数据通过 Audit.write 一起写入 bi_capability_invocations 表
    （利用 audit.py 已有的 llm_tokens_in / llm_tokens_out / latency_ms 字段）。
    """

    def record(self, cost: CostRecord) -> None:
        """
        记录成本数据。

        实际写入由 audit.py 的 write_audit 统一处理，
        这里只负责聚合日志记录。
        """
        logger.info(
            "CostMeter: trace_id=%s capability=%s user=%d role=%s "
            "tokens_in=%d tokens_out=%d latency_ms=%d cached=%s",
            cost.trace_id,
            cost.capability,
            cost.principal_id,
            cost.principal_role,
            cost.input_tokens,
            cost.output_tokens,
            cost.latency_ms,
            cost.cached,
        )

    @staticmethod
    def aggregate_daily(
        capability: Optional[str] = None,
        principal_id: Optional[int] = None,
    ) -> dict:
        """
        聚合查询（从 bi_capability_invocations 统计）。

        实际聚合 SQL 建议在业务层按需查询，此处只定义聚合维度。
        """
        # TODO: 实现聚合查询
        # SELECT capability, principal_id, DATE(created_at),
        #        SUM(llm_tokens_in), SUM(llm_tokens_out), AVG(latency_ms),
        #        COUNT(*) as total_calls
        # FROM bi_capability_invocations
        # WHERE created_at >= NOW() - INTERVAL '30 days'
        # GROUP BY ROLLUP(capability, principal_id, DATE(created_at))
        return {}
