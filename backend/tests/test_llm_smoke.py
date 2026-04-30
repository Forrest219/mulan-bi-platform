"""
LLM 冒烟测试 — 验证 MiniMax / Ksyun LLM 真实连通性

使用环境变量（不得硬编码 Token）：
  MiniMax: MINIMAX_TOKEN / MINIMAX_BASE_URL / MINIMAX_MODEL
  Ksyun:   KSYUN_TOKEN / KSYUN_BASE_URL / KSYUN_MODEL

运行：
  cd backend
  export MINIMAX_TOKEN="sk-cp-..." && export KSYUN_TOKEN="..." && python tests/test_llm_smoke.py
"""
import asyncio
import os
import time


# MiniMax 配置（从环境变量读取）
MINIMAX_TOKEN = os.environ.get("MINIMAX_TOKEN", "")
MINIMAX_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com/anthropic")
MINIMAX_MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7")

# Ksyun 配置（从环境变量读取）
KSYUN_TOKEN = os.environ.get("KSYUN_TOKEN", "")
KSYUN_BASE_URL = os.environ.get("KSYUN_BASE_URL", "https://kspmas.ksyun.com")
KSYUN_MODEL = os.environ.get("KSYUN_MODEL", "glm-5")


async def test_minimax():
    import anthropic
    from anthropic.types import TextBlock

    client = anthropic.AsyncAnthropic(
        api_key=MINIMAX_TOKEN,
        base_url=MINIMAX_BASE_URL,
        timeout=30,
    )
    start = time.time()
    response = await client.messages.create(
        model=MINIMAX_MODEL,
        max_tokens=64,
        messages=[{"role": "user", "content": "回复 OK"}],
    )
    latency_ms = int((time.time() - start) * 1000)
    # MiniMax-M2.7 可能返回 ThinkingBlock，过滤出 TextBlock
    text_blocks = [b for b in response.content if isinstance(b, TextBlock)]
    text = text_blocks[0].text.strip() if text_blocks else ""
    assert text, f"response content 不应为空: {response}"
    assert "OK" in text, f"预期响应包含 'OK'，实际: {text}"
    print(f"✓ MiniMax 连通性 OK | model={response.model} | latency={latency_ms}ms | response={text}")


async def test_ksyun():
    """Ksyun 连通性测试 — 当前 token 返回 403，标记为需人工确认"""
    import anthropic
    from anthropic.types import TextBlock

    client = anthropic.AsyncAnthropic(
        api_key=KSYUN_TOKEN,
        base_url=KSYUN_BASE_URL,
        timeout=30,
    )
    start = time.time()
    try:
        response = await client.messages.create(
            model=KSYUN_MODEL,
            max_tokens=64,
            messages=[{"role": "user", "content": "回复 OK"}],
        )
        latency_ms = int((time.time() - start) * 1000)
        text_blocks = [b for b in response.content if isinstance(b, TextBlock)]
        text = text_blocks[0].text.strip() if text_blocks else ""
        print(f"✓ Ksyun 连通性 OK | model={response.model} | latency={latency_ms}ms | response={text}")
    except anthropic.PermissionDeniedError as e:
        print(f"✗ Ksyun 连通性失败 | 403 Forbidden — token 无权限，请检查 Ksyun Token | {e}")
        raise
    except Exception as e:
        print(f"✗ Ksyun 连通性失败 | {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    if not MINIMAX_TOKEN:
        raise RuntimeError("MINIMAX_TOKEN 环境变量未设置，不得硬编码 Token。运行方式：export MINIMAX_TOKEN=\"sk-cp-...\" && python tests/test_llm_smoke.py")
    print("=" * 60)
    print("LLM 冒烟测试 — MiniMax")
    print("=" * 60)
    asyncio.run(test_minimax())

    print()
    print("=" * 60)
    print("LLM 冒烟测试 — Ksyun")
    print("=" * 60)
    asyncio.run(test_ksyun())

    print()
    print("全部通过 ✓")
