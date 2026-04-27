"""单元测试：Data Agent ReAct Engine — 纯逻辑函数

覆盖范围：
- _estimate_tokens: CJK/ASCII 估算
- _truncate_history: 历史消息截断
- _build_think_prompt: Think prompt 构建
- _build_history_messages: session 历史消息提取
- ReActEngine._parse_llm_response: JSON 解析
- ReActEngine._parse_text_response: 非 JSON fallback
"""
import os
import pytest
from unittest.mock import MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")

from services.data_agent.engine import (
    _estimate_tokens,
    _truncate_history,
    _build_think_prompt,
    _build_history_messages,
    ReActEngine,
    DEFAULT_MAX_STEPS,
    DEFAULT_STEP_TIMEOUT,
    DEFAULT_TOTAL_TIMEOUT,
    DEFAULT_MAX_TOOL_RETRIES,
    DEFAULT_MAX_HISTORY_TOKENS,
)
from services.data_agent.tool_base import ToolRegistry, ToolContext


# =====================================================================
# _estimate_tokens
# =====================================================================


class TestEstimateTokens:
    """Token 估算函数测试"""

    def test_empty_string(self):
        assert _estimate_tokens("") == 1  # +1 baseline

    def test_ascii_only(self):
        """纯 ASCII: 每 4 字符 ≈ 1 token"""
        result = _estimate_tokens("abcd")
        assert result == 2  # ascii_count // 4 + 1 = 1 + 1

    def test_cjk_only(self):
        """纯 CJK: 每字 1 token"""
        result = _estimate_tokens("你好世界")
        assert result == 5  # 4 CJK + 1

    def test_mixed(self):
        """中英混合"""
        text = "hello你好"  # 5 ASCII + 2 CJK
        result = _estimate_tokens(text)
        # cjk=2, ascii=5 → 2 + 5//4 + 1 = 2 + 1 + 1 = 4
        assert result == 4


# =====================================================================
# _truncate_history
# =====================================================================


class TestTruncateHistory:
    """历史消息截断测试"""

    def test_empty_messages(self):
        assert _truncate_history([], 100) == []

    def test_within_budget_no_truncation(self):
        """预算充裕不截断"""
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = _truncate_history(msgs, 10000)
        assert len(result) == 2

    def test_truncation_preserves_recent_messages(self):
        """截断保留最近 2 条消息"""
        msgs = [
            {"role": "user", "content": "a" * 100},
            {"role": "assistant", "content": "b" * 100},
            {"role": "user", "content": "c" * 100},
            {"role": "assistant", "content": "d"},
        ]
        # 给很小的预算，强制截断
        result = _truncate_history(msgs, 10)
        # 至少保留最近 2 条
        assert len(result) >= 2
        assert result[-1]["content"] == "d"

    def test_truncation_marker_inserted(self):
        """截断时插入 [历史已截断] 标记"""
        msgs = [
            {"role": "user", "content": "x" * 200},
            {"role": "assistant", "content": "y" * 200},
            {"role": "user", "content": "z"},
            {"role": "assistant", "content": "w"},
        ]
        result = _truncate_history(msgs, 15)
        # 检查是否有截断标记
        has_marker = any("[历史已截断]" in msg.get("content", "") for msg in result)
        # 如果发生了截断，应该有标记
        if len(result) < len(msgs):
            assert has_marker

    def test_single_message_no_truncation(self):
        """单条消息不截断"""
        msgs = [{"role": "user", "content": "hello"}]
        result = _truncate_history(msgs, 1)
        assert len(result) >= 1


# =====================================================================
# _build_think_prompt
# =====================================================================


class TestBuildThinkPrompt:
    """Think prompt 构建测试"""

    def test_basic_prompt(self):
        """基本 prompt 包含用户问题和步数"""
        prompt = _build_think_prompt("分析销量", [], 1)
        assert "分析销量" in prompt
        assert "1" in prompt
        assert "请根据以上信息" in prompt

    def test_prompt_with_history(self):
        """带历史的 prompt"""
        history = [
            {"role": "user", "content": "之前的问题"},
            {"role": "assistant", "content": "之前的回答"},
        ]
        prompt = _build_think_prompt("新问题", history, 2)
        assert "新问题" in prompt
        assert "历史对话" in prompt

    def test_prompt_with_tool_history(self):
        """带工具结果的历史"""
        history = [
            {"role": "tool", "name": "query_tool", "content": '{"data": [1,2,3]}'},
        ]
        prompt = _build_think_prompt("继续分析", history, 3)
        assert "query_tool" in prompt

    def test_prompt_step_number(self):
        """步数正确显示"""
        prompt = _build_think_prompt("q", [], 5)
        assert "5" in prompt


# =====================================================================
# _build_history_messages
# =====================================================================


class TestBuildHistoryMessages:
    """session 历史消息提取测试"""

    def test_none_session(self):
        """session=None 返回空列表"""
        assert _build_history_messages(None) == []

    def test_session_with_get_messages(self):
        """session.get_messages 可用"""
        msg = MagicMock()
        msg.role = "user"
        msg.content = "hello"

        session = MagicMock()
        session.get_messages.return_value = [msg]

        result = _build_history_messages(session)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "hello"

    def test_session_with_messages_attr(self):
        """session.messages 属性可用"""
        session = MagicMock(spec=[])
        session.messages = [
            {"role": "user", "content": "test"},
        ]
        # 移除 get_messages 让它走 messages 分支
        del session.get_messages

        result = _build_history_messages(session)
        assert len(result) == 1

    def test_session_exception_returns_empty(self):
        """session 异常返回空列表"""
        session = MagicMock()
        session.get_messages.side_effect = RuntimeError("db error")

        result = _build_history_messages(session)
        assert result == []


