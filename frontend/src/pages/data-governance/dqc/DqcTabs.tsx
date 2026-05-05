import { useLocation, useNavigate } from 'react-router-dom';

const TABS = [
  { key: '/governance/dqc', label: '概览' },
  { key: '/governance/dqc/monitor', label: '监控资产' },
  { key: '/governance/dqc/signals', label: '信号灯' },
  { key: '/governance/dqc/templates', label: '规则模板' },
] as const;

export default function DqcTabs() {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  return (
    <div className="flex gap-1 mt-4">
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
  );
}
