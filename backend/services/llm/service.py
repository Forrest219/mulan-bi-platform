"""LLM 调用服务（异步）"""
import os
import logging
from typing import Optional

from .models import LLMConfigDatabase
from services.common.crypto import CryptoHelper

logger = logging.getLogger(__name__)

# 加密密钥（优先 LLM_ENCRYPTION_KEY，回退 DATASOURCE_ENCRYPTION_KEY）
_ENCRYPTION_KEY = os.environ.get("LLM_ENCRYPTION_KEY") or os.environ.get("DATASOURCE_ENCRYPTION_KEY")
if not _ENCRYPTION_KEY:
    raise RuntimeError("LLM_ENCRYPTION_KEY or DATASOURCE_ENCRYPTION_KEY must be set")

_crypto = CryptoHelper(_ENCRYPTION_KEY)
_encrypt = _crypto.encrypt
_decrypt = _crypto.decrypt


class LLMService:
    """LLM 调用服务 — 单例，异步接口，客户端单例缓存"""
    _instance = None
    _clients: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config_db = LLMConfigDatabase()
            cls._instance._clients = {}
        return cls._instance

    def _load_config(self):
        return self._config_db.get_config()

    def _get_openai_client(self, api_key: str, base_url: str, timeout: int):
        from openai import AsyncOpenAI
        key = f"openai:{base_url}"
        if key not in self._clients:
            self._clients[key] = AsyncOpenAI(
                api_key=api_key, base_url=base_url, timeout=timeout,
            )
        return self._clients[key]

    def _get_anthropic_client(self, api_key: str, base_url: str, timeout: int):
        from anthropic import AsyncAnthropic
        key = f"anthropic:{base_url}"
        if key not in self._clients:
            self._clients[key] = AsyncAnthropic(
                api_key=api_key, base_url=base_url, timeout=timeout,
            )
        return self._clients[key]

    async def complete(self, prompt: str, system: str = None, timeout: int = 15) -> dict:
        """
        异步 LLM 调用
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

    async def _openai_complete(self, api_key: str, config, prompt: str, system: str, timeout: int) -> dict:
        client = self._get_openai_client(api_key, config.base_url, timeout)
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
        client = self._get_anthropic_client(api_key, base_url, timeout)
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
            return {"error": f"MiniMax 响应格式异常：未找到文本内容"}
        content = text_blocks[0].text.strip()
        return {"content": content}

    async def generate_asset_summary(self, asset) -> dict:
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

        result = await self.complete(prompt, system="你是一个数据分析助手。", timeout=15)
        if "content" in result:
            return {"summary": result["content"]}
        return result

    async def generate_asset_explanation(self, asset, context: str = None) -> dict:
        """
        对报表/视图生成 AI 解读
        asset: TableauAsset 对象
        context: 可选的额外上下文信息
        Returns: { "explanation": str } or { "error": str }
        """
        from .prompts import ASSET_EXPLAIN_TEMPLATE
        from tableau.models import TableauDatabase

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


llm_service = LLMService()
