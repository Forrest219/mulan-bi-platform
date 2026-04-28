"""
Spec 36 §15: 意图识别 — context_aware 策略

基于会话上下文推断意图。
- 续接上一轮问题时直接继承上一轮的数据源/意图
- 若上下文不足则抛出异常，fallback 到下一级
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from .strategy import IntentResult, IntentStrategy

logger = logging.getLogger(__name__)


class ContextAwareStrategy(IntentStrategy):
    """
    基于上下文的意图识别。

    规则：
    - 若当前问题是简单确认/追问（短句、含代词），继承上轮意图
    - 若存在 connection_id 和近期会话，使用上轮数据源
    - 无法推断时抛出异常
    """

    name = "context_aware"

    # 简单的确认/追问模式（中文）
    CONFIRMATION_PATTERNS = [
        r"^(对|是的|好|可以|没错|就是)$",
        r"^为什么[呢？?]?$",
        r"^还有呢[？?]?$",
        r"^然后呢[？?]?$",
        r"^继续[。.]?$",
        r"^再说一遍[。.]?$",
        r"^换成(.+)$",
    ]

    # 意图继承关键词
    INTENT_CONTINUE_KEYWORDS = [
        "换一个", "换回", "重新", "再看看", "改成",
    ]

    def __init__(self, db: Session):
        self.db = db

    async def classify(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """
        基于上下文推断意图。

        :param context: 必须包含 session_id 和可选的 conversation_history
        """
        import re

        if not context:
            raise ValueError("context_aware requires context with session_id")

        session_id = context.get("session_id")
        if not session_id:
            raise ValueError("context_aware requires session_id in context")

        # 检查是否是简单的确认/追问
        is_confirmation = any(
            re.match(p, question.strip()) for p in self.CONFIRMATION_PATTERNS
        )

        # 从会话历史获取上轮意图
        from services.data_agent.session import SessionManager

        session_mgr = SessionManager(self.db)
        history = session_mgr.get_recent_messages(
            session_id=session_id,
            limit=3,
        )

        last_intent = None
        last_connection_id = None
        last_params = None

        for msg in reversed(history):
            if msg.role == "assistant" and msg.content:
                # 尝试从上一轮消息解析意图
                # 这里简化处理，实际可从 metadata 中获取
                pass

        if is_confirmation and last_intent:
            return IntentResult(
                intent=last_intent,
                confidence=0.95,
                strategy=self.name,
                params={
                    "inherited": True,
                    "from_session_id": session_id,
                    "connection_id": last_connection_id,
                    "original_params": last_params,
                },
            )

        # 检查是否要求更换/重新
        for kw in self.INTENT_CONTINUE_KEYWORDS:
            if kw in question:
                # 继承上轮意图，重新解析
                if last_intent:
                    return IntentResult(
                        intent=last_intent,
                        confidence=0.85,
                        strategy=self.name,
                        params={
                            "reparse": True,
                            "original_intent": last_intent,
                        },
                    )
                break

        # 无法从上下文推断
        raise ValueError("context_aware: cannot infer intent from available context")