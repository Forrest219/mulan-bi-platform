"""
Spec 36 §15: 意图识别策略注册表

管理三级 fallback 链：
  context_aware → keyword_match → llm_classify → fallback("chat")

唯一出口：IntentRecognizer.classify()
"""
import logging
from typing import Any, Dict, Optional

from .strategy import IntentResult, IntentStrategy
from .context_aware import ContextAwareStrategy
from .keyword_match import KeywordMatchStrategy
from .llm_classify import LLMClassifyStrategy

logger = logging.getLogger(__name__)


class IntentRegistry:
    """
    意图识别策略注册表。

    使用策略链式调用（chain of responsibility）。
    每级策略失败后尝试下一级，最终 fallback 到 "chat"。
    """

    DEFAULT_CHAIN = [
        "context_aware",
        "keyword_match",
        "llm_classify",
    ]

    def __init__(self, db=None, llm_service=None):
        self._strategies: Dict[str, IntentStrategy] = {}
        self._db = db
        self._llm_service = llm_service

        # 注册默认策略
        self.register("context_aware", ContextAwareStrategy(db) if db else None)
        self.register("keyword_match", KeywordMatchStrategy())
        self.register("llm_classify", LLMClassifyStrategy(llm_service))

    def register(self, name: str, strategy: Optional[IntentStrategy]) -> None:
        """注册或更新策略"""
        if strategy:
            self._strategies[name] = strategy

    async def classify(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        trace_id: Optional[str] = None,
        db=None,
    ) -> IntentResult:
        """
        执行意图识别链。

        :param question: 用户问题
        :param context: 可选上下文（session_id, connection_id 等）
        :param user_id: 用户 ID（用于审计日志）
        :param trace_id: 追踪 ID（用于审计日志）
        :param db: 数据库 session（用于审计日志）
        :return: 最终识别的 IntentResult
        """
        chain = self.DEFAULT_CHAIN
        last_error = None

        for strategy_name in chain:
            strategy = self._strategies.get(strategy_name)
            if not strategy:
                logger.warning("Strategy %s not registered, skipping", strategy_name)
                continue

            try:
                result = await strategy.classify(question, context)
                # 成功后写审计日志
                if db and user_id and trace_id:
                    strategy._log_intent(
                        db=db,
                        question=question,
                        intent=result.intent,
                        confidence=result.confidence,
                        strategy=strategy_name,
                        trace_id=trace_id,
                        user_id=user_id,
                        error=result.error,
                    )
                return result

            except Exception as e:
                last_error = e
                logger.debug(
                    "Strategy %s failed for question '%s': %s",
                    strategy_name, question[:100], e,
                )
                continue

        # 所有策略都失败，fallback 到 chat
        fallback_result = IntentResult(
            intent="chat",
            confidence=0.5,
            strategy="fallback",
            params={"fallback_reason": str(last_error) if last_error else "no strategy matched"},
        )

        # fallback 也写审计日志
        if db and user_id and trace_id:
            from .strategy import IntentStrategy
            # 使用 keyword_match 作为代理写日志（因为它总是存在）
            strategy = self._strategies.get("keyword_match")
            if strategy:
                strategy._log_intent(
                    db=db,
                    question=question,
                    intent=fallback_result.intent,
                    confidence=fallback_result.confidence,
                    strategy=fallback_result.strategy,
                    trace_id=trace_id,
                    user_id=user_id,
                    error=fallback_result.params.get("fallback_reason"),
                )

        return fallback_result


# 全局注册表实例（延迟初始化）
_registry: Optional[IntentRegistry] = None


def get_intent_registry(db=None, llm_service=None) -> IntentRegistry:
    """获取全局意图识别注册表"""
    global _registry
    if _registry is None:
        _registry = IntentRegistry(db=db, llm_service=llm_service)
    return _registry


class IntentRecognizer:
    """
    意图识别统一入口。

    使用方式：
        result = await IntentRecognizer().recognize(
            question="查一下今天的销售额",
            context={"session_id": "xxx"},
            user_id=1,
            trace_id="t-abc123",
            db=db,
        )
    """

    def __init__(self, db=None, llm_service=None):
        self._registry = get_intent_registry(db=db, llm_service=llm_service)

    async def recognize(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        trace_id: Optional[str] = None,
        db=None,
    ) -> IntentResult:
        """
        识别用户意图。

        :param question: 用户自然语言问题
        :param context: 可选上下文（如 session_id, connection_id）
        :param user_id: 用户 ID（用于审计）
        :param trace_id: 追踪 ID（用于审计）
        :param db: 数据库 session（用于审计日志）
        """
        return await self._registry.classify(
            question=question,
            context=context,
            user_id=user_id,
            trace_id=trace_id,
            db=db,
        )