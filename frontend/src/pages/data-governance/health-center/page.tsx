import { lazy, Suspense } from 'react';
import { useSearchParams } from 'react-router-dom';

const DataHealthPage = lazy(() => import('../health/page'));
const TableauHealthPage = lazy(() => import('../../tableau/health/page'));
const DataQualityPage = lazy(() => import('../quality/page'));

type Tab = 'warehouse' | 'tableau' | 'quality' | 'compliance';

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'warehouse', label: '数仓体检', icon: 'ri-heart-pulse-line' },
  { key: 'tableau', label: 'Tableau 健康', icon: 'ri-pulse-line' },
  { key: 'quality', label: '质量监控', icon: 'ri-shield-check-line' },
  { key: 'compliance', label: '数仓合规', icon: 'ri-checkbox-circle-line' },
];

export default function HealthCenterPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get('tab') as Tab) || 'warehouse';

  function handleTabChange(tab: Tab) {
    setSearchParams({ tab }, { replace: true });
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-1">
            <i className="ri-heart-pulse-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">健康中心</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7 mb-4">
            数仓体检 · Tableau 资产健康 · 数据质量监控 · 数仓合规
          </p>
          <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1 w-fit">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => handleTabChange(t.key)}
                className={`flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  activeTab === t.key
                    ? 'bg-white text-slate-800 shadow-sm'
                    : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                <i className={t.icon} />
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <Suspense
        fallback={
          <div className="text-center py-20 text-slate-400 text-sm">
            加载中...
          </div>
        }
      >
        {activeTab === 'warehouse' && <DataHealthPage />}
        {activeTab === 'tableau' && <TableauHealthPage />}
        {activeTab === 'quality' && <DataQualityPage />}
        {activeTab === 'compliance' && <DataHealthPage />}
      </Suspense>
    </div>
  );
}
