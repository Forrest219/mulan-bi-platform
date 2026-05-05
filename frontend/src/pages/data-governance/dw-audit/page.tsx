import { lazy, Suspense, useEffect, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';

const DataHealthPage = lazy(() => import('../health/page'));
const CompliancePage = lazy(() => import('../compliance/page'));

type Tab = 'warehouse' | 'compliance';

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'warehouse', label: '数仓体检', icon: 'ri-heart-pulse-line' },
  { key: 'compliance', label: 'DDL 合规规则', icon: 'ri-checkbox-circle-line' },
];

export default function HealthCenterPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const rawTab = searchParams.get('tab');
  const activeTab = (rawTab as Tab) || 'warehouse';
  const headerControlsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (rawTab === 'quality') {
      navigate('/governance/dqc', { replace: true });
    }
    if (rawTab === 'tableau') {
      navigate('/governance/tableau-audit', { replace: true });
    }
  }, [rawTab, navigate]);

  function handleTabChange(tab: Tab) {
    setSearchParams({ tab }, { replace: true });
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-1">
            <i className="ri-heart-pulse-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">数仓巡检</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7 mb-4">
            数仓体检 · DDL 合规规则
          </p>
          <div className="flex items-center justify-between">
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
            <div ref={headerControlsRef} className="flex items-center gap-2" />
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
        {activeTab === 'warehouse' && <DataHealthPage headerControlsRef={headerControlsRef} />}
        {activeTab === 'compliance' && <CompliancePage />}
      </Suspense>
    </div>
  );
}
