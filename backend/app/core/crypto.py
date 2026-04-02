"""
共享加密模块 - 工厂函数

从 src/common/crypto.py 导入 CryptoHelper，提供按环境变量初始化的工厂函数。
"""
import os

from services.common.crypto import CryptoHelper


def get_datasource_crypto() -> CryptoHelper:
    """获取数据源加密工具"""
    key = os.environ.get("DATASOURCE_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("DATASOURCE_ENCRYPTION_KEY environment variable must be set")
    return CryptoHelper(key)


def get_llm_crypto() -> CryptoHelper:
    """获取 LLM 加密工具（优先使用 LLM_ENCRYPTION_KEY，回退到 DATASOURCE_ENCRYPTION_KEY）"""
    key = os.environ.get("LLM_ENCRYPTION_KEY") or os.environ.get("DATASOURCE_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("LLM_ENCRYPTION_KEY or DATASOURCE_ENCRYPTION_KEY environment variable must be set")
    return CryptoHelper(key)


def get_tableau_crypto() -> CryptoHelper:
    """获取 Tableau 加密工具"""
    key = os.environ.get("TABLEAU_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("TABLEAU_ENCRYPTION_KEY environment variable must be set")
    return CryptoHelper(key)
