import { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { listAssets, searchAssets, getProjects, listConnections, TableauAsset, TableauConnection, ProjectNode } from '../../../api/tableau';

const ASSET_TYPE_LABELS: Record<string, string> = {
  workbook: '工作簿',
  dashboard: '仪表板',
  view: '视图',
  datasource: '数据源'
};

const ASSET_TYPE_ICONS: Record<string, string> = {
  workbook: 'ri-file-chart-line',
  dashboard: 'ri-dashboard-line',
  view: 'ri-bar-chart-box-line',
  datasource: 'ri-database-2-line',
};

export default function TableauAssetBrowserPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const connectionId = Number(searchParams.get('connection_id') || '0');

  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [assets, setAssets] = useState<TableauAsset[]>([]);
  const [projects, setProjects] = useState<ProjectNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [assetTypeFilter, setAssetTypeFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('grid');

  useEffect(() => {
    listConnections().then(d => {
      setConnections(d.connections);
      if (!connectionId && d.connections.length > 0) {
        setSearchParams({ connection_id: String(d.connections[0].id) });
      }
    }).catch(console.error);
  }, []);

  useEffect(() => {
    if (!connectionId) return;
    setLoading(true);
    const promise = search
      ? searchAssets({ q: search, connection_id: connectionId, asset_type: assetTypeFilter || undefined, page, page_size: 24 })
      : listAssets({ connection_id: connectionId, asset_type: assetTypeFilter || undefined, page, page_size: 24 });

    Promise.all([
      promise,
      getProjects(connectionId).catch(() => ({ projects: [] as ProjectNode[] }))
    ]).then(([assetsData, projectsData]) => {
      setAssets(assetsData.assets);
      setTotal(assetsData.total);
      setProjects(projectsData.projects || []);
    }).catch(console.error).finally(() => setLoading(false));
  }, [connectionId, search, assetTypeFilter, page]);

  const handleAssetClick = (asset: TableauAsset) => {
    navigate(`/tableau/assets/${asset.id}`);
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
                <i className="ri-table-line text-blue-500" />
                Tableau 资产浏览
              </h1>
            </div>
            <div className="flex items-center gap-3">
              {connections.length > 0 && (
                <select value={connectionId} onChange={e => { setSearchParams({ connection_id: e.target.value }); setPage(1); }}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white">
                  {connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              )}
              <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
                <button onClick={() => setViewMode('grid')}
                  className={`px-3 py-1.5 text-xs rounded-md ${viewMode === 'grid' ? 'bg-white shadow-sm' : ''}`}>
                  <i className="ri-grid-line" />
                </button>
                <button onClick={() => setViewMode('list')}
                  className={`px-3 py-1.5 text-xs rounded-md ${viewMode === 'list' ? 'bg-white shadow-sm' : ''}`}>
                  <i className="ri-list-check" />
                </button>
              </div>
            </div>
          </div>
          {/* Search */}
          <div className="relative">
            <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input type="text" placeholder="搜索资产名称、项目或所有者..."
              value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
              className="w-full pl-9 pr-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500" />
          </div>
          {/* Filters */}
          <div className="flex items-center gap-2 mt-3">
            <button onClick={() => { setAssetTypeFilter(''); setPage(1); }}
              className={`px-3 py-1.5 text-xs rounded-lg ${!assetTypeFilter ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
              全部
            </button>
            {Object.entries(ASSET_TYPE_LABELS).map(([key, label]) => (
              <button key={key} onClick={() => { setAssetTypeFilter(key); setPage(1); }}
                className={`px-3 py-1.5 text-xs rounded-lg flex items-center gap-1 ${assetTypeFilter === key ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
                <i className={ASSET_TYPE_ICONS[key]} />
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-8 py-6">
        <div className="flex gap-6">
          {/* Sidebar - Project Tree */}
          <aside className="w-56 shrink-0">
            <div className="bg-white border border-slate-200 rounded-xl p-4">
              <h3 className="text-xs font-semibold text-slate-500 uppercase mb-3">项目</h3>
              <div className="space-y-1">
                {projects.length === 0 && !loading && (
                  <p className="text-xs text-slate-400">暂无项目数据</p>
                )}
                {projects.map(p => (
                  <div key={p.name} className="text-sm">
                    <div className="font-medium text-slate-700 py-1">{p.name}</div>
                    <div className="pl-3 space-y-0.5">
                      {Object.values(p.children).map((child: any) => (
                        <div key={child.type} className="flex items-center justify-between text-xs text-slate-500 py-0.5">
                          <span className="flex items-center gap-1">
                            <i className={ASSET_TYPE_ICONS[child.type]} />
                            {ASSET_TYPE_LABELS[child.type]}
                          </span>
                          <span className="bg-slate-100 px-1.5 rounded">{child.count}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </aside>

          {/* Main Content */}
          <main className="flex-1">
            {loading ? (
              <div className="text-center py-20 text-slate-400">
                <i className="ri-loader-4-line text-2xl animate-spin" />
                <p className="mt-2">加载中...</p>
              </div>
            ) : assets.length === 0 ? (
              <div className="text-center py-20 text-slate-400">
                <i className="ri-folder-open-line text-3xl mb-2 block" />
                <p>未找到资产，请先点击"同步"获取资产数据</p>
              </div>
            ) : viewMode === 'grid' ? (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {assets.map(asset => (
                  <div key={asset.id}
                    onClick={() => handleAssetClick(asset)}
                    className="bg-white border border-slate-200 rounded-xl p-4 cursor-pointer hover:border-blue-300 hover:shadow-sm transition-all">
                    <div className="flex items-start justify-between mb-3">
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                        asset.asset_type === 'workbook' ? 'bg-blue-50 text-blue-500' :
                        asset.asset_type === 'dashboard' ? 'bg-purple-50 text-purple-500' :
                        asset.asset_type === 'view' ? 'bg-emerald-50 text-emerald-500' :
                        'bg-orange-50 text-orange-500'
                      }`}>
                        <i className={`${ASSET_TYPE_ICONS[asset.asset_type]} text-lg`} />
                      </div>
                      <span className="text-[10px] text-slate-400">{ASSET_TYPE_LABELS[asset.asset_type]}</span>
                    </div>
                    <h4 className="font-medium text-slate-800 text-sm truncate">{asset.name}</h4>
                    <p className="text-xs text-slate-400 mt-1 truncate">{asset.project_name || '未分类'}</p>
                    {asset.owner_name && (
                      <p className="text-xs text-slate-400 mt-1">所有者: {asset.owner_name}</p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <table className="w-full">
                  <thead>
                    <tr className="bg-slate-50 border-b border-slate-200">
                      <th className="text-left text-xs font-semibold text-slate-500 px-4 py-3">类型</th>
                      <th className="text-left text-xs font-semibold text-slate-500 px-4 py-3">名称</th>
                      <th className="text-left text-xs font-semibold text-slate-500 px-4 py-3">项目</th>
                      <th className="text-left text-xs font-semibold text-slate-500 px-4 py-3">所有者</th>
                      <th className="text-left text-xs font-semibold text-slate-500 px-4 py-3">同步时间</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {assets.map(asset => (
                      <tr key={asset.id} onClick={() => handleAssetClick(asset)}
                        className="hover:bg-slate-50 cursor-pointer">
                        <td className="px-4 py-3">
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs ${
                            asset.asset_type === 'workbook' ? 'bg-blue-50 text-blue-600' :
                            asset.asset_type === 'dashboard' ? 'bg-purple-50 text-purple-600' :
                            asset.asset_type === 'view' ? 'bg-emerald-50 text-emerald-600' :
                            'bg-orange-50 text-orange-600'
                          }`}>
                            <i className={ASSET_TYPE_ICONS[asset.asset_type]} />
                            {ASSET_TYPE_LABELS[asset.asset_type]}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-slate-800">{asset.name}</td>
                        <td className="px-4 py-3 text-sm text-slate-500">{asset.project_name || '-'}</td>
                        <td className="px-4 py-3 text-sm text-slate-500">{asset.owner_name || '-'}</td>
                        <td className="px-4 py-3 text-xs text-slate-400">{asset.synced_at}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {total > 24 && (
              <div className="flex items-center justify-center gap-2 mt-6">
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                  className="px-3 py-1.5 text-sm bg-white border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50">
                  上一页
                </button>
                <span className="text-sm text-slate-500">第 {page} 页，共 {Math.ceil(total / 24)} 页</span>
                <button onClick={() => setPage(p => p + 1)} disabled={page >= Math.ceil(total / 24)}
                  className="px-3 py-1.5 text-sm bg-white border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50">
                  下一页
                </button>
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
