import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { listDataSources, type DataSource } from '../../../api/datasources';
import { listConnections, type TableauConnection } from '../../../api/tableau';
import { useAuth } from '../../../context/AuthContext';

type ConnectionTab = 'overview' | 'db' | 'tableau' | 'sync-logs' | 'policies';
type HealthStatus = 'healthy' | 'warning' | 'failed';

type NormalizedConnectionItem = {
  uid: string;
  sourceType: 'db' | 'tableau';
  rawId: number;
  name: string;
  platform: string;
  endpoint: string;
  owner: string;
  status: HealthStatus;
  updatedAt: string;
  note?: string;
};

const TAB_DEFS: { key: ConnectionTab; label: string }[] = [
  { key: 'overview', label: '总览' },
  { key: 'db', label: '数据库' },
  { key: 'tableau', label: 'Tableau' },
  { key: 'sync-logs', label: '同步日志' },
  { key: 'policies', label: '策略' },
];

function getTabFromTypeQuery(type: string | null): ConnectionTab {
  if (type === 'db') return 'db';
  if (type === 'tableau') return 'tableau';
  return 'overview';
}

function mapDatasourceToItem(ds: DataSource): NormalizedConnectionItem {
  return {
    uid: `db-${ds.id}`,
    sourceType: 'db',
    rawId: ds.id,
    name: ds.name,
    platform: ds.db_type.toUpperCase(),
    endpoint: `${ds.host}:${ds.port}/${ds.database_name}`,
    owner: `owner#${ds.owner_id}`,
    status: ds.is_active ? 'healthy' : 'failed',
    updatedAt: ds.updated_at,
    note: `username: ${ds.username}`,
  };
}

function mapTableauToItem(conn: TableauConnection): NormalizedConnectionItem {
  const status: HealthStatus = !conn.is_active
    ? 'failed'
    : conn.last_test_success === false
      ? 'warning'
      : 'healthy';

  return {
    uid: `tableau-${conn.id}`,
    sourceType: 'tableau',
    rawId: conn.id,
    name: conn.name,
    platform: `Tableau ${conn.connection_type.toUpperCase()}`,
    endpoint: `${conn.server_url} / ${conn.site}`,
    owner: `owner#${conn.owner_id}`,
    status,
    updatedAt: conn.updated_at,
    note: conn.last_test_message || undefined,
  };
}

