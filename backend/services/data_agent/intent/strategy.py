"""
Spec 36 §15: 意图识别抽象策略类

三级 fallback 链：
  context_aware → keyword_match → llm_classify → fallback("chat")

所有策略必须实现 classify() 方法并落 bi_agent_intent_log。
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class IntentResult:
    """意图识别结果"""
    intent: str  # "chat" | "query" | "analysis" | "report" | etc.
    confidence: float  # 0.0 ~ 1.0
    strategy: str  # 触发策略名
    params: Dict[str, Any] = None  # 解析出的参数
    error: Optional[str] = None


class IntentStrategy(ABC):
    """
    意图识别策略抽象基类。

    子类必须实现 classify() 方法。
    classify() 失败时应抛出异常（由调用方捕获并尝试下一级策略）。
    """

    name: str = "base"

    @abstractmethod
    async def classify(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """
        对问题进行意图识别。

        :param question: 用户自然语言问题
        :param context: 可选的上下文信息（会话历史、数据源信息等）
        :return: IntentResult
        :raises: 当本级策略无法识别时抛出异常
        """
        ...

    def _log_intent(
        self,
        db: "Session",
        question: str,
        intent: str,
        confidence: float,
        strategy: str,
        trace_id: str,
        user_id: int,
        error: Optional[str] = None,
    ) -> None:
        """
        落 bi_agent_intent_log 表。

        :param db: 数据库 session
        :param question: 原始问题
        :param intent: 识别结果意图
        :param confidence: 置信度
        :param strategy: 策略名
        :param trace_id: 追踪 ID
        :param user_id: 用户 ID
        :param error: 可选的错误信息
        """
        from app.core.database import engine
        from sqlalchemy import text

        now = datetime.now()
        partition_key = now.strftime("%Y%m")

        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO bi_agent_intent_log
                    (question, intent, confidence, strategy, trace_id,
                     user_id, error, created_at, partition_key)
                    VALUES
                    (:question, :intent, :confidence, :strategy, :trace_id,
                     :user_id, :error, :created_at, :partition_key)
                """),
                {
                    "question": question[:2000],  # 截断防止过长
                    "intent": intent,
                    "confidence": confidence,
                    "strategy": strategy,
                    "trace_id": trace_id,
                    "user_id": user_id,
                    "error": error,
                    "created_at": now,
                    "partition_key": partition_key,
                },
            )
            conn.commit()