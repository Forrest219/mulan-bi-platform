import { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  listDwDatabases,
  listDwTables,
  triggerDwSync,
  fetchDomainValues,
  DwDatabaseItem,
  DwAssetTable,
  DwTablesParams,
  DomainValueItem,
  DW_LAYER_OPTIONS,
  DW_TABLE_TYPE_OPTIONS,
  DW_SORT_OPTIONS,
} from '../../../api/dwAssets';

// ============================================================
// 工具函数
// ============================================================

function formatRowCount(count: number | null): string {
  if (count === null || count === undefined) return '-';
  if (count < 1000) return String(count);
  if (count < 10000) return `${(count / 1000).toFixed(1)}K`;
  if (count < 1000000) return `${Math.round(count / 1000)}K`;
  if (count < 1000000000) return `${(count / 1000000).toFixed(1)}M`;
  return `${(count / 1000000000).toFixed(2)}B`;
}

function formatTime(ts: string | null): string {
  if (!ts) return '-';
  const d = new Date(ts);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 3600000) return `${Math.round(diff / 60000)} 分钟前`;
  if (diff < 86400000) return `${Math.round(diff / 3600000)} 小时前`;
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

// ============================================================
// Indeterminate checkbox（L1 半选态）
// ============================================================

function L1Checkbox({ label, checked, indeterminate, onChange }: {
  label: string; checked: boolean; indeterminate: boolean; onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = indeterminate; }, [indeterminate]);
  return (
    <label className="flex items-center gap-1.5 px-2 py-1.5 rounded-md cursor-pointer hover:bg-slate-50 transition-colors">
      <input ref={ref} type="checkbox" checked={checked} onChange={onChange}
        className="w-3.5 h-3.5 rounded border-slate-300 text-slate-700 focus:ring-0 focus:ring-offset-0" />
      <span className="text-xs font-medium text-slate-600">{label}</span>
    </label>
  );
}

// ============================================================
// 页面组件
// ============================================================

