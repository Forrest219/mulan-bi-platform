import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { API_BASE } from '../../../config';

interface UnifiedConnection {
  id: string;
  type: 'sql_database' | 'tableau_site' | 'llm_provider';
  name: string;
  health_status: 'healthy' | 'warning' | 'failed' | 'unknown';
  is_active: boolean;
  meta: Record<string, unknown>;
}

type TabType = 'all' | 'sql_database' | 'tableau_site' | 'llm_provider';

const STATUS_LABEL: Record<string, string> = {
  healthy: '正常',
  warning: '警告',
  failed: '故障',
  unknown: '未知',
};

const STATUS_COLOR: Record<string, string> = {
  healthy: 'text-green-600 bg-green-50',
  warning: 'text-amber-600 bg-amber-50',
  failed: 'text-red-600 bg-red-50',
  unknown: 'text-slate-400 bg-slate-50',
};

const TYPE_LABEL: Record<string, string> = {
  sql_database: '数据库',
  tableau_site: 'Tableau',
  llm_provider: 'LLM',
};

export default function ConnectionCenterPage() {
  const [connections, setConnections] = useState<UnifiedConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>('all');

  useEffect(() => {
    fetch(`${API_BASE}/api/connection-hub/connections`, { credentials: 'include' })
      .then(r => {
        if (!r.ok) throw new Error('获取连接列表失败');
        return r.json();
      })
      .then(data => setConnections(data.connections ?? []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = activeTab === 'all' ? connections : connections.filter(c => c.type === activeTab);

  const kpi = {
    total: connections.length,
    healthy: connections.filter(c => c.health_status === 'healthy').length,
    warning: connections.filter(c => c.health_status === 'warning').length,
    failed: connections.filter(c => c.health_status === 'failed').length,
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">连接中心</h1>
          <p className="text-sm text-slate-400 mt-0.5">统一管理所有数据连接</p>
        </div>
      </div>

      {/* KPI 卡片 */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: '总计', value: kpi.total, color: 'text-slate-700' },
          { label: '正常', value: kpi.healthy, color: 'text-green-600' },
          { label: '警告', value: kpi.warning, color: 'text-amber-600' },
          { label: '故障', value: kpi.failed, color: 'text-red-600' },
        ].map(card => (
          <div key={card.label} className="bg-white rounded-xl border border-slate-100 px-5 py-4 shadow-sm">
            <p className="text-xs text-slate-400">{card.label}</p>
            <p className={`text-3xl font-semibold mt-1 ${card.color}`}>{card.value}</p>
          </div>
        ))}
      </div>

      {/* 快捷跳转 */}
      <div className="flex gap-3">
        <Link to="/system/datasources" className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50">
          <i className="ri-database-2-line" /> 管理数据库连接
        </Link>
        <Link to="/assets/tableau-connections" className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50">
          <i className="ri-bar-chart-box-line" /> 管理 Tableau 连接
        </Link>
        <Link to="/system/llm-configs" className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50">
          <i className="ri-robot-line" /> 管理 LLM 配置
        </Link>
      </div>

      {/* Tab 筛选 */}
      <div className="flex gap-1 border-b border-slate-100">
        {([['all', '全部'], ['sql_database', '数据库'], ['tableau_site', 'Tableau'], ['llm_provider', 'LLM']] as [TabType, string][]).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === key
                ? 'border-violet-500 text-violet-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {label}
            {key !== 'all' && (
              <span className="ml-1.5 text-xs text-slate-400">
                ({connections.filter(c => c.type === key).length})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* 连接列表 */}
      {loading && (
        <div className="text-center py-12 text-slate-400 text-sm">加载中…</div>
      )}
      {error && (
        <div className="bg-red-50 border border-red-100 text-red-600 text-sm px-4 py-3 rounded-lg">{error}</div>
      )}
      {!loading && !error && filtered.length === 0 && (
        <div className="text-center py-12 text-slate-400 text-sm">暂无连接数据</div>
      )}
      {!loading && !error && filtered.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-100 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-100">
              <tr>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500">名称</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500">类型</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500">状态</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500">健康状态</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {filtered.map(conn => (
                <tr key={conn.id} className="hover:bg-slate-50/50">
                  <td className="px-4 py-3 font-medium text-slate-700">{conn.name}</td>
                  <td className="px-4 py-3 text-slate-500">{TYPE_LABEL[conn.type] ?? conn.type}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${conn.is_active ? 'text-green-600 bg-green-50' : 'text-slate-400 bg-slate-100'}`}>
                      {conn.is_active ? '已启用' : '已停用'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLOR[conn.health_status] ?? STATUS_COLOR.unknown}`}>
                      {STATUS_LABEL[conn.health_status] ?? '未知'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
