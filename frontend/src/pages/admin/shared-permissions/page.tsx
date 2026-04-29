/**
 * 共享权限巡检页面（Spec 11 §4.2）
 * 
 * 功能：
 * - 用户/组维度展示共享的语义表/datasource 权限列表
 * - 字段：grantee / resource_type / resource_name / permission_level / granted_by / expires_at
 * - 批量撤销按钮
 * - 过期权限高亮提示（warning 颜色）
 */
import { useState, useEffect } from 'react';
import { API_BASE } from '../../../config';

interface SharedPermission {
  id: number;
  grantee_type: 'user' | 'group';
  grantee_id: number;
  grantee_name: string;
  resource_type: string;
  resource_id: string;
  resource_name: string;
  permission_level: 'read' | 'write' | 'admin';
  granted_by: number;
  granted_by_name: string;
  granted_at: string;
  expires_at: string | null;
  is_expired: boolean;
}

interface User {
  id: number;
  username: string;
  display_name: string;
}

interface Group {
  id: number;
  name: string;
}

type FilterMode = 'all' | 'user' | 'group';

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  semantic_table: '语义表',
  datasource: '数据源',
  workbook: '工作簿',
  dashboard: '仪表板',
};

const PERMISSION_LEVEL_LABELS: Record<string, string> = {
  read: '读取',
  write: '写入',
  admin: '管理',
};

