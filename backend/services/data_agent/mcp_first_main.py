"""MCP-first controlled main path for homepage Data Agent questions."""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
from typing import Any, AsyncGenerator, Mapping, Optional

from services.data_agent.answer_prompt_builder import build_answer_prompt
from services.data_agent.intent_classifier import IntentClassification
from services.data_agent.query_plan import OperatorResult, QueryPlanContext
from services.data_agent.queryspec import FilterSpec, MetricSpec, QuerySpec, SortSpec
from services.data_agent.queryspec_fallback import build_fallback_queryspec, infer_fallback_operator
from services.data_agent.queryspec_prompt_builder import build_queryspec_prompt
from services.data_agent.queryspec_validator import validate_queryspec
from services.data_agent.response import AgentEvent
from services.data_agent.semantic_operators.registry import default_registry
from services.data_agent.skill_prompt_loader import SkillPromptLoader
from services.data_agent.table_display import infer_table_display_schema
from services.data_agent.tool_base import ToolContext
from services.llm.nlq_service import get_datasource_fields_cached, route_datasource
from services.llm.service import LLMService

logger = logging.getLogger(__name__)


async def run_mcp_first_main_path(
    *,
    question: str,
    context: ToolContext,
    intent_result: IntentClassification,
    datasource_name_hint: Optional[str] = None,
    analysis_context: Optional[Mapping[str, Any]] = None,
    llm_service: Optional[LLMService] = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Execute the controlled §16 chain for data intents."""

    loader = SkillPromptLoader()
    llm = llm_service or LLMService()

    yield AgentEvent(type="thinking", content=f"已识别为受控问数意图：{intent_result.intent}。")

    ds_info = _resolve_datasource(question, context, datasource_name_hint)
    if not ds_info:
        yield AgentEvent(type="error", content=_fallback_payload(
            "datasource_not_matched",
            "未找到可安全查询的 Tableau 数据源。",
            "请先选择一个 Tableau 数据源，或在问题中明确数据源名称。",
            context.trace_id,
            intent_result,
        ))
        return

    field_captions = _queryable_fields(ds_info, connection_id=context.connection_id)
    if not field_captions:
        yield AgentEvent(type="error", content=_fallback_payload(
            "query_plan_unavailable",
            "当前数据源没有可用于 MCP/VizQL 查询的字段。",
            "请确认 published datasource 字段已同步，且字段可被 Tableau MCP 查询。",
            context.trace_id,
            intent_result,
        ))
        return

    planning_skill = loader.load_planning(intent_result.intent)
    yield AgentEvent(type="tool_call", content={
        "tool": "planning_skill_loader",
        "params": {"skill_key": intent_result.intent, "kind": "planning"},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "planning_skill_loader",
        "result": {"data": _skill_result_summary(planning_skill)},
    })
    if not planning_skill.ok or not planning_skill.content:
        yield AgentEvent(type="error", content=_fallback_payload(
            "query_plan_unavailable",
            "未找到该意图对应的 planning skill。",
            "请联系管理员补齐 planning skill 配置。",
            context.trace_id,
            intent_result,
        ))
        return

    datasource_payload = {"name": ds_info.get("name"), "luid": ds_info.get("luid")}
    queryspec_fallback_enabled = _queryspec_fallback_enabled()

    raw_spec = None
    if queryspec_fallback_enabled and _should_prefer_deterministic_queryspec(question, intent_result, analysis_context):
        raw_spec = _build_fallback_queryspec(
            question=question,
            intent_result=intent_result,
            datasource=ds_info,
            queryable_fields=field_captions,
            analysis_context=analysis_context,
            reason="deterministic_preflight",
        )
        if raw_spec:
            yield AgentEvent(type="tool_call", content={
                "tool": "queryspec_fallback",
                "params": {"reason": "deterministic_preflight", "intent": intent_result.intent},
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "queryspec_fallback",
                "result": {"data": {"queryspec": _redact_large(raw_spec)}},
            })

    if raw_spec is None:
        prompt_messages = build_queryspec_prompt(
            question=question,
            intent=intent_result.intent,
            datasource=datasource_payload,
            queryable_fields=field_captions,
            analysis_context=analysis_context or {},
            planning_skill_content=planning_skill.content,
        )
        yield AgentEvent(type="tool_call", content={
            "tool": "llm_queryspec",
            "params": {
                "intent": intent_result.intent,
                "datasource": datasource_payload,
                "field_count": len(field_captions),
                "skill_checksum": planning_skill.checksum,
            },
        })
        queryspec_result = await _call_llm_json(llm, prompt_messages, purpose="data_agent_queryspec")
        if not queryspec_result.get("ok"):
            fallback_reason = str(queryspec_result.get("error") or "llm_queryspec_failed")
            yield AgentEvent(type="tool_result", content={
                "tool": "llm_queryspec",
                "result": {"success": False, "error": queryspec_result.get("error"), "data": queryspec_result},
            })
            if not queryspec_fallback_enabled:
                yield AgentEvent(type="error", content=_fallback_payload(
                    "QS_LLM_INVALID",
                    "LLM 未生成可执行的 QuerySpec。",
                    "请换一种更明确的问法，补充指标、时间范围或维度。",
                    context.trace_id,
                    intent_result,
                    fallback_type="query_plan_rejected",
                    detail={"fallback_disabled": True, "fallback_reason": fallback_reason},
                ))
                return
            raw_spec = _build_fallback_queryspec(
                question=question,
                intent_result=intent_result,
                datasource=ds_info,
                queryable_fields=field_captions,
                analysis_context=analysis_context,
                reason=fallback_reason,
            )
            if not raw_spec:
                yield AgentEvent(type="error", content=_fallback_payload(
                    "query_plan_unavailable",
                    "没有生成可安全执行的 QuerySpec。",
                    "请换一种更明确的问法，补充指标、时间范围或维度。",
                    context.trace_id,
                    intent_result,
                ))
                return
            yield AgentEvent(type="tool_call", content={
                "tool": "queryspec_fallback",
                "params": {"reason": "llm_queryspec_failed", "intent": intent_result.intent},
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "queryspec_fallback",
                "result": {"data": {"queryspec": _redact_large(raw_spec)}},
            })
        else:
            raw_spec = queryspec_result["json"]
            yield AgentEvent(type="tool_result", content={
                "tool": "llm_queryspec",
                "result": {"data": {"queryspec": _redact_large(raw_spec)}},
            })

    try:
        spec = QuerySpec.model_validate(raw_spec)
        spec = _normalize_mcp_handled_metrics(spec, question, field_captions)
    except Exception as exc:
        fallback_reason = f"queryspec_model_invalid: {exc}"
        if not queryspec_fallback_enabled:
            yield AgentEvent(type="error", content=_fallback_payload(
                "QS_INVALID_JSON",
                "QuerySpec 结构不符合契约。",
                "我没有生成可安全执行的查询计划，请换一种更明确的问法。",
                context.trace_id,
                intent_result,
                fallback_type="query_plan_rejected",
                detail={"error": str(exc)[:500], "fallback_disabled": True, "fallback_reason": fallback_reason[:500]},
            ))
            return
        raw_spec = _build_fallback_queryspec(
            question=question,
            intent_result=intent_result,
            datasource=ds_info,
            queryable_fields=field_captions,
            analysis_context=analysis_context,
            reason=fallback_reason,
        )
        if not raw_spec:
            yield AgentEvent(type="error", content=_fallback_payload(
                "QS_INVALID_JSON",
                "QuerySpec 结构不符合契约。",
                "我没有生成可安全执行的查询计划，请换一种更明确的问法。",
                context.trace_id,
                intent_result,
                detail={"error": str(exc)[:500]},
            ))
            return
        yield AgentEvent(type="tool_call", content={
            "tool": "queryspec_fallback",
            "params": {"reason": "queryspec_model_invalid", "intent": intent_result.intent},
        })
        yield AgentEvent(type="tool_result", content={
            "tool": "queryspec_fallback",
            "result": {"data": {"queryspec": _redact_large(raw_spec)}},
        })
        spec = _normalize_mcp_handled_metrics(QuerySpec.model_validate(raw_spec), question, field_captions)

    replacement_reason = _queryspec_replacement_reason(question, intent_result, spec, analysis_context)
    if replacement_reason:
        if not queryspec_fallback_enabled:
            yield AgentEvent(type="error", content=_fallback_payload(
                "QS_OPERATOR_MISMATCH",
                "QuerySpec 与用户问题的语义方向不一致。",
                "请重新提问并明确要查询的指标、维度和判断方向。",
                context.trace_id,
                intent_result,
                fallback_type="query_plan_rejected",
                detail={"fallback_disabled": True, "fallback_reason": replacement_reason},
            ))
            return
        fallback_raw = _build_fallback_queryspec(
            question=question,
            intent_result=intent_result,
            datasource=ds_info,
            queryable_fields=field_captions,
            analysis_context=analysis_context,
            reason=replacement_reason,
        )
        if fallback_raw:
            yield AgentEvent(type="tool_call", content={
                "tool": "queryspec_fallback",
                "params": {"reason": replacement_reason, "intent": intent_result.intent},
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "queryspec_fallback",
                "result": {"data": {"queryspec": _redact_large(fallback_raw)}},
            })
            spec = _normalize_mcp_handled_metrics(QuerySpec.model_validate(fallback_raw), question, field_captions)

    validation = validate_queryspec(
        spec,
        field_captions,
        {
            "name": ds_info.get("name"),
            "luid": ds_info.get("luid"),
            "metadata_fields": ds_info.get("metadata_fields") or [],
        },
        {
            "accessible_datasource_luids": [ds_info.get("luid")],
            "question": question,
            "analysis_context": analysis_context or {},
        },
    )
    yield AgentEvent(type="tool_call", content={
        "tool": "queryspec_validator",
        "params": {"intent": spec.intent, "operator": spec.effective_operator},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "queryspec_validator",
        "result": {"data": validation.to_dict(), "success": validation.passed},
    })
    if not validation.passed:
        fallback_raw = None
        if queryspec_fallback_enabled and spec.source != "deterministic_fallback":
            fallback_raw = _build_fallback_queryspec(
                question=question,
                intent_result=intent_result,
                datasource=ds_info,
                queryable_fields=field_captions,
                analysis_context=analysis_context,
                reason=f"queryspec_validation_failed: {validation.code}",
            )
        if fallback_raw:
            yield AgentEvent(type="tool_call", content={
                "tool": "queryspec_fallback",
                "params": {"reason": "queryspec_validation_failed", "intent": intent_result.intent, "code": validation.code},
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "queryspec_fallback",
                "result": {"data": {"queryspec": _redact_large(fallback_raw)}},
            })
            spec = _normalize_mcp_handled_metrics(QuerySpec.model_validate(fallback_raw), question, field_captions)
            validation = validate_queryspec(
                spec,
                field_captions,
                {
                    "name": ds_info.get("name"),
                    "luid": ds_info.get("luid"),
                    "metadata_fields": ds_info.get("metadata_fields") or [],
                },
                {
                    "accessible_datasource_luids": [ds_info.get("luid")],
                    "question": question,
                    "analysis_context": analysis_context or {},
                },
            )
            yield AgentEvent(type="tool_call", content={
                "tool": "queryspec_validator",
                "params": {"intent": spec.intent, "operator": spec.effective_operator, "source": spec.source},
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "queryspec_validator",
                "result": {"data": validation.to_dict(), "success": validation.passed},
            })
        if not validation.passed:
            rejection_detail = dict(validation.detail or {})
            if not queryspec_fallback_enabled:
                rejection_detail.update({
                    "fallback_disabled": True,
                    "fallback_reason": f"queryspec_validation_failed: {validation.code}",
                })
            yield AgentEvent(type="error", content=_fallback_payload(
                validation.code,
                validation.message,
                validation.user_hint,
                context.trace_id,
                intent_result,
                fallback_type="query_plan_rejected" if not queryspec_fallback_enabled else "query_plan_unavailable",
                detail=rejection_detail,
            ))
            return

    yield AgentEvent(type="tool_call", content={
        "tool": "tableau_mcp",
        "params": {"operator": spec.effective_operator, "datasource_luid": ds_info.get("luid")},
    })
    try:
        mcp_data = await _execute_queryspec(spec, ds_info, context, question)
    except Exception as exc:
        logger.exception("controlled MCP execution failed")
        yield AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp",
            "result": {"success": False, "error": str(exc), "data": {"error": str(exc)}},
        })
        yield AgentEvent(type="error", content=_fallback_payload(
            "mcp_execution_failed",
            "Tableau MCP 查询失败，本次不输出结论。",
            "请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 Tableau/MCP 执行日志。",
            context.trace_id,
            intent_result,
        ))
        return
    yield AgentEvent(type="tool_result", content={
        "tool": "tableau_mcp",
        "result": {"data": mcp_data},
    })

    rendering_skill = loader.load_rendering("answer_renderer")
    yield AgentEvent(type="tool_call", content={
        "tool": "rendering_skill_loader",
        "params": {"skill_key": "answer_renderer", "kind": "rendering"},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "rendering_skill_loader",
        "result": {"data": _skill_result_summary(rendering_skill)},
    })
    if not rendering_skill.ok or not rendering_skill.content:
        yield AgentEvent(type="error", content=_fallback_payload(
            "answer_render_unavailable",
            "回答渲染 skill 缺失，本次不输出结论。",
            "请联系管理员补齐 answer renderer 配置。",
            context.trace_id,
            intent_result,
        ))
        return

    if spec.source == "deterministic_fallback":
        rendered = _render_deterministic_answer(mcp_data, spec)
        yield AgentEvent(type="tool_call", content={
            "tool": "answer_renderer",
            "params": {"renderer": "deterministic", "row_count": len(mcp_data.get("rows") or [])},
        })
        yield AgentEvent(type="tool_result", content={
            "tool": "answer_renderer",
            "result": {"data": mcp_data, "renderer": "deterministic"},
        })
        yield AgentEvent(type="answer", content=rendered)
        return

    answer_messages = build_answer_prompt(
        mcp_result=mcp_data,
        queryspec=spec.model_dump(mode="json"),
        rendering_skill_content=rendering_skill.content,
    )
    yield AgentEvent(type="tool_call", content={
        "tool": "answer_renderer",
        "params": {"skill_checksum": rendering_skill.checksum, "row_count": len(mcp_data.get("rows") or [])},
    })
    rendered = await _call_llm_text(llm, answer_messages, purpose="data_agent_answer")
    answer_replacement_reason = (
        "answer_renderer_empty"
        if not rendered
        else _answer_replacement_reason(rendered, mcp_data, spec, question)
    )
    if answer_replacement_reason:
        rendered = _render_deterministic_answer(mcp_data, spec)
        yield AgentEvent(type="tool_result", content={
            "tool": "answer_renderer",
            "result": {"success": False, "error": answer_replacement_reason, "data": mcp_data, "fallback_answer": rendered},
        })
        yield AgentEvent(type="answer", content=rendered)
        return

    yield AgentEvent(type="tool_result", content={
        "tool": "answer_renderer",
        "result": {"data": mcp_data},
    })
    yield AgentEvent(type="answer", content=rendered)


def _resolve_datasource(question: str, context: ToolContext, datasource_name_hint: Optional[str]) -> Optional[dict[str, Any]]:
    if datasource_name_hint:
        try:
            from services.data_agent.tools.query_tool import _lookup_datasource_by_name

            matched = _lookup_datasource_by_name(datasource_name_hint, connection_id=context.connection_id)
            if matched:
                return matched
        except Exception:
            logger.debug("datasource hint lookup skipped", exc_info=True)
    return route_datasource(question, connection_id=context.connection_id)


def _queryable_fields(ds_info: Mapping[str, Any], connection_id: Optional[int] = None) -> list[str]:
    luid = ds_info.get("luid")
    if luid and connection_id:
        try:
            from services.tableau.mcp_client import get_tableau_mcp_client

            metadata = get_tableau_mcp_client(connection_id=connection_id).get_datasource_metadata(
                str(luid),
                timeout=20,
            )
            mcp_fields = _extract_mcp_field_names(metadata)
            if mcp_fields:
                return mcp_fields
        except Exception:
            logger.warning("MCP metadata fields unavailable; falling back to local cache", exc_info=True)

    asset_id = ds_info.get("asset_id")
    if not asset_id:
        return []
    fields = get_datasource_fields_cached(asset_id) or []
    return [str(field) for field in fields if str(field or "").strip()]


def _extract_mcp_field_names(metadata: Mapping[str, Any]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []

    def add(value: Any) -> None:
        name = str(value or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    for item in metadata.get("fields") or []:
        if isinstance(item, Mapping):
            add(item.get("name") or item.get("caption") or item.get("fieldCaption"))
        else:
            add(item)

    raw = metadata.get("raw")
    if isinstance(raw, Mapping):
        for group in raw.get("fieldGroups") or []:
            if not isinstance(group, Mapping):
                continue
            for item in group.get("fields") or []:
                if isinstance(item, Mapping):
                    add(item.get("name") or item.get("caption") or item.get("fieldCaption"))
                else:
                    add(item)

    return names


async def _call_llm_json(llm: LLMService, messages: list[dict[str, str]], *, purpose: str) -> dict[str, Any]:
    try:
        result = await llm.complete(
            prompt=messages[-1]["content"],
            system=messages[0]["content"],
            timeout=45,
            purpose=purpose,
        )
    except Exception as exc:
        logger.warning("LLM QuerySpec generation failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    content = (result.get("content") or "").strip()
    if not content:
        return {"ok": False, "error": result.get("error") or "empty_llm_response"}
    try:
        return {"ok": True, "json": json.loads(_strip_json_fence(content))}
    except json.JSONDecodeError as exc:
        extracted = _extract_first_json_object(content)
        if extracted:
            try:
                return {"ok": True, "json": json.loads(extracted)}
            except json.JSONDecodeError:
                pass
        return {"ok": False, "error": f"invalid_json: {exc}", "raw": content[:1000]}


async def _call_llm_text(llm: LLMService, messages: list[dict[str, str]], *, purpose: str) -> str:
    try:
        result = await llm.complete(
            prompt=messages[-1]["content"],
            system=messages[0]["content"],
            timeout=45,
            purpose=purpose,
        )
    except Exception:
        logger.warning("LLM answer rendering failed", exc_info=True)
        return ""
    return (result.get("content") or "").strip()


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, flags=re.DOTALL | re.IGNORECASE)
    return fenced.group(1).strip() if fenced else stripped


def _extract_first_json_object(content: str) -> Optional[str]:
    start = content.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(content[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start:index + 1]
    return None


async def _execute_queryspec(
    spec: QuerySpec,
    ds_info: Mapping[str, Any],
    context: ToolContext,
    question: str,
) -> dict[str, Any]:
    operator = spec.effective_operator
    if operator == "asset_inventory":
        raise ValueError("asset_inventory is handled by deterministic schema route")

    if operator == "aggregate":
        vizql = _vizql_from_queryspec(spec)
        result = await _execute_vizql(ds_info["luid"], vizql, context, question, limit=spec.limit or 1000)
        return _normalize_mcp_data(result, spec, ds_info)

    if operator == "trend_condition" and not spec.dimensions:
        vizql = _vizql_from_queryspec(spec)
        result = await _execute_vizql(ds_info["luid"], vizql, context, question, limit=spec.limit or 100)
        return _normalize_mcp_data(result, spec, ds_info)

    registry = default_registry()
    semantic_operator = registry.get(operator)
    ctx = _query_plan_context(spec, ds_info, context, question)
    steps = semantic_operator.build_steps(ctx)
    step_results: dict[str, dict[str, Any]] = {}
    for step in steps:
        step_results[step.name] = await _execute_vizql(
            ds_info["luid"],
            step.vizql_json,
            context,
            question,
            limit=step.mcp_limit(),
        )
    reduced = semantic_operator.reduce(ctx, step_results)
    return _operator_result_to_data(reduced, ds_info, spec, step_results)


async def _execute_vizql(
    datasource_luid: str,
    vizql_json: dict[str, Any],
    context: ToolContext,
    question: str,
    *,
    limit: int,
) -> dict[str, Any]:
    from services.data_agent.tools.query_tool import _execute_query_with_date_fallback

    result, _effective_vizql, substitutions = await _execute_query_with_date_fallback(
        datasource_luid=datasource_luid,
        vizql_json=vizql_json,
        connection_id=context.connection_id,
        question=question,
        limit=limit,
    )
    if substitutions:
        result = dict(result)
        result["field_substitutions"] = substitutions
    if inspect.isawaitable(result):
        result = await result
    return result


def _vizql_from_queryspec(spec: QuerySpec) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    if spec.time and spec.time.field and spec.time.grain:
        fields.append({"fieldCaption": spec.time.field, "function": spec.time.grain})
    fields.extend({"fieldCaption": dimension} for dimension in spec.dimensions)
    metric_fields = [_metric_to_vizql(metric, _effective_sorts(spec)) for metric in spec.metrics]
    fields.extend(metric_fields)
    return {"fields": fields, "filters": _filters_from_queryspec(spec)}


def _effective_sorts(spec: QuerySpec) -> list[SortSpec]:
    if spec.sort:
        return list(spec.sort)
    if spec.effective_operator != "aggregate" or not spec.metrics:
        return []
    if spec.dimensions and not spec.time:
        metric = spec.metrics[0]
        sort_field = f"{metric.aggregation}({metric.field})" if metric.aggregation else metric.field
        return [SortSpec(field=sort_field, direction="DESC")]
    return []


def _metric_to_vizql(metric: MetricSpec, sorts: list[SortSpec]) -> dict[str, Any]:
    field = {"fieldCaption": metric.field}
    if metric.aggregation:
        field["function"] = metric.aggregation
    sort = _matching_metric_sort(metric, sorts)
    if sort:
        field["sortDirection"] = sort.direction
        field["sortPriority"] = 1
    if metric.alias:
        field["fieldAlias"] = metric.alias
    return field


def _matching_metric_sort(metric: MetricSpec, sorts: list[SortSpec]) -> Optional[SortSpec]:
    expected = (
        f"{metric.aggregation}({metric.field})" if metric.aggregation else metric.field
    ).casefold().replace(" ", "")
    for sort in sorts:
        if sort.field.casefold().replace(" ", "") in {expected, metric.field.casefold().replace(" ", "")}:
            return sort
    return None


def _filters_from_queryspec(spec: QuerySpec) -> list[dict[str, Any]]:
    filters = [_filter_to_vizql(item) for item in spec.filters]
    if spec.time:
        time_filter = _time_filter_to_vizql(spec.time.field, spec.time.range)
        if time_filter:
            filters.append(time_filter)
    return [item for item in filters if item]


def _filter_to_vizql(filter_spec: FilterSpec) -> dict[str, Any]:
    values = filter_spec.values or ([] if filter_spec.value is None else [filter_spec.value])
    if filter_spec.op in {"IN", "=", "=="}:
        return {"field": {"fieldCaption": filter_spec.field}, "filterType": "SET", "values": values}
    return {"field": {"fieldCaption": filter_spec.field}, "filterType": "SET", "values": values}


def _time_filter_to_vizql(field: str, range_spec: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    if not field or not range_spec:
        return None
    value = range_spec.get("value")
    if value and str(value).isdigit() and len(str(value)) == 4:
        year = int(value)
        return _year_date_filter(field, year)
    start = range_spec.get("start") or range_spec.get("from") or range_spec.get("start_year")
    end = range_spec.get("end") or range_spec.get("to") or range_spec.get("end_year")
    if start and end and str(start).isdigit() and str(end).isdigit():
        return {
            "field": {"fieldCaption": field},
            "filterType": "QUANTITATIVE_DATE",
            "quantitativeFilterType": "RANGE",
            "minDate": f"{int(start)}-01-01",
            "maxDate": f"{int(end)}-12-31",
        }
    return None


def _year_date_filter(field: str, year: int) -> dict[str, Any]:
    return {
        "field": {"fieldCaption": field},
        "filterType": "QUANTITATIVE_DATE",
        "quantitativeFilterType": "RANGE",
        "minDate": f"{year}-01-01",
        "maxDate": f"{year}-12-31",
    }


def _query_plan_context(
    spec: QuerySpec,
    ds_info: Mapping[str, Any],
    context: ToolContext,
    question: str,
) -> QueryPlanContext:
    params = dict(spec.params or {})
    params.update(spec.operator_spec or {})
    if spec.limit:
        params.setdefault("n", spec.limit)
        params.setdefault("top_n", spec.limit)
        params.setdefault("top_n_per_dimension", spec.limit)
        params.setdefault("max_groups", spec.limit)
        params.setdefault("max_rows", min(max(spec.limit * 10, 100), 1000))
    if spec.direction:
        params.setdefault("direction", spec.direction)
    if spec.sort:
        params.setdefault("sort_direction", spec.sort[0].direction)
    if spec.time and spec.time.grain:
        params.setdefault("period_function", spec.time.grain)
    if spec.time and spec.time.range:
        params.setdefault("time_range", spec.time.range)
        range_years = _range_years(spec.time.range)
        if range_years:
            params.setdefault("expected_periods", range_years)
    if spec.breakdown_dimensions:
        params.setdefault("candidate_dimensions", spec.breakdown_dimensions)
    if spec.metrics:
        params.setdefault("metrics", [metric.model_dump(mode="json") for metric in spec.metrics])
    if spec.universe:
        params.setdefault("target_dimension", spec.universe.target_dimension)
        params.setdefault("universe_filters", _clause_filters(spec.universe))
    if spec.occurred:
        params.setdefault("occurred_filters", _clause_filters(spec.occurred))
    return QueryPlanContext(
        question=question,
        datasource_luid=str(ds_info.get("luid") or ""),
        datasource_name=str(ds_info.get("name") or ""),
        connection_id=context.connection_id,
        fields=[],
        trace_id=context.trace_id,
        intent="analysis",
        metric=spec.metrics[0].field if spec.metrics else None,
        dimensions=spec.breakdown_dimensions or spec.dimensions,
        time_field=spec.time.field if spec.time else None,
        filters=_filters_from_queryspec(spec),
        operator_hint=spec.effective_operator,
        params=params,
    )


def _clause_filters(clause: Any) -> list[dict[str, Any]]:
    filters = [_filter_to_vizql(item) for item in (clause.filters or [])]
    if clause.time:
        time_filter = _time_filter_to_vizql(clause.time.field, clause.time.range)
        if time_filter:
            filters.append(time_filter)
    return filters


def _normalize_mcp_data(result: Mapping[str, Any], spec: QuerySpec, ds_info: Mapping[str, Any]) -> dict[str, Any]:
    fields = list(result.get("fields") or [])
    rows = [list(row) if isinstance(row, list) else row for row in list(result.get("rows") or [])]
    fields, rows = _append_derived_metric_columns(fields, rows, spec)
    rows = _sort_result_rows(fields, rows, spec)
    return {
        "fields": fields,
        "rows": rows,
        "intent": spec.intent,
        "operator": spec.effective_operator,
        "confidence": 0.95,
        "datasource_name": ds_info.get("name"),
        "datasource_luid": ds_info.get("luid"),
        "queryspec": spec.model_dump(mode="json"),
        "table_display": infer_table_display_schema(
            fields,
            rows,
            operator=spec.effective_operator,
            metric_names=_table_metric_names(spec),
        ),
        **({"field_substitutions": result["field_substitutions"]} if result.get("field_substitutions") else {}),
    }


def _table_metric_names(spec: QuerySpec) -> list[str]:
    names = [metric.field for metric in spec.metrics if metric.field]
    names.extend(metric.name for metric in spec.derived_metrics if metric.name)
    requested = _requested_derived_metrics(spec)
    names.extend(name for name in requested if name not in names)
    return names


def _append_derived_metric_columns(
    fields: list[Any],
    rows: list[Any],
    spec: QuerySpec,
) -> tuple[list[Any], list[Any]]:
    return fields, rows


def _requested_derived_metrics(spec: QuerySpec) -> set[str]:
    names: set[str] = set()
    for metric in spec.derived_metrics:
        if metric.name:
            names.add(metric.name)
    if isinstance(spec.params, Mapping):
        raw = spec.params.get("derived_metrics")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, Mapping) and item.get("name"):
                    names.add(str(item["name"]))
                elif isinstance(item, str):
                    names.add(item)
    if spec.answer_contract:
        names.update(str(item) for item in spec.answer_contract.must_include if item)
    return {name for name in names if name in {"利润率", "客单价"}}


def _sort_result_rows(fields: list[Any], rows: list[Any], spec: QuerySpec) -> list[Any]:
    sorts = _effective_sorts(spec)
    if not sorts or not rows:
        return rows
    display_fields = [_display_field(field) for field in fields]
    sort_idx = _sort_field_index(display_fields, sorts[0].field)
    if sort_idx is None:
        return rows
    reverse = sorts[0].direction.upper() != "ASC"

    valid_rows: list[Any] = []
    missing_rows: list[Any] = []
    for row in rows:
        if isinstance(row, list) and len(row) > sort_idx and row[sort_idx] is not None:
            valid_rows.append(row)
        else:
            missing_rows.append(row)

    numeric_values = [_numeric(row[sort_idx]) for row in valid_rows if isinstance(row, list)]
    numeric_sort = len(numeric_values) == len(valid_rows) and all(value is not None for value in numeric_values)

    def sort_key(row: Any) -> Any:
        value = _numeric(row[sort_idx])
        if numeric_sort and value is not None:
            return value
        return str(row[sort_idx])

    return sorted(valid_rows, key=sort_key, reverse=reverse) + missing_rows


def _sort_field_index(fields: list[str], sort_field: str) -> Optional[int]:
    expected = sort_field.casefold().replace(" ", "")
    for index, field in enumerate(fields):
        normalized = field.casefold().replace(" ", "")
        if normalized == expected:
            return index
        clean = _clean_metric_name(field).casefold().replace(" ", "")
        if clean == expected:
            return index
    return None


def _operator_result_to_data(
    result: OperatorResult,
    ds_info: Mapping[str, Any],
    spec: QuerySpec,
    step_results: Mapping[str, Any],
) -> dict[str, Any]:
    payload = result.to_tool_data(datasource_name=str(ds_info.get("name") or ""))
    payload.update({
        "datasource_luid": ds_info.get("luid"),
        "operator": spec.effective_operator,
        "queryspec": spec.model_dump(mode="json"),
        "mcp_steps": {
            name: {
                "fields": value.get("fields"),
                "row_count": len(value.get("rows") or []),
            }
            for name, value in step_results.items()
            if isinstance(value, Mapping)
        },
    })
    return payload


def _skill_result_summary(result: Any) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "skill_key": result.skill_key,
        "kind": result.kind,
        "checksum": result.checksum,
        "version": result.version,
        "source_path": result.source_path,
        "error": result.error,
    }


def _fallback_payload(
    error_code: str,
    message: str,
    user_hint: str,
    trace_id: str,
    intent_result: IntentClassification,
    *,
    fallback_type: str = "query_plan_unavailable",
    detail: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    tools_used = ["intent_classifier", "llm_queryspec", "queryspec_validator"]
    if fallback_type != "query_plan_rejected":
        tools_used = [
            "intent_classifier",
            "llm_queryspec",
            "queryspec_fallback",
            "queryspec_validator",
            "tableau_mcp",
            "answer_renderer",
        ]
    return {
        "fallback_type": fallback_type,
        "error_code": error_code,
        "message": message,
        "user_hint": user_hint,
        "trace_id": trace_id,
        "retryable": True,
        "suggested_actions": ["请补充指标、时间范围、维度或筛选条件后重试。"],
        "tools_used": tools_used,
        "intent_classifier": intent_result.to_dict(),
        "controlled_chain": {"status": "failed", "detail": detail or {}},
    }


def _queryspec_fallback_enabled() -> bool:
    return str(os.getenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _normalize_mcp_handled_metrics(
    spec: QuerySpec,
    question: str,
    queryable_fields: Optional[list[Any]] = None,
) -> QuerySpec:
    """Let MCP-owned calculation fields execute without an extra aggregate wrapper."""

    requested = _explicit_mcp_handled_metrics_in_question(question)
    if not requested:
        return spec

    available_fields = [_field_caption(field) for field in queryable_fields or []]
    payload = spec.model_dump(mode="json")
    metrics = list(payload.get("metrics") or [])
    changed = False
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        field = str(metric.get("field") or "")
        if _mcp_handles_metric_field(field, requested, available_fields):
            if metric.get("aggregation") is not None:
                metric["aggregation"] = None
                changed = True

    if not changed:
        return spec

    payload["metrics"] = metrics
    payload["sort"] = _normalize_mcp_handled_metric_sorts(list(payload.get("sort") or []), requested)
    answer_contract = dict(payload.get("answer_contract") or {})
    must_include = list(answer_contract.get("must_include") or [])
    for name in requested:
        if name not in must_include:
            must_include.append(name)
    answer_contract["must_include"] = must_include
    payload["answer_contract"] = answer_contract
    return QuerySpec.model_validate(payload)


def _explicit_mcp_handled_metrics_in_question(question: str) -> set[str]:
    compact = re.sub(r"\s+", "", question or "")
    requested: set[str] = set()
    if "利润率" in compact or "毛利率" in compact:
        requested.add("利润率")
    if "客单价" in compact or "平均客单" in compact:
        requested.add("客单价")
    return requested


def _mcp_handles_metric_field(field: str, requested: set[str], available_fields: list[str]) -> bool:
    if not any(field == available for available in available_fields):
        return False
    metric_names = _metric_semantic_names(field, None)
    return bool(metric_names.intersection(requested))


def _field_caption(field: Any) -> str:
    if isinstance(field, Mapping):
        for key in ("caption", "fieldCaption", "name", "field", "label"):
            value = field.get(key)
            if value:
                return str(value)
        return ""
    return str(field or "")


def _normalize_mcp_handled_metric_sorts(
    sorts: list[Mapping[str, Any]],
    requested: set[str],
) -> list[dict[str, Any]]:
    next_sorts: list[dict[str, Any]] = []
    for sort in sorts:
        item = dict(sort)
        field = str(item.get("field") or "")
        for name in requested:
            if name in field:
                item["field"] = name
        next_sorts.append(item)
    return next_sorts


def _metric_semantic_names(field: str, aggregation: str) -> set[str]:
    normalized = re.sub(r"\s+", "", str(field or "")).lower()
    names: set[str] = set()
    if any(token in normalized for token in ("销售额", "销售金额", "营收", "收入")):
        names.add("销售额")
    if "利润率" in normalized:
        names.add("利润率")
    elif any(token in normalized for token in ("利润", "毛利")):
        names.add("利润")
    if "客单价" in normalized:
        names.add("客单价")
    if any(token in normalized for token in ("客户数", "客户数量", "客户名称", "客户id", "客户编号", "客户")):
        if str(aggregation or "").upper() in {"COUNT", "COUNTD"}:
            names.add("客户数")
    return names


def _build_fallback_queryspec(
    *,
    question: str,
    intent_result: IntentClassification,
    datasource: Mapping[str, Any],
    queryable_fields: list[str],
    analysis_context: Optional[Mapping[str, Any]],
    reason: str,
) -> Optional[dict[str, Any]]:
    try:
        return build_fallback_queryspec(
            question=question,
            intent_result=intent_result,
            datasource=datasource,
            queryable_fields=queryable_fields,
            analysis_context=analysis_context,
            reason=reason,
        )
    except Exception:
        logger.warning("deterministic QuerySpec fallback failed", exc_info=True)
        return None


def _queryspec_replacement_reason(
    question: str,
    intent_result: IntentClassification,
    spec: QuerySpec,
    analysis_context: Optional[Mapping[str, Any]],
) -> Optional[str]:
    if spec.source == "deterministic_fallback":
        return None
    if spec.raw_rows or spec.detail_scan or str(spec.result_shape or "").lower() == "detail_table":
        return "llm_queryspec_requested_detail_scan"
    expected_operator = infer_fallback_operator(question, intent_result.intent)
    if spec.effective_operator == "asset_inventory" and expected_operator != "asset_inventory":
        return "llm_queryspec_routed_data_question_to_asset_inventory"
    semantic_expected = {
        "set_difference",
        "trend_condition",
        "all_period_condition",
        "root_cause",
        "customer_record",
        "ranking",
    }
    if expected_operator in semantic_expected and spec.effective_operator != expected_operator:
        return f"llm_queryspec_operator_mismatch:{spec.effective_operator}->{expected_operator}"
    if analysis_context and re.search(r"(继续|拆分|过去|趋势|每年|年份)", question):
        has_context = bool(analysis_context.get("metric_names") or analysis_context.get("dimension_names"))
        if has_context and not spec.time and re.search(r"(过去|趋势|每年|年份)", question):
            return "llm_queryspec_missing_followup_time_context"
    return None


def _should_prefer_deterministic_queryspec(
    question: str,
    intent_result: IntentClassification,
    analysis_context: Optional[Mapping[str, Any]],
) -> bool:
    expected_operator = infer_fallback_operator(question, intent_result.intent)
    if expected_operator != "aggregate":
        return True
    if analysis_context and (
        analysis_context.get("metric_names")
        or analysis_context.get("metrics")
        or analysis_context.get("dimension_names")
        or analysis_context.get("dimensions")
        or analysis_context.get("time")
    ):
        if re.search(r"(继续|拆分|过去|趋势|每年|年份)", question):
            return True
    return False


def _range_years(range_spec: Mapping[str, Any]) -> list[int]:
    start = range_spec.get("start") or range_spec.get("from") or range_spec.get("start_year")
    end = range_spec.get("end") or range_spec.get("to") or range_spec.get("end_year")
    if start is not None and end is not None and str(start).isdigit() and str(end).isdigit():
        return list(range(int(start), int(end) + 1))
    value = range_spec.get("value")
    return [int(value)] if value is not None and str(value).isdigit() else []


def _render_deterministic_answer(mcp_data: Mapping[str, Any], spec: QuerySpec) -> str:
    rows = list(mcp_data.get("rows") or [])
    fields = [_display_field(field) for field in (mcp_data.get("fields") or [])]
    row_count = len(rows)
    if not rows:
        return "当前条件下没有查询到匹配结果。"

    prefix = "" if row_count > 1 else "基于 Tableau MCP 聚合结果，"
    derived = _derived_metric_sentence(fields, rows[0])
    if derived:
        return f"{prefix}{derived}"

    summary = _multirow_summary(fields, rows, spec)
    return f"{prefix}{summary}详细数据见下方表格。"


def _answer_replacement_reason(
    rendered: str,
    mcp_data: Mapping[str, Any],
    spec: QuerySpec,
    question: str,
) -> Optional[str]:
    rows = list(mcp_data.get("rows") or [])
    if rows and any(token in rendered for token in ("无法直接回答", "无法回答", "没有包含", "缺少维度", "请确认查询")):
        return "answer_renderer_contradicts_available_data"
    if "省" not in question and "地区" not in question and rows and any(token in rendered for token in ("省份", "地区维度")):
        return "answer_renderer_introduced_unasked_dimension"
    if spec.answer_contract and spec.answer_contract.must_include:
        missing = [
            item
            for item in spec.answer_contract.must_include
            if item and str(item) not in rendered and _metric_alias(str(item)) not in rendered
        ]
        if missing and rows:
            return "answer_renderer_missed_required_terms"
    return None


def _metric_alias(value: str) -> str:
    aliases = {
        "客户名称": "客户",
        "COUNTD(客户名称)": "客户数",
        "销售额": "销售",
        "利润率": "利润率",
        "客单价": "客单价",
    }
    return aliases.get(value, value)


def _multirow_summary(fields: list[str], rows: list[list[Any]], spec: QuerySpec) -> str:
    operator = spec.effective_operator
    if operator == "aggregate" and spec.time and spec.time.grain:
        return _time_aggregate_summary(fields, rows, spec)
    if operator == "aggregate":
        return _grouped_aggregate_summary(fields, spec)
    if operator == "ranking":
        return _ranking_summary(fields, rows, spec)
    if operator == "set_difference":
        return _set_difference_summary(fields, rows, spec)
    if operator in {"trend_condition", "all_period_condition"}:
        return _condition_summary(fields, rows, operator)
    if operator == "root_cause":
        return _root_cause_summary(fields, rows)
    return ""


def _grouped_aggregate_summary(fields: list[str], spec: QuerySpec) -> str:
    dimensions = spec.dimensions or [
        field for field in fields if not _is_metric_field(field) and field not in _requested_derived_metrics(spec)
    ]
    metrics = [_clean_metric_name(field) for field in fields if _is_metric_field(field)]
    for derived in _requested_derived_metrics(spec):
        if any(derived in field for field in fields) and derived not in metrics:
            metrics.append(derived)
    if not dimensions or not metrics:
        return ""
    return f"已按{'、'.join(dimensions)}汇总{'、'.join(metrics)}。"


def _time_aggregate_summary(fields: list[str], rows: list[list[Any]], spec: QuerySpec) -> str:
    time_idx = _time_index(fields)
    metric_idx = _primary_metric_index(fields, spec)
    if time_idx is None or metric_idx is None:
        return ""

    points: list[tuple[Any, float]] = []
    for row in rows:
        if len(row) <= max(time_idx, metric_idx):
            continue
        value = _numeric(row[metric_idx])
        if value is not None:
            points.append((row[time_idx], value))
    if len(points) < 2:
        return ""

    points.sort(key=lambda item: item[0])
    first_period, first_value = points[0]
    last_period, last_value = points[-1]
    peak_period, peak_value = max(points, key=lambda item: item[1])
    metric_name = _clean_metric_name(fields[metric_idx])
    direction = "上升" if last_value >= first_value else "下降"
    delta = last_value - first_value
    return (
        f"{metric_name}从 {first_period} 年的 {_format_value(first_value)} "
        f"{direction}到 {last_period} 年的 {_format_value(last_value)}，"
        f"变化 {_format_value(delta)}；最高年份是 {peak_period} 年，"
        f"达到 {_format_value(peak_value)}。"
    )


def _ranking_summary(fields: list[str], rows: list[list[Any]], spec: QuerySpec) -> str:
    if not rows or not fields:
        return ""
    dimension_idx = _first_dimension_index(fields)
    metric_idx = _primary_metric_index(fields, spec)
    if dimension_idx is None or metric_idx is None:
        return ""
    snippets = []
    for row in rows[:3]:
        if len(row) <= max(dimension_idx, metric_idx):
            continue
        snippets.append(f"{row[dimension_idx]}（{_format_value(row[metric_idx])}）")
    return f"Top{len(snippets)} 为：" + "、".join(snippets) + "。" if snippets else ""


def _set_difference_summary(fields: list[str], rows: list[list[Any]], spec: QuerySpec) -> str:
    target = spec.universe.target_dimension if spec.universe else (fields[0] if fields else "对象")
    values = [str(row[0]) for row in rows[:10] if row]
    if len(rows) <= 10 and values:
        return f"共有 {len(rows)} 个{target}满足条件：" + "、".join(values) + "。"
    return f"共有 {len(rows)} 个{target}满足条件。"


def _condition_summary(fields: list[str], rows: list[list[Any]], operator: str) -> str:
    dimension_idx = _field_index(fields, "dimension")
    if dimension_idx is None:
        dimension_idx = 0 if fields else None
    if dimension_idx is None:
        return ""
    values = [str(row[dimension_idx]) for row in rows[:10] if len(row) > dimension_idx]
    label = "持续趋势条件" if operator == "trend_condition" else "每期条件"
    if len(rows) <= 10 and values:
        return f"共有 {len(rows)} 个对象满足{label}：" + "、".join(values) + "。"
    return f"共有 {len(rows)} 个对象满足{label}。"


def _root_cause_summary(fields: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    dimension_idx = _field_index(fields, "dimension")
    segment_idx = _field_index(fields, "segment")
    metric_idx = _last_numeric_index(fields, rows)
    if dimension_idx is None or segment_idx is None or metric_idx is None:
        return ""
    snippets = []
    for row in rows[:3]:
        if len(row) <= max(dimension_idx, segment_idx, metric_idx):
            continue
        snippets.append(f"{row[dimension_idx]}={row[segment_idx]}（{_format_value(row[metric_idx])}）")
    return "主要贡献项为：" + "、".join(snippets) + "。" if snippets else ""


def _derived_metric_sentence(fields: list[str], row: list[Any]) -> str:
    if len(fields) > 1 and len(row) == len(fields) and any(not _is_metric_field(field) for field in fields):
        return ""
    if any(not _is_metric_field(field) for field in fields):
        return ""
    if len(row) != len(fields):
        return ""
    values = {field: row[index] for index, field in enumerate(fields)}
    sales = _first_numeric_by_token(values, "销售额")
    profit = _first_numeric_by_token(values, "利润")
    customers = _first_numeric_by_token(values, "客户")
    parts: list[str] = []
    if sales is not None:
        parts.append(f"销售额 {_format_value(sales)}")
    if profit is not None:
        parts.append(f"利润 {_format_value(profit)}")
    if customers is not None:
        parts.append(f"客户数 {_format_value(customers)}")
    return "，".join(parts) + "。" if parts else ""


def _is_metric_field(field: str) -> bool:
    normalized = field.upper()
    return any(token in normalized for token in ("SUM(", "AVG(", "COUNT", "MIN(", "MAX(", "MEDIAN("))


def _time_index(fields: list[str]) -> Optional[int]:
    for index, field in enumerate(fields):
        if any(token in field.upper() for token in ("YEAR(", "QUARTER(", "MONTH(", "WEEK(", "DAY(")):
            return index
    return None


def _primary_metric_index(fields: list[str], spec: QuerySpec) -> Optional[int]:
    metric_fields = [metric.field for metric in spec.metrics]
    for metric_name in metric_fields:
        for index, field in enumerate(fields):
            if metric_name and metric_name in field and _is_metric_field(field):
                return index
    for token in ("销售额", "利润"):
        for index, field in enumerate(fields):
            if token in field and _is_metric_field(field):
                return index
    return _last_numeric_metric_field_index(fields)


def _last_numeric_metric_field_index(fields: list[str]) -> Optional[int]:
    for index in range(len(fields) - 1, -1, -1):
        if _is_metric_field(fields[index]):
            return index
    return None


def _last_numeric_index(fields: list[str], rows: list[list[Any]]) -> Optional[int]:
    max_len = max((len(row) for row in rows), default=0)
    for index in range(min(len(fields), max_len) - 1, -1, -1):
        if any(len(row) > index and _numeric(row[index]) is not None for row in rows[:5]):
            return index
    return None


def _first_dimension_index(fields: list[str]) -> Optional[int]:
    for index, field in enumerate(fields):
        if not _is_metric_field(field) and index != _time_index(fields):
            return index
    return None


def _field_index(fields: list[str], expected: str) -> Optional[int]:
    expected_norm = expected.casefold()
    for index, field in enumerate(fields):
        if expected_norm in field.casefold():
            return index
    return None


def _clean_metric_name(field: str) -> str:
    match = re.match(r"^\s*(SUM|AVG|COUNT|COUNTD|MIN|MAX|MEDIAN)\((.+)\)\s*$", field, flags=re.IGNORECASE)
    return match.group(2) if match else field


def _first_numeric_by_token(values: Mapping[str, Any], token: str) -> Optional[float]:
    for field, value in values.items():
        if token in field:
            return _numeric(value)
    return None


def _numeric(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _format_value(value: Any) -> str:
    number = _numeric(value)
    if number is None:
        return str(value)
    if abs(number) >= 100:
        return f"{number:,.2f}"
    return f"{number:.4g}"


def _display_field(field: Any) -> str:
    if isinstance(field, Mapping):
        return str(field.get("name") or field.get("fieldAlias") or field.get("fieldCaption") or "")
    return str(field or "")


def _redact_large(value: Any) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)[:1000]
    if len(encoded) <= 2000:
        return value
    return {"truncated": True, "preview": encoded[:2000]}
