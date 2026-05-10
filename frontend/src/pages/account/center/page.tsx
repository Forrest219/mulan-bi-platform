import { Outlet, useLocation, useNavigate } from 'react-router-dom';

const TABS = [
  { key: '/account/profile', label: '个人资料' },
  { key: '/account/password', label: '修改密码' },
  { key: '/account/security', label: '两步验证' },
] as const;

export default function AccountCenterPage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 页面大标题 */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-user-3-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">账号设置</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">管理您的个人资料与账户安全</p>
        </div>
      </div>

      {/* Tab 控制栏 */}
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-6xl mx-auto">
          <div className="flex gap-1 py-2">
            {TABS.map(({ key, label }) => {
              const active = pathname === key;
              return (
                <button
                  key={key}
                  onClick={() => navigate(key)}
                  className={`px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${
                    active
                      ? 'bg-slate-800 text-white'
                      : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* 内容区 */}
      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto">
          <Outlet />
        </div>
      </div>
    </div>
  );
}