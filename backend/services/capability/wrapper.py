"""Capability Wrapper — 统一入口

对应 spec §4.1 — 统一入口 CapabilityWrapper.invoke(...)。
执行顺序（spec §4）：
  1. trace_id 生成/继承
  2. Registry.get(capability) 找能力定义
  3. Authz.check(principal, capability)          ← Phase 1
  4. Params JSON Schema 校验                    ← Phase 1
  5. Sensitivity.check(principal, capability, params)  ← Phase 1
  6. RateLimiter.acquire(principal, capability) ← Phase 1.5 NEW
  7. CircuitBreaker.allow(capability)           ← Phase 1.5 NEW
  8. ResultCache.get(key) → hit return           ← Phase 1.5 NEW
  9. capabilities.{name}.run(params) → downstream← existing
 10. ResultCache.set(key, result)                ← Phase 1.5 NEW
 11. CostMeter.record(...)                      ← Phase 1.5 NEW
 12. Audit.write(...)                           ← Phase 1
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .audit import InvocationRecord, new_trace_id, get_trace_id, write_audit
from .circuit_breaker import CircuitBreaker
from .cost_meter import CostMeter, CostRecord
from .errors import (
    CapabilityError,
    CapabilityInternalError,
    CapabilityNotFound,
    CapabilityParamsInvalid,
    CapabilityRateLimited,
    CapabilityTimeout,
)
from .rate_limiter import RateLimiter
from .registry import CapabilityDefinition, get_capability, list_all
from .result_cache import ResultCache
from .sensitivity import check as sensitivity_check


# ---------------------------------------------------------------------------
# Backend registry — maps capability.backend name → async callable
# ---------------------------------------------------------------------------

_BACKENDS: dict[str, callable] = {}


def register_backend(name: str, handler: callable) -> None:
    """Register a backend handler for a capability.

    Handler signature: async def handler(params: dict) -> Any
    """
    _BACKENDS[name] = handler
    logger.info("Backend registered: %s → %s", name, handler.__module__ or handler.__qualname__)

logger = logging.getLogger(__name__)


@dataclass
class CapabilityResult:
    """Capability 调用结果"""
    data: Any
    meta: dict = field(default_factory=dict)


class CapabilityWrapper:
    """
    Capability 统一调用入口。

    组合 Registry、Authz、Sensitivity、RateLimiter、CircuitBreaker、
    ResultCache、CostMeter、Audit 各组件，按顺序执行调用链。
    """

    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.result_cache = ResultCache()
        self.cost_meter = CostMeter()
        # CircuitBreaker 实例缓存（per-capability）
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    def _get_circuit_breaker(self, cap_def: CapabilityDefinition) -> CircuitBreaker:
        """获取或创建 per-capability 的 CircuitBreaker"""
        if cap_def.name not in self._circuit_breakers:
            self._circuit_breakers[cap_def.name] = CircuitBreaker(
                capability=cap_def.name,
                failure_threshold=cap_def.circuit_breaker.failure_threshold,
                recovery_seconds=cap_def.circuit_breaker.recovery_seconds,
            )
        return self._circuit_breakers[cap_def.name]

    async def invoke(
        self,
        principal: dict,
        capability_name: str,
        params: dict,
        trace_id: str | None = None,
    ) -> CapabilityResult:
        """
        执行 Capability 调用。

        Args:
            principal: {id, role}
            capability_name: 能力名称，如 'query_metric'
            params: 业务参数
            trace_id: 可选的 trace_id（不传则自动生成）

        Returns:
            CapabilityResult(data, meta)
        """
        # 1. trace_id 生成/继承
        if trace_id is None:
            trace_id = new_trace_id()
        else:
            from .audit import _trace_id_var
            _trace_id_var.set(trace_id)

        start_time = time.time()
        status = "ok"
        error_code: Optional[str] = None
        error_detail: Optional[str] = None
        cached = False
        audit_recorded = False

        # 2. 查找能力定义
        try:
            cap_def = get_capability(capability_name)
        except CapabilityNotFound:
            raise

        # 3. Authz 检查（角色）
        if principal.get("role") not in cap_def.roles:
            raise CapabilityError(
                f"Role '{principal.get('role')}' not allowed for capability '{capability_name}'",
                detail="CAP_001",
            )

        # 4. Params JSON Schema 校验
        _validate_params(params, cap_def)

        try:
            # 5. Sensitivity 检查
            sensitivity_check(principal, cap_def, params)

            # 6. RateLimiter.acquire
            self.rate_limiter.acquire(
                capability=capability_name,
                user_id=principal.get("id", 0),
                rate=cap_def.rate_limit.rate,
                window_seconds=cap_def.rate_limit.window,
            )

            # 7. CircuitBreaker.allow
            cb = self._get_circuit_breaker(cap_def)
            cb.allow()

            # 8. ResultCache.get → 命中直接返回
            cache_key_fields = {k: params.get(k) for k in cap_def.cache.key_fields if k in params}
            cached_result = self.result_cache.get(
                capability=capability_name,
                cache_key_fields=cache_key_fields,
                principal_role=principal.get("role", ""),
            )
            if cached_result is not None:
                cached = True
                latency_ms = int((time.time() - start_time) * 1000)
                # 记录成本
                self.cost_meter.record(CostRecord(
                    trace_id=trace_id,
                    principal_id=principal.get("id", 0),
                    principal_role=principal.get("role", ""),
                    capability=capability_name,
                    latency_ms=latency_ms,
                    cached=True,
                ))
                # 审计
                self._write_audit(InvocationRecord(
                    trace_id=trace_id,
                    principal_id=principal.get("id", 0),
                    principal_role=principal.get("role", ""),
                    capability=capability_name,
                    params_jsonb=params,
                    status="ok",
                    latency_ms=latency_ms,
                ))
                return CapabilityResult(data=cached_result, meta={"cached": True, "trace_id": trace_id, "latency_ms": latency_ms})

            # 9. 调用下游 capability 实现
            result = await self._dispatch_capability(capability_name, params, cap_def)

            # 10. ResultCache.set
            self.result_cache.set(
                capability=capability_name,
                cache_key_fields=cache_key_fields,
                principal_role=principal.get("role", ""),
                result=result,
                ttl_seconds=cap_def.cache.ttl_seconds,
            )

            # 记录成功到 CircuitBreaker
            cb.record_success()

        except CapabilityRateLimited:
            raise
        except CapabilityError:
            raise
        except Exception as e:
            error_code = "CAP_009"
            error_detail = str(e)[:2000]
            status = "failed"
            # 通知 CircuitBreaker
            try:
                cb = self._get_circuit_breaker(cap_def)
                cb.record_failure()
            except Exception:
                pass
            raise CapabilityInternalError(str(e)) from e

        finally:
            latency_ms = int((time.time() - start_time) * 1000)

            # 11. CostMeter.record
            if not cached:
                self.cost_meter.record(CostRecord(
                    trace_id=trace_id,
                    principal_id=principal.get("id", 0),
                    principal_role=principal.get("role", ""),
                    capability=capability_name,
                    latency_ms=latency_ms,
                    cached=False,
                ))

            # 12. Audit.write
            self._write_audit(InvocationRecord(
                trace_id=trace_id,
                principal_id=principal.get("id", 0),
                principal_role=principal.get("role", ""),
                capability=capability_name,
                params_jsonb=params,
                status=status,
                error_code=error_code,
                error_detail=error_detail,
                latency_ms=latency_ms,
            ))

        return CapabilityResult(data=result, meta={"cached": False, "trace_id": trace_id, "latency_ms": latency_ms})

    def _write_audit(self, rec: InvocationRecord) -> None:
        """写审计记录（fire-and-forget）"""
        try:
            write_audit(rec)
        except Exception as e:
            logger.error("Audit write failed: %s", e)

    async def _dispatch_capability(
        self,
        capability_name: str,
        params: dict,
        cap_def: CapabilityDefinition,
    ) -> Any:
        """
        调度具体 capability 实现。

        优先从 _BACKENDS 查找已注册的 backend；fallback 到 llm_service.complete
        作为 llm_complete capability 的 backend 实现。
        """
        backend_name = cap_def.backend

        # 1. 已知 backend（tableau_mcp 等外部 MCP）
        if backend_name in _BACKENDS:
            logger.info("Dispatching capability '%s' → backend '%s'", capability_name, backend_name)
            return await _BACKENDS[backend_name](params)

        # 2. llm_service backend: complete_for_semantic (nlq/semantic 专用)
        if backend_name == "llm":
            from services.llm.service import LLMService
            llm = LLMService()
            result = await llm.complete_for_semantic(
                prompt=params.get("prompt", ""),
                system=params.get("system"),
                timeout=params.get("timeout", 30),
                purpose=params.get("purpose", "default"),
            )
            return result

        # 3. nlq backend: delegate to nlq_service.run (nlq_search capability)
        if backend_name == "nlq":
            from services.llm import nlq_service as _nlq_svc
            result = await _nlq_svc.run(
                question=params.get("question", ""),
                datasource_luid=params.get("datasource_luid"),
                connection_id=params.get("connection_id"),
                conversation_id=params.get("conversation_id"),
                options=params.get("options"),
                use_conversation_context=params.get("use_conversation_context", False),
                target_sites=params.get("target_sites"),
            )
            return result

        # 4. query_metric backend: delegate to query_executor.execute_query
        if backend_name == "tableau_mcp":
            from services.llm.query_executor import execute_query as _qe
            result = await _qe(
                datasource_luid=params.get("datasource_luid"),
                vizql_json=params.get("vizql_json"),
                limit=params.get("limit", 1000),
                timeout=params.get("timeout", 30),
                connection_id=params.get("connection_id"),
            )
            return result

        # 5. Unknown backend → mock
        logger.warning("Unknown backend '%s' for capability '%s', returning mock", backend_name, capability_name)
        return {"status": "ok", "capability": capability_name, "params": params}


def _validate_params(params: dict, cap_def: CapabilityDefinition) -> None:
    """JSON Schema 参数校验"""
    import jsonschema
    schema = cap_def.params_schema
    try:
        jsonschema.validate(instance=params, schema=schema)
    except jsonschema.exceptions.ValidationError as e:
        raise CapabilityParamsInvalid(
            f"Params validation failed: {e.message}",
            detail=f"Failed on field: {'.'.join(str(p) for p in e.path)}",
        )
