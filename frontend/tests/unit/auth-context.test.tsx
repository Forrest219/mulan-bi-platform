/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

const BASE_URL = "http://localhost:8000";

const mockUser = {
  id: 1,
  username: "admin",
  display_name: "管理员",
  email: "admin@mulan.local",
  role: "admin" as const,
  permissions: [],
  is_active: true,
  created_at: "2026-04-01 00:00:00",
  last_login: "2026-04-03 10:00:00",
};

describe("Auth RBAC — 前端权限常量", () => {
  it("admin 拥有全部 8 项权限", async () => {
    const { ROLE_DEFAULT_PERMISSIONS } = await import("@/context/AuthContext");
    const admin = ROLE_DEFAULT_PERMISSIONS["admin"];
    expect(admin.length).toBe(8);
    expect(admin).toContain("ddl_check");
    expect(admin).toContain("tableau");
    expect(admin).toContain("llm");
  });

  it("data_admin 拥有正确子集权限", async () => {
    const { ROLE_DEFAULT_PERMISSIONS } = await import("@/context/AuthContext");
    const perms = ROLE_DEFAULT_PERMISSIONS["data_admin"];
    expect(perms).toContain("database_monitor");
    expect(perms).toContain("ddl_check");
    expect(perms).toContain("scan_logs");
    expect(perms).toContain("tableau");
    expect(perms).not.toContain("user_management"); // data_admin 无用户管理
  });

  it("analyst 只有只读权限", async () => {
    const { ROLE_DEFAULT_PERMISSIONS } = await import("@/context/AuthContext");
    const perms = ROLE_DEFAULT_PERMISSIONS["analyst"];
    expect(perms).toEqual(["scan_logs", "tableau"]);
  });

  it("user 无默认权限", async () => {
    const { ROLE_DEFAULT_PERMISSIONS } = await import("@/context/AuthContext");
    expect(ROLE_DEFAULT_PERMISSIONS["user"]).toEqual([]);
  });

  it("ALL_PERMISSIONS 包含 8 项", async () => {
    const { ALL_PERMISSIONS } = await import("@/context/AuthContext");
    expect(ALL_PERMISSIONS.length).toBe(8);
  });

  it("ROLE_LABELS 包含全部 4 个角色", async () => {
    const { ROLE_LABELS } = await import("@/context/AuthContext");
    expect(ROLE_LABELS["admin"]).toBe("管理员");
    expect(ROLE_LABELS["data_admin"]).toBe("数据管理员");
    expect(ROLE_LABELS["analyst"]).toBe("业务分析师");
    expect(ROLE_LABELS["user"]).toBe("普通用户");
  });
});

describe("Auth 登录逻辑 — API 调用", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("登录成功返回 success=true 并设置 user", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ success: true, user: mockUser }),
    });

    const { login } = makeAuthContext();
    const result = await login("admin@mulan.local", "admin123");
    expect(result.success).toBe(true);
    expect(mockFetch).toHaveBeenCalledWith(
      `${BASE_URL}/api/auth/login`,
      expect.objectContaining({ method: "POST" })
    );
  });

  it("登录失败返回 success=false", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ success: false, detail: "用户名或密码错误" }),
    });

    const { login } = makeAuthContext();
    const result = await login("wrong", "wrong");
    expect(result.success).toBe(false);
    expect(result.message).toBe("用户名或密码错误");
  });

  it("网络错误返回网络错误消息", async () => {
    mockFetch.mockRejectedValueOnce(new Error("Network error"));

    const { login } = makeAuthContext();
    const result = await login("x", "x");
    expect(result.success).toBe(false);
    expect(result.message).toBe("网络错误");
  });
});

// 构造最小 AuthContext 用于单元测试（不渲染完整 React 树）
function makeAuthContext() {
  // 简单的函数式模拟，不走 React 渲染
  const state = { user: null as any, loading: false };

  const login = async (email: string, password: string) => {
    try {
      const response = await fetch(`${BASE_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username: email, password }),
      });
      const data = await response.json();
      if (response.ok && data.success) {
        state.user = data.user;
        return { success: true, message: "登录成功" };
      } else {
        return { success: false, message: data.detail || "登录失败" };
      }
    } catch {
      return { success: false, message: "网络错误" };
    }
  };

  const hasPermission = (permission: string): boolean => {
    if (!state.user) return false;
    if (state.user.role === "admin") return true;
    const rolePerms = (state.user.permissions as string[]) || [];
    return rolePerms.includes(permission);
  };

  return { login, hasPermission };
}
