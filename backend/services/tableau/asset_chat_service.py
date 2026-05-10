"""Tableau 资产对话服务（SPEC 41）

ReAct 文本解析方式实现 tool dispatch：
- LLMService 不支持原生 tool calling，使用文本约定格式
- System prompt 描述工具格式：TOOL_CALL: tool_name({"arg": "value"})
- 后端解析 LLM 输出，检测 TOOL_CALL: 行，提取 tool 名和参数执行
- 执行结果注入 history 继续生成

架构约束：
- 不得 import app.api 层任何内容
- 直接 import IntentSearchService 和 ImpactService，不发 HTTP 请求
"""
import json
import logging
import re
from typing import AsyncGenerator, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3  # 硬编码常量，不得改为数字字面量


# ── Dependency Stubs（待 SPEC 39 完成后替换）────────────────────────────────────

try:
    from services.tableau.intent_search_service import IntentSearchService
except ImportError:
    # Stub：待 SPEC 39 完成后替换
    class IntentSearchService:  # type: ignore[no-redef]
        def __init__(self, db: Session):
            self.db = db

        def recall_and_rank(
            self,
            query: str,
            connection_id: int,
            asset_type: Optional[str] = None,
            health_score_max: Optional[float] = None,
        ) -> list:
            raise NotImplementedError("Intent search service not yet implemented")


try:
    from services.tableau.impact_service import ImpactService
except ImportError:
    # Stub：待 SPEC 40 完成后替换
    class ImpactService:  # type: ignore[no-redef]
        def __init__(self, db: Session):
            self.db = db

        def get_asset_impact(self, asset_id: int) -> dict:
            raise NotImplementedError("Impact service not yet implemented")


# ── System Prompt 模板 ─────────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """\
你是 Tableau BI 资产助手，帮助用户在连接 {connection_id} 中查找和分析资产。
当前视图：{current_filter}，共 {visible_asset_count} 个资产。

可用工具（使用精确格式调用）：

工具 1：search_assets
用途：根据自然语言查询搜索 Tableau 资产，返回相关资产列表
调用格式：TOOL_CALL: search_assets({{"query": "<查询词>", "asset_type": "<类型或null>", "health_score_max": <数字或null>}})
参数说明：
  - query（必填）：自然语言搜索词
  - asset_type（可选）：workbook | dashboard | view | datasource | null
  - health_score_max（可选）：健康分上限，如 60 表示只返回健康分 <60 的资产，不需要则填 null

工具 2：get_impact_analysis
用途：获取某个数据源的下游影响树，返回受影响的工作簿和视图/仪表板列表
调用格式：TOOL_CALL: get_impact_analysis({{"asset_id": "<资产ID>"}})
参数说明：
  - asset_id（必填）：datasource 类型资产的整数 ID

