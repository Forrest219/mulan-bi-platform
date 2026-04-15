"""LLM 调用服务（异步）"""
import logging
import time
from typing import Optional, Tuple

from app.core.config import get_settings
from services.common.crypto import CryptoHelper

from .models import LLMConfigDatabase

logger = logging.getLogger(__name__)

# =============================================================================
# 加密工具（惰性加载，缓存清除后下次调用重新初始化）
# =============================================================================

_crypto_helper: Optional[CryptoHelper] = None
_crypto_helper_key_hash: Optional[str] = None  # 追踪当前加密密钥，防止 key rotation 后旧缓存


def _get_crypto() -> Tuple[CryptoHelper, str]:
    """获取 CryptoHelper 实例（惰性单例）。
    返回：(crypto_instance, key_hash) 元组。
    当密钥轮换后（key_hash 变化），重新初始化 CryptoHelper。
    """
    global _crypto_helper, _crypto_helper_key_hash
    settings = get_settings()
    current_key = settings.LLM_ENCRYPTION_KEY
    if not current_key:
        raise RuntimeError("LLM_ENCRYPTION_KEY 未配置，禁止启动 LLM 服务")
    key_hash = hash(current_key)  # 用 hash 而非明文比较

    if _crypto_helper is None or _crypto_helper_key_hash != key_hash:
        _crypto_helper = CryptoHelper(current_key)
        _crypto_helper_key_hash = key_hash
        logger.info("CryptoHelper 初始化完成（密钥 hash: %s）", key_hash)

    return _crypto_helper, key_hash


def _encrypt(plaintext: str) -> str:
    return _get_crypto()[0].encrypt(plaintext)


def _decrypt(ciphertext: str) -> str:
    return _get_crypto()[0].decrypt(ciphertext)


def clear_crypto_cache() -> None:
    """运维用：清除加密工具缓存（强制重新初始化，适用于密钥轮换）"""
    global _crypto_helper, _crypto_helper_key_hash
    _crypto_helper = None
    _crypto_helper_key_hash = None


# =============================================================================
# LLM Client 缓存（带 TTL 的 LRU，防止 API Key rotation 后旧 Client 卡死）
# =============================================================================

_CLIENT_CACHE_TTL_SECONDS = 300  # 5 分钟


class _TimedClientCache:
    """带 TTL 的 LLM Client 缓存。

    问题背景：若将 API Key 直接作为 client 缓存键，
    密钥轮换后旧 client 仍持有旧密钥导致 401。
    修复：按 (base_url, model) 缓存 client，
    并在每次 complete() 调用前检查 TTL 过期，过期则驱逐并重建。
    """

    def __init__(self, ttl_seconds: int = _CLIENT_CACHE_TTL_SECONDS):
        self._cache: dict = {}
        self._timestamps: dict = {}
        self._ttl = ttl_seconds

    def _make_key(self, provider: str, base_url: str, model: str, api_key: str) -> str:
        return f"{provider}:{base_url}:{model}:{hash(api_key)}"

    def get(self, provider: str, base_url: str, model: str, api_key: str):
        key = self._make_key(provider, base_url, model, api_key)
        if key in self._cache:
            # 检查 TTL
            if time.time() - self._timestamps.get(key, 0) > self._ttl:
                self._evict(key)
                return None
            return self._cache[key]
        return None

    def set(self, provider: str, base_url: str, model: str, api_key: str, client):
        key = self._make_key(provider, base_url, model, api_key)
        self._cache[key] = client
        self._timestamps[key] = time.time()

    def _evict(self, key: str):
        self._cache.pop(key, None)
        self._timestamps.pop(key, None)

    def clear(self):
        self._cache.clear()
        self._timestamps.clear()


_client_cache = _TimedClientCache()


