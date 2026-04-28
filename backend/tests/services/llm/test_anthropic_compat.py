"""
B11: Anthropic兼容+MiniMax测试

验证点：
1. client.messages.create() — Anthropic SDK 调用路径正确
2. base_url fallback — config.base_url 为 None 时默认 https://api.minimaxi.com/anthropic
3. system prompt 格式 — <system>...</system>\n\n 包装到 user message 中
4. MiniMax ThinkingBlock 处理 — 只提取 TextBlock 内容，忽略 ThinkingBlock

覆盖：services/llm/service.py
  - _anthropic_complete()            → line 322
  - _anthropic_complete_with_temp()  → line 271
  - complete() routing               → line 139
"""
import sys
import types
import pytest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock


# =============================================================================
# Build a proper mock anthropic module chain BEFORE service.py is imported.
# service.py does runtime imports:  from anthropic.types import TextBlock
# We need sys.modules["anthropic.types"] to contain our mock TextBlock class.
# =============================================================================

class MockTextBlock:
    """Mimics anthropic.types.TextBlock"""
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class MockThinkingBlock:
    """Mimics anthropic.types.ThinkingBlock (MiniMax extended type)"""
    def __init__(self, thinking: str):
        self.type = "thinking"
        self.thinking = thinking


# Build a fake anthropic package
mock_anthropic = types.ModuleType("anthropic")
mock_anthropic_types = types.ModuleType("anthropic.types")
mock_anthropic_types.TextBlock = MockTextBlock
mock_anthropic_types.ThinkingBlock = MockThinkingBlock
mock_anthropic.types = mock_anthropic_types

sys.modules["anthropic"] = mock_anthropic
sys.modules["anthropic.types"] = mock_anthropic_types

# Also patch the import inside service.py's methods via mock.patch
# (service.py imports TextBlock at runtime per-call, so we patch the reference)
from services.llm.service import LLMService  # noqa: E402


# =============================================================================
# Fixtures
# =============================================================================

