import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { LOGO_URL } from '../../config';

const navItems = [
  { label: '数据治理', path: '/data-governance/health' },
  { label: '规则配置', path: '/rule-config' },
  { label: 'Tableau', path: '/tableau/assets' },
  { label: '语义维护', path: '/semantic-maintenance/datasources' },
  { label: 'DDL 预览', path: '/ddl-validator' },
];

export default function Navbar() {
  const location = useLocation();
  const { user, logout, isAdmin } = useAuth();

  const handleLogout = async () => {
    await logout();
  };

  const isAdminPath = location.pathname.startsWith('/admin');

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
      <div className="px-6 flex items-center h-14">
        <Link to="/" className="flex items-center gap-2.5 mr-10 shrink-0">
          <img
            src={LOGO_URL}
            alt="Mulan Platform Logo"
            className="w-7 h-7 object-contain"
          />
          <span className="text-[15px] font-semibold text-slate-800 tracking-wide">
            Mulan <span className="text-slate-400 font-normal">Platform</span>
          </span>
        </Link>

        <nav className="flex items-center gap-1">
          {navItems.map((item) => {
            const active =
              item.path === '/'
                ? location.pathname === '/'
                : location.pathname.startsWith(item.path);
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`px-3.5 py-1.5 rounded-md text-[13px] font-medium transition-colors whitespace-nowrap cursor-pointer ${
                  active
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                }`}
              >
                {item.label}
              </Link>
            );
          })}
          {isAdmin && (
            <Link
              to="/admin/users"
              className={`px-3.5 py-1.5 rounded-md text-[13px] font-medium transition-colors whitespace-nowrap cursor-pointer ${
                isAdminPath
                  ? 'bg-blue-900 text-white'
                  : 'text-blue-600 hover:text-blue-900 hover:bg-blue-50'
              }`}
            >
              <i className="ri-settings-2-line mr-1" />
              后台管理
            </Link>
          )}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
            v0.3.1-beta
          </span>
          {user ? (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-100 rounded-lg">
                <i className="ri-user-3-line text-slate-600 text-sm" />
                <span className="text-[13px] font-medium text-slate-700">
                  {user.username}
                </span>
                {user.role === 'admin' && (
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">
                    管理员
                  </span>
                )}
                {user.role === 'data_admin' && (
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">
                    数据管理员
                  </span>
                )}
                {user.role === 'analyst' && (
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">
                    分析师
                  </span>
                )}
              </div>
              <button
                onClick={handleLogout}
                className="w-7 h-7 flex items-center justify-center bg-slate-100 rounded-full cursor-pointer hover:bg-red-50 hover:text-red-600 transition-colors"
                title="退出登录"
              >
                <i className="ri-logout-box-line text-slate-600 text-sm" />
              </button>
            </div>
          ) : (
            <Link
              to="/login"
              className="w-7 h-7 flex items-center justify-center bg-slate-100 rounded-full cursor-pointer hover:bg-slate-200 transition-colors"
            >
              <i className="ri-user-3-line text-slate-600 text-sm" />
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
