"""测试：Tableau 资产对话 (SPEC 41)

测试场景：
1. LLM 返回 tool_call：SSE 帧序列包含 tool_call + assets + done
2. LLM 不调用 tool，直接回答：仅有 text + done
3. Tool Calling 超过 3 轮：验证强制截断，不无限循环
4. connection_id 无效：返回 403
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_sse_frames(text: str) -> list:
    """解析 SSE 响应文本，返回 frame dict 列表"""
    frames = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                frames.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return frames


MOCK_ASSETS = [
    {
        "id": 42,
        "name": "Executive Sales Dashboard",
        "asset_type": "dashboard",
        "health_score": 42,
        "project_name": "Revenue",
        "relevance_reason": "健康分低于阈值",
    }
]


# ── 场景 1：LLM 返回 tool_call，资产搜索 ─────────────────────────────────────

def test_chat_with_tool_call_returns_assets(admin_client, db_session):
    """LLM 返回 TOOL_CALL 格式，verify_connection_access pass，最终 SSE 含 assets 帧"""

    llm_responses = [
        # 第一轮：LLM 调用 search_assets
        {"content": 'TOOL_CALL: search_assets({"query": "健康分低于60的仪表板", "asset_type": "dashboard", "health_score_max": 60})'},
        # 第二轮：LLM 根据结果生成回答
        {"content": "根据搜索结果，找到以下健康分低于 60 的仪表板："},
    ]
    call_count = 0

    async def mock_complete(prompt, system=None, timeout=15, purpose="default"):
        nonlocal call_count
        resp = llm_responses[min(call_count, len(llm_responses) - 1)]
        call_count += 1
        return resp

    with patch("app.api.tableau.verify_connection_access"), \
         patch("services.tableau.asset_chat_service.IntentSearchService") as MockIS, \
         patch("services.llm.service.LLMService.complete", side_effect=mock_complete):

        mock_is_instance = MagicMock()
        mock_is_instance.recall_and_rank.return_value = MOCK_ASSETS
        MockIS.return_value = mock_is_instance

        resp = admin_client.post("/api/tableau/assets/chat", json={
            "message": "健康分低于60的仪表板",
            "connection_id": 1,
            "history": [],
            "context": {"current_filter": "dashboard", "visible_asset_count": 48},
        })

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert "text/event-stream" in resp.headers.get("content-type", "")

    frames = _parse_sse_frames(resp.text)
    frame_types = [f["type"] for f in frames]

    assert "tool_call" in frame_types, f"期望含 tool_call 帧，实际帧类型：{frame_types}"
    assert "assets" in frame_types, f"期望含 assets 帧，实际帧类型：{frame_types}"
    assert "done" in frame_types, f"期望含 done 帧，实际帧类型：{frame_types}"

    # 验证 assets 帧结构
    assets_frame = next(f for f in frames if f["type"] == "assets")
    assert isinstance(assets_frame["assets"], list)
    assert len(assets_frame["assets"]) > 0

    # done 必须是最后一帧
    assert frames[-1]["type"] == "done"


# ── 场景 2：LLM 直接回答，不调用 tool ────────────────────────────────────────

def test_chat_without_tool_call_returns_text_only(admin_client, db_session):
    """LLM 直接回答（无 TOOL_CALL）：SSE 仅含 text + done 帧"""

    async def mock_complete(prompt, system=None, timeout=15, purpose="default"):
        return {"content": "Tableau 是一个 BI 工具，用于数据可视化和分析。"}

    with patch("app.api.tableau.verify_connection_access"), \
         patch("services.llm.service.LLMService.complete", side_effect=mock_complete):

        resp = admin_client.post("/api/tableau/assets/chat", json={
            "message": "Tableau 是什么？",
            "connection_id": 1,
            "history": [],
            "context": {},
        })

    assert resp.status_code == 200
    frames = _parse_sse_frames(resp.text)
    frame_types = [f["type"] for f in frames]

    assert "text" in frame_types, f"期望含 text 帧，实际：{frame_types}"
    assert "done" in frame_types, f"期望含 done 帧，实际：{frame_types}"
    assert "tool_call" not in frame_types, f"不应含 tool_call 帧，实际：{frame_types}"
    assert "assets" not in frame_types, f"不应含 assets 帧，实际：{frame_types}"
    assert frames[-1]["type"] == "done"


# ── 场景 3：Tool Calling 超过 3 轮强制截断 ────────────────────────────────────

def test_chat_tool_calling_max_rounds_truncation(admin_client, db_session):
    """LLM 每轮都返回 tool_call，超过 MAX_TOOL_ROUNDS=3 后强制截断"""

    # LLM 永远返回 tool_call
    async def mock_complete_always_tool(prompt, system=None, timeout=15, purpose="default"):
        return {"content": 'TOOL_CALL: search_assets({"query": "测试", "asset_type": null, "health_score_max": null})'}

    call_count_holder = [0]

    with patch("app.api.tableau.verify_connection_access"), \
         patch("services.tableau.asset_chat_service.IntentSearchService") as MockIS, \
         patch("services.llm.service.LLMService.complete", side_effect=mock_complete_always_tool):

        mock_is_instance = MagicMock()
        mock_is_instance.recall_and_rank.return_value = []
        MockIS.return_value = mock_is_instance

        resp = admin_client.post("/api/tableau/assets/chat", json={
            "message": "给我找所有资产",
            "connection_id": 1,
            "history": [],
            "context": {},
        })

    assert resp.status_code == 200
    frames = _parse_sse_frames(resp.text)

    # 验证有 done 帧（没有无限循环）
    assert frames[-1]["type"] == "done", "强制截断后必须有 done 帧"

    # tool_call 帧数不超过 MAX_TOOL_ROUNDS=3
    tool_call_frames = [f for f in frames if f["type"] == "tool_call"]
    assert len(tool_call_frames) <= 3, f"tool_call 帧数超过上限 3，实际：{len(tool_call_frames)}"


# ── 场景 4：connection_id 无效返回 403 ────────────────────────────────────────

def test_chat_invalid_connection_returns_403(admin_client, db_session):
    """connection_id 无效时返回 403 HTTP 错误（非 SSE 响应）"""
    from fastapi import HTTPException

    with patch("app.api.tableau.verify_connection_access",
               side_effect=HTTPException(status_code=403, detail="无权访问该连接")):

        resp = admin_client.post("/api/tableau/assets/chat", json={
            "message": "搜索资产",
            "connection_id": 99999,
            "history": [],
            "context": {},
        })

    assert resp.status_code == 403, f"期望 403，实际 {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("detail", {}).get("error_code") == "TAB_AC_001"


# ── 场景 5：LLM 不可用返回 error 帧 ─────────────────────────────────────────

def test_chat_llm_unavailable_returns_error_frame(admin_client, db_session):
    """LLM 不可用时 SSE 流中返回 error 帧"""
    from app.core.errors import MulanError

    async def mock_complete_raises(*args, **kwargs):
        raise MulanError("LLM_500", "所有 LLM 配置均不可用", 500, {})

    with patch("app.api.tableau.verify_connection_access"), \
         patch("services.llm.service.LLMService.complete", side_effect=mock_complete_raises):

        resp = admin_client.post("/api/tableau/assets/chat", json={
            "message": "搜索资产",
            "connection_id": 1,
            "history": [],
            "context": {},
        })

    assert resp.status_code == 200  # SSE 本身 200，错误通过帧传递
    frames = _parse_sse_frames(resp.text)
    error_frames = [f for f in frames if f["type"] == "error"]
    assert len(error_frames) > 0, f"期望有 error 帧，实际帧：{frames}"
    assert error_frames[0]["code"] == "TAB_AC_002"
