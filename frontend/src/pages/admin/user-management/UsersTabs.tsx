import { useLocation, useNavigate } from 'react-router-dom';

const TABS = [
  { key: '/system/users', label: '用户列表' },
  { key: '/system/users/groups', label: '用户组' },
] as const;

export default function UsersTabs() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  return (
    <div className="bg-white border-b border-slate-100 px-8">
      <div className="max-w-6xl mx-auto flex gap-1 py-2">
        {TABS.map(({ key, label }) => {
          const active = pathname === key || (key !== '/system/users' && pathname.startsWith(key + '/'));
          return (
            <button
              key={key}
              onClick={() => navigate(key)}
              className={`px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${active ? 'bg-slate-800 text-white' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'}`}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
