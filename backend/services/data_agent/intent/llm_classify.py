"""
Spec 36 §15: 意图识别 — llm_classify 策略

基于 LLM 进行意图分类。
使用轻量 prompt 快速分类为 chat / query / analysis / report / chart 等。
无法识别时抛出异常，fallback 到 fallback("chat")。
"""
import logging
from typing import Any, Dict, Optional

from .strategy import IntentResult, IntentStrategy

logger = logging.getLogger(__name__)


# LLM 意图分类 prompt
INTENT_CLASSIFY_PROMPT = """你是一个意图分类器。请将用户问题分类为以下意图之一：

- chat: 闲聊、问候、一般问答
- query: 数据查询（查数据、统计、汇总）
- analysis: 数据分析（归因、趋势、对比、挖掘）
- report: 生成报表/报告
- chart: 生成图表

分类规则：
1. 含"生成"、"报表"、"报告" → report
2. 含"分析"、"原因"、"趋势"、"对比" → analysis
3. 含"查"、"统计"、"多少"、"汇总" → query
4. 含"图"、"可视化" → chart
5. 其他 → chat

问题：{question}

请只输出分类结果，不要解释。"""


class LLMClassifyStrategy(IntentStrategy):
    """
    基于 LLM 的意图分类。

    使用轻量 prompt + 快速模型（如有），确保延迟 < 500ms。
    分类结果为 chat / query / analysis / report / chart。
    """

    name = "llm_classify"

    VALID_INTENTS = {"chat", "query", "analysis", "report", "chart"}

    def __init__(self, llm_service=None):
        """
        :param llm_service: 可选的 LLM 服务实例。若不传则使用默认实现。
        """
        self._llm = llm_service

    async def classify(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """
        使用 LLM 进行意图分类。
        """
        from services.llm.nlq_service import one_pass_llm

        prompt = INTENT_CLASSIFY_PROMPT.format(question=question[:500])

        try:
            # 使用 one_pass_llm 进行快速分类
            response = await one_pass_llm(
                prompt=prompt,
                system="你是一个意图分类助手，直接输出分类结果。",
                temperature=0.1,
                max_tokens=20,
            )

            # 解析 LLM 返回结果
            intent = response.strip().lower()

            # 验证返回的意图是否合法
            if intent not in self.VALID_INTENTS:
                intent = "chat"

            return IntentResult(
                intent=intent,
                confidence=0.80,
                strategy=self.name,
                params={"llm_raw_response": response},
            )

        except Exception as e:
            logger.warning("LLM classify failed: %s", e)
            raise ValueError(f"llm_classify: LLM call failed: {e}")