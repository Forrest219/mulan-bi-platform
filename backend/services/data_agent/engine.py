"""Data Agent ReAct Engine — 核心推理循环

Spec: docs/specs/36-data-agent-architecture-spec.md §3.3
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

from .tool_base import ToolContext, ToolRegistry, ToolResult
from .response import AgentEvent
from .prompts import build_react_system_prompt
from .intent.keyword_match import is_chart_request as _is_chart_request

logger = logging.getLogger(__name__)


# 默认约束
DEFAULT_MAX_STEPS = 20
DEFAULT_STEP_TIMEOUT = 30  # 秒
DEFAULT_TOTAL_TIMEOUT = 300  # 秒
DEFAULT_MAX_TOOL_RETRIES = 1
DEFAULT_MAX_HISTORY_TOKENS = 8000


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数：CJK 字符 ≈ 每字 1 token，ASCII ≈ 每 4 字符 1 token。"""
    cjk_count = sum(1 for c in text if '一' <= c <= '鿿')
    ascii_count = len(text) - cjk_count
    return cjk_count + (ascii_count // 4) + 1


def _truncate_history(messages: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
    """截断历史消息以控制在 token 预算内。

    策略：从最旧的消息开始移除，始终保留最近 2 条消息。
    截断发生时在开头插入 [历史已截断] 标记。
    """
    if not messages:
        return messages

    # 计算总 token 数
    total_tokens = sum(
        _estimate_tokens(msg.get("content", ""))
        for msg in messages
    )

    if total_tokens <= max_tokens:
        return messages

    # 始终保留最近 2 条消息
    min_keep = min(2, len(messages))
    kept_tail = messages[-min_keep:]

    # 从保留的尾部开始，向前逐条添加，直到超出预算
    tail_tokens = sum(
        _estimate_tokens(msg.get("content", ""))
        for msg in kept_tail
    )

    result = []
    remaining_budget = max_tokens - tail_tokens

    # 从倒数第 min_keep+1 条开始，向前遍历（越靠后越新，优先保留）
    middle = messages[:-min_keep] if min_keep > 0 else []
    for msg in reversed(middle):
        msg_tokens = _estimate_tokens(msg.get("content", ""))
        if remaining_budget >= msg_tokens:
            result.insert(0, msg)
            remaining_budget -= msg_tokens
        else:
            break  # 预算不够，停止添加更旧的消息

    # 如果发生了截断（result 比 middle 短），插入标记
    if len(result) < len(middle):
        truncation_marker = {
            "role": "system",
            "content": "[历史已截断]",
        }
        result.insert(0, truncation_marker)

    result.extend(kept_tail)
    return result


class ReActEngine:
    """ReAct 循环引擎：Think → Act → Observe → 重复直到完成

    Args:
        registry: ToolRegistry 实例
        llm_service: LLM 服务（需有 async complete(prompt, system, timeout, purpose) 方法）
    """

    def __init__(
        self,
        registry: ToolRegistry,
        llm_service,
        max_steps: int = DEFAULT_MAX_STEPS,
        step_timeout: int = DEFAULT_STEP_TIMEOUT,
        total_timeout: int = DEFAULT_TOTAL_TIMEOUT,
        max_tool_retries: int = DEFAULT_MAX_TOOL_RETRIES,
        max_history_tokens: int = DEFAULT_MAX_HISTORY_TOKENS,
        wrapper=None,
    ):
        self.registry = registry
        self.llm = llm_service
        self.max_steps = max_steps
        self.step_timeout = step_timeout
        self.total_timeout = total_timeout
        self.max_tool_retries = max_tool_retries
        self.max_history_tokens = max_history_tokens
        self._wrapper = wrapper

    async def run(
        self,
        query: str,
        context: ToolContext,
        session: Optional[Any] = None,
        force_first_tool: Optional[str] = None,
        force_first_params: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """执行 ReAct 循环，yield 流式事件

        Args:
            query: 用户问题
            context: 工具执行上下文
            session: 可选会话对象（用于加载历史消息）
        """
        start_time = time.time()
        step_count = 0
        tools_used: List[str] = []

        # 构建 system prompt（尝试注入数据源字段上下文，让 LLM 直接生成 VizQL）
        tool_descriptions = self.registry.get_tool_descriptions()
        datasource_context = None
        if context.connection_id:
            try:
                from services.llm.nlq_service import route_datasource, get_datasource_fields_cached
                _ds = route_datasource(query, connection_id=context.connection_id)
                if _ds and _ds.get("asset_id"):
                    _fields = get_datasource_fields_cached(_ds["asset_id"])
                    datasource_context = {
                        "luid": _ds["luid"],
                        "name": _ds["name"],
                        "fields": _fields,
                    }
            except Exception as _e:
                logger.debug("engine: datasource pre-load skipped: %s", _e)
        system_prompt = build_react_system_prompt(tool_descriptions, datasource_context=datasource_context)

        # 构建历史消息
        history_messages = _build_history_messages(session)

        for step in range(self.max_steps):
            step_count += 1

            # 阶段性超时检查
            if time.time() - start_time >= self.total_timeout:
                yield AgentEvent(
                    type="answer",
                    content="已达到最大执行时间，基于当前信息给出回答...",
                )
                return

            # ── 强制首步（直接查询快速路径）──────────────────────────────
            # 跳过 LLM Think，直接执行指定工具；工具结果注入 history 后
            # 进入下一步的正常 LLM Think（此时 LLM 拿到数据，通常直接 final_answer）
            if force_first_tool and step == 0:
                tool = self.registry.get(force_first_tool)
                if tool:
                    params = force_first_params or {"question": query}
                    yield AgentEvent(type="tool_call", content={"tool": force_first_tool, "params": params})
                    forced_result = await self._execute_tool_with_retry(
                        tool=tool,
                        tool_name=force_first_tool,
                        tool_params=params,
                        context=context,
                        start_time=start_time,
                    )
                    if isinstance(forced_result, ToolResult):
                        result_data: Dict[str, Any] = {"success": forced_result.success, "data": forced_result.data}
                        if not forced_result.success:
                            result_data["error"] = forced_result.error
                    else:
                        result_data = forced_result if isinstance(forced_result, dict) else {"data": forced_result}
                    yield AgentEvent(type="tool_result", content={"tool": force_first_tool, "result": result_data})
                    history_messages.append({
                        "role": "assistant",
                        "content": json.dumps({
                            "action": "tool_call",
                            "tool_name": force_first_tool,
                            "tool_params": params,
                            "reasoning": "直接查询快速路径",
                        }, ensure_ascii=False),
                    })
                    history_messages.append({
                        "role": "tool",
                        "name": force_first_tool,
                        "content": json.dumps(result_data, ensure_ascii=False),
                    })
                    if force_first_tool not in tools_used:
                        tools_used.append(force_first_tool)
                    # 工具成功 → 直接生成答案，完全跳过 LLM Think
                    if isinstance(forced_result, ToolResult) and forced_result.success:
                        # Emit structured table data before the text answer so the frontend
                        # can render a native table component instead of a Markdown table.
                        _data = result_data.get("data") or {}
                        _fields = _data.get("fields", [])
                        _rows = _data.get("rows", [])
                        if _rows:
                            yield AgentEvent(
                                type="table_data",
                                content={
                                    "fields": _fields,
                                    "rows": _rows,
                                    "col_types": _infer_col_types(_fields, _rows),
                                },
                            )
                            _is_chart, _chart_type = _is_chart_request(query)
                            if _is_chart:
                                yield AgentEvent(
                                    type="chart_data",
                                    content=_build_chart_data(
                                        _fields, _rows, _infer_col_types(_fields, _rows), _chart_type
                                    ),
                                )
                        yield AgentEvent(type="answer", content=_format_direct_answer(query, result_data))
                        return
                    continue  # 工具失败时走正常 LLM Think 尝试恢复

            # 1. Think：LLM 推理下一步
            think_result = await self._think(
                query=query,
                history=history_messages,
                system_prompt=system_prompt,
                context=context,
                step=step_count,
                connection_id=context.connection_id,
                connection_name=context.connection_name,
                connection_type=context.connection_type,
            )

            if think_result.get("error"):
                error_code = think_result.get("error_code", "AGENT_006")
                yield AgentEvent(type="error", content={
                    "error_code": error_code,
                    "message": think_result["error"],
                })
                return

            reasoning = think_result.get("reasoning", "")
            yield AgentEvent(type="thinking", content=reasoning)

            action = think_result.get("action", "final_answer")

            # 2. 判断是否可以直接回答
            if action == "final_answer":
                answer = think_result.get("answer", "")
                yield AgentEvent(type="answer", content=answer)
                return

            # 3. Act：调用工具
            tool_name = think_result.get("tool_name", "")
            tool_params = think_result.get("tool_params", {})

            if not tool_name:
                yield AgentEvent(type="error", content={"error": "LLM 未返回 tool_name"})
                return

            # 检查工具是否存在
            if tool_name not in self.registry:
                yield self._make_error_event(
                    error_code="AGENT_003",
                    message=f"工具不存在: {tool_name}",
                    context=context,
                    extra={"step": step_count, "last_tool": tool_name},
                )
                return

            tool = self.registry.get(tool_name)

            if _HAS_JSONSCHEMA and tool.parameters_schema and tool_params:
                try:
                    jsonschema.validate(instance=tool_params, schema=tool.parameters_schema)
                except jsonschema.ValidationError as ve:
                    yield self._make_error_event(
                        error_code="AGENT_002",
                        message=f"工具参数校验失败: {ve.message}",
                        context=context,
                        extra={"tool": tool_name, "step": step_count},
                    )
                    return

            yield AgentEvent(
                type="tool_call",
                content={"tool": tool_name, "params": tool_params},
            )

            # 4. 执行工具（含重试 + 超时）
            result = await self._execute_tool_with_retry(
                tool=tool,
                tool_name=tool_name,
                tool_params=tool_params,
                context=context,
                start_time=start_time,
            )

            # 5. Observe：记录结果
            if isinstance(result, ToolResult):
                result_data: Dict[str, Any] = {"success": result.success, "data": result.data}
                if not result.success:
                    result_data["error"] = result.error
            elif isinstance(result, dict) and result.get("error_code"):
                # 是错误响应
                yield AgentEvent(type="error", content=result)
                result_data = {"success": False, "error": result.get("message", "")}
            else:
                result_data = result if isinstance(result, dict) else {"data": result}

            yield AgentEvent(
                type="tool_result",
                content={"tool": tool_name, "result": result_data},
            )

            # 更新历史
            history_messages.append({
                "role": "assistant",
                "content": json.dumps({
                    "action": "tool_call",
                    "tool_name": tool_name,
                    "tool_params": tool_params,
                    "reasoning": reasoning,
                }, ensure_ascii=False),
            })
            history_messages.append({
                "role": "tool",
                "name": tool_name,
                "content": json.dumps(result_data, ensure_ascii=False),
            })

            # 记录工具使用
            if tool_name not in tools_used:
                tools_used.append(tool_name)

        # 6. 达到 max_steps 上限
        yield AgentEvent(
            type="answer",
            content="已达到最大推理步数，基于当前信息给出回答...",
        )

    async def _think(
        self,
        query: str,
        history: List[Dict[str, Any]],
        system_prompt: str,
        context: ToolContext,
        step: int,
        connection_id: Optional[int] = None,
        connection_name: Optional[str] = None,
        connection_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """调用 LLM 进行推理决策"""
        # 构造 prompt
        prompt = _build_think_prompt(
            query, history, step, self.max_history_tokens,
            connection_id=connection_id,
            connection_name=connection_name,
            connection_type=connection_type,
        )

        # 调用 LLM
        try:
            # 优先通过 wrapper.invoke(llm_complete) 调用，fallback 到 self.llm.complete
            if self._wrapper is not None:
                try:
                    result = await self._wrapper.invoke(
                        principal={"id": context.user_id, "role": "analyst"},
                        capability_name="llm_complete",
                        params={
                            "prompt": prompt,
                            "system": system_prompt,
                            "timeout": self.step_timeout,
                            "purpose": "agent",
                        },
                        trace_id=context.trace_id or None,
                    )
                    # wrapper 返回 CapabilityResult，取 .data
                    result_data = result.data if hasattr(result, "data") else result
                except Exception as e:
                    logger.warning("wrapper.invoke(llm_complete) failed, falling back to llm.complete: %s", e)
                    result_data = await self.llm.complete(
                        prompt=prompt,
                        system=system_prompt,
                        timeout=self.step_timeout,
                        purpose="agent",
                    )
            else:
                # purpose 优先用 "agent"，若无则 fallback 到 "general"
                try:
                    result_data = await self.llm.complete(
                        prompt=prompt,
                        system=system_prompt,
                        timeout=self.step_timeout,
                        purpose="agent",
                    )
                except Exception as e:
                    logger.warning("LLM purpose='agent' failed, falling back to 'general': %s", e)
                    result_data = await self.llm.complete(
                        prompt=prompt,
                        system=system_prompt,
                        timeout=self.step_timeout,
                        purpose="general",
                    )
        except Exception as e:
            logger.exception("LLM 调用失败")
            return {"error": "LLM 服务暂时不可用", "error_code": "AGENT_006"}

        if "error" in result_data:
            return {"error": result_data["error"], "error_code": "AGENT_006"}

        content = result_data.get("content", "")
        if not content.strip():
            return {"error": "无法理解用户意图", "error_code": "AGENT_002"}
        return self._parse_llm_response(content)

    def _parse_llm_response(self, content: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON 决策"""
        import re
        # 去掉 markdown 代码围栏（```json ... ```）
        stripped = re.sub(r'^```\w*\s*', '', content.strip())
        stripped = re.sub(r'\s*```$', '', stripped).strip()

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as e1:
            try:
                # LLM 有时在 JSON 字符串值内输出真实换行符而非 \n，strict=False 容许此行为
                data = json.JSONDecoder(strict=False).decode(stripped)
            except (json.JSONDecodeError, ValueError) as e2:
                logger.warning(
                    "_parse_llm_response: JSON parse failed. strict err=%s | strict=False err=%s | stripped[:200]=%r",
                    e1, e2, stripped[:200],
                )
                # 第三层 fallback：长 markdown 答案中可能含有未转义的 "，用 regex 逐字段提取
                extracted = self._extract_from_malformed_json(stripped)
                if extracted:
                    return extracted
                return self._parse_text_response(content)

        action = data.get("action", "final_answer")
        return {
            "action": action,
            "tool_name": data.get("tool_name", ""),
            "tool_params": data.get("tool_params", {}),
            "reasoning": data.get("reasoning", ""),
            "answer": data.get("answer", ""),
        }

    def _extract_from_malformed_json(self, stripped: str) -> Optional[Dict[str, Any]]:
        """从含未转义引号的 JSON 字符串中逐字段提取关键值（第三层 fallback）。

        适用场景：LLM 在 answer 字段内含有字面量 "，导致 JSON 解析失败。
        action/tool_name 均为简单关键字，不含嵌套引号，可安全用 regex 提取。
        answer 是最后一个字段，通过定位起始 " 并裁剪末尾 "} 来还原完整内容。
        """
        import re
        action_m = re.search(r'"action"\s*:\s*"([^"]+)"', stripped)
        if not action_m:
            return None
        action = action_m.group(1)

        reasoning_m = re.search(r'"reasoning"\s*:\s*"([^"]*)"', stripped)
        reasoning = reasoning_m.group(1) if reasoning_m else ""

        if action == "final_answer":
            ans_m = re.search(r'"answer"\s*:\s*"', stripped)
            if ans_m:
                raw = stripped[ans_m.end():]
                # answer 是 JSON 最后一个字段，裁去末尾的 closing " 和 }
                answer = re.sub(r'"\s*\}?\s*$', '', raw, flags=re.DOTALL)
                # 还原 JSON 字符串转义序列（json.loads 跳过时这些仍是原始字节）
                # 顺序：先还原 \\ 避免二次替换
                answer = (
                    answer
                    .replace('\\\\', '\x00BSLASH\x00')  # 占位符保护真实反斜杠
                    .replace('\\"', '"')
                    .replace('\\n', '\n')
                    .replace('\\r', '\r')
                    .replace('\\t', '\t')
                    .replace('\x00BSLASH\x00', '\\')
                )
                return {
                    "action": "final_answer",
                    "tool_name": "",
                    "tool_params": {},
                    "reasoning": reasoning,
                    "answer": answer,
                }

        elif action == "tool_call":
            tool_m = re.search(r'"tool_name"\s*:\s*"([^"]*)"', stripped)
            tool_name = tool_m.group(1) if tool_m else ""
            return {
                "action": "tool_call",
                "tool_name": tool_name,
                "tool_params": {},
                "reasoning": reasoning,
                "answer": "",
            }

        return None

    def _parse_text_response(self, content: str) -> Dict[str, Any]:
        """从非 JSON 文本中提取决策信息（最终 fallback）"""
        import re
        tool_match = re.search(r'"tool_name"\s*:\s*"([^"]+)"', content)

        if tool_match:
            return {
                "action": "tool_call",
                "tool_name": tool_match.group(1),
                "tool_params": {},
                "reasoning": content[:200],
                "answer": "",
            }
        else:
            return {
                "action": "final_answer",
                "tool_name": "",
                "tool_params": {},
                "reasoning": "",
                "answer": content[:500] if content else "抱歉，我无法理解您的问题。",
            }

    async def _execute_tool_with_retry(
        self,
        tool,
        tool_name: str,
        tool_params: Dict[str, Any],
        context: ToolContext,
        start_time: float,
    ) -> Union[Dict[str, Any], ToolResult]:
        """执行工具，支持重试和超时"""

        for attempt in range(self.max_tool_retries + 1):
            try:
                # 使用 asyncio.wait_for 实现超时
                result = await asyncio.wait_for(
                    tool.execute(tool_params, context),
                    timeout=self.step_timeout,
                )
                return result
            except asyncio.TimeoutError:
                logger.warning("工具 %s 执行超时（step %ds）", tool_name, self.step_timeout)
                if attempt < self.max_tool_retries:
                    continue
                return {
                    "error_code": "AGENT_001",
                    "message": f"工具执行超时: {tool_name}",
                    "detail": {
                        "tool": tool_name,
                        "timeout_seconds": self.step_timeout,
                    },
                }
            except Exception as e:
                logger.warning("工具 %s 执行失败（attempt %d/%d）: %s", tool_name, attempt + 1, self.max_tool_retries + 1, e)
                if attempt < self.max_tool_retries:
                    continue
                # 重试耗尽，返回 error dict 以便 run() 发出 error 事件
                return {
                    "error_code": "AGENT_003",
                    "message": "工具执行失败",
                    "detail": {
                        "tool": tool_name,
                        "reason": "工具执行异常",
                    },
                }

        # 不应到达这里
        return {
            "error_code": "AGENT_003",
            "message": "工具执行失败",
            "detail": {"tool": tool_name},
        }

    def _make_error_event(
        self,
        error_code: str,
        message: str,
        context: ToolContext,
        extra: Optional[Dict[str, Any]] = None,
    ) -> AgentEvent:
        content: Dict[str, Any] = {
            "error_code": error_code,
            "message": message,
        }
        if extra:
            content["detail"] = extra
        if context.trace_id:
            content["trace_id"] = context.trace_id
        return AgentEvent(type="error", content=content)


def _build_think_prompt(
    query: str,
    history: List[Dict[str, Any]],
    step: int,
    max_history_tokens: int = DEFAULT_MAX_HISTORY_TOKENS,
    connection_id: Optional[int] = None,
    connection_name: Optional[str] = None,
    connection_type: Optional[str] = None,
) -> str:
    """构建 Think 阶段的 prompt"""
    prompt_parts = [
        f"用户问题：{query}",
        f"当前推理步：{step}",
    ]

    if connection_id:
        conn_desc = f"当前数据连接：{connection_name or '未知'}（ID={connection_id}，类型={connection_type or '未知'}）"
        prompt_parts.append(conn_desc)
        prompt_parts.append("请基于此连接回答用户问题。调用工具时无需额外指定 connection_id，系统会自动使用当前连接。")

    if history:
        truncated = _truncate_history(history[-10:], max_history_tokens)
        prompt_parts.append("历史对话：")
        for msg in truncated:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "tool":
                name = msg.get("name", "unknown")
                prompt_parts.append(f"[工具 {name} 返回]: {content[:4000]}")
            else:
                prompt_parts.append(f"[{role}]: {content[:500]}")

    prompt_parts.append("请根据以上信息，决定下一步操作。")
    return "\n".join(prompt_parts)


def _format_direct_answer(query: str, result_data: dict) -> str:
    """为直接查询结果生成摘要行（结构化表格数据由 table_data 事件传给前端）"""
    data = result_data.get("data") or {}
    rows = data.get("rows", [])
    ds_name = data.get("datasource_name", "")
    row_count = len(rows)

    if not row_count:
        hint = f"数据源「{ds_name}」" if ds_name else "数据源"
        return f"在{hint}中未查询到符合条件的数据，请确认筛选条件是否正确。"

    hint = f"「{ds_name}」" if ds_name else ""
    return f"已从{hint}查询到 **{row_count}** 条记录，详见下方表格。"


_TIME_KEYWORDS = {'年', '月', '季', '日', '周', '年份', '月份', '日期', '时间', '季度',
                  'year', 'month', 'quarter', 'date', 'week', 'time'}


def _is_time_field(name: str) -> bool:
    lower = name.lower()
    return any(k in lower for k in _TIME_KEYWORDS)


def _build_chart_data(fields: list, rows: list, col_types: list, chart_type: str) -> dict:
    """Build chart-ready data structure from query result fields/rows.

    x_field: time field preferred; fallback to first string col.
    series_field: non-x string col with ≤8 unique values; skipped if too many series.
    """
    if not fields or not rows:
        return {"chart_type": chart_type, "x_field": None, "y_fields": [], "series_field": None, "data": []}

    string_idxs = [i for i, t in enumerate(col_types) if t == "string"]
    numeric_idxs = [i for i, t in enumerate(col_types) if t == "numeric"]

    # Prefer time-dimension field as x-axis
    time_idxs = [i for i in string_idxs if _is_time_field(fields[i])]
    x_idx = time_idxs[0] if time_idxs else (string_idxs[0] if string_idxs else 0)
    x_field = fields[x_idx]

    # series_field: string col (not x) with ≤8 unique values to avoid legend explosion
    series_field = None
    for i in [j for j in string_idxs if j != x_idx]:
        unique_count = len({str(row[i]) for row in rows if i < len(row)})
        if unique_count <= 8:
            series_field = fields[i]
            break

    y_fields = [fields[i] for i in numeric_idxs]

    data = []
    for row in rows:
        record = {fields[i]: row[i] for i in range(min(len(fields), len(row)))}
        data.append(record)

    return {
        "chart_type": chart_type,
        "x_field": x_field,
        "y_fields": y_fields,
        "series_field": series_field,
        "data": data,
    }


def _infer_col_types(fields: list, rows: list) -> list:
    """推断每列类型：'numeric' 或 'string'，用于前端格式化数字列。"""
    if not rows or not fields:
        return ["string"] * len(fields)
    col_types = []
    for col_idx in range(len(fields)):
        # Sample up to 10 rows; if all non-null values are numeric → numeric
        sample = [rows[i][col_idx] for i in range(min(10, len(rows))) if col_idx < len(rows[i])]
        non_null = [v for v in sample if v is not None and v != ""]
        is_num = bool(non_null) and all(isinstance(v, (int, float)) for v in non_null)
        col_types.append("numeric" if is_num else "string")
    return col_types


def _build_history_messages(session: Optional[Any]) -> List[Dict[str, Any]]:
    """从 session 对象构建历史消息"""
    if session is None:
        return []

    # 尝试从 session 获取历史消息
    try:
        if hasattr(session, "get_messages"):
            messages = session.get_messages(limit=10)
        elif hasattr(session, "messages"):
            messages = session.messages[-10:]
        else:
            messages = []
    except Exception:
        messages = []

    result = []
    for msg in messages:
        role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
        content = msg.content if hasattr(msg, "content") else msg.get("content", "")

        # 追问图表时 LLM 需要看到上轮的表格数据；将 response_data 摘要追加到 content
        r_type = getattr(msg, "response_type", None) or (msg.get("response_type") if isinstance(msg, dict) else None)
        r_data = getattr(msg, "response_data", None) or (msg.get("response_data") if isinstance(msg, dict) else None)
        if role == "assistant" and r_type == "table" and r_data and isinstance(r_data, dict):
            fields = r_data.get("fields", [])
            rows = r_data.get("rows", [])
            if fields and rows:
                sample = rows[:5]
                content = content + f"\n\n[查询结果数据 fields={fields} rows(前{len(sample)}行)={sample} 共{len(rows)}行]"

        result.append({"role": role, "content": content})

    return result