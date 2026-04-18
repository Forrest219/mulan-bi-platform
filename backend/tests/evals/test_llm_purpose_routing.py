"""
Eval: 陷阱 5 — LLM purpose 路由静默降级

验证目标：
  当请求 embedding purpose 的配置，但数据库中只有 default purpose 配置时，
  LLMConfigDatabase.get_config(purpose='embedding') 会静默 fallback 到 default，
  导致 embedding 调用实际走了 general LLM（可能返回文本而非向量）。

  正确行为应该是：
  - 若业务代码明确需要 purpose='embedding' 的配置，应当显式检测并抛出明确异常，
    而不是静默降级到 default。

本测试会：
1. 检测当前 get_config() 的 fallback 行为（记录现状）
2. 验证调用层（LLMService.generate_embedding）在无 embedding 配置时的实际行为
3. 若静默降级，标记为 ❌ FAIL 并说明陷阱依然存在

注意：本测试不连接真实数据库，通过 monkeypatch/mock 模拟配置层。
"""
import pytest
from unittest.mock import MagicMock, patch
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：构造 mock LLMConfig 对象
# ─────────────────────────────────────────────────────────────────────────────

def _make_config(purpose: str = "default", is_active: bool = True) -> MagicMock:
    cfg = MagicMock()
    cfg.purpose = purpose
    cfg.is_active = is_active
    cfg.api_key_encrypted = "encrypted_key"
    cfg.provider = "openai"
    cfg.base_url = "https://api.openai.com/v1"
    cfg.model = "gpt-4o-mini"
    cfg.temperature = 0.7
    cfg.max_tokens = 1024
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# 测试 LLMConfigDatabase.get_config() 的 fallback 行为
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMPurposeRoutingFallback:
    """
    验证 get_config() 的路由逻辑。

    当前实现（models.py）：
      1. 查 purpose=<purpose> AND is_active=True → 找到则返回
      2. 找不到 → fallback 查 purpose='default' AND is_active=True
      3. 仍找不到 → 返回 None

    陷阱：步骤 2 的 fallback 是静默的，embedding 调用方不会收到任何警告。
    """

    def test_get_config_returns_specific_purpose_when_exists(self):
        """有 embedding 配置时，应返回 embedding 配置（正常路由）"""
        from services.llm.models import LLMConfigDatabase

        embedding_cfg = _make_config(purpose="embedding")
        default_cfg = _make_config(purpose="default")

        db = LLMConfigDatabase()

        # mock query 链
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_order = MagicMock()

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.order_by.return_value = mock_order
        # 第一次查询（embedding purpose）返回 embedding_cfg
        mock_order.first.return_value = embedding_cfg

        with patch.object(db, "get_session", return_value=mock_session):
            result = db.get_config(purpose="embedding")

        assert result is not None
        assert result.purpose == "embedding"

    def test_get_config_silently_falls_back_to_default(self):
        """
        无 embedding 配置时，get_config('embedding') 会静默 fallback 到 default。

        这记录了陷阱的现状：当前代码不会抛出异常，而是返回 default 配置。
        """
        from services.llm.models import LLMConfigDatabase

        default_cfg = _make_config(purpose="default")

        db = LLMConfigDatabase()

        call_count = [0]

        mock_session = MagicMock()
        mock_query = MagicMock()

        def mock_filter(*args, **kwargs):
            f = MagicMock()
            o = MagicMock()
            f.order_by.return_value = o
            call_count[0] += 1
            if call_count[0] == 1:
                # 第一次查询 embedding purpose → 返回 None（无配置）
                o.first.return_value = None
            else:
                # 第二次查询 default purpose → 返回 default_cfg（fallback）
                o.first.return_value = default_cfg
            return f

        mock_session.query.return_value = mock_query
        mock_query.filter.side_effect = mock_filter

        with patch.object(db, "get_session", return_value=mock_session):
            result = db.get_config(purpose="embedding")

        # ─── 陷阱现状记录 ───────────────────────────────────────────────────
        # 当前代码静默 fallback，返回 default 配置而非 None 或异常
        # 这意味着 embedding 调用会被路由到 general LLM，静默产生错误结果
        assert result is not None, (
            "get_config('embedding') 返回了 None，未发生 fallback（行为变更）"
        )
        assert result.purpose == "default", (
            f"预期 fallback 返回 default 配置，实际 purpose={result.purpose}"
        )
        # ────────────────────────────────────────────────────────────────────

    def test_get_config_returns_none_when_no_config_at_all(self):
        """数据库完全无配置时，get_config 返回 None"""
        from services.llm.models import LLMConfigDatabase

        db = LLMConfigDatabase()

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_order = MagicMock()
        mock_order.first.return_value = None

        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.order_by.return_value = mock_order

        with patch.object(db, "get_session", return_value=mock_session):
            result = db.get_config(purpose="default")

        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# 测试 LLMService.generate_embedding 的实际行为
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMServiceEmbeddingBehavior:
    """
    验证 LLMService.generate_embedding / generate_embedding_minimax
    在无专用 embedding 配置时的行为。

    陷阱：generate_embedding_minimax 调用 self._load_config()（无 purpose 参数），
    即默认走 purpose='default' 路由，即使数据库完全无配置也只返回 {"error": "..."}，
    不会抛出明确的"embedding 配置缺失"异常。
    """

    @pytest.mark.asyncio
    async def test_generate_embedding_returns_error_when_no_config(self):
        """
        无 LLM 配置时，generate_embedding 返回 {"error": "..."} 而非抛出异常。
        这是当前的设计（返回错误字典），测试确认此行为存在。
        """
        import os
        os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

        from services.llm.service import LLMService

        service = LLMService.__new__(LLMService)
        service._config_db = MagicMock()
        # 模拟无任何配置
        service._config_db.get_config.return_value = None

        result = await service.generate_embedding("test text")

        # 当前行为：返回错误字典，不抛出异常
        assert "error" in result, (
            f"无配置时 generate_embedding 应返回包含 error 的字典，实际返回: {result}"
        )
        assert "LLM 未配置" in result["error"] or "未配置" in result["error"], (
            f"错误信息应提示 LLM 未配置，实际: {result['error']}"
        )

    @pytest.mark.asyncio
    async def test_generate_embedding_silent_fallback_detection(self):
        """
        ❌ 陷阱核心检测：
        当 embedding purpose 无配置，但 default purpose 有配置时，
        generate_embedding_minimax 会静默使用 default 配置调用通用 LLM API。

        期望行为（修复后）：应抛出明确异常或返回带有 purpose_mismatch 标记的错误。
        当前行为（陷阱存在）：静默使用 default 配置，可能调用非 embedding 模型。

        本测试验证当前行为，并将静默降级标记为已知问题。
        """
        import os
        os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

        from services.llm.service import LLMService

        # 构造只有 default 配置的场景（无 embedding 专用配置）
        default_only_config = _make_config(purpose="default")

        service = LLMService.__new__(LLMService)
        service._config_db = MagicMock()
        # get_config() 无论传什么 purpose 都返回 default 配置（模拟 fallback）
        service._config_db.get_config.return_value = default_only_config

        # mock _decrypt 以避免真实加密操作
        with patch("services.llm.service._decrypt", return_value="fake-api-key"):
            # mock httpx 调用，模拟 MiniMax embedding API 响应
            import httpx
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1, 0.2, 0.3]}]
            }

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = MagicMock(return_value=mock_ctx)
                mock_ctx.__aexit__ = MagicMock(return_value=False)
                mock_ctx.post = MagicMock(return_value=mock_response)
                mock_client_class.return_value = mock_ctx

                # 当前 generate_embedding_minimax 使用 _load_config()（无 purpose 参数）
                # 即默认走 'default' 路由，不管调用方意图
                result = await service.generate_embedding_minimax(["test"])

        # ─── 陷阱现状记录 ───────────────────────────────────────────────────
        # 当前代码会"成功"返回，但实际使用的是 default 配置（非 embedding 专用）
        # 这就是静默降级：调用方以为用了 embedding 模型，实际可能用了 general LLM
        #
        # 若此断言失败（result 中有 error），说明代码已被修复，陷阱已消除
        if "error" not in result:
            # 静默降级发生了：调用"成功"但配置来源不对
            pytest.xfail(
                "陷阱 5 仍然存在：generate_embedding_minimax 静默使用了 default 配置，"
                "未检测 embedding purpose 配置的缺失。"
                "修复建议：在 generate_embedding_minimax 中先检查专用 embedding 配置，"
                "若不存在则抛出明确异常：raise LLMPurposeNotConfiguredError('embedding')"
            )
        else:
            # 如果有 error，说明某个层面已有检测（可能修复了）
            pass

    @pytest.mark.asyncio
    async def test_embedding_purpose_specific_config_lookup(self):
        """
        理想行为测试（文档性）：
        若代码已修复，应使用 purpose='embedding' 查询配置。
        本测试验证 _load_config 是否被正确调用。
        """
        import os
        os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

        from services.llm.service import LLMService

        service = LLMService.__new__(LLMService)
        service._config_db = MagicMock()
        service._config_db.get_config.return_value = None  # 无配置

        result = await service.generate_embedding("test")

        # 无论如何，结果应该是 error（无配置）
        assert "error" in result

        # 记录实际调用了哪个 purpose（揭示当前行为）
        call_args = service._config_db.get_config.call_args
        actual_purpose = call_args[1].get("purpose", call_args[0][0] if call_args[0] else "default")

        # 文档性断言：记录当前行为
        # 若 actual_purpose == "default"，说明 embedding 未使用专用 purpose 路由（陷阱存在）
        # 若 actual_purpose == "embedding"，说明已修复
        if actual_purpose == "default" or actual_purpose is None:
            pytest.xfail(
                f"陷阱 5 确认：generate_embedding 调用 _load_config(purpose='{actual_purpose}')，"
                "未使用 embedding 专用 purpose。"
                "这意味着即使配置了专用 embedding 模型，generate_embedding 也不会使用它。"
            )