export default function DwAssetsPage() {
  const navigate = useNavigate();
  // ========== 数据源 & 数据库 筛选 ==========
  const [datasources, setDatasources] = useState<DwDatabaseItem[]>([]);
  const [dsLoading, setDsLoading] = useState(true);
  const [selectedDsId, setSelectedDsId] = useState<number | null>(null);
  const [selectedDb, setSelectedDb] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  // ========== 表列表 ==========
  const [tables, setTables] = useState<DwAssetTable[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 筛选
  const [layer, setLayer] = useState('');
  const [selectedDomains, setSelectedDomains] = useState<Set<string>>(new Set());
  const [tableType, setTableType] = useState('');
  const [sort, setSort] = useState('heat_score');
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(1);
  const pageSize = 20;

  // 主题域枚举
  const [domainValues, setDomainValues] = useState<DomainValueItem[]>([]);
  useEffect(() => {
    fetchDomainValues().then((r) => setDomainValues(r.items)).catch(() => {});
  }, []);

  const domainKey = Array.from(selectedDomains).sort().join('\0');

  // 当前选中数据源的元信息
  const currentDs = datasources.find((d) => d.datasource_id === selectedDsId) || null;

  // ========== 加载数据源列表（用于筛选 pill） ==========
  useEffect(() => {
    setDsLoading(true);
    listDwDatabases()
      .then((res) => setDatasources(res.items))
      .catch(() => {})
      .finally(() => setDsLoading(false));
  }, []);

  // ========== 加载表列表 ==========
  const fetchTables = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: DwTablesParams = { page, page_size: pageSize, sort };
      if (selectedDsId) params.datasource_id = selectedDsId;
      if (selectedDb) params.database_name = selectedDb;
      if (layer) params.layer = layer;
      if (selectedDomains.size > 0) params.domain = Array.from(selectedDomains);
      if (tableType) params.table_type = tableType;
      if (searchQuery.trim()) params.q = searchQuery.trim();

      const res = await listDwTables(params);
      setTables(res.items);
      setTotal(res.total);
      setPages(res.pages);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDsId, selectedDb, layer, domainKey, tableType, sort, searchQuery, page]);

  useEffect(() => { fetchTables(); }, [fetchTables]);

  const resetPage = () => setPage(1);

  // ========== 操作 ==========
  const handleSync = async () => {
    if (!selectedDsId) return;
    setSyncing(true);
    try {
      await triggerDwSync(selectedDsId, { mode: 'incremental', include_partitions: true });
      fetchTables();
      const res = await listDwDatabases();
      setDatasources(res.items);
    } catch { /* 静默 */ }
    finally { setSyncing(false); }
  };

  const handleSelectDs = (dsId: number | null) => {
    setSelectedDsId(dsId);
    setSelectedDb(null);
    resetPage();
  };

  const handleSelectDb = (dbName: string | null) => {
    setSelectedDb(dbName);
    resetPage();
  };

  // ============================================================
  // Render
  // ============================================================

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 mb-0.5">
                <i className="ri-database-2-line text-base text-slate-500" />
                <h1 className="text-lg font-semibold text-slate-800">数仓资产</h1>
              </div>
              <p className="text-[13px] text-slate-400 ml-7">
                浏览数仓表结构，查看字段血缘与分类标签
              </p>
            </div>
            {selectedDsId && (
              <button
                onClick={handleSync}
                disabled={syncing}
                className="flex items-center gap-1.5 text-xs px-3 py-2 text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50"
              >
                <i className={`ri-refresh-line ${syncing ? 'animate-spin' : ''}`} />
                同步元数据
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 数据源 pill 筛选 */}
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-6xl mx-auto py-3">
          {dsLoading ? (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <i className="ri-loader-4-line animate-spin" />
              加载数据源...
            </div>
          ) : (
            <div className="space-y-2">
              {/* 第一行：数据源 pills */}
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-slate-400 mr-1 shrink-0">数据源</span>
                <button
                  onClick={() => handleSelectDs(null)}
                  className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${
                    !selectedDsId
                      ? 'bg-slate-800 text-white'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  全部
                </button>
                {datasources.map((ds) => (
                  <button
                    key={ds.datasource_id}
                    onClick={() => handleSelectDs(ds.datasource_id)}
                    className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${
                      selectedDsId === ds.datasource_id
                        ? 'bg-slate-800 text-white'
                        : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                    }`}
                  >
                    {ds.name}
                  </button>
                ))}
              </div>

              {/* 第二行：数据库 pills（仅选中数据源时显示） */}
              {currentDs && currentDs.databases.length > 1 && (
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs text-slate-400 mr-1 shrink-0">数据库</span>
                  <button
                    onClick={() => handleSelectDb(null)}
                    className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                      !selectedDb
                        ? 'bg-blue-600 text-white'
                        : 'bg-blue-50 text-blue-700 hover:bg-blue-100'
                    }`}
                  >
                    全部
                  </button>
                  {currentDs.databases.map((dbName) => (
                    <button
                      key={dbName}
                      onClick={() => handleSelectDb(dbName)}
                      className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                        selectedDb === dbName
                          ? 'bg-blue-600 text-white'
                          : 'bg-blue-50 text-blue-700 hover:bg-blue-100'
                      }`}
                    >
                      {dbName}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Filter strip */}
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 py-2">
            <div className="relative flex-1 max-w-xs">
              <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => { setSearchQuery(e.target.value); resetPage(); }}
                placeholder="搜索表名或业务名..."
                className="w-full pl-9 pr-4 py-1.5 border border-slate-200 rounded-lg text-[12px] focus:outline-none focus:border-blue-400"
              />
            </div>
            <select
              value={layer}
              onChange={(e) => { setLayer(e.target.value); resetPage(); }}
              className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:border-blue-400"
            >
              {DW_LAYER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <select
              value={tableType}
              onChange={(e) => { setTableType(e.target.value); resetPage(); }}
              className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:border-blue-400"
            >
              {DW_TABLE_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <select
              value={sort}
              onChange={(e) => { setSort(e.target.value); resetPage(); }}
              className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:border-blue-400"
            >
              {DW_SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <span className="text-xs text-slate-400 ml-auto">共 {total} 张表</span>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="px-8 py-6">
        <div className="max-w-6xl mx-auto">
          <div className="flex gap-6">

            {/* Sidebar - 主题域多选筛选 */}
            <aside className="w-56 shrink-0">
              <div className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-semibold text-slate-500 uppercase">主题域</h3>
                  <div className="flex items-center gap-2">
                    {selectedDomains.size > 0 && (
                      <button
                        onClick={() => { setSelectedDomains(new Set()); resetPage(); }}
                        className="text-[11px] text-slate-400 hover:text-slate-600"
                      >
                        清空
                      </button>
                    )}
                    <Link to="/assets/dw/taxonomy" title="主题域配置"
                      className="text-slate-300 hover:text-slate-500 transition-colors">
                      <i className="ri-settings-3-line text-sm" />
                    </Link>
                  </div>
                </div>
                <div className="space-y-0.5">
                  {domainValues.map((d) => {
                    const l2Keys = d.l2_list.map((l2) => `${d.l1}/${l2}`);
                    const allKeys = [d.l1, ...l2Keys];
                    const checkedCount = allKeys.filter((k) => selectedDomains.has(k)).length;
                    const isAllChecked = checkedCount === allKeys.length;
                    const isIndeterminate = checkedCount > 0 && !isAllChecked;

                    const toggleL1 = () => {
                      setSelectedDomains((prev) => {
                        const next = new Set(prev);
                        if (isAllChecked) {
                          allKeys.forEach((k) => next.delete(k));
                        } else {
                          allKeys.forEach((k) => next.add(k));
                        }
                        return next;
                      });
                      resetPage();
                    };

                    const toggleL2 = (l2Key: string) => {
                      setSelectedDomains((prev) => {
                        const next = new Set(prev);
                        if (next.has(l2Key)) {
                          next.delete(l2Key);
                        } else {
                          next.add(l2Key);
                        }
                        const remaining = allKeys.filter((k) => next.has(k));
                        if (remaining.length === allKeys.length) {
                          allKeys.forEach((k) => next.add(k));
                        }
                        return next;
                      });
                      resetPage();
                    };

                    return (
                      <div key={d.l1}>
                        <L1Checkbox
                          label={d.l1}
                          checked={isAllChecked}
                          indeterminate={isIndeterminate}
                          onChange={toggleL1}
                        />
                        {d.l2_list.length > 0 && (
                          <div className="ml-5 space-y-0.5">
                            {d.l2_list.map((l2) => {
                              const l2Key = `${d.l1}/${l2}`;
                              return (
                                <label key={l2Key} className="flex items-center gap-1.5 px-1.5 py-1 rounded-md cursor-pointer hover:bg-slate-50 transition-colors">
                                  <input
                                    type="checkbox"
                                    checked={selectedDomains.has(l2Key)}
                                    onChange={() => toggleL2(l2Key)}
                                    className="w-3.5 h-3.5 rounded border-slate-300 text-slate-700 focus:ring-0 focus:ring-offset-0"
                                  />
                                  <span className="text-xs text-slate-500">{l2}</span>
                                </label>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {domainValues.length === 0 && (
                    <p className="text-xs text-slate-300 py-2">暂无主题域</p>
                  )}
                </div>
              </div>
            </aside>

            {/* Main Content */}
            <main className="flex-1 min-w-0">
              {error && (
                <div className="mb-4 flex items-start gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-xs">
                  <i className="ri-error-warning-line mt-0.5 flex-shrink-0" />
                  <span className="flex-1">{error}</span>
                  <button onClick={fetchTables} className="text-red-400 hover:text-red-600 flex-shrink-0">
                    <i className="ri-refresh-line" />
                  </button>
                </div>
              )}

              {loading ? (
                <div className="flex flex-col items-center justify-center py-20">
                  <i className="ri-loader-4-line text-2xl text-blue-600 animate-spin" />
                  <p className="mt-3 text-xs text-slate-500">加载中...</p>
                </div>
              ) : tables.length === 0 ? (
                <div className="text-center py-20 text-slate-400">
                  <i className="ri-database-2-line text-3xl text-slate-300 block mb-2" />
                  <p className="mb-2">暂无数仓资产</p>
                  <p className="text-xs text-slate-400">请先配置数据源并触发元数据同步</p>
                </div>
              ) : (
                <>
                  <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-slate-50 border-b border-slate-200">
                          <th className="text-left font-medium text-slate-600 px-3 py-3 whitespace-nowrap">分层</th>
                          <th className="text-left font-medium text-slate-600 px-3 py-3">表名</th>
                          <th className="text-left font-medium text-slate-600 px-3 py-3">库 / Schema</th>
                          <th className="text-left font-medium text-slate-600 px-3 py-3">主题域</th>
                          <th className="text-right font-medium text-slate-600 px-3 py-3 whitespace-nowrap">行数</th>
                          <th className="text-left font-medium text-slate-600 px-3 py-3 whitespace-nowrap">热度</th>
                          <th className="text-right font-medium text-slate-600 px-3 py-3 whitespace-nowrap">字段数</th>
                          <th className="text-left font-medium text-slate-600 px-3 py-3 whitespace-nowrap">同步时间</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {tables.map((table) => {
                          const syncStale = table.synced_at && (Date.now() - new Date(table.synced_at).getTime() > 86400000);
                          return (
                            <tr key={table.id}
                              onClick={() => navigate(`/assets/dw/${table.id}`)}
                              className="hover:bg-slate-50 cursor-pointer">
                              <td className="px-3 py-3 whitespace-nowrap">
                                {table.layer ? (
                                  <span className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-medium uppercase ${
                                    table.layer === 'ods' ? 'bg-slate-100 text-slate-600' :
                                    table.layer === 'dwd' ? 'bg-blue-50 text-blue-600' :
                                    table.layer === 'dws' ? 'bg-purple-50 text-purple-600' :
                                    table.layer === 'ads' ? 'bg-emerald-50 text-emerald-600' :
                                    table.layer === 'dim' ? 'bg-orange-50 text-orange-600' :
                                    'bg-slate-100 text-slate-500'
                                  }`}>{table.layer}</span>
                                ) : (
                                  <span className="text-slate-300">-</span>
                                )}
                              </td>
                              <td className="px-3 py-3">
                                <div className="text-slate-800 font-medium truncate max-w-xs">{table.table_name}</div>
                                {table.business_name && (
                                  <div className="text-slate-400 text-[11px] truncate max-w-xs mt-0.5">{table.business_name}</div>
                                )}
                              </td>
                              <td className="px-3 py-3 text-slate-600 whitespace-nowrap">
                                {table.database_name}{table.schema_name ? `/${table.schema_name}` : ''}
                              </td>
                              <td className="px-3 py-3 text-slate-600">{table.domain || '-'}</td>
                              <td className="px-3 py-3 text-slate-600 text-right whitespace-nowrap">
                                {formatRowCount(table.row_count_estimate)}
                              </td>
                              <td className="px-3 py-3 whitespace-nowrap">
                                <div className="flex items-center gap-1.5">
                                  <div className="w-16 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                                    <div className="h-full rounded-full" style={{
                                      width: `${Math.min(100, table.heat_score)}%`,
                                      backgroundColor: table.heat_score >= 70 ? '#b91c1c' : table.heat_score >= 40 ? '#d97706' : '#94a3b8',
                                    }} />
                                  </div>
                                  <span className="text-slate-500 w-6 text-right">{Math.round(table.heat_score)}</span>
                                </div>
                              </td>
                              <td className="px-3 py-3 text-slate-600 text-right">{table.field_count}</td>
                              <td className={`px-3 py-3 whitespace-nowrap ${syncStale ? 'text-amber-500' : 'text-slate-600'}`}
                                title={table.synced_at || ''}>
                                {formatTime(table.synced_at)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {pages > 1 && (
                    <div className="flex items-center justify-center gap-2 mt-6">
                      <button
                        onClick={() => setPage((p) => Math.max(1, p - 1))}
                        disabled={page <= 1}
                        className="px-3 py-1.5 text-xs bg-white border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50"
                      >
                        上一页
                      </button>
                      <span className="text-xs text-slate-500">第 {page} / {pages} 页，共 {total} 条</span>
                      <button
                        onClick={() => setPage((p) => Math.min(pages, p + 1))}
                        disabled={page >= pages}
                        className="px-3 py-1.5 text-xs bg-white border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50"
                      >
                        下一页
                      </button>
                    </div>
                  )}
                </>
              )}
            </main>
          </div>
        </div>
      </div>
    </div>
  );
}