class LLMService:
    """LLM 调用服务 — 单例，异步接口，客户端带 TTL 缓存"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config_db = LLMConfigDatabase()
        return cls._instance

    def _load_config(self):
        return self._config_db.get_config()

    def _get_openai_client(self, api_key: str, base_url: str, model: str, timeout: int):
        from openai import AsyncOpenAI
        cached = _client_cache.get("openai", base_url, model, api_key)
        if cached is not None:
            return cached
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        _client_cache.set("openai", base_url, model, api_key, client)
        return client

    def _get_anthropic_client(self, api_key: str, base_url: str, model: str, timeout: int):
        from anthropic import AsyncAnthropic
        cached = _client_cache.get("anthropic", base_url, model, api_key)
        if cached is not None:
            return cached
        client = AsyncAnthropic(api_key=api_key, base_url=base_url, timeout=timeout)
        _client_cache.set("anthropic", base_url, model, api_key, client)
        return client

    async def complete(self, prompt: str, system: str = None, timeout: int = 15) -> dict:
        """异步 LLM 调用
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
                return await self._anthropic_complete(api_key, config, prompt, system, timeout)
            else:
                return await self._openai_complete(api_key, config, prompt, system, timeout)
        except Exception as e:
            logger.error("LLM 调用失败: %s", e, exc_info=True)
            return {"error": str(e)}

    async def complete_with_temp(
        self, prompt: str, system: str = None, timeout: int = 15, temperature: float = 0.1
    ) -> dict:
        """异步 LLM 调用（指定 temperature，不继承全局配置）。
        用于 NL-to-Query One-Pass LLM 等对输出稳定性有强制要求的场景。
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
                return await self._anthropic_complete_with_temp(
                    api_key, config, prompt, system, timeout, temperature
                )
            else:
                return await self._openai_complete_with_temp(
                    api_key, config, prompt, system, timeout, temperature
                )
        except Exception as e:
            logger.error("LLM 调用失败: %s", e, exc_info=True)
            return {"error": str(e)}

    async def complete_for_semantic(
        self, prompt: str, system: str = None, timeout: int = 30
    ) -> dict:
        """Semantic 语义生成专用调用（Spec v1.2 §4.2 强制超参数）。

        - temperature=0.1（抑制幻觉，格式化元数据生成必须低随机性）
        - OpenAI 供应商：额外指定 response_format={"type": "json_object"}
        - Anthropic 供应商：不支持 response_format，仅设置 temperature=0.1

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
                return await self._anthropic_complete_with_temp(
                    api_key, config, prompt, system, timeout, temperature=0.1
                )
            else:
                return await self._openai_complete_with_semantic(
                    api_key, config, prompt, system, timeout
                )
        except Exception as e:
            logger.error("LLM 调用失败: %s", e, exc_info=True)
            return {"error": str(e)}

    async def _openai_complete_with_semantic(
        self, api_key: str, config, prompt: str, system: str, timeout: int
    ) -> dict:
        """OpenAI 语义生成专用路径：temperature=0.1 + response_format=json_object。
        """
        client = self._get_openai_client(api_key, config.base_url, config.model, timeout)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        logger.info(
            "LLM 调用（语义生成, temp=0.1, json_object）：model=%s, timeout=%ds",
            config.model, timeout,
        )
        response = await client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=0.1,
            max_tokens=config.max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content.strip()
        return {"content": content}

    async def _openai_complete_with_temp(
        self, api_key: str, config, prompt: str, system: str, timeout: int, temperature: float
    ) -> dict:
        client = self._get_openai_client(api_key, config.base_url, config.model, timeout)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        logger.info(
            "LLM 调用（OpenAI, temp=%.1f）：model=%s, timeout=%ds",
            temperature, config.model, timeout,
        )
        response = await client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=config.max_tokens,
        )
        content = response.choices[0].message.content.strip()
        return {"content": content}

    async def _anthropic_complete_with_temp(
        self, api_key: str, config, prompt: str, system: str, timeout: int, temperature: float
    ) -> dict:
        base_url = config.base_url or "https://api.minimaxi.com/anthropic"
        client = self._get_anthropic_client(api_key, base_url, config.model, timeout)
        messages = []
        if system:
            messages.append({"role": "user", "content": f"<system>{system}</system>\n\n{prompt}"})
        else:
            messages.append({"role": "user", "content": prompt})
        logger.info(
            "LLM 调用（Anthropic, temp=%.1f）：model=%s, base_url=%s, timeout=%ds",
            temperature, config.model, base_url, timeout,
        )
        try:
            response = await client.messages.create(
                model=config.model,
                messages=messages,
                temperature=temperature,
                max_tokens=config.max_tokens,
            )
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error("Anthropic API 调用失败 [%s]: %s", error_type, error_msg, exc_info=True)
            return {"error": f"Anthropic API 错误: {error_msg}"}

        from anthropic.types import TextBlock
        text_blocks = [block for block in response.content if isinstance(block, TextBlock)]
        if not text_blocks:
            logger.error("Anthropic 响应中无 TextBlock: %s", response.content)
            return {"error": "MiniMax 响应格式异常：未找到文本内容"}
        content = text_blocks[0].text.strip()
        return {"content": content}

    async def _openai_complete(self, api_key: str, config, prompt: str, system: str, timeout: int) -> dict:
        client = self._get_openai_client(api_key, config.base_url, config.model, timeout)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        logger.info("LLM 调用（OpenAI）：model=%s, timeout=%ds", config.model, timeout)
        response = await client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        content = response.choices[0].message.content.strip()
        return {"content": content}

    async def _anthropic_complete(self, api_key: str, config, prompt: str, system: str, timeout: int) -> dict:
        base_url = config.base_url or "https://api.minimaxi.com/anthropic"
        client = self._get_anthropic_client(api_key, base_url, config.model, timeout)
        messages = []
        if system:
            messages.append({"role": "user", "content": f"<system>{system}</system>\n\n{prompt}"})
        else:
            messages.append({"role": "user", "content": prompt})
        logger.info("LLM 调用（Anthropic）：model=%s, base_url=%s, timeout=%ds", config.model, base_url, timeout)
        try:
            response = await client.messages.create(
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
        from anthropic.types import TextBlock
        text_blocks = [block for block in response.content if isinstance(block, TextBlock)]
        if not text_blocks:
            logger.error("Anthropic 响应中无 TextBlock: %s", response.content)
            return {"error": "MiniMax 响应格式异常：未找到文本内容"}
        content = text_blocks[0].text.strip()
        return {"content": content}

    async def generate_asset_summary(self, asset) -> dict:
        """对 Tableau 资产生成摘要
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

        result = await self.complete(prompt, system="你是一个数据分析助手。", timeout=15)
        if "content" in result:
            return {"summary": result["content"]}
        return result

    async def generate_asset_explanation(self, asset, context: str = None) -> dict:
        """对报表/视图生成 AI 解读
        asset: TableauAsset 对象
        context: 可选的额外上下文信息
        Returns: { "explanation": str } or { "error": str }
        """
        from tableau.models import TableauDatabase

        from .prompts import ASSET_EXPLAIN_TEMPLATE

        db = TableauDatabase()

        # 获取父工作簿信息
        parent_workbook_info = "无"
        if asset.parent_workbook_id and asset.parent_workbook_name:
            parent_workbook_info = f"工作簿名称：{asset.parent_workbook_name}（ID: {asset.parent_workbook_id}）"
        elif asset.parent_workbook_id:
            parent_asset = db.get_parent_asset(asset.id)
            if parent_asset:
                parent_workbook_info = f"工作簿名称：{parent_asset.name}（ID: {asset.parent_workbook_id}）"

        # 获取关联数据源
        datasources_info = "无"
        datasources = db.get_asset_datasources(asset.id)
        if datasources:
            ds_list = []
            for ds in datasources[:5]:  # 最多显示5个
                ds_list.append(f"- {ds.datasource_name} ({ds.datasource_type or '未知类型'})")
            if len(datasources) > 5:
                ds_list.append(f"- ...还有 {len(datasources) - 5} 个数据源")
            datasources_info = "\n".join(ds_list)

        # 获取字段元数据
        field_metadata = "无"
        fields = db.get_datasource_fields(asset.id)
        if fields:
            field_list = []
            for f in fields[:10]:  # 最多显示10个字段
                role_label = "度量" if f.role == "measure" else "维度"
                formula_info = f"（公式: {f.formula}）" if f.formula else ""
                desc_info = f" - {f.description}" if f.description else ""
                field_list.append(f"- [{role_label}] {f.field_caption or f.field_name}{formula_info}{desc_info}")
            if len(fields) > 10:
                field_list.append(f"- ...还有 {len(fields) - 10} 个字段")
            field_metadata = "\n".join(field_list)

        prompt = ASSET_EXPLAIN_TEMPLATE.format(
            name=asset.name or "",
            asset_type=asset.asset_type or "",
            project_name=asset.project_name or "",
            description=asset.description or "",
            owner_name=asset.owner_name or "",
            parent_workbook_info=parent_workbook_info,
            datasources=datasources_info,
            field_metadata=field_metadata,
        )

        system_prompt = "你是一个 BI 报表解读专家。"
        if context:
            system_prompt += f"\n\n附加上下文：{context}"

        result = await self.complete(prompt, system=system_prompt, timeout=30)
        if "content" in result:
            return {"explanation": result["content"]}
        return result

    async def test_connection(self, test_prompt: str = "Hello, respond with 'OK'") -> dict:
        """测试 LLM 连接"""
        result = await self.complete(test_prompt, timeout=15)
        if "error" in result:
            return {"success": False, "message": result["error"]}
        return {"success": True, "message": result["content"]}

    async def generate_embedding_minimax(
        self,
        texts: list,
        model: str = "embo-01",
        type: str = "query",
        timeout: int = 30,
    ) -> dict:
        """批量生成 embedding（MiniMax embo-01）。

        Returns: { "embeddings": List[List[float]], "model": str } or { "error": str }
        注: 本方法独立于全局 provider 配置，固定走 MiniMax OpenAI 兼容 /v1/embeddings
        """
        config = self._load_config()
        if not config or not config.is_active or not config.api_key_encrypted:
            return {"error": "LLM 未配置，请联系管理员"}
        try:
            api_key = _decrypt(config.api_key_encrypted)
        except Exception as e:
            logger.error("解密失败: %s", e)
            return {"error": "LLM 认证配置错误"}

        import httpx
        url = "https://api.minimaxi.com/v1/embeddings"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "texts": texts, "type": type}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                body = resp.json()
            # MiniMax returns OpenAI-compatible { "data": [{ "embedding": [...] }] }
            embeddings = [item["embedding"] for item in body.get("data", [])]
            if not embeddings:
                # Fallback: MiniMax may return { "vectors": [...] }
                embeddings = body.get("vectors", [])
            if not embeddings:
                return {"error": f"MiniMax embedding 响应异常: {body}"}
            return {"embeddings": embeddings, "model": model}
        except httpx.HTTPStatusError as e:
            logger.error("MiniMax embedding HTTP %s: %s", e.response.status_code, e.response.text)
            return {"error": f"HTTP {e.response.status_code}"}
        except Exception as e:
            logger.error("MiniMax embedding 失败: %s", e)
            return {"error": str(e)}

    async def generate_embedding(self, text: str, model: str = "embo-01", timeout: int = 15) -> dict:
        """单条 embedding 向量生成（向后兼容）。
        内部转发到 MiniMax 批量接口。
        Returns: { "embedding": List[float] } or { "error": str }
        """
        result = await self.generate_embedding_minimax([text], model=model, type="query", timeout=timeout)
        if "error" in result:
            return result
        return {"embedding": result["embeddings"][0]}


llm_service = LLMService()
