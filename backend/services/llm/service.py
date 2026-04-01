"""LLM 调用服务"""
import os
import logging
from typing import Optional

from .models import LLMConfigDatabase
from common.crypto import CryptoHelper

logger = logging.getLogger(__name__)

# 加密密钥
_ENCRYPTION_KEY = os.environ.get("DATASOURCE_ENCRYPTION_KEY")
if not _ENCRYPTION_KEY:
    raise RuntimeError("DATASOURCE_ENCRYPTION_KEY must be set")

_crypto = CryptoHelper(_ENCRYPTION_KEY)
_encrypt = _crypto.encrypt
_decrypt = _crypto.decrypt


class LLMService:
    """LLM 调用服务 — 单例"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config_db = LLMConfigDatabase()
        return cls._instance

    def _load_config(self):
        return self._config_db.get_config()

    def complete(self, prompt: str, system: str = None, timeout: int = 15) -> dict:
        """
        同步 LLM 调用
        Returns: { "content": str } or { "error": str }
        """
        config = self._load_config()
        if not config or not config.is_active or not config.api_key_encrypted:
            return {"error": "LLM 未配置，请联系管理员"}

        try:
            api_key = _decrypt(config.api_key_encrypted)
        except Exception as e:
            logger.error("LLM API Key 解密失败: %s", e, exc_info=True)
            return {"error": "LLM 认证配置错误"}

        try:
            if config.provider == "anthropic":
                return self._anthropic_complete(api_key, config, prompt, system, timeout)
            else:
                return self._openai_complete(api_key, config, prompt, system, timeout)
        except Exception as e:
            logger.error("LLM 调用失败: %s", e, exc_info=True)
            return {"error": str(e)}

    def _openai_complete(self, api_key: str, config, prompt: str, system: str, timeout: int) -> dict:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=config.base_url, timeout=timeout)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        logger.info(f"LLM 调用（OpenAI）：model={config.model}, timeout={timeout}s")
        response = client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        content = response.choices[0].message.content.strip()
        return {"content": content}

    def _anthropic_complete(self, api_key: str, config, prompt: str, system: str, timeout: int) -> dict:
        from anthropic import Anthropic
        base_url = config.base_url or "https://api.minimaxi.com/anthropic"
        client = Anthropic(api_key=api_key, base_url=base_url, timeout=timeout)
        messages = []
        if system:
            messages.append({"role": "user", "content": f"<system>{system}</system>\n\n{prompt}"})
        else:
            messages.append({"role": "user", "content": prompt})
        logger.info(f"LLM 调用（Anthropic）：model={config.model}, base_url={base_url}, timeout={timeout}s")
        try:
            response = client.messages.create(
                model=config.model,
                messages=messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error("Anthropic API 调用失败 [%s]: %s", error_type, error_msg, exc_info=True)
            return {"error": f"Anthropic API 错误: {error_msg}"}

        # 兼容 MiniMax 的 ThinkingBlock（思维链），提取第一个 TextBlock
        from anthropic.types import TextBlock, Message
        text_blocks = [block for block in response.content if isinstance(block, TextBlock)]
        if not text_blocks:
            logger.error("Anthropic 响应中无 TextBlock: %s", response.content)
            return {"error": f"MiniMax 响应格式异常：未找到文本内容"}
        content = text_blocks[0].text.strip()
        return {"content": content}

    def generate_asset_summary(self, asset) -> dict:
        """
        对 Tableau 资产生成摘要
        asset: TableauAsset 对象
        Returns: { "summary": str } or { "error": str }
        """
        from .prompts import ASSET_SUMMARY_TEMPLATE

        prompt = ASSET_SUMMARY_TEMPLATE.format(
            asset_type=asset.asset_type or "",
            name=asset.name or "",
            project_name=asset.project_name or "",
            description=asset.description or "",
            owner_name=asset.owner_name or "",
        )

        result = self.complete(prompt, system="你是一个数据分析助手。", timeout=15)
        if "content" in result:
            return {"summary": result["content"]}
        return result

    def test_connection(self, test_prompt: str = "Hello, respond with 'OK'") -> dict:
        """测试 LLM 连接"""
        result = self.complete(test_prompt, timeout=15)
        if "error" in result:
            return {"success": False, "message": result["error"]}
        return {"success": True, "message": result["content"]}


llm_service = LLMService()
