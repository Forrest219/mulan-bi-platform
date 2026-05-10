import { useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import DatasourcesPage, { type DatasourcesPageRef } from '../../assets/datasources/page';
import TableauConnectionsPage, { type TableauConnectionsPageRef } from '../../tableau/connections/page';

const TABS = [
  { key: 'datasources', label: '数据库连接' },
  { key: 'tableau', label: 'Tableau 连接' },
] as const;

type TabKey = typeof TABS[number]['key'];

export default function DataConnectionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get('tab') as TabKey) ?? 'datasources';
  const datasourcesRef = useRef<DatasourcesPageRef>(null);
  const tableauRef = useRef<TableauConnectionsPageRef>(null);

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-server-line text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">数据连接</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">管理数据库连接与 Tableau 连接</p>
          </div>
          {activeTab === 'datasources' && (
            <button
              onClick={() => datasourcesRef.current?.openNew()}
              className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700 transition-colors"
            >
              <i className="ri-add-line" />
              新建数据源
            </button>
          )}
          {activeTab === 'tableau' && (
            <button
              onClick={() => tableauRef.current?.openNew()}
              className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700 transition-colors"
            >
              <i className="ri-add-line" />
              新建连接
            </button>
          )}
        </div>
      </div>
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-6xl mx-auto flex gap-1 py-2">
          {TABS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setSearchParams({ tab: tab.key })}
              className={`px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${
                activeTab === tab.key
                  ? 'bg-slate-800 text-white'
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      {activeTab === 'datasources' && <DatasourcesPage headerless ref={datasourcesRef} />}
      {activeTab === 'tableau' && <TableauConnectionsPage headerless ref={tableauRef} />}
    </div>
  );
}
