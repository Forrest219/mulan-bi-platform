/**
 * @vitest-environment jsdom
 *
 * 覆盖场景：
 *   P0-1  sendMessage 并发保护 — 快速双击时只允许一个请求在途
 *   P0-2  listQueryDatasources 竞态取消 — 旧请求被 abort 后结果不写入 state
 *   P2-1  超时错误 — fetch 抛出 TimeoutError/AbortError 时展示友好消息
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// ─── 全局 fetch mock（在 import 模块之前设置） ───────────────────────────────
const mockFetch = vi.fn();
global.fetch = mockFetch;

// 顶层 import，确保所有 case 使用同一份已打过补丁的模块
import { useQuerySession } from '@/hooks/useQuerySession';
import { listQueryDatasources } from '@/api/query';

// ─── P0-1: sendMessage 并发保护 ──────────────────────────────────────────────

describe('P0-1 useQuerySession — sendMessage 并发保护', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('第二次调用 sendMessage 在第一次未完成时应被忽略（只发一次 fetch）', async () => {
    // 模拟慢请求：fetch 挂起，直到手动 resolve
    let resolveFirst!: () => void;

    mockFetch.mockImplementationOnce(
      () =>
        new Promise<{ ok: true; json: () => Promise<object> }>((resolve) => {
          resolveFirst = () =>
            resolve({
              ok: true,
              json: async () => ({
                session_id: 'sess-1',
                message_id: 'msg-1',
                answer: '结果',
              }),
            });
        }),
    );

    const { result } = renderHook(() => useQuerySession());

    const req = {
      message: '问题',
      connection_id: 1,
      datasource_luid: 'ds-luid',
    };

    // 第一次发送（不 await，让它挂起）
    act(() => {
      void result.current.sendMessage(req);
    });

    // 立即发第二次（模拟快速双击）
    act(() => {
      void result.current.sendMessage(req);
    });

    // 第一次 fetch 完成
    await act(async () => {
      resolveFirst();
      await Promise.resolve();
    });

    // fetch 只应被调用一次
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('第一次请求完成后，可以正常发出第二次请求', async () => {
    const makeResponse = (answer: string) => ({
      ok: true,
      json: async () => ({
        session_id: 'sess-1',
        message_id: crypto.randomUUID(),
        answer,
      }),
    });

    mockFetch
      .mockResolvedValueOnce(makeResponse('第一次回答'))
      .mockResolvedValueOnce(makeResponse('第二次回答'));

    const { result } = renderHook(() => useQuerySession());

    const req = { message: '问题', connection_id: 1, datasource_luid: 'ds-luid' };

    await act(async () => {
      await result.current.sendMessage(req);
    });

    await act(async () => {
      await result.current.sendMessage(req);
    });

    // 两次请求均应发出
    expect(mockFetch).toHaveBeenCalledTimes(2);
    // 消息列表：user + assistant + user + assistant = 4 条
    expect(result.current.messages).toHaveLength(4);
  });
});

// ─── P0-2: listQueryDatasources 竞态取消 ────────────────────────────────────

describe('P0-2 listQueryDatasources — signal 透传', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('传入 signal 后，fetch 应携带该 signal', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [{ luid: 'ds-1', name: '数据源1', connection_id: 1 }],
    });

    const controller = new AbortController();
    await listQueryDatasources(1, controller.signal);

    const fetchCall = mockFetch.mock.calls[0] as [string, RequestInit];
    const fetchInit = fetchCall[1];
    expect(fetchInit.signal).toBe(controller.signal);
  });

  it('abort 后，fetch 抛出 AbortError，函数应向上抛出', async () => {
    const abortError = new DOMException('Aborted', 'AbortError');
    mockFetch.mockRejectedValueOnce(abortError);

    const controller = new AbortController();
    controller.abort();

    await expect(listQueryDatasources(1, controller.signal)).rejects.toThrow('Aborted');
  });

  it('快速切换：第一个请求被 abort 后结果丢弃，第二个正常返回', async () => {
    let resolveFirst!: () => void;

    const ds1 = [{ luid: 'ds-1', name: '数据源1', connection_id: 1 }];
    const ds2 = [{ luid: 'ds-2', name: '数据源2', connection_id: 2 }];

    mockFetch
      .mockImplementationOnce((_url: string, init: RequestInit) => {
        return new Promise((resolve, reject) => {
          resolveFirst = () => resolve({ ok: true, json: async () => ds1 });
          init.signal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'));
          });
        });
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ds2,
      });

    const controller1 = new AbortController();
    const controller2 = new AbortController();

    const p1 = listQueryDatasources(1, controller1.signal).catch((e: DOMException) => {
      expect(e.name).toBe('AbortError');
      return null;
    });

    const p2 = listQueryDatasources(2, controller2.signal);

    // abort 第一个（模拟 useEffect cleanup）
    controller1.abort();
    resolveFirst();

    const [result1, result2] = await Promise.all([p1, p2]);

    expect(result1).toBeNull(); // abort 后结果丢弃
    expect(result2).toEqual(ds2); // 第二个正常返回
  });
});

// ─── P2-1: 超时错误展示为友好消息 ───────────────────────────────────────────

describe('P2-1 useQuerySession — 超时错误展示', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetch 抛出 TimeoutError 时，messages 中展示"请求超时"提示', async () => {
    const timeoutError = new DOMException('signal timed out', 'TimeoutError');
    mockFetch.mockRejectedValueOnce(timeoutError);

    const { result } = renderHook(() => useQuerySession());

    await act(async () => {
      await result.current.sendMessage({
        message: '超时测试',
        connection_id: 1,
        datasource_luid: 'ds-luid',
      });
    });

    const errorMsg = result.current.messages.find((m) => m.isError);
    expect(errorMsg?.content).toBe('请求超时，请稍后重试');
  });

  it('fetch 抛出 AbortError 时，messages 中展示"请求超时"提示', async () => {
    const abortError = new DOMException('The operation was aborted', 'AbortError');
    mockFetch.mockRejectedValueOnce(abortError);

    const { result } = renderHook(() => useQuerySession());

    await act(async () => {
      await result.current.sendMessage({
        message: '中止测试',
        connection_id: 1,
        datasource_luid: 'ds-luid',
      });
    });

    const errorMsg = result.current.messages.find((m) => m.isError);
    expect(errorMsg?.content).toBe('请求超时，请稍后重试');
  });
});