# =====================================================================
# ReActEngine._parse_llm_response
# =====================================================================


class TestParseLlmResponse:
    """LLM 响应解析测试"""

    def _make_engine(self):
        registry = ToolRegistry()
        llm = MagicMock()
        return ReActEngine(registry=registry, llm_service=llm)

    def test_parse_valid_json_tool_call(self):
        """有效 JSON tool_call 响应"""
        engine = self._make_engine()
        content = '{"action": "tool_call", "tool_name": "query_tool", "tool_params": {"sql": "SELECT 1"}, "reasoning": "需要查询"}'
        result = engine._parse_llm_response(content)
        assert result["action"] == "tool_call"
        assert result["tool_name"] == "query_tool"
        assert result["tool_params"]["sql"] == "SELECT 1"
        assert result["reasoning"] == "需要查询"

    def test_parse_valid_json_final_answer(self):
        """有效 JSON final_answer 响应"""
        engine = self._make_engine()
        content = '{"action": "final_answer", "answer": "销量为 1000"}'
        result = engine._parse_llm_response(content)
        assert result["action"] == "final_answer"
        assert result["answer"] == "销量为 1000"

    def test_parse_invalid_json_with_tool_name(self):
        """非 JSON 但包含 tool_name"""
        engine = self._make_engine()
        content = 'Let me use "tool_name": "schema_tool" to check'
        result = engine._parse_llm_response(content)
        assert result["action"] == "tool_call"
        assert result["tool_name"] == "schema_tool"

    def test_parse_plain_text_becomes_final_answer(self):
        """纯文本变为 final_answer"""
        engine = self._make_engine()
        content = "这是一个直接的回答。"
        result = engine._parse_llm_response(content)
        assert result["action"] == "final_answer"
        assert "直接的回答" in result["answer"]

    def test_parse_empty_json(self):
        """空 JSON 默认 final_answer"""
        engine = self._make_engine()
        content = '{}'
        result = engine._parse_llm_response(content)
        assert result["action"] == "final_answer"


# =====================================================================
# ReActEngine._parse_text_response
# =====================================================================


class TestParseTextResponse:
    """非 JSON 文本响应解析测试"""

    def _make_engine(self):
        registry = ToolRegistry()
        llm = MagicMock()
        return ReActEngine(registry=registry, llm_service=llm)

    def test_extract_tool_name(self):
        """从文本中提取 tool_name"""
        engine = self._make_engine()
        result = engine._parse_text_response('I think I should use "tool_name": "metrics_tool"')
        assert result["action"] == "tool_call"
        assert result["tool_name"] == "metrics_tool"

    def test_extract_action(self):
        """从文本中提取 action"""
        engine = self._make_engine()
        result = engine._parse_text_response('I need to run "action": "tool_call" with "tool_name": "query_tool"')
        assert result["tool_name"] == "query_tool"

    def test_no_tool_name_becomes_final_answer(self):
        """无 tool_name 视为最终回答"""
        engine = self._make_engine()
        result = engine._parse_text_response("答案是 42。")
        assert result["action"] == "final_answer"
        assert "42" in result["answer"]

    def test_empty_content(self):
        """空内容返回默认回答"""
        engine = self._make_engine()
        result = engine._parse_text_response("")
        assert result["action"] == "final_answer"
        assert "抱歉" in result["answer"]

    def test_long_text_truncated(self):
        """过长文本截断到 500 字符"""
        engine = self._make_engine()
        long_text = "x" * 600
        result = engine._parse_text_response(long_text)
        assert len(result["answer"]) <= 500


# =====================================================================
# ReActEngine 配置默认值
# =====================================================================


class TestEngineDefaults:
    """引擎默认配置测试"""

    def test_default_values(self):
        assert DEFAULT_MAX_STEPS == 10
        assert DEFAULT_STEP_TIMEOUT == 30
        assert DEFAULT_TOTAL_TIMEOUT == 120
        assert DEFAULT_MAX_TOOL_RETRIES == 1
        assert DEFAULT_MAX_HISTORY_TOKENS == 4000

    def test_engine_initialization(self):
        """引擎初始化使用默认值"""
        registry = ToolRegistry()
        llm = MagicMock()
        engine = ReActEngine(registry=registry, llm_service=llm)

        assert engine.max_steps == DEFAULT_MAX_STEPS
        assert engine.step_timeout == DEFAULT_STEP_TIMEOUT
        assert engine.total_timeout == DEFAULT_TOTAL_TIMEOUT
        assert engine.max_tool_retries == DEFAULT_MAX_TOOL_RETRIES
        assert engine.max_history_tokens == DEFAULT_MAX_HISTORY_TOKENS

    def test_engine_custom_config(self):
        """引擎自定义配置"""
        registry = ToolRegistry()
        llm = MagicMock()
        engine = ReActEngine(
            registry=registry,
            llm_service=llm,
            max_steps=5,
            step_timeout=60,
        )
        assert engine.max_steps == 5
        assert engine.step_timeout == 60
