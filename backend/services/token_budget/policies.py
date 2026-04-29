"""截断策略（Spec 12 §18.5）

Policy 接口 + 三种内置实现：PriorityDropPolicy / FIFODropPolicy / SummarizePolicy
"""
import logging
from typing import Optional, Protocol

from .counter import TokenCounter

logger = logging.getLogger(__name__)


class Policy(Protocol):
    """截断策略接口（Spec 12 §18.5）"""

    def order(self, items: list["BudgetItem"]) -> list["BudgetItem"]:
        """排序 items（决定处理顺序）"""
        ...

    def shrink(self, item: "BudgetItem", target_tokens: int) -> Optional["BudgetItem"]:
        """
        尝试压缩单个 item 到 target_tokens 以内。

        Returns:
            压缩后的 BudgetItem，或 None（不可压缩，直接丢弃）
        """
        ...


# 延迟导入避免循环依赖
from dataclasses import dataclass, field
from typing import List


@dataclass
class BudgetItem:
    """Budget 截断单元（Spec 12 §18.3）"""
    content: str
    priority: int = 5  # 0 = highest, 5 = lowest
    droppable: bool = True  # False 表示不可丢弃
    truncatable: bool = False  # True 表示可摘要/截断子串
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        # priority 超出范围的归一化
        self.priority = max(0, min(5, self.priority))


class PriorityDropPolicy:
    """
    优先级丢弃策略（Spec 12 §18.5）。

    行为：按 priority 升序保留（priority=0 永不丢弃），
    超限丢弃 droppable=True 的低优先级项。

    默认场景：semantic_field / semantic_ds（核心字段优先）
    """

    def __init__(self, counter: Optional[TokenCounter] = None):
        self.counter = counter or TokenCounter()

    def order(self, items: list[BudgetItem]) -> list[BudgetItem]:
        """按 priority 升序排序（高优先级在前）"""
        return sorted(items, key=lambda x: x.priority)

    def shrink(self, item: BudgetItem, target_tokens: int) -> Optional[BudgetItem]:
        """
        尝试截断 item 到 target_tokens 以内。

        对 truncatable=True 的项进行字符级截断；
        对不可截断的项返回 None（表示应直接丢弃）。
        """
        if not item.truncatable:
            # 不可截断的项，直接返回 None（触发丢弃）
            return None

        content = item.content
        current_tokens = self.counter.count(content)

        if current_tokens <= target_tokens:
            return item

        # 二分查找最大可接受长度
        # 简化实现：按比例估算
        ratio = target_tokens / max(current_tokens, 1)
        estimated_len = int(len(content) * ratio)
        estimated_len = max(10, min(estimated_len, len(content)))

        # 迭代调整直到 token 数达标
        for try_len in range(estimated_len, 0, -1):
            truncated = content[:try_len]
            if self.counter.count(truncated) <= target_tokens:
                return BudgetItem(
                    content=truncated + "...",
                    priority=item.priority,
                    droppable=item.droppable,
                    truncatable=False,  # 已截断，不可再压缩
                    metadata=item.metadata,
                )

        # 无法截断到目标，直接丢弃
        return None

    def fit(self, items: list[BudgetItem], budget_tokens: int) -> tuple[list[BudgetItem], int]:
        """
        按优先级顺序填充 items 到 budget_tokens 以内。

        Returns:
            (kept_items, total_tokens_used)
        """
        ordered = self.order(items)
        kept = []
        used = 0
        dropped_count = 0

        for item in ordered:
            item_tokens = self.counter.count(item.content)

            # priority=0 的项有保底预算，不受 budget 限制
            if item.priority == 0:
                if used + item_tokens <= budget_tokens * 2:  # 允许 P0 超一点
                    kept.append(item)
                    used += item_tokens
                continue

            if used + item_tokens > budget_tokens:
                if item.droppable:
                    dropped_count += 1
                    continue
                else:
                    # 不可丢弃，尝试压缩
                    shrunk = self.shrink(item, budget_tokens - used)
                    if shrunk is not None:
                        kept.append(shrunk)
                        used += self.counter.count(shrunk.content)
                    else:
                        dropped_count += 1
                    continue

            kept.append(item)
            used += item_tokens

        return kept, used


