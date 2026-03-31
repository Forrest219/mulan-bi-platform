"""LLM 调用服务"""
import os
import logging
from typing import Generator, Optional

from .models import LLMConfigDatabase

logger = logging.getLogger(__name__)

# 加密密钥
_ENCRYPTION_KEY = os.environ.get("DATASOURCE_ENCRYPTION_KEY")
if not _ENCRYPTION_KEY:
    raise RuntimeError("DATASOURCE_ENCRYPTION_KEY must be set")


def _get_cipher(salt: bytes = None):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64

    if salt is None:
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(_ENCRYPTION_KEY.encode()))
        return salt, Fernet(key)

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    key = base64.urlsafe_b64encode(kdf.derive(_ENCRYPTION_KEY.encode()))
    return Fernet(key)


def _encrypt(text: str) -> str:
    import base64
    salt, cipher = _get_cipher()
    return base64.urlsafe_b64encode(salt + cipher.encrypt(text.encode())).decode()


def _decrypt(token: str) -> str:
    import base64
    data = base64.urlsafe_b64decode(token.encode())
    salt = data[:16]
    ciphertext = data[16:]
    cipher = _get_cipher(salt)
    return cipher.decrypt(ciphertext).decode()


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
        except Exception:
            logger.error("LLM API Key 解密失败")
            return {"error": "LLM 认证配置错误"}

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=config.base_url, timeout=timeout)

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            logger.info(f"LLM 调用：model={config.model}, timeout={timeout}s")

            response = client.chat.completions.create(
                model=config.model,
                messages=messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
            content = response.choices[0].message.content.strip()
            return {"content": content}

        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return {"error": str(e)}

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
