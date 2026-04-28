"""Async-to-sync bridge for calling async LLM functions from sync contexts.

Handles both "no event loop" (Celery worker) and "running event loop" (FastAPI)
scenarios without crashing.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=4)


def run_async_safely(coro):
    """Run an async coroutine from sync code, regardless of event loop state.

    - No running loop (e.g. Celery worker): uses asyncio.run() directly.
    - Running loop (e.g. FastAPI handler): offloads to a thread via ThreadPoolExecutor.
    """
    try:
        asyncio.get_running_loop()
        future = _executor.submit(asyncio.run, coro)
        return future.result(timeout=120)
    except RuntimeError:
        return asyncio.run(coro)
