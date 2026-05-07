import { useLocation, useNavigate } from 'react-router-dom';

const TABS = [
  { key: '/governance/dqc',              label: '健康看板' },
  { key: '/governance/dqc/monitor',      label: '监控资产' },
  { key: '/governance/dqc/check-records', label: '检查记录' },
  { key: '/governance/dqc/derived-rules', label: '检查规则' },
  { key: '/governance/dqc/templates',     label: '检查能力库' },
] as const;

export default function DqcTabs() {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  return (
    <div className="flex gap-1 py-2">
      {TABS.map(({ key, label }) => {
        const active =
          pathname === key ||
          (key !== '/governance/dqc' && pathname.startsWith(key + '/'));
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
