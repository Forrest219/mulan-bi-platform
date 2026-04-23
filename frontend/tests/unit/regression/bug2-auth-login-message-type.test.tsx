/**
 * 回归测试 Bug 2：
 * AuthContext.login() 把 FastAPI 返回的 detail（可能是对象）原样透传给 message，
 * 调用方 setError(result.message) 存入对象，JSX 直接渲染 {error} 崩溃。
 *
 * 检查规则：
 * 1. login() 无论 API 返回什么，返回值的 message 字段必须是字符串。
 * 2. login/page.tsx 里 setError 的参数必须是字符串（通过 typeof 防御）。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { ReactNode } from 'react';
import { AuthProvider, useAuth } from '../../../src/context/AuthContext';

// 包裹 AuthProvider
function wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

// 构造一个 mock fetch，返回指定的响应 body 和 status
function mockFetch(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

describe('Bug 2 回归：AuthContext.login() 返回的 message 始终是字符串', () => {
  const originalFetch = global.fetch;

  // 先 mock /api/auth/me（checkAuth 初始化调用）返回 401
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({}),
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('后端 detail 为对象时，login() 返回的 message 仍是字符串', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    // 等待初始化 checkAuth 完成
    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    // 模拟 FastAPI 422 返回 detail 为对象数组的情况
    global.fetch = mockFetch(
      {
        success: false,
        detail: [{ loc: ['body', 'username'], msg: 'field required', type: 'value_error.missing' }],
      },
      422
    );

    let loginResult: Awaited<ReturnType<typeof result.current.login>>;
    await act(async () => {
      loginResult = await result.current.login('bad@example.com', 'wrongpass');
    });

    expect(loginResult!.success).toBe(false);
    expect(typeof loginResult!.message).toBe('string');
    expect(loginResult!.message.length).toBeGreaterThan(0);
  });

  it('后端 detail 为字符串时，login() 返回的 message 是该字符串', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    global.fetch = mockFetch(
      { success: false, detail: '用户名或密码错误' },
      401
    );

    let loginResult: Awaited<ReturnType<typeof result.current.login>>;
    await act(async () => {
      loginResult = await result.current.login('user@example.com', 'wrongpass');
    });

    expect(loginResult!.success).toBe(false);
    expect(typeof loginResult!.message).toBe('string');
    expect(loginResult!.message).toBe('用户名或密码错误');
  });

  it('后端返回 success: false 且无 detail/message 时，login() 仍返回字符串 message', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    global.fetch = mockFetch({ success: false }, 500);

    let loginResult: Awaited<ReturnType<typeof result.current.login>>;
    await act(async () => {
      loginResult = await result.current.login('user@example.com', 'wrongpass');
    });

    expect(loginResult!.success).toBe(false);
    expect(typeof loginResult!.message).toBe('string');
    expect(loginResult!.message.length).toBeGreaterThan(0);
  });

  it('网络异常时，login() 返回的 message 是字符串', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    global.fetch = vi.fn().mockRejectedValue(new Error('Network Error'));

    let loginResult: Awaited<ReturnType<typeof result.current.login>>;
    await act(async () => {
      loginResult = await result.current.login('user@example.com', 'wrongpass');
    });

    expect(loginResult!.success).toBe(false);
    expect(typeof loginResult!.message).toBe('string');
  });
});

describe('Bug 2 回归：login/page.tsx 对 setError 有字符串防御', () => {
  it('page.tsx 中 setError 调用必须有 typeof 字符串守卫', async () => {
    // 通过读取源码文本验证防御性写法存在
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');

    const pagePath = resolve(__dirname, '../../../src/pages/login/page.tsx');
    const source = readFileSync(pagePath, 'utf-8');

    // page.tsx 里对 result.message 的处理必须有 typeof 检查，
    // 防止 setError 收到非字符串对象导致 React 崩溃
    const hasStringGuard =
      source.includes("typeof result.message === 'string'") ||
      source.includes('typeof result.message === "string"') ||
      source.includes('String(result.message)');

    expect(
      hasStringGuard,
      'login/page.tsx 中 setError 处缺少 typeof 字符串守卫，对象值会导致 React 崩溃'
    ).toBe(true);
  });
});
