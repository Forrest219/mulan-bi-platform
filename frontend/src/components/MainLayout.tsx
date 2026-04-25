import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { usePlatformSettings } from '../context/PlatformSettingsContext';

interface MenuItem {
  path: string;
  label: string;
  icon: string;
}

interface MenuSection {
  section: string;
  items: MenuItem[];
}

const mainMenuSections: MenuSection[] = [
  {
    section: '数据治理',
    items: [
      { path: '/data-governance/health', label: '数据仓库体检', icon: 'ri-heart-pulse-line' },
      { path: '/data-governance/quality', label: '数据质量监控', icon: 'ri-shield-check-line' },
      { path: '/rule-config', label: '规则配置', icon: 'ri-file-settings-line' },
    ],
  },
  {
    section: 'BI语义',
    items: [
      { path: '/tableau/assets', label: '资产浏览', icon: 'ri-bar-chart-box-line' },
      { path: '/semantic-maintenance/datasources', label: '语义维护', icon: 'ri-ai-generate' },
      { path: '/semantic-maintenance/publish-logs', label: '发布记录', icon: 'ri-file-history-line' },
    ],
  },
  {
    section: '知识库',
    items: [
      { path: '/knowledge/metrics', label: '指标字典', icon: 'ri-book-2-line' },
      { path: '/knowledge/handbook', label: '品控手册', icon: 'ri-book-open-line' },
      { path: '/knowledge/systems', label: '业务系统信息', icon: 'ri-computer-line' },
    ],
  },
];

export default function MainLayout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { user, isAdmin, hasPermission } = useAuth();
  const { settings } = usePlatformSettings();

  const isHome = location.pathname === '/';

  // Check if a path is active (exact match or starts with)
  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  // Filter sections by permission
  const visibleSections = mainMenuSections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => {
        // 知识库占位页所有人都可看
        if (item.path.startsWith('/knowledge')) return true;
        // 数据治理需要对应权限
        if (item.path.startsWith('/data-governance') || item.path.startsWith('/rule-config')) {
          return hasPermission('database_monitor') || hasPermission('rule_config') || isAdmin;
        }
        // BI语义需要 tableau 权限
        if (item.path.startsWith('/tableau') || item.path.startsWith('/semantic-maintenance')) {
          return hasPermission('tableau') || isAdmin;
        }
        return true;
      }),
    }))
    .filter((section) => section.items.length > 0);

  return (
    <div className="flex min-h-screen bg-slate-50">
      {/* 侧边栏 - 首页不显示 */}
      {!isHome && (
        <aside className="w-56 bg-white border-r border-slate-200 text-slate-700 flex flex-col shrink-0">

          {/* 标题 */}
          <div className="px-5 pt-5 pb-2">
            <Link to="/" className="block">
              <h1 className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                {settings.platform_name}
              </h1>
            </Link>
          </div>

          {/* 菜单 */}
          <nav className="flex-1 px-3 overflow-y-auto">
            {visibleSections.map((section) => (
              <div key={section.section} className="mb-4">
                <div className="px-3 mb-1">
                  <span className="text-[10px] text-gray-400 font-semibold uppercase tracking-wide">
                    {section.section}
                  </span>
                </div>
                {section.items.map((item) => {
                  const active = isActive(item.path);
                  return (
                    <Link
                      key={item.path}
                      to={item.path}
                      className={`flex items-center gap-2.5 px-3 py-2 rounded-lg mb-0.5 transition-colors ${
                        active
                          ? 'bg-blue-50 text-blue-700 font-medium'
                          : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
                      }`}
                    >
                      <i className={`${item.icon} text-base`} />
                      <span className="text-[13px] font-medium">{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            ))}

            {/* 后台管理单独区隔 */}
            {isAdmin && (
              <div className="mb-4">
                <div className="px-3 mb-1">
                  <span className="text-[10px] text-gray-400 font-semibold uppercase tracking-wide">
                    后台管理
                  </span>
                </div>
                <Link
                  to="/admin/users"
                  className={`flex items-center gap-2.5 px-3 py-2 rounded-lg mb-0.5 transition-colors ${
                    location.pathname.startsWith('/admin')
                      ? 'bg-blue-50 text-blue-600'
                      : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
                  }`}
                >
                  <i className="ri-settings-2-line text-base" />
                  <span className="text-[13px] font-medium">后台管理</span>
                </Link>
              </div>
            )}
          </nav>

          {/* 用户信息 */}
          <div className="px-3 py-3 border-t border-gray-200 bg-slate-50">
            <div className="flex items-center gap-2.5 px-3 py-2">
              <div className="w-7 h-7 flex items-center justify-center bg-blue-100 text-blue-600 rounded-full shrink-0">
                <span className="text-xs font-semibold">
                  {user?.display_name?.charAt(0) || 'A'}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[12px] font-semibold text-gray-700 truncate">
                  {user?.display_name}
                </div>
                <div className="text-[10px] text-gray-500">{user?.username}</div>
              </div>
            </div>
          </div>
        </aside>
      )}

      {/* 主内容区 */}
      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </div>
  );
}
