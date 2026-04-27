/**
 * 统一顶部栏（Spec 18 §5.1）
 *
 * 替代原有 Navbar.tsx：
 * - Logo + 平台名称
 * - 全局搜索（占位）
 * - 用户信息 + 登出
 */
import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { getAvatarGradient } from '../../config';

export default function AppHeader() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const avatarGradient = getAvatarGradient(user?.display_name ?? 'A');

  return (
    <header className="h-[58px] bg-white border-b border-slate-200 flex items-center pl-4 pr-4 gap-4 shrink-0 z-30">

      {/* 全局搜索（占位，后续迭代） */}
      <div className="flex-1 max-w-md mx-auto">
        <div className="relative">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
          <input
            type="text"
            placeholder="搜索..."
            className="w-full pl-9 pr-4 py-1.5 text-[13px] bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent text-slate-600 placeholder-slate-400"
          />
        </div>
      </div>

      {/* 用户信息 */}
      <div className="relative">
        <button
          onClick={() => setMenuOpen((o) => !o)}
          className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-slate-50 transition-colors"
        >
          <div className={`w-7 h-7 rounded-full bg-gradient-to-br ${avatarGradient} flex items-center justify-center shrink-0`}>
            <span className="text-white text-xs font-bold">
              {user?.display_name?.charAt(0) ?? 'A'}
            </span>
          </div>
          <div className="hidden sm:block text-left">
            <div className="text-[12px] font-semibold text-slate-700 leading-tight">
              {user?.display_name ?? '用户'}
            </div>
            <div className="text-[10px] text-slate-400 leading-tight">
              {user?.role === 'admin' ? '管理员'
                : user?.role === 'data_admin' ? '数据管理员'
                : user?.role === 'analyst' ? '业务分析师'
                : '普通用户'}
            </div>
          </div>
          <i className="ri-arrow-down-s-line text-slate-400 text-sm" />
        </button>

        {/* 下拉菜单 */}
        {menuOpen && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
            <div className="absolute right-0 top-full mt-1 w-44 bg-white border border-slate-200 rounded-xl shadow-lg z-50 py-1">
              <Link
                to="/account/security"
                onClick={() => setMenuOpen(false)}
                className="w-full flex items-center gap-2 px-4 py-2.5 text-[13px] text-slate-600 hover:bg-slate-50 transition-colors"
              >
                <i className="ri-shield-keyhole-line text-base" />
                账户安全
              </Link>
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-2 px-4 py-2.5 text-[13px] text-slate-600 hover:bg-slate-50 hover:text-red-600 transition-colors"
              >
                <i className="ri-logout-box-line text-base" />
                退出登录
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  );
}