规则：
1. 用中文回答
2. 找到资产时直接呈现资产信息，不要冗长解释
3. 调用工具时输出单独一行 TOOL_CALL: 开头的调用语句
4. 工具结果会以 TOOL_RESULT: 格式提供，你根据结果继续生成回答
5. 如果问题不需要搜索资产，直接回答即可
"""

_TOOL_CALL_PATTERN = re.compile(
    r"TOOL_CALL:\s*(\w+)\s*\(\s*(\{.*?\})\s*\)",
    re.DOTALL,
)


def _build_system_prompt(connection_id: int, context: dict) -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        connection_id=connection_id,
        current_filter=context.get("current_filter") or "全部",
        visible_asset_count=context.get("visible_asset_count") or 0,
    )


def _extract_tool_call(text: str) -> Optional[tuple]:
    """从 LLM 输出文本中提取第一个 TOOL_CALL，返回 (tool_name, tool_args) 或 None"""
    match = _TOOL_CALL_PATTERN.search(text)
    if not match:
        return None
    tool_name = match.group(1)
    args_str = match.group(2)
    try:
        tool_args = json.loads(args_str)
    except json.JSONDecodeError:
        logger.warning("tool_args JSON 解析失败: %r", args_str)
        return None
    return tool_name, tool_args


def _strip_tool_call_line(text: str) -> str:
    """移除 TOOL_CALL: 行，返回纯文字部分"""
    return _TOOL_CALL_PATTERN.sub("", text).strip()


class AssetChatService:
    def __init__(self, db: Session):
        self.db = db
        self._intent_service = IntentSearchService(db)
        self._impact_service = ImpactService(db)

    def _execute_tool(self, tool_name: str, tool_args: dict, connection_id: int) -> Optional[dict]:
        """执行工具调用，返回结构化结果"""
        if tool_name == "search_assets":
            query = tool_args.get("query", "")
            asset_type = tool_args.get("asset_type")
            health_score_max = tool_args.get("health_score_max")
            # null 值处理
            if asset_type == "null":
                asset_type = None
            if health_score_max == "null":
                health_score_max = None

            raw = self._intent_service.recall_and_rank(
                query=query,
                connection_id=connection_id,
                asset_type=asset_type,
                health_score_max=health_score_max,
            )
            # recall_and_rank 返回 list of dict 或 list of ORM 对象
            assets = []
            for item in (raw or []):
                if isinstance(item, dict):
                    assets.append(item)
                else:
                    # ORM 对象，尝试 to_dict() 或 __dict__
                    if hasattr(item, "to_dict"):
                        assets.append(item.to_dict())
                    else:
                        assets.append({k: v for k, v in item.__dict__.items() if not k.startswith("_")})
            return {"tool": "search_assets", "assets": assets}

        elif tool_name == "get_impact_analysis":
            raw_asset_id = tool_args.get("asset_id")
            try:
                asset_id = int(raw_asset_id)
            except (TypeError, ValueError):
                return {"tool": "get_impact_analysis", "error": f"asset_id 无效: {raw_asset_id}"}
            # P0 安全校验：资产必须属于当前 chat session 的连接，防止跨连接数据泄漏
            from services.tableau.models import TableauAsset

            asset = self.db.query(TableauAsset).filter(
                TableauAsset.id == asset_id,
                TableauAsset.connection_id == connection_id,
                TableauAsset.is_deleted == False,
            ).first()
            if asset is None:
                return {
                    "tool": "get_impact_analysis",
                    "error": "无权访问该资产或资产不存在",
                }
            result = self._impact_service.get_asset_impact(asset_id)
            return {"tool": "get_impact_analysis", "impact": result}

        return None

    async def stream_chat(
        self,
        message: str,
        connection_id: int,
        history: list,
        context: dict,
    ) -> AsyncGenerator[dict, None]:
        """
        异步生成器，yield SSE 帧字典。
        帧类型：text / tool_call / assets / action / done / error

        调用方负责将帧序列化为 text/event-stream 格式。
        """
        from services.llm.service import LLMService

        llm = LLMService()
        system_prompt = _build_system_prompt(connection_id, context)

        # 构建消息列表（含历史）
        messages = list(history)
        messages.append({"role": "user", "content": message})

        # 将消息列表转换为单一 prompt 字符串（LLMService.complete 接受 prompt + system）
        prompt = _messages_to_prompt(messages)

        collected_assets: list = []
        tool_rounds = 0

        while tool_rounds <= MAX_TOOL_ROUNDS:
            try:
                result = await llm.complete(prompt, system=system_prompt, timeout=30)
            except Exception as exc:
                logger.error("LLM 调用失败: %s", exc, exc_info=True)
                yield {"type": "error", "code": "TAB_AC_002", "message": "对话服务暂时不可用"}
                return

            if "error" in result:
                yield {"type": "error", "code": "TAB_AC_002", "message": result["error"]}
                return

            llm_output: str = result.get("content", "")

            # 检查是否包含 tool call
            tool_call_info = _extract_tool_call(llm_output)

            if tool_call_info is None or tool_rounds >= MAX_TOOL_ROUNDS:
                # 无 tool call 或已达上限：直接输出文字
                clean_text = _strip_tool_call_line(llm_output)
                if clean_text:
                    yield {"type": "text", "delta": clean_text}

                # 如果本轮达上限强制截断，记录日志
                if tool_rounds >= MAX_TOOL_ROUNDS and tool_call_info is not None:
                    logger.warning("Tool calling 已达 %d 轮上限，强制截断", MAX_TOOL_ROUNDS)

                break

            tool_name, tool_args = tool_call_info
            tool_rounds += 1

            # 通知前端：工具调用中
            yield {"type": "tool_call", "tool": tool_name, "status": "running"}

            # 文字部分（TOOL_CALL: 之前的文字）
            text_before = _strip_tool_call_line(
                llm_output[: _TOOL_CALL_PATTERN.search(llm_output).start()]  # type: ignore[union-attr]
            )
            if text_before:
                yield {"type": "text", "delta": text_before}

            # 执行工具
            try:
                tool_result = self._execute_tool(tool_name, tool_args, connection_id)
            except NotImplementedError:
                tool_result = {"error": f"工具 {tool_name} 尚未实现"}
            except ValueError as ve:
                tool_result = {"error": str(ve)}
            except Exception as exc:
                logger.error("工具执行失败 [%s]: %s", tool_name, exc, exc_info=True)
                tool_result = {"error": f"工具执行失败: {exc}"}

            if tool_result is None:
                tool_result = {"error": f"未知工具: {tool_name}"}

            # 收集资产列表
            if tool_result.get("tool") == "search_assets" and "assets" in tool_result:
                collected_assets.extend(tool_result["assets"])

            # 将 tool result 注入 prompt，继续 LLM
            tool_result_str = json.dumps(tool_result, ensure_ascii=False)
            prompt = prompt + f"\n\n工具调用结果：\nTOOL_RESULT: {tool_result_str}\n\n请根据以上结果继续回答用户问题。"

        # 输出收集的资产卡片
        if collected_assets:
            # 规范化资产格式
            normalized = _normalize_assets(collected_assets)
            yield {"type": "assets", "assets": normalized}

            # 建议 action
            asset_types = list({a.get("asset_type") for a in normalized if a.get("asset_type")})
            if len(asset_types) == 1:
                atype = asset_types[0]
                yield {
                    "type": "action",
                    "action_type": "apply_filter",
                    "payload": {"asset_type": atype},
                    "action_label": f"仅显示{_asset_type_label(atype)}",
                }
            elif asset_types:
                # 有多种类型，建议 highlight
                asset_ids = [str(a["id"]) for a in normalized if a.get("id")]
                if asset_ids:
                    yield {
                        "type": "action",
                        "action_type": "highlight_assets",
                        "payload": {"asset_ids": asset_ids},
                        "action_label": "在列表中高亮显示",
                    }

        yield {"type": "done"}


# ── 私有辅助函数 ───────────────────────────────────────────────────────────────

def _messages_to_prompt(messages: list) -> str:
    """将多轮历史消息列表转为单一 prompt 字符串"""
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            parts.append(f"用户：{content}")
        elif role == "assistant":
            parts.append(f"助手：{content}")
        else:
            parts.append(content)
    return "\n\n".join(parts)


def _normalize_assets(raw_assets: list) -> list:
    """将原始资产 dict 规范化为 SPEC §3.2 定义的格式"""
    result = []
    for a in raw_assets:
        result.append({
            "id": a.get("id") or a.get("asset_id"),
            "name": a.get("name") or "",
            "asset_type": a.get("asset_type") or "",
            "health_score": a.get("health_score"),
            "project_name": a.get("project_name") or "",
            "relevance_reason": a.get("relevance_reason") or a.get("reason") or "",
        })
    return result


def _asset_type_label(asset_type: str) -> str:
    mapping = {
        "workbook": "工作簿",
        "dashboard": "仪表板",
        "view": "视图",
        "datasource": "数据源",
    }
    return mapping.get(asset_type, asset_type)
