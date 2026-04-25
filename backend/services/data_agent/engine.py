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

logger = logging.getLogger(__name__)


# 默认约束
DEFAULT_MAX_STEPS = 10
DEFAULT_STEP_TIMEOUT = 30  # 秒
DEFAULT_TOTAL_TIMEOUT = 120  # 秒
DEFAULT_MAX_TOOL_RETRIES = 1
DEFAULT_MAX_HISTORY_TOKENS = 4000


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
    ):
        self.registry = registry
        self.llm = llm_service
        self.max_steps = max_steps
        self.step_timeout = step_timeout
        self.total_timeout = total_timeout
        self.max_tool_retries = max_tool_retries
        self.max_history_tokens = max_history_tokens

    async def run(
        self,
        query: str,
        context: ToolContext,
        session: Optional[Any] = None,
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

        # 构建 system prompt
        tool_descriptions = self.registry.get_tool_descriptions()
        system_prompt = build_react_system_prompt(tool_descriptions)

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

            # 1. Think：LLM 推理下一步
            think_result = await self._think(
                query=query,
                history=history_messages,
                system_prompt=system_prompt,
                context=context,
                step=step_count,
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
    ) -> Dict[str, Any]:
        """调用 LLM 进行推理决策"""
        # 构造 prompt
        prompt = _build_think_prompt(query, history, step, self.max_history_tokens)

        # 调用 LLM
        try:
            # purpose 优先用 "agent"，若无则 fallback 到 "general"
            try:
                result = await self.llm.complete(
                    prompt=prompt,
                    system=system_prompt,
                    timeout=self.step_timeout,
                    purpose="agent",
                )
            except Exception as e:
                logger.warning("LLM purpose='agent' failed, falling back to 'general': %s", e)
                result = await self.llm.complete(
                    prompt=prompt,
                    system=system_prompt,
                    timeout=self.step_timeout,
                    purpose="general",
                )
        except Exception as e:
            logger.exception("LLM 调用失败")
            return {"error": "LLM 服务暂时不可用", "error_code": "AGENT_006"}

        if "error" in result:
            return {"error": result["error"], "error_code": "AGENT_006"}

        content = result.get("content", "")
        if not content.strip():
            return {"error": "无法理解用户意图", "error_code": "AGENT_002"}
        return self._parse_llm_response(content)

    def _parse_llm_response(self, content: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON 决策"""
        try:
            # 尝试提取 JSON
            data = json.loads(content)
            action = data.get("action", "final_answer")
            return {
                "action": action,
                "tool_name": data.get("tool_name", ""),
                "tool_params": data.get("tool_params", {}),
                "reasoning": data.get("reasoning", ""),
                "answer": data.get("answer", ""),
            }
        except json.JSONDecodeError:
            # 不是 JSON，尝试从文本中提取
            return self._parse_text_response(content)

    def _parse_text_response(self, content: str) -> Dict[str, Any]:
        """从非 JSON 文本中提取决策信息（fallback）"""
        import re
        tool_match = re.search(r'"tool_name"\s*:\s*"([^"]+)"', content)
        action_match = re.search(r'"action"\s*:\s*"([^"]+)"', content)

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
) -> str:
    """构建 Think 阶段的 prompt"""
    prompt_parts = [
        f"用户问题：{query}",
        f"当前推理步：{step}",
    ]

    if history:
        truncated = _truncate_history(history[-10:], max_history_tokens)
        prompt_parts.append("历史对话：")
        for msg in truncated:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "tool":
                name = msg.get("name", "unknown")
                prompt_parts.append(f"[工具 {name} 返回]: {content[:200]}")
            else:
                prompt_parts.append(f"[{role}]: {content[:200]}")

    prompt_parts.append("请根据以上信息，决定下一步操作。")
    return "\n".join(prompt_parts)


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
        if hasattr(msg, "role"):
            result.append({"role": msg.role, "content": msg.content})
        elif isinstance(msg, dict):
            result.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    return result