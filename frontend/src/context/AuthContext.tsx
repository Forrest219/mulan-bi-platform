import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
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
  is_active: boolean;
  created_at: string;
  last_login: string | null;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<{ success: boolean; message: string }>;
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

// Access Token 剩余多少秒时触发 proactive refresh
const ACCESS_TOKEN_REFRESH_THRESHOLD_SECONDS = 5 * 60; // 5 分钟

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  // Access Token 过期时间戳（毫秒），用于 proactive refresh
  const [tokenExpiresAt, setTokenExpiresAt] = useState<number | null>(null);

  // 从登录响应中解析 JWT payload 获取 exp
  const parseJwtExpiry = (token: string): number | null => {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.exp * 1000; // JWT exp 是秒，转毫秒
    } catch {
      return null;
    }
  };

  const refreshToken = async (): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      });
      if (response.ok) {
        // 从 Set-Cookie 中获取新的 expiry（无法直接读 HTTP-only cookie）
        // 下次 /me 调用成功时会更新 tokenExpiresAt
        return true;
      }
      // Refresh 失败，说明需要重新登录
      setUser(null);
      return false;
    } catch {
      return false;
    }
  };

  // 检查是否需要 proactive token refresh
  const scheduleProactiveRefresh = (expiresAt: number) => {
    const now = Date.now();
    const msUntilRefresh = expiresAt - now - ACCESS_TOKEN_REFRESH_THRESHOLD_SECONDS * 1000;
    if (msUntilRefresh > 0) {
      setTimeout(async () => {
        await refreshToken();
      }, msUntilRefresh);
    }
  };

  const checkAuth = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/me`, {
        credentials: 'include',
      });
      if (response.ok) {
        const userData = await response.json();
        setUser(userData);
        // 从 session cookie 中尝试读取 expiry（cookie 是 HTTP-only，
        // 但 login 响应中我们已知 expiresAt，将其存内存）
        // 如果没有存过，使用默认值不触发 refresh
        if (tokenExpiresAt) {
          scheduleProactiveRefresh(tokenExpiresAt);
        }
      } else if (response.status === 401) {
        // 尝试用 refresh token 续期
        const refreshed = await refreshToken();
        if (refreshed) {
          // 刷新成功，重新获取用户信息
          await checkAuth();
        } else {
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
  };

  useEffect(() => {
    checkAuth();
  }, []);

  const login = async (email: string, password: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ username: email, password }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        setUser(data.user);
        // 计算 Access Token 过期时间（当前时间 + JWT_EXPIRE_SECONDS）
        // JWT_EXPIRE_SECONDS = 7 天 = 604800 秒
        const expiresAt = Date.now() + 7 * 24 * 60 * 60 * 1000;
        setTokenExpiresAt(expiresAt);
        scheduleProactiveRefresh(expiresAt);
        return { success: true, message: '登录成功' };
      } else {
        return { success: false, message: data.detail || '登录失败' };
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
      setTokenExpiresAt(null);
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
      setTokenExpiresAt(null);
    }
  };

  const hasPermission = (permission: string): boolean => {
    if (!user) return false;
    if (user.role === 'admin') return true;  // admin has all permissions
    // 合并角色默认权限和个人权限
    const rolePerms = ROLE_DEFAULT_PERMISSIONS[user.role] || [];
    const personalPerms = user.permissions || [];
    return [...rolePerms, ...personalPerms].includes(permission);
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