def _make_anthropic_config(
    base_url: str = "https://api.minimaxi.com/anthropic",
    model: str = "MiniMax-Text-01",
    provider: str = "anthropic",
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> MagicMock:
    cfg = MagicMock()
    cfg.base_url = base_url
    cfg.model = model
    cfg.provider = provider
    cfg.temperature = temperature
    cfg.max_tokens = max_tokens
    cfg.api_key_encrypted = "encrypted_key"
    cfg.is_active = True
    return cfg


# =============================================================================
# Test 1: client.messages.create() 调用路径
# =============================================================================

class TestAnthropicMessagesCreate:
    """验证 _anthropic_complete 调用 client.messages.create() 而非 chat.completions"""

    @pytest.mark.asyncio
    async def test_anthropic_complete_calls_messages_create(self):
        service = LLMService()
        config = _make_anthropic_config()
        mock_response = MagicMock()
        mock_response.content = [MockTextBlock("OK")]

        with (
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_anthropic_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service._anthropic_complete(
                api_key="fake_key",
                config=config,
                prompt="Say OK",
                system=None,
                timeout=15,
            )

        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "MiniMax-Text-01"
        assert call_kwargs["max_tokens"] == 1024
        assert call_kwargs["temperature"] == 0.7
        assert result["content"] == "OK"

    @pytest.mark.asyncio
    async def test_anthropic_complete_with_temp_calls_messages_create(self):
        service = LLMService()
        config = _make_anthropic_config()
        mock_response = MagicMock()
        mock_response.content = [MockTextBlock("OK")]

        with (
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_anthropic_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service._anthropic_complete_with_temp(
                api_key="fake_key",
                config=config,
                prompt="Say OK",
                system=None,
                timeout=15,
                temperature=0.3,
            )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3  # explicit temp used, not config default


# =============================================================================
# Test 2: base_url fallback
# =============================================================================

class TestBaseUrlFallback:
    """验证 config.base_url 为 None 时 fallback 到 https://api.minimaxi.com/anthropic"""

    @pytest.mark.asyncio
    async def test_base_url_fallback_in_anthropic_complete(self):
        service = LLMService()
        config = _make_anthropic_config(base_url=None)
        mock_response = MagicMock()
        mock_response.content = [MockTextBlock("OK")]

        captured_base_url = None

        def capture_client(api_key, base_url, model, timeout):
            nonlocal captured_base_url
            captured_base_url = base_url
            client = AsyncMock()
            client.messages.create = AsyncMock(return_value=mock_response)
            return client

        with (
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_anthropic_client", side_effect=capture_client),
        ):
            await service._anthropic_complete(
                api_key="fake_key",
                config=config,
                prompt="Hi",
                system=None,
                timeout=15,
            )

        assert captured_base_url == "https://api.minimaxi.com/anthropic"

    @pytest.mark.asyncio
    async def test_base_url_explicit_preserved(self):
        service = LLMService()
        explicit_url = "https://api.anthropic.com/v1"
        config = _make_anthropic_config(base_url=explicit_url)
        mock_response = MagicMock()
        mock_response.content = [MockTextBlock("OK")]

        captured_base_url = None

        def capture_client(api_key, base_url, model, timeout):
            nonlocal captured_base_url
            captured_base_url = base_url
            client = AsyncMock()
            client.messages.create = AsyncMock(return_value=mock_response)
            return client

        with (
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_anthropic_client", side_effect=capture_client),
        ):
            await service._anthropic_complete(
                api_key="fake_key",
                config=config,
                prompt="Hi",
                system=None,
                timeout=15,
            )

        assert captured_base_url == explicit_url


# =============================================================================
# Test 3: system prompt 格式
# =============================================================================

class TestSystemPromptFormat:
    """验证 system prompt 被包装为 <system>...</system>\n\n{prompt} 并放在 user message 中"""

    @pytest.mark.asyncio
    async def test_system_wrapped_in_system_tag_user_message(self):
        service = LLMService()
        config = _make_anthropic_config()
        mock_response = MagicMock()
        mock_response.content = [MockTextBlock("OK")]

        captured_messages = None

        def capture_client(api_key, base_url, model, timeout):
            client = AsyncMock()
            async def capture_create(**kwargs):
                nonlocal captured_messages
                captured_messages = kwargs["messages"]
                return mock_response
            client.messages.create = capture_create
            return client

        with (
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_anthropic_client", side_effect=capture_client),
        ):
            await service._anthropic_complete(
                api_key="fake_key",
                config=config,
                prompt="What is 2+2?",
                system="You are a mathematician.",
                timeout=15,
            )

        assert captured_messages is not None
        assert len(captured_messages) == 1
        assert captured_messages[0]["role"] == "user"
        content = captured_messages[0]["content"]
        assert content.startswith("<system>You are a mathematician.</system>\n\n")
        assert "What is 2+2?" in content

    @pytest.mark.asyncio
    async def test_no_system_prompt_no_system_tag(self):
        service = LLMService()
        config = _make_anthropic_config()
        mock_response = MagicMock()
        mock_response.content = [MockTextBlock("OK")]

        captured_messages = None

        def capture_client(api_key, base_url, model, timeout):
            client = AsyncMock()
            async def capture_create(**kwargs):
                nonlocal captured_messages
                captured_messages = kwargs["messages"]
                return mock_response
            client.messages.create = capture_create
            return client

        with (
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_anthropic_client", side_effect=capture_client),
        ):
            await service._anthropic_complete(
                api_key="fake_key",
                config=config,
                prompt="Hello",
                system=None,
                timeout=15,
            )

        assert captured_messages[0]["role"] == "user"
        assert "<system>" not in captured_messages[0]["content"]
        assert captured_messages[0]["content"] == "Hello"


# =============================================================================
# Test 4: MiniMax ThinkingBlock 处理
# =============================================================================

class TestMiniMaxThinkingBlock:
    """验证响应中包含 ThinkingBlock 时，只提取 TextBlock 内容"""

    @pytest.mark.asyncio
    async def test_thinking_block_ignored_text_block_extracted(self):
        service = LLMService()
        config = _make_anthropic_config()
        mock_response = MagicMock()

        # 模拟 MiniMax 返回：先 ThinkingBlock，后 TextBlock
        mock_response.content = [
            MockThinkingBlock("I should calculate step by step"),
            MockTextBlock("The answer is 4."),
        ]

        with (
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_anthropic_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service._anthropic_complete(
                api_key="fake_key",
                config=config,
                prompt="2+2=?",
                system=None,
                timeout=15,
            )

        # 应当返回 TextBlock 内容，而非 ThinkingBlock 内容
        assert result["content"] == "The answer is 4."

    @pytest.mark.asyncio
    async def test_only_text_block_returns_content(self):
        service = LLMService()
        config = _make_anthropic_config()
        mock_response = MagicMock()
        mock_response.content = [MockTextBlock("Simple answer.")]

        with (
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_anthropic_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service._anthropic_complete(
                api_key="fake_key",
                config=config,
                prompt="Hello",
                system=None,
                timeout=15,
            )

        assert result["content"] == "Simple answer."

    @pytest.mark.asyncio
    async def test_no_text_block_returns_error(self):
        service = LLMService()
        config = _make_anthropic_config()
        mock_response = MagicMock()

        # 只有 ThinkingBlock，没有 TextBlock
        mock_response.content = [MockThinkingBlock("思考中...")]

        with (
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_anthropic_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service._anthropic_complete(
                api_key="fake_key",
                config=config,
                prompt="Hello",
                system=None,
                timeout=15,
            )

        assert "error" in result
        assert "未找到文本内容" in result["error"]


# =============================================================================
# Test 5: complete() 路由到 Anthropic 路径
# =============================================================================

class TestAnthropicRouting:
    """验证 complete() 方法正确路由到 _anthropic_complete"""

    @pytest.mark.asyncio
    async def test_complete_routes_to_anthropic_for_minimax_provider(self):
        service = LLMService()
        config = _make_anthropic_config(provider="minimax")
        mock_response = MagicMock()
        mock_response.content = [MockTextBlock("OK")]

        with (
            mock.patch.object(service, "_load_config", return_value=config),
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_anthropic_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service.complete(
                prompt="Hello",
                system=None,
                timeout=15,
            )

        mock_get_client.assert_called_once()
        assert result["content"] == "OK"

    @pytest.mark.asyncio
    async def test_complete_routes_to_anthropic_for_base_url_with_anthropic(self):
        service = LLMService()
        # provider is openai, but base_url contains "anthropic" → should still route to anthropic
        config = _make_anthropic_config(provider="openai", base_url="https://custom.anthropic.com/v1")
        mock_response = MagicMock()
        mock_response.content = [MockTextBlock("OK")]

        with (
            mock.patch.object(service, "_load_config", return_value=config),
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_anthropic_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service.complete(
                prompt="Hello",
                system=None,
                timeout=15,
            )

        mock_get_client.assert_called_once()
        assert result["content"] == "OK"

    @pytest.mark.asyncio
    async def test_complete_routes_to_openai_for_openai_provider(self):
        service = LLMService()
        cfg = MagicMock()
        cfg.base_url = "https://api.openai.com/v1"
        cfg.model = "gpt-4o"
        cfg.provider = "openai"
        cfg.temperature = 0.7
        cfg.max_tokens = 1024
        cfg.api_key_encrypted = "encrypted_key"
        cfg.is_active = True
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hi"))]

        with (
            mock.patch.object(service, "_load_config", return_value=cfg),
            mock.patch("services.llm.service._decrypt", return_value="fake_key"),
            mock.patch.object(service, "_get_openai_client") as mock_get_client,
        ):
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service.complete(
                prompt="Hello",
                system=None,
                timeout=15,
            )

        mock_get_client.assert_called_once()
        # Should NOT call anthropic
        assert result["content"] == "Hi"
