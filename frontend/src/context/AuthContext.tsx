import { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from 'react';
import { API_BASE } from '../config';

export const ALL_PERMISSIONS = [
  { key: 'ddl_check', label: 'DDL 规范检查' },
  { key: 'ddl_generator', label: 'DDL 生成器' },
  { key: 'database_monitor', label: '数据库监控' },
  { key: 'rule_config', label: '规则配置' },
  { key: 'scan_logs', label: '扫描日志' },
  { key: 'user_management', label: '用户管理' },
  { key: 'tableau', label: 'Tableau 资产' },
  { key: 'llm', label: 'LLM 管理' },
];

export const ROLE_DEFAULT_PERMISSIONS: Record<string, string[]> = {
  admin: ALL_PERMISSIONS.map(p => p.key),
  data_admin: ['database_monitor', 'ddl_check', 'rule_config', 'scan_logs', 'tableau', 'llm'],
  analyst: ['scan_logs', 'tableau'],
  user: [],
};

export const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  data_admin: '数据管理员',
  analyst: '业务分析师',
  user: '普通用户',
};

export type UserRole = 'admin' | 'data_admin' | 'analyst' | 'user';

interface User {
  id: number;
  username: string;
  display_name: string;
  email: string | null;
  role: UserRole;
  permissions: string[];
  all_permissions?: string[];  // 后端合并后的生效权限（角色默认+个人+组继承）
  group_ids?: number[];       // 所属用户组 ID 列表
  group_names?: string[];     // 所属用户组名称列表
  is_active: boolean;
  created_at: string;
  last_login: string | null;
  position?: string | null;
  department?: string | null;
  phone?: string | null;
  avatar_url?: string | null;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<{ success: boolean; message: string; mfa_required?: boolean }>;
  logout: () => Promise<void>;
  logoutAll: () => Promise<void>;  // 退出所有设备
  checkAuth: () => Promise<void>;
  refreshToken: () => Promise<boolean>;  // 主动刷新 Token
  isAdmin: boolean;
  isDataAdmin: boolean;
  isAnalyst: boolean;
  hasPermission: (permission: string) => boolean;
  updateUser: (user: User) => void;
}

type LoginResponse =
  | { success: true; mfa_required: true; message: string; user?: null }
  | { success: true; mfa_required?: false; message: string; user: User }
  | { success: false; message?: string; detail?: string };

// Access Token 剩余多少秒时触发 proactive refresh
const ACCESS_TOKEN_REFRESH_THRESHOLD_SECONDS = 5 * 60; // 5 分钟

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  // Access Token 过期时间戳（毫秒），用于 proactive refresh
  // 用 ref 而非 state：不需要触发重渲染，避免 checkAuth 的 useCallback dep 循环
  const tokenExpiresAtRef = useRef<number | null>(null);
  // 防止并发 refresh 的 in-flight 锁；refreshPromiseRef 用于让所有并发调用方等待同一个 refresh
  const isRefreshingRef = useRef(false);
  const refreshPromiseRef = useRef<Promise<boolean> | null>(null);

  const refreshToken = useCallback(async (): Promise<boolean> => {
    // 已有 refresh 在飞行 → 返回同一个 promise，所有调用方等待同一次完成
    if (refreshPromiseRef.current) {
      return refreshPromiseRef.current;
    }
    isRefreshingRef.current = true;
    const p = (async () => {
      try {
        const response = await fetch(`${API_BASE}/api/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
        });
        return response.ok;
      } catch {
        return false;
      } finally {
        isRefreshingRef.current = false;
        refreshPromiseRef.current = null;
      }
    })();
    refreshPromiseRef.current = p;
    return p;
  }, []);

  // 检查是否需要 proactive token refresh
  const scheduleProactiveRefresh = useCallback((expiresAt: number) => {
    const now = Date.now();
    const msUntilRefresh = expiresAt - now - ACCESS_TOKEN_REFRESH_THRESHOLD_SECONDS * 1000;
    if (msUntilRefresh > 0) {
      setTimeout(async () => {
        await refreshToken();
      }, msUntilRefresh);
    }
  }, [refreshToken]);

  const checkAuth = useCallback(async (retrying = false) => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/me`, {
        credentials: 'include',
      });
      if (response.ok) {
        const userData = await response.json();
        setUser(userData);
        if (tokenExpiresAtRef.current) {
          scheduleProactiveRefresh(tokenExpiresAtRef.current);
        }
      } else if (response.status === 401) {
        // 401 且尚未重试过 → refresh 一次后复查 /me
        if (!retrying) {
          const ok = await refreshToken();
          if (ok) {
            await checkAuth(true);
          } else {
            setUser(null);
          }
        } else {
          // refresh 后 /me 仍失败，清空 user 不再递归
          setUser(null);
        }
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [refreshToken, scheduleProactiveRefresh]);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = async (email: string, password: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ username: email, password }),
      });

      const data = await response.json() as LoginResponse;

      if (response.ok && data.success) {
        if (data.mfa_required === true) {
          // MFA enabled — 返回 MFA challenge，不设置用户上下文（验证未完成）
          return { success: true, message: data.message || '请输入 MFA 验证码', mfa_required: true };
        }
        if (!data.user) {
          return { success: false, message: '登录响应缺少用户信息' };
        }
        // 正常登录完成
        setUser(data.user);
        // 计算 Access Token 过期时间（当前时间 + JWT_EXPIRE_SECONDS）
        // JWT_EXPIRE_SECONDS = 7 天 = 604800 秒
        const expiresAt = Date.now() + 7 * 24 * 60 * 60 * 1000;
        tokenExpiresAtRef.current = expiresAt;
        scheduleProactiveRefresh(expiresAt);
        return { success: true, message: '登录成功' };
      } else {
        const detail = 'detail' in data ? data.detail : undefined;
        // detail 可能是 FastAPI 返回的对象（如验证错误数组），必须转为字符串，
        // 否则调用方 setError(result.message) 存入对象会导致 React 渲染崩溃
        const detailStr =
          typeof detail === 'string'
            ? detail
            : detail != null && Object.keys(detail).length > 0
              ? JSON.stringify(detail)
              : undefined;
        const messageStr =
          typeof data.message === 'string' ? data.message : undefined;
        return { success: false, message: detailStr || messageStr || '登录失败' };
      }
    } catch {
      return { success: false, message: '网络错误' };
    }
  };

  const logout = async () => {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      });
    } finally {
      setUser(null);
      tokenExpiresAtRef.current = null;
    }
  };

  // 退出所有设备：撤销所有 Refresh Token
  const logoutAll = async () => {
    try {
      await fetch(`${API_BASE}/api/auth/refresh/revoke-all`, {
        method: 'POST',
        credentials: 'include',
      });
    } finally {
      setUser(null);
      tokenExpiresAtRef.current = null;
    }
  };

  const hasPermission = (permission: string): boolean => {
    if (!user) return false;
    if (user.role === 'admin') return true;  // admin has all permissions
    // 优先使用后端合并后的 all_permissions（含组继承）；兜底本地计算
    const effective = user.all_permissions ?? [
      ...(ROLE_DEFAULT_PERMISSIONS[user.role] || []),
      ...(user.permissions || []),
    ];
    return effective.includes(permission);
  };

  const updateUser = (updatedUser: User) => {
    setUser(updatedUser);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        logout,
        logoutAll,
        checkAuth,
        refreshToken,
        isAdmin: user?.role === 'admin',
        isDataAdmin: user?.role === 'data_admin',
        isAnalyst: user?.role === 'analyst',
        hasPermission,
        updateUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