class FIFODropPolicy:
    """
    先进先出丢弃策略（Spec 12 §18.5）。

    行为：按时间序丢老消息（最早进入的先弃）。

    默认场景：agent_step（多轮对话）
    """

    def __init__(self, counter: Optional[TokenCounter] = None):
        self.counter = counter or TokenCounter()

    def order(self, items: list[BudgetItem]) -> list[BudgetItem]:
        """
        保持原始顺序（FIFO），但优先保留 droppable=False 的项。

        实际截断逻辑在 fit() 中处理。
        """
        # 按原始顺序（假设 items 已按时间顺序传入）
        return items

    def shrink(self, item: BudgetItem, target_tokens: int) -> Optional[BudgetItem]:
        """不支持 shrink，返回 None"""
        return None

    def fit(self, items: list[BudgetItem], budget_tokens: int) -> tuple[list[BudgetItem], int]:
        """
        从后向前保留（最新消息优先），丢弃最早的消息直到 budget 内。

        Returns:
            (kept_items, total_tokens_used)
        """
        kept = []
        used = 0
        dropped_count = 0

        # 从后向前处理
        for item in reversed(items):
            item_tokens = self.counter.count(item.content)

            if used + item_tokens > budget_tokens:
                if item.droppable:
                    dropped_count += 1
                    continue
                else:
                    # 不可丢弃，停止
                    break

            kept.append(item)
            used += item_tokens

        # 反转回原始顺序
        kept.reverse()
        return kept, used


class SummarizePolicy:
    """
    摘要压缩策略（Spec 12 §18.5）。

    行为：对 truncatable=True 的项调摘要 LLM 压缩；
    摘要失败回退到 truncate。

    默认场景：rag_context（可选）
    """

    def __init__(self, counter: Optional[TokenCounter] = None, summarize_llm=None):
        """
        Args:
            counter: Token 计数器
            summarize_llm: 摘要 LLM 函数，签名为 async def summarize(text: str, target_tokens: int) -> str
                        如果为 None，则降级为纯截断
        """
        self.counter = counter or TokenCounter()
        self.summarize_llm = summarize_llm

    def order(self, items: list[BudgetItem]) -> list[BudgetItem]:
        """按 priority 升序排序（高优先级先摘要）"""
        return sorted(items, key=lambda x: x.priority)

    def shrink(self, item: BudgetItem, target_tokens: int) -> Optional[BudgetItem]:
        """
        尝试压缩 item。

        - 有 summarize_llm 时：调用 LLM 摘要
        - 无 summarize_llm 时：降级为字符截断
        """
        if not item.truncatable:
            return None

        # 尝试 LLM 摘要
        if self.summarize_llm is not None:
            try:
                import asyncio
                summarized = asyncio.run(self.summarize_llm(item.content, target_tokens))
                if self.counter.count(summarized) <= target_tokens:
                    return BudgetItem(
                        content=summarized,
                        priority=item.priority,
                        droppable=item.droppable,
                        truncatable=False,
                        metadata={**item.metadata, "summarized": True},
                    )
            except Exception as e:
                logger.warning("LLM 摘要失败，降级为截断: %s", e)

        # 降级：字符截断
        return self._truncate(item, target_tokens)

    def _truncate(self, item: BudgetItem, target_tokens: int) -> Optional[BudgetItem]:
        """纯截断（不调 LLM）"""
        content = item.content
        current_tokens = self.counter.count(content)

        if current_tokens <= target_tokens:
            return item

        ratio = target_tokens / max(current_tokens, 1)
        estimated_len = max(10, int(len(content) * ratio))

        for try_len in range(estimated_len, 0, -1):
            truncated = content[:try_len]
            if self.counter.count(truncated) <= target_tokens:
                return BudgetItem(
                    content=truncated + "...",
                    priority=item.priority,
                    droppable=item.droppable,
                    truncatable=False,
                    metadata={**item.metadata, "truncated": True},
                )

        return None

    def fit(self, items: list[BudgetItem], budget_tokens: int) -> tuple[list[BudgetItem], int]:
        """
        按优先级顺序处理 items，高优先级优先保留和摘要。

        Returns:
            (kept_items, total_tokens_used)
        """
        ordered = self.order(items)
        kept = []
        used = 0
        dropped_count = 0

        for item in ordered:
            item_tokens = self.counter.count(item.content)

            if used + item_tokens > budget_tokens:
                if item.droppable:
                    # 尝试压缩
                    shrunk = self.shrink(item, budget_tokens - used)
                    if shrunk is not None:
                        kept.append(shrunk)
                        used += self.counter.count(shrunk.content)
                    else:
                        dropped_count += 1
                    continue
                else:
                    # 不可丢弃
                    break

            kept.append(item)
            used += item_tokens

        return kept, used
