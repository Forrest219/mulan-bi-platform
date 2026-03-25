import { Link, useLocation } from 'react-router-dom';

const navItems = [
  { label: '主页', path: '/' },
  { label: 'DDL Validator', path: '/ddl-validator' },
  { label: '数据库监控', path: '/database-monitor' },
  { label: '规则配置', path: '/rule-config' },
];

export default function Navbar() {
  const location = useLocation();

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
      <div className="px-6 flex items-center h-14">
        <Link to="/" className="flex items-center gap-2.5 mr-10 shrink-0">
          <img
            src="https://public.readdy.ai/ai/img_res/d9bf8fa2-dfff-4c50-98cf-7b635309e7d6.png"
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
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
            v0.3.1-beta
          </span>
          <div className="w-7 h-7 flex items-center justify-center bg-slate-100 rounded-full cursor-pointer hover:bg-slate-200 transition-colors">
            <i className="ri-user-3-line text-slate-600 text-sm" />
          </div>
        </div>
      </div>
    </header>
  );
}