export default function SharedPermissionsPage() {
  const [permissions, setPermissions] = useState<SharedPermission[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [filterMode, setFilterMode] = useState<FilterMode>('all');
  const [filterId, setFilterId] = useState<number | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => { fetchData(); }, [filterMode, filterId]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterMode === 'user' && filterId) {
        params.set('filter_by_user', String(filterId));
      } else if (filterMode === 'group' && filterId) {
        params.set('filter_by_group', String(filterId));
      }

      const [permResp, usersResp, groupsResp] = await Promise.all([
        fetch(`${API_BASE}/api/permissions/shared?${params}`, { credentials: 'include' }),
        fetch(`${API_BASE}/api/permissions/users`, { credentials: 'include' }),
        fetch(`${API_BASE}/api/permissions/groups`, { credentials: 'include' }),
      ]);

      const permData = await permResp.json();
      const usersData = await usersResp.json();
      const groupsData = await groupsResp.json();

      setPermissions(permData.permissions || []);
      setUsers(usersData.users || []);
      setGroups(groupsData.groups || []);
    } catch (e) {
      console.error('Failed to fetch shared permissions:', e);
    } finally {
      setLoading(false);
    }
  };

  const toggleSelect = (id: number) => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === permissions.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(permissions.map(p => p.id)));
    }
  };

  const handleBatchRevoke = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`确认撤销选中的 ${selectedIds.size} 条权限？`)) return;

    setRevoking(true);
    setMessage(null);
    try {
      const resp = await fetch(`${API_BASE}/api/permissions/shared/batch`, {
        method: 'DELETE',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ permission_ids: Array.from(selectedIds) }),
      });
      const data = await resp.json();
      if (resp.ok) {
        setMessage({ type: 'success', text: `已撤销 ${data.deleted} 条权限` });
        setSelectedIds(new Set());
        fetchData();
      } else {
        setMessage({ type: 'error', text: data.detail || '撤销失败' });
      }
    } catch (e) {
      setMessage({ type: 'error', text: '网络错误' });
    } finally {
      setRevoking(false);
    }
  };

  const getFilterOptions = () => {
    if (filterMode === 'user') {
      return users.map(u => ({ id: u.id, label: u.display_name || u.username }));
    }
    if (filterMode === 'group') {
      return groups.map(g => ({ id: g.id, label: g.name }));
    }
    return [];
  };

  return (
    <div className="p-6">
      {/* 页面标题栏 */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-slate-800">共享权限巡检</h1>
        <p className="text-sm text-slate-400 mt-0.5">查看和管理资源共享权限（语义表 / 数据源）</p>
      </div>

      {/* 消息提示 */}
      {message && (
        <div className={`mb-4 px-4 py-3 rounded-lg text-sm ${message.type === 'success' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
          {message.text}
        </div>
      )}

      {/* 筛选器 */}
      <div className="flex items-center gap-4 mb-4">
        <div className="flex items-center gap-2">
          <label className="text-sm text-slate-600">筛选：</label>
          <select
            className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={filterMode}
            onChange={e => { setFilterMode(e.target.value as FilterMode); setFilterId(null); }}
          >
            <option value="all">全部</option>
            <option value="user">按用户</option>
            <option value="group">按用户组</option>
          </select>

          {filterMode !== 'all' && (
            <select
              className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={filterId ?? ''}
              onChange={e => setFilterId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">请选择</option>
              {getFilterOptions().map(opt => (
                <option key={opt.id} value={opt.id}>{opt.label}</option>
              ))}
            </select>
          )}
        </div>

        <div className="ml-auto flex items-center gap-2">
          {selectedIds.size > 0 && (
            <button
              onClick={handleBatchRevoke}
              disabled={revoking}
              className="px-4 py-1.5 text-sm bg-red-50 text-red-600 border border-red-200 rounded-lg hover:bg-red-100 disabled:opacity-50 transition-colors"
            >
              {revoking ? '撤销中...' : `批量撤销 (${selectedIds.size})`}
            </button>
          )}
        </div>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 flex items-center justify-center bg-blue-100 rounded-lg">
              <i className="ri-file-list-2-line text-blue-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-800">{permissions.length}</div>
              <div className="text-xs text-slate-500">共享权限总数</div>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 flex items-center justify-center bg-amber-100 rounded-lg">
              <i className="ri-time-line text-amber-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-800">
                {permissions.filter(p => p.is_expired).length}
              </div>
              <div className="text-xs text-slate-500">已过期</div>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 flex items-center justify-center bg-emerald-100 rounded-lg">
              <i className="ri-user-follow-line text-emerald-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-800">
                {new Set(permissions.map(p => `${p.grantee_type}:${p.grantee_id}`)).size}
              </div>
              <div className="text-xs text-slate-500">被授权主体</div>
            </div>
          </div>
        </div>
      </div>

      {/* 权限列表 */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-slate-400">加载中...</div>
        ) : permissions.length === 0 ? (
          <div className="p-8 text-center text-slate-400">暂无共享权限</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="px-4 py-3 text-left">
                  <input
                    type="checkbox"
                    checked={selectedIds.size === permissions.length && permissions.length > 0}
                    onChange={toggleSelectAll}
                    className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                  />
                </th>
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">授权对象</th>
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">资源类型</th>
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">资源名称</th>
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">权限级别</th>
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">授予人</th>
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">过期时间</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {permissions.map((perm) => (
                <tr
                  key={perm.id}
                  className={`hover:bg-slate-50/50 ${perm.is_expired ? 'bg-amber-50/30' : ''}`}
                >
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(perm.id)}
                      onChange={() => toggleSelect(perm.id)}
                      className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className={`inline-flex items-center px-2 py-0.5 text-xs rounded-full ${
                        perm.grantee_type === 'user'
                          ? 'bg-blue-50 text-blue-700'
                          : 'bg-purple-50 text-purple-700'
                      }`}>
                        <i className={`ri-${perm.grantee_type === 'user' ? 'user' : 'group'}-line mr-1`} />
                        {perm.grantee_type === 'user' ? '用户' : '组'}
                      </span>
                      <span className="text-sm text-slate-700 font-medium">{perm.grantee_name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center px-2 py-0.5 text-xs bg-slate-100 text-slate-600 rounded">
                      {RESOURCE_TYPE_LABELS[perm.resource_type] || perm.resource_type}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-slate-700">{perm.resource_name}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center px-2 py-0.5 text-xs rounded-full ${
                      perm.permission_level === 'admin'
                        ? 'bg-red-50 text-red-700'
                        : perm.permission_level === 'write'
                        ? 'bg-blue-50 text-blue-700'
                        : 'bg-emerald-50 text-emerald-700'
                    }`}>
                      {PERMISSION_LEVEL_LABELS[perm.permission_level] || perm.permission_level}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-slate-600">{perm.granted_by_name}</span>
                  </td>
                  <td className="px-4 py-3">
                    {perm.is_expired ? (
                      <span className="inline-flex items-center gap-1 text-xs text-amber-600 font-medium">
                        <i className="ri-error-warning-line" />
                        已过期 {perm.expires_at}
                      </span>
                    ) : perm.expires_at ? (
                      <span className="text-xs text-slate-400">{perm.expires_at}</span>
                    ) : (
                      <span className="text-xs text-slate-400">永不过期</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 过期权限说明 */}
      {permissions.some(p => p.is_expired) && (
        <div className="mt-4 flex items-center gap-2 text-xs text-amber-600">
          <i className="ri-error-warning-line" />
          <span>标黄的行表示权限已过期，建议及时清理或更新</span>
        </div>
      )}
    </div>
  );
}
