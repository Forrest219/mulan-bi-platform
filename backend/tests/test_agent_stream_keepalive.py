"""SSE keep-alive behavior for Data Agent streaming."""

import asyncio

import pytest

from app.api.agent import _stream_with_keepalive


pytestmark = pytest.mark.skip_db


@pytest.mark.asyncio
async def test_stream_with_keepalive_emits_comment_during_silent_await():
    async def source():
        await asyncio.sleep(0.03)
        yield 'data: {"type": "done"}\n\n'

    stream = _stream_with_keepalive(source(), heartbeat_interval_seconds=0.01)
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    assert any(chunk.startswith(": ping ") for chunk in chunks)
    assert 'data: {"type": "done"}\n\n' in chunks
