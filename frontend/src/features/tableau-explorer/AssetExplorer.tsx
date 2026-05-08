import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  listAssets,
  searchAssets,
  getProjects,
  listConnections,
  syncConnection,
  TableauAsset,
  TableauConnection,
  ProjectNode,
} from '../../api/tableau';
import { ASSET_TYPE_LABELS } from '../../config';

const ASSET_TYPE_ICONS: Record<string, string> = {
  workbook: 'ri-file-chart-line',
  dashboard: 'ri-dashboard-line',
  view: 'ri-bar-chart-box-line',
  datasource: 'ri-database-2-line',
};

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
}

function isSyncStale(iso: string): boolean {
  return Date.now() - new Date(iso).getTime() > 24 * 60 * 60 * 1000;
}

interface AssetExplorerProps {
  connectionId?: number;
  onSelect?: (assetId: string) => void;
}

const LS_KEY = 'tableau-explorer-connection';

export function AssetExplorer({ connectionId: connectionIdProp, onSelect }: AssetExplorerProps) {
  const navigate = useNavigate();

  const [connectionId, setConnectionId] = useState<number>(connectionIdProp ?? 0);
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [selectedConn, setSelectedConn] = useState<TableauConnection | null>(null);
  const [assets, setAssets] = useState<TableauAsset[]>([]);
  const [projects, setProjects] = useState<ProjectNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [projectSearch, setProjectSearch] = useState('');
  const [assetTypeFilter, setAssetTypeFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('list');
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState('');
  const [loadError, setLoadError] = useState('');

  const filteredProjects = useMemo(() => {
    if (!projectSearch.trim()) return projects;
    const q = projectSearch.toLowerCase();
    return projects.filter(p => p.name.toLowerCase().includes(q));
  }, [projects, projectSearch]);

  const handleSync = async () => {
    if (!connectionId || syncing) return;
    setSyncing(true);
    setSyncMsg('');
    try {
      await syncConnection(connectionId);
      setSyncMsg('同步任务已提交，数据将在后台刷新');
      setTimeout(() => {
        setPage(1);
        setLoading(true);
        const promise = search
          ? searchAssets({ q: search, connection_id: connectionId, asset_type: assetTypeFilter || undefined, page: 1, page_size: 24 })
          : listAssets({ connection_id: connectionId, asset_type: assetTypeFilter || undefined, page: 1, page_size: 24 });
        Promise.all([
          promise,
          getProjects(connectionId).catch(() => ({ projects: [] as ProjectNode[] })),
        ]).then(([assetsData, projectsData]) => {
          setAssets(assetsData.assets);
          setTotal(assetsData.total);
          setProjects(projectsData.projects || []);
        }).catch(() => {}).finally(() => setLoading(false));
      }, 3000);
    } catch (e: unknown) {
      setSyncMsg(e instanceof Error ? e.message : '同步请求失败');
    } finally {
      setSyncing(false);
    }
  };

  /* eslint-disable react-hooks/exhaustive-deps -- 初始化只执行一次 */
  useEffect(() => {
    listConnections().then(d => {
      setConnections(d.connections);
      if (connectionIdProp) return;
      const savedName = localStorage.getItem(LS_KEY);
      const match = savedName ? d.connections.find(c => c.name === savedName) : null;
      const target = match || d.connections[0];
      if (target) {
        setConnectionId(target.id);
        setSelectedConn(target);
        localStorage.setItem(LS_KEY, target.name);
      }
    }).catch(() => { setLoadError('无法加载连接列表，请刷新重试'); });
  }, []);
  /* eslint-enable react-hooks/exhaustive-deps */

  useEffect(() => {
    const found = connections.find(c => c.id === connectionId);
    setSelectedConn(found || null);
  }, [connectionId, connections]);

  useEffect(() => {
    if (!connectionId) return;
    setLoading(true);
    setLoadError('');
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
    }).catch((e: unknown) => { setLoadError(e instanceof Error ? e.message : '加载资产数据失败，请刷新重试'); }).finally(() => setLoading(false));
  }, [connectionId, search, assetTypeFilter, page]);

  const handleAssetClick = (asset: TableauAsset) => {
    if (onSelect) {
      onSelect(String(asset.id));
    } else {
      navigate(`/assets/tableau/${asset.id}`);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-bar-chart-box-line text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">Tableau 资产</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">浏览和探索 Tableau 工作簿、视图与数据源</p>
          </div>
          <div className="flex items-center gap-3">
            {connections.length > 0 && (
              <>
                <select value={connectionId} onChange={e => {
                    const id = Number(e.target.value);
                    setConnectionId(id);
                    setPage(1);
                    const conn = connections.find(c => c.id === id);
                    if (conn) localStorage.setItem(LS_KEY, conn.name);
                  }}
                  className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white">
                  {connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                {selectedConn && (
                  <div className="flex items-center gap-1.5">
                    <span className={`text-xs px-2 py-1 rounded-full flex items-center gap-1.5 ${
                      !selectedConn.is_active ? 'bg-red-50 text-red-600' :
                      selectedConn.last_test_success === false ? 'bg-orange-50 text-orange-600' :
                      'bg-emerald-50 text-emerald-600'
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                        !selectedConn.is_active ? 'bg-red-400' :
                        selectedConn.last_test_success === false ? 'bg-orange-400' :
                        'bg-emerald-400'
                      }`} />
                      {!selectedConn.is_active ? '已禁用' :
                       selectedConn.last_test_success === false ? '连接异常' :
                       '连接正常'}
                    </span>
                    <button
                      onClick={handleSync}
                      disabled={syncing || !connectionId || !selectedConn.is_active}
                      title="触发后台同步并刷新数据"
                      className="flex items-center gap-1 text-xs text-slate-600 border border-slate-200 rounded-lg px-2.5 py-1 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      <i className={syncing ? 'ri-loader-4-line animate-spin' : 'ri-refresh-line'} />
                      {syncing ? '同步中' : '立即刷新'}
                    </button>
                  </div>
                )}
              </>
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
      </div>

      {/* Filter strip */}
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-center gap-2 py-2">
            <button onClick={() => { setAssetTypeFilter(''); setPage(1); }}
              className={`px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${!assetTypeFilter ? 'bg-slate-800 text-white' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'}`}>
              全部
            </button>
            {Object.entries(ASSET_TYPE_LABELS).map(([key, label]) => (
              <button key={key} onClick={() => { setAssetTypeFilter(key); setPage(1); }}
                className={`flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${assetTypeFilter === key ? 'bg-slate-800 text-white' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'}`}>
                <i className={ASSET_TYPE_ICONS[key]} />
                {label}
              </button>
            ))}
            <div className="flex-1" />
            <div className="relative">
              <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
              <input type="text" placeholder="搜索资产名称、项目或所有者..."
                value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
                className="pl-9 pr-4 py-1.5 border border-slate-200 rounded-lg text-[12px] w-56 focus:outline-none focus:border-blue-400" />
            </div>
          </div>
        </div>
      </div>

      <div className="px-8 py-6">
        <div className="max-w-7xl mx-auto">
        <div className="flex gap-6">

          {/* Sidebar - Project Tree */}
          <aside className="w-56 shrink-0">
            <div className="bg-white border border-slate-200 rounded-xl p-4">
              <h3 className="text-xs font-semibold text-slate-500 uppercase mb-2">项目</h3>
              {/* Project search filter */}
              <div className="relative mb-3">
                <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-[11px]" />
                <input
                  type="text"
                  placeholder="过滤项目..."
                  value={projectSearch}
                  onChange={e => setProjectSearch(e.target.value)}
                  className="w-full pl-7 pr-2.5 py-1 border border-slate-200 rounded-md text-[11px] text-slate-600 placeholder-slate-400 focus:outline-none focus:border-blue-400"
                />
              </div>
              <div className="space-y-1">
                {filteredProjects.length === 0 && !loading && (
                  <p className="text-[11px] text-slate-400">
                    {projectSearch.trim() ? '无匹配项目' : '暂无项目数据'}
                  </p>
                )}
                {filteredProjects.map(p => (
                  <div key={p.name} className="text-xs">
                    <div className="font-medium text-slate-700 py-1 truncate" title={p.name}>{p.name}</div>
                    <div className="pl-3 space-y-0.5">
                      {Object.values(p.children).map((child: any) => (
                        <div key={child.type} className="flex items-center justify-between text-xs text-slate-500 py-0.5">
                          <span className="flex items-center gap-1">
                            <i className={ASSET_TYPE_ICONS[child.type]} />
                            {ASSET_TYPE_LABELS[child.type]}
                          </span>
                          <span className="min-w-[18px] text-center bg-blue-50 text-blue-600 text-[10px] px-1.5 py-0.5 rounded-full font-medium leading-none">
                            {child.count}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </aside>

          {/* Main Content */}
          <main className="flex-1 min-w-0">
            {loadError && (
              <div className="mb-4 flex items-start gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-xs">
                <i className="ri-error-warning-line mt-0.5 flex-shrink-0" />
                <span className="flex-1">{loadError}</span>
                <button onClick={() => setLoadError('')} className="text-red-400 hover:text-red-600 flex-shrink-0">
                  <i className="ri-close-line" />
                </button>
              </div>
            )}
            {loading ? (
              <div className="flex flex-col items-center justify-center py-20">
                <i className="ri-loader-4-line text-2xl text-blue-600 animate-spin" />
                <p className="mt-3 text-xs text-slate-500">加载中...</p>
              </div>
            ) : assets.length === 0 ? (
              <div className="text-center py-20 text-slate-400">
                <i className="ri-folder-open-line text-3xl text-slate-300 block mb-2" />
                <p className="mb-4">未找到资产，请同步以获取资产数据</p>
                {syncMsg && (
                  <p className={`text-xs mb-3 ${syncMsg.includes('失败') ? 'text-red-500' : 'text-emerald-600'}`}>
                    {syncMsg}
                  </p>
                )}
                <button
                  onClick={handleSync}
                  disabled={syncing || !connectionId}
                  data-testid="empty-sync-btn"
                  className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <i className={`${syncing ? 'ri-loader-4-line animate-spin' : 'ri-refresh-line'}`} />
                  {syncing ? '同步中...' : '同步资产'}
                </button>
              </div>
            ) : viewMode === 'grid' ? (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {assets.map(asset => (
                  <div key={asset.id}
                    onClick={() => handleAssetClick(asset)}
                    className="bg-white border border-slate-200 rounded-xl p-4 cursor-pointer hover:border-blue-300 hover:shadow-sm transition-all">
                    <div className="flex items-start justify-between mb-3">
                      {asset.thumbnail_url ? (
                        <img
                          src={asset.thumbnail_url}
                          alt={asset.name}
                          className="w-10 h-10 rounded-lg object-cover"
                          onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }}
                        />
                      ) : (
                        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                          asset.asset_type === 'workbook' ? 'bg-blue-50 text-blue-500' :
                          asset.asset_type === 'dashboard' ? 'bg-purple-50 text-purple-500' :
                          asset.asset_type === 'view' ? 'bg-emerald-50 text-emerald-500' :
                          'bg-orange-50 text-orange-500'
                        }`}>
                          <i className={`${ASSET_TYPE_ICONS[asset.asset_type]} text-lg`} />
                        </div>
                      )}
                      <span className="text-[10px] text-slate-400">{ASSET_TYPE_LABELS[asset.asset_type]}</span>
                    </div>
                    <h4 className="font-medium text-slate-800 text-xs truncate">{asset.name}</h4>
                    <p className="text-xs text-slate-400 mt-1 truncate">{asset.project_name || '未分类'}</p>
                    {asset.parent_workbook_name && (asset.asset_type === 'view' || asset.asset_type === 'dashboard') && (
                      <p className="text-xs text-slate-400 mt-1 truncate flex items-center gap-1">
                        <i className="ri-file-chart-line" />{asset.parent_workbook_name}
                      </p>
                    )}
                    <div className="flex items-center gap-2 mt-1.5">
                      {asset.owner_name && (
                        <span className="text-xs text-slate-400 truncate">{asset.owner_name}</span>
                      )}
                      {asset.view_count != null && asset.view_count > 0 && (
                        <span className="text-xs text-slate-400 flex items-center gap-0.5">
                          <i className="ri-eye-line" />{asset.view_count}
                        </span>
                      )}
                      {asset.health_score != null && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                          asset.health_score >= 80 ? 'bg-emerald-50 text-emerald-600' :
                          asset.health_score >= 50 ? 'bg-yellow-50 text-yellow-600' :
                          'bg-red-50 text-red-600'
                        }`}>
                          {asset.health_score}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-slate-50 border-b border-slate-200">
                      <th className="text-left font-medium text-slate-600 px-3 py-3 whitespace-nowrap">类型</th>
                      <th className="text-left font-medium text-slate-600 px-3 py-3">名称</th>
                      <th className="text-left font-medium text-slate-600 px-3 py-3">项目</th>
                      <th className="text-left font-medium text-slate-600 px-3 py-3">所有者</th>
                      <th className="text-right font-medium text-slate-600 px-3 py-3 whitespace-nowrap">浏览量</th>
                      <th className="text-left font-medium text-slate-600 px-3 py-3 whitespace-nowrap">创建时间</th>
                      <th className="text-left font-medium text-slate-600 px-3 py-3 whitespace-nowrap">修改时间</th>
                      <th className="text-left font-medium text-slate-600 px-3 py-3 whitespace-nowrap">同步时间</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {assets.map(asset => (
                      <tr key={asset.id} onClick={() => handleAssetClick(asset)}
                        className="hover:bg-slate-50 cursor-pointer">
                        <td className="px-3 py-3 whitespace-nowrap">
                          <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] ${
                            asset.asset_type === 'workbook' ? 'bg-blue-50 text-blue-600' :
                            asset.asset_type === 'dashboard' ? 'bg-purple-50 text-purple-600' :
                            asset.asset_type === 'view' ? 'bg-emerald-50 text-emerald-600' :
                            'bg-orange-50 text-orange-600'
                          }`}>
                            <i className={ASSET_TYPE_ICONS[asset.asset_type]} />
                            {ASSET_TYPE_LABELS[asset.asset_type]}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-slate-700">{asset.name}</td>
                        <td className="px-3 py-3 text-slate-700">{asset.project_name || '-'}</td>
                        <td className="px-3 py-3 text-slate-700">{asset.owner_name || '-'}</td>
                        <td className="px-3 py-3 text-slate-700 text-right">
                          {asset.view_count != null ? asset.view_count.toLocaleString() : '-'}
                        </td>
                        <td className="px-3 py-3 text-slate-700 whitespace-nowrap">{asset.created_on_server || '-'}</td>
                        <td className="px-3 py-3 text-slate-700 whitespace-nowrap">{asset.updated_on_server || '-'}</td>
                        <td className={`px-3 py-3 whitespace-nowrap ${asset.synced_at && isSyncStale(asset.synced_at) ? 'text-amber-500' : 'text-slate-700'}`}
                            title={asset.synced_at || ''}>
                          {asset.synced_at ? relativeTime(asset.synced_at) : '-'}
                        </td>
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
                  className="px-3 py-1.5 text-xs bg-white border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50">
                  上一页
                </button>
                <span className="text-xs text-slate-500">第 {page} 页，共 {Math.ceil(total / 24)} 页</span>
                <button onClick={() => setPage(p => p + 1)} disabled={page >= Math.ceil(total / 24)}
                  className="px-3 py-1.5 text-xs bg-white border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50">
                  下一页
                </button>
              </div>
            )}

            {/* Sync feedback (non-empty state) */}
            {syncMsg && assets.length > 0 && (
              <p className={`text-center text-[11px] mt-3 ${syncMsg.includes('失败') ? 'text-red-500' : 'text-emerald-600'}`}>
                {syncMsg}
              </p>
            )}

            {/* Data source disclosure */}
            {selectedConn && (
              <p className="text-center text-[11px] text-slate-400 mt-4">
                数据来自 Mulan 本地镜像 · 最后同步：
                {selectedConn.last_sync_at
                  ? relativeTime(selectedConn.last_sync_at)
                  : '暂无同步记录'}
              </p>
            )}
          </main>
        </div>
        </div>
      </div>
    </div>
  );
}
