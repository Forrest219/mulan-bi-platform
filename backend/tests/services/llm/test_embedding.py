"""
单元测试：services/llm/service.py embedding 相关（P3 T3.4）

覆盖：
- generate_embedding_minimax 返回正确形状
- generate_embedding 单条包装正确
- API 错误时返回 error dict
"""
import json
from unittest import mock

import pytest


class TestMinimaxEmbedding:
    """test_minimax_embedding_shape"""

    @pytest.mark.asyncio
    async def test_minimax_embedding_shape(self):
        """MiniMax API 返回 200 → embeddings 字段正确"""
        from services.llm.service import LLMService

        service = LLMService()

        mock_config = mock.Mock()
        mock_config.is_active = True
        mock_config.api_key_encrypted = "encrypted_key"
        mock_config.model = "embo-01"

        async def mock_post(url, json=None, headers=None, timeout=None):
            return mock.Mock(
                raise_for_status=lambda: None,
                json=lambda: {
                    "data": [{"embedding": [0.1] * 1024}],
                    "model": "embo-01",
                },
            )

        with (
            mock.patch.object(service, "_load_config", return_value=mock_config),
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch("httpx.AsyncClient") as MockAsyncClient,
        ):
            mock_client = mock.Mock()
            mock_client.post = mock_post
            mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mock.AsyncMock(return_value=None)
            MockAsyncClient.return_value = mock_client

            result = await service.generate_embedding_minimax(["test"])

        assert "embeddings" in result
        assert len(result["embeddings"][0]) == 1024
        assert result["model"] == "embo-01"

    @pytest.mark.asyncio
    async def test_embedding_compat_wrapper(self):
        """generate_embedding 包装 generate_embedding_minimax 单条结果"""
        from services.llm.service import LLMService

        service = LLMService()

        mock_config = mock.Mock()
        mock_config.is_active = True
        mock_config.api_key_encrypted = "encrypted_key"
        mock_config.model = "embo-01"

        async def mock_post(url, json=None, headers=None, timeout=None):
            return mock.Mock(
                raise_for_status=lambda: None,
                json=lambda: {
                    "data": [{"embedding": [0.5] * 1024}],
                    "model": "embo-01",
                },
            )

        with (
            mock.patch.object(service, "_load_config", return_value=mock_config),
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch("httpx.AsyncClient") as MockAsyncClient,
        ):
            mock_client = mock.Mock()
            mock_client.post = mock_post
            mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mock.AsyncMock(return_value=None)
            MockAsyncClient.return_value = mock_client

            result = await service.generate_embedding("销售额")

        assert "embedding" in result
        assert len(result["embedding"]) == 1024

    @pytest.mark.asyncio
    async def test_embedding_error_returns_error_dict(self):
        """HTTP 错误时返回 {error: ...} 而非抛异常"""
        from services.llm.service import LLMService

        service = LLMService()

        mock_config = mock.Mock()
        mock_config.is_active = True
        mock_config.api_key_encrypted = "encrypted_key"
        mock_config.model = "embo-01"

        async def mock_post(url, json=None, headers=None, timeout=None):
            resp = mock.Mock()
            resp.status_code = 429
            resp.text = "Rate limit"
            resp.raise_for_status = mock.Mock(
                side_effect=Exception("HTTP 429")
            )
            return resp

        with (
            mock.patch.object(service, "_load_config", return_value=mock_config),
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch("httpx.AsyncClient") as MockAsyncClient,
        ):
            mock_client = mock.Mock()
            mock_client.post = mock_post
            mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mock.AsyncMock(return_value=None)
            MockAsyncClient.return_value = mock_client

            result = await service.generate_embedding("test")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_minimax_fallback_vectors_field(self):
        """MiniMax 返回 vectors 字段（而非 data）时的兜底"""
        from services.llm.service import LLMService

        service = LLMService()

        mock_config = mock.Mock()
        mock_config.is_active = True
        mock_config.api_key_encrypted = "encrypted_key"
        mock_config.model = "embo-01"

        async def mock_post(url, json=None, headers=None, timeout=None):
            return mock.Mock(
                raise_for_status=lambda: None,
                json=lambda: {
                    "vectors": [[0.3] * 1024],
                    "model": "embo-01",
                },
            )

        with (
            mock.patch.object(service, "_load_config", return_value=mock_config),
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch("httpx.AsyncClient") as MockAsyncClient,
        ):
            mock_client = mock.Mock()
            mock_client.post = mock_post
            mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mock.AsyncMock(return_value=None)
            MockAsyncClient.return_value = mock_client

            result = await service.generate_embedding_minimax(["test"])

        assert "embeddings" in result
        assert len(result["embeddings"][0]) == 1024