export default function ConnectionCenterPage() {
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const [tab, setTab] = useState<ConnectionTab>(getTabFromTypeQuery(searchParams.get('type')));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dbItems, setDbItems] = useState<NormalizedConnectionItem[]>([]);
  const [tableauItems, setTableauItems] = useState<NormalizedConnectionItem[]>([]);

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | HealthStatus>('all');
  const [selectedItem, setSelectedItem] = useState<NormalizedConnectionItem | null>(null);

  useEffect(() => {
    setTab(getTabFromTypeQuery(searchParams.get('type')));
  }, [searchParams]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [dbRes, tableauRes] = await Promise.all([listDataSources(), listConnections(true)]);
        setDbItems(dbRes.datasources.map(mapDatasourceToItem));
        setTableauItems(tableauRes.connections.map(mapTableauToItem));
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : '加载 Connection Center 数据失败';
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    load();
  }, []);

  const scopedItems = useMemo(() => {
    if (tab === 'db') return dbItems;
    if (tab === 'tableau' || tab === 'sync-logs') return tableauItems;
    if (tab === 'policies') return [];
    return [...dbItems, ...tableauItems];
  }, [dbItems, tableauItems, tab]);

  const kpis = useMemo(() => {
    const total = scopedItems.length;
    const healthy = scopedItems.filter((item) => item.status === 'healthy').length;
    const warning = scopedItems.filter((item) => item.status === 'warning').length;
    const failed = scopedItems.filter((item) => item.status === 'failed').length;
    return { total, healthy, warning, failed };
  }, [scopedItems]);

  const filteredItems = useMemo(() => {
    return scopedItems.filter((item) => {
      const hitSearch = search.trim().length === 0
        || item.name.toLowerCase().includes(search.toLowerCase())
        || item.endpoint.toLowerCase().includes(search.toLowerCase());
      const hitStatus = statusFilter === 'all' || item.status === statusFilter;
      return hitSearch && hitStatus;
    });
  }, [scopedItems, search, statusFilter]);

  const visibleTabs = TAB_DEFS.filter((item) => item.key !== 'policies' || isAdmin);

  const handleTabChange = (next: ConnectionTab) => {
    setTab(next);
    if (next === 'db' || next === 'tableau') {
      setSearchParams({ type: next });
    } else {
      setSearchParams({});
    }
  };

  const statusStyle: Record<HealthStatus, string> = {
    healthy: 'bg-emerald-50 text-emerald-700 border border-emerald-200',
    warning: 'bg-amber-50 text-amber-700 border border-amber-200',
    failed: 'bg-red-50 text-red-700 border border-red-200',
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-5 py-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">连接总览</h1>
          <p className="text-sm text-slate-500 mt-1">查看所有数据库与 Tableau 连接状态</p>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="text-xs text-slate-500">总计</div>
          <div className="text-2xl font-semibold text-slate-800 mt-1">{kpis.total}</div>
        </div>
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <div className="text-xs text-emerald-700">正常</div>
          <div className="text-2xl font-semibold text-emerald-800 mt-1">{kpis.healthy}</div>
        </div>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="text-xs text-amber-700">警告</div>
          <div className="text-2xl font-semibold text-amber-800 mt-1">{kpis.warning}</div>
        </div>
        <div className="rounded-xl border border-red-200 bg-red-50 p-4">
          <div className="text-xs text-red-700">失败</div>
          <div className="text-2xl font-semibold text-red-800 mt-1">{kpis.failed}</div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-3">
        <div className="flex items-center gap-2 flex-wrap">
          {visibleTabs.map((item) => (
            <button
              key={item.key}
              onClick={() => handleTabChange(item.key)}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                tab === item.key
                  ? 'bg-slate-900 text-white border-slate-900'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-3">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索名称 / 地址..."
            className="md:col-span-2 px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'all' | HealthStatus)}
            className="px-3 py-2 text-sm border border-slate-200 rounded-lg bg-white focus:outline-none focus:border-blue-500"
          >
            <option value="all">全部状态</option>
            <option value="healthy">正常</option>
            <option value="warning">警告</option>
            <option value="failed">失败</option>
          </select>
          {(tab === 'db' || tab === 'overview') && (
            <Link to="/assets/datasources" className="px-3 py-2 text-sm border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 whitespace-nowrap">
              管理数据源
            </Link>
          )}
          {(tab === 'tableau' || tab === 'overview') && (
            <Link to="/assets/tableau-connections" className="px-3 py-2 text-sm border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 whitespace-nowrap">
              管理 Tableau 连接
            </Link>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        {loading ? (
          <div className="text-center py-16 text-slate-500">加载中...</div>
        ) : error ? (
          <div className="text-center py-16 text-red-600">{error}</div>
        ) : tab === 'policies' ? (
          <div className="p-8">
            <h3 className="text-base font-semibold text-slate-800">策略管理（仅管理员）</h3>
            <p className="text-sm text-slate-500 mt-2">连接策略管理功能开发中，敬请期待。</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">名称</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">类型</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">地址</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">负责人</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">状态</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">更新时间</th>
                {tab === 'sync-logs' && <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">操作</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filteredItems.map((item) => (
                <tr key={item.uid} className="hover:bg-slate-50 cursor-pointer" onClick={() => setSelectedItem(item)}>
                  <td className="px-4 py-3 font-medium text-slate-800">{item.name}</td>
                  <td className="px-4 py-3 text-slate-600">{item.platform}</td>
                  <td className="px-4 py-3 text-slate-600">{item.endpoint}</td>
                  <td className="px-4 py-3 text-slate-500">{item.owner}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${statusStyle[item.status]}`}>
                      {item.status === 'healthy' ? '正常' : item.status === 'warning' ? '警告' : '失败'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-500">{new Date(item.updatedAt).toLocaleString()}</td>
                  {tab === 'sync-logs' && (
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => navigate(`/assets/tableau-connections/${item.rawId}/sync-logs`)}
                        className="px-2 py-1 text-xs rounded border border-slate-200 hover:bg-slate-50"
                      >
                        查看日志
                      </button>
                    </td>
                  )}
                </tr>
              ))}
              {filteredItems.length === 0 && (
                <tr>
                  <td colSpan={tab === 'sync-logs' ? 7 : 6} className="px-4 py-16 text-center text-slate-400">
                    暂无记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {selectedItem && (
        <div className="fixed inset-0 z-50" onClick={() => setSelectedItem(null)}>
          <div className="absolute inset-0 bg-black/20" />
          <div
            className="absolute right-0 top-0 h-full w-full max-w-md bg-white border-l border-slate-200 shadow-xl p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-800">连接详情</h3>
              <button className="text-slate-400 hover:text-slate-600" onClick={() => setSelectedItem(null)}>
                <i className="ri-close-line text-xl" />
              </button>
            </div>
            <div className="mt-4 space-y-2 text-sm">
              <div><span className="text-slate-500">名称:</span> {selectedItem.name}</div>
              <div><span className="text-slate-500">类型:</span> {selectedItem.platform}</div>
              <div><span className="text-slate-500">地址:</span> {selectedItem.endpoint}</div>
              <div><span className="text-slate-500">负责人:</span> {selectedItem.owner}</div>
              <div><span className="text-slate-500">状态:</span> {selectedItem.status === 'healthy' ? '正常' : selectedItem.status === 'warning' ? '警告' : '失败'}</div>
              <div><span className="text-slate-500">更新时间:</span> {new Date(selectedItem.updatedAt).toLocaleString()}</div>
              {selectedItem.note && <div className="pt-2 text-slate-500">{selectedItem.note}</div>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
