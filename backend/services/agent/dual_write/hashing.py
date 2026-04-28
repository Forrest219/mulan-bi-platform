"""
Spec 36 §15: Dual Write Hashing — 唯一 result_hash 算法实现

所有双写路径必须共用此模块的 hash_result()，禁止在其他位置实现。
"""
import hashlib
import json
from typing import Any, Dict, Optional


def compute_result_hash(result_data: Any) -> str:
    """
    计算结果数据的 MD5 哈希值（用于双写审计去重）。

    算法：
    1. 序列化 result_data 为规范 JSON（keys 排序）
    2. 取 MD5 hexdigest（32字符）

    用途：
    - bi_agent_dual_write_audit.result_hash
    - NLQ 结果与 Agent 结果的等价性判断

    :param result_data: 任意可序列化数据（dict/list/scalar）
    :return: 32字符 MD5 hex string
    """
    try:
        # 确保可 JSON 序列化
        normalized = json.dumps(result_data, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        # 无法序列化时用字符串表示
        normalized = str(result_data)

    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def hash_query_params(question: str, connection_id: Optional[int] = None, **extra) -> str:
    """
    计算查询参数的哈希（用于意图识别去重）。
    """
    params = {"q": question, "conn": connection_id}
    params.update(extra)
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()