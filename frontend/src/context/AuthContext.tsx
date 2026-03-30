import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

const API_BASE = 'http://localhost:8000';

export const ALL_PERMISSIONS = [
  { key: 'ddl_check', label: 'DDL 规范检查' },
  { key: 'ddl_generator', label: 'DDL 生成器' },
  { key: 'database_monitor', label: '数据库监控' },
  { key: 'rule_config', label: '规则配置' },
  { key: 'scan_logs', label: '扫描日志' },
  { key: 'user_management', label: '用户管理' },
  { key: 'tableau', label: 'Tableau 资产' },
];

export const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  data_admin: '数据管理员',
  analyst: '业务分析师',
  user: '普通用户',
};

export const ROLE_DEFAULT_PERMISSIONS: Record<string, string[]> = {
  admin: ALL_PERMISSIONS.map(p => p.key),
  data_admin: ['database_monitor', 'ddl_check', 'rule_config', 'scan_logs', 'tableau'],
  analyst: ['scan_logs', 'tableau'],
  user: [],
};

type UserRole = 'admin' | 'data_admin' | 'analyst' | 'user';

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
  checkAuth: () => Promise<void>;
  isAdmin: boolean;
  isDataAdmin: boolean;
  isAnalyst: boolean;
  hasPermission: (permission: string) => boolean;
  updateUser: (user: User) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/me`, {
        credentials: 'include',
      });
      if (response.ok) {
        const userData = await response.json();
        setUser(userData);
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
        checkAuth,
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
