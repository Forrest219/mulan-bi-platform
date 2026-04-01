import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const adminMenuItems = [
  {
    path: '/admin/users',
    label: '用户与权限',
    icon: 'ri-user-settings-line',
    desc: '用户账号和权限',
  },
  {
    path: '/admin/datasources',
    label: '数据源管理',
    icon: 'ri-database-2-line',
    desc: '数据库连接配置',
  },
  {
    path: '/admin/tableau/connections',
    label: 'Tableau 连接',
    icon: 'ri-bar-chart-box-line',
    desc: 'Tableau Server 配置',
  },
  {
    path: '/admin/llm',
    label: '系统配置',
    icon: 'ri-robot-line',
    desc: 'AI 能力配置',
  },
  {
    path: '/admin/activity',
    label: '访问日志',
    icon: 'ri-history-line',
    desc: '操作日志查看',
  },
  {
    path: '/admin/tasks',
    label: '任务管理',
    icon: 'ri-task-line',
    desc: '定时任务配置',
  },
];

export default function AdminSidebarLayout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { user } = useAuth();

  return (
    <div className="flex min-h-screen bg-slate-50">
      {/* 侧边栏 */}
      <aside className="w-56 bg-white border-r border-slate-200 text-slate-700 flex flex-col">

        {/* 标题 */}
        <div className="px-5 pt-5 pb-2">
          <h2 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
            后台管理
          </h2>
        </div>

        {/* 菜单 */}
        <nav className="flex-1 px-3">
          {adminMenuItems.map((item) => {
            const isActive = location.pathname === item.path || location.pathname.startsWith(item.path + '/');
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg mb-0.5 transition-colors ${
                  isActive
                    ? 'bg-blue-50 text-blue-600'
                    : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
                }`}
              >
                <i className={`${item.icon} text-base`} />
                <div>
                  <div className="text-[13px] font-medium">{item.label}</div>
                  <div className={`text-[10px] ${isActive ? 'text-blue-400' : 'text-slate-400'}`}>
                    {item.desc}
                  </div>
                </div>
              </Link>
            );
          })}
        </nav>

        {/* 返回首页 */}
        <div className="px-3 py-3 border-t border-slate-100">
          <Link
            to="/"
            className="flex items-center gap-2.5 px-3 py-2 text-slate-400 hover:text-slate-600 hover:bg-slate-50 rounded-lg transition-colors"
          >
            <i className="ri-arrow-left-line text-base" />
            <span className="text-[12px]">返回首页</span>
          </Link>
        </div>

        {/* 用户信息 */}
        <div className="px-3 py-3 border-t border-slate-100">
          <div className="flex items-center gap-2.5 px-3 py-2 bg-slate-50 rounded-lg">
            <div className="w-7 h-7 flex items-center justify-center bg-blue-100 text-blue-600 rounded-full shrink-0">
              <span className="text-xs font-semibold">
                {user?.display_name?.charAt(0) || 'A'}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[12px] font-medium text-slate-700 truncate">{user?.display_name}</div>
              <div className="text-[10px] text-slate-400">{user?.username}</div>
            </div>
          </div>
        </div>
      </aside>

      {/* 主内容区 */}
      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </div>
  );
}
