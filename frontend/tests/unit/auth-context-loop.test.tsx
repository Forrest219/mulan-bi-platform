/**
 * @vitest-environment jsdom
 *
 * Eval: 陷阱 1 — AuthContext useCallback 无限重渲染
 *
 * 验证目标：AuthProvider 挂载后，/api/auth/me 的调用次数 ≤ 2。
 * 背景：若 checkAuth 的 useCallback deps 包含不稳定引用（如频繁变化的 state），
 * useEffect([checkAuth]) 会在每次渲染时重新触发，导致 /me 无限循环调用。
 *
 * 修复后的代码使用 tokenExpiresAtRef（useRef 而非 useState）来避免循环。
 * 本测试确保修复保持有效。
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, act, waitFor } from "@testing-library/react";
import React from "react";
import { AuthProvider } from "@/context/AuthContext";

// 拦截全局 fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

const mockUser = {
  id: 1,
  username: "admin",
  display_name: "管理员",
  email: "admin@mulan.local",
  role: "admin",
  permissions: [],
  is_active: true,
  created_at: "2026-04-01T00:00:00",
  last_login: null,
};

/** 等待所有挂起的 Promise/微任务稳定 */
const flushPromises = () => new Promise<void>((resolve) => setTimeout(resolve, 50));

describe("陷阱 1 — AuthContext useCallback 无限重渲染检测", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it(
    "AuthProvider 挂载后 /api/auth/me 调用次数 ≤ 2（无循环渲染）",
    async () => {
      // /me 返回已登录用户
      mockFetch.mockImplementation(async (url: string) => {
        if (url.includes("/api/auth/me")) {
          return {
            ok: true,
            status: 200,
            json: async () => mockUser,
          };
        }
        return { ok: false, status: 404, json: async () => ({}) };
      });

      await act(async () => {
        render(
          <AuthProvider>
            <div data-testid="child">loaded</div>
          </AuthProvider>
        );
      });

      // 等待所有异步副作用完成（包括 useEffect + fetch）
      await act(async () => {
        await flushPromises();
      });

      const meCalls = mockFetch.mock.calls.filter((call) =>
        String(call[0]).includes("/api/auth/me")
      );

      // 核心断言：最多 2 次（正常初始化 1 次，token refresh 后最多再 1 次）
      // 若发生无限循环，此处会远超 2
      expect(meCalls.length).toBeGreaterThanOrEqual(1); // 至少初始化 1 次
      expect(meCalls.length).toBeLessThanOrEqual(2);    // 不超过 2 次
    },
    10000 // 给足超时时间
  );

  it(
    "401 → refresh → /me 再调用，总调用次数 ≤ 3",
    async () => {
      let meCallCount = 0;

      mockFetch.mockImplementation(async (url: string) => {
        if (url.includes("/api/auth/me")) {
          meCallCount++;
          // 第一次返回 401，触发 refresh 流程
          if (meCallCount === 1) {
            return { ok: false, status: 401, json: async () => ({}) };
          }
          // 第二次（refresh 成功后重试）返回用户
          return {
            ok: true,
            status: 200,
            json: async () => mockUser,
          };
        }
        if (url.includes("/api/auth/refresh")) {
          return { ok: true, status: 200, json: async () => ({}) };
        }
        return { ok: false, status: 404, json: async () => ({}) };
      });

      await act(async () => {
        render(
          <AuthProvider>
            <div>child</div>
          </AuthProvider>
        );
      });

      await act(async () => {
        await flushPromises();
      });

      // 额外稳定等待：确保无后续触发
      await act(async () => {
        await flushPromises();
      });

      // 401 → refresh → 重新 checkAuth，共 2 次 /me，仍 ≤ 3
      expect(meCallCount).toBeGreaterThanOrEqual(1);
      expect(meCallCount).toBeLessThanOrEqual(3);
    },
    10000
  );
});
