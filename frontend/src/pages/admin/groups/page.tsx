import { useState, useEffect } from 'react';
import { ALL_PERMISSIONS } from '../../../context/AuthContext';
import { API_BASE, getAvatarGradient } from '../../../config';

interface Group {
  id: number;
  name: string;
  description: string;
  member_count: number;
  permissions: string[];
  created_at: string;
}

interface User {
  id: number;
  username: string;
  display_name: string;
}

interface PendingPermissionChange {
  groupId: number;
  permissions: string[];
}

export default function GroupsPage() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showMembersModal, setShowMembersModal] = useState(false);
  const [editingGroup, setEditingGroup] = useState<Group | null>(null);
  const [groupMembers, setGroupMembers] = useState<User[]>([]);
  const [newGroup, setNewGroup] = useState({ name: '', description: '', permissions: [] as string[] });
  const [pendingChanges, setPendingChanges] = useState<Map<number, string[]>>(new Map());
  const [hasPendingChanges, setHasPendingChanges] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [message, setMessage] = useState('');

  const fetchGroups = async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/groups/`, { credentials: 'include' });
      if (!resp.ok) throw new Error('获取用户组列表失败');
      const data = await resp.json();
      setGroups(data.groups || []);
    } finally {
      setLoading(false);
    }
  };

  const fetchUsers = async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/permissions/users`, { credentials: 'include' });
      if (!resp.ok) throw new Error('获取用户列表失败');
      const data = await resp.json();
      setUsers(data.users || []);
    } catch (e) { /* silently ignore */ }
  };

  useEffect(() => { fetchGroups(); fetchUsers(); }, []);

  // 暂存权限修改
  const handlePermissionToggle = (groupId: number, permKey: string, currentPerms: string[]) => {
    const newPerms = currentPerms.includes(permKey)
      ? currentPerms.filter(p => p !== permKey)
      : [...currentPerms, permKey];

    setPendingChanges(prev => {
      const newMap = new Map(prev);
      newMap.set(groupId, newPerms);
      return newMap;
    });
    setHasPendingChanges(true);
  };

  // 取消暂存的修改
  const cancelChanges = () => {
    setPendingChanges(new Map());
    setHasPendingChanges(false);
  };

  // 保存所有修改
  const saveChanges = async () => {
    for (const [groupId, permissions] of pendingChanges) {
      const resp = await fetch(`${API_BASE}/api/groups/${groupId}/permissions`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ permissions })
      });
      if (!resp.ok) throw new Error(`更新用户组 ${groupId} 权限失败`);
    }
    setPendingChanges(new Map());
    setHasPendingChanges(false);
    fetchGroups();
  };

  // 获取实际显示的权限（暂存 > 当前）
  const getDisplayPermissions = (group: Group) => {
    if (pendingChanges.has(group.id)) {
      return pendingChanges.get(group.id)!;
    }
    return group.permissions || [];
  };

  const handleCreateGroup = async () => {
    if (!newGroup.name.trim()) { setMessage('请输入组名称'); return; }
    const resp = await fetch(`${API_BASE}/api/groups/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify(newGroup)
    });
    if (resp.ok) { setShowCreateModal(false); setNewGroup({ name: '', description: '', permissions: [] }); fetchGroups(); }
    else { setMessage('创建失败'); }
  };

  const handleDeleteGroup = async (groupId: number) => {
    if (!confirm('确定要删除该用户组吗？')) return;
    const resp = await fetch(`${API_BASE}/api/groups/${groupId}`, { method: 'DELETE', credentials: 'include' });
    if (!resp.ok) throw new Error('删除用户组失败');
    fetchGroups();
  };

  const handleOpenMembers = async (group: Group) => {
    setEditingGroup(group);
    const resp = await fetch(`${API_BASE}/api/groups/${group.id}/members`, { credentials: 'include' });
    if (!resp.ok) throw new Error('获取组成员失败');
    const data = await resp.json();
    setGroupMembers(data.members || []);
    setShowMembersModal(true);
  };

  const handleAddMembers = async (groupId: number, userIds: number[]) => {
    const resp = await fetch(`${API_BASE}/api/groups/${groupId}/members`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ user_ids: userIds })
    });
    if (resp.ok) { const data = await resp.json(); setGroupMembers(data.members || []); fetchGroups(); }
  };

  const handleRemoveMember = async (groupId: number, userId: number) => {
    await fetch(`${API_BASE}/api/groups/${groupId}/members/${userId}`, { method: 'DELETE', credentials: 'include' })
      .then(resp => { if (!resp.ok) throw new Error('移除成员失败'); });
    setGroupMembers(groupMembers.filter(m => m.id !== userId));
    fetchGroups();
  };

  const togglePermission = (permKey: string, perms: string[]) =>
    perms.includes(permKey) ? perms.filter(p => p !== permKey) : [...perms, permKey];

  const getPermissionLabel = (key: string) => {
    const perm = ALL_PERMISSIONS.find(p => p.key === key);
    return perm ? perm.label : key;
  };

  // 获取权限变更状态：'added' | 'removed' | 'unchanged'
  const getPermChangeStatus = (group: Group, permKey: string) => {
    if (!pendingChanges.has(group.id)) return 'unchanged';
    const originalPerms = group.permissions || [];
    const displayPerms = pendingChanges.get(group.id)!;
    const wasInOriginal = originalPerms.includes(permKey);
    const isInDisplay = displayPerms.includes(permKey);
    if (!wasInOriginal && isInDisplay) return 'added';
    if (wasInOriginal && !isInDisplay) return 'removed';
    return 'unchanged';
  };

  // 过滤用户组
  const filteredGroups = groups.filter(g =>
    g.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (g.description || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;

  return (
    <div className="p-6">
      {message && <div className="mb-4 px-4 py-2 bg-amber-50 text-amber-700 border border-amber-200 rounded-lg text-sm">{message}</div>}
      {/* 页面标题栏 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">用户组管理</h1>
          <p className="text-sm text-slate-400 mt-0.5">创建用户组，批量配置权限</p>
        </div>
        <button onClick={() => setShowCreateModal(true)}
          className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800 flex items-center gap-1.5">
          <i className="ri-add-line" /> 创建用户组
        </button>
      </div>

      {/* 搜索栏 */}
      <div className="mb-4">
        <div className="relative max-w-xs">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索用户组..."
            className="w-full pl-9 pr-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      {/* 暂存更改提示栏 */}
      {hasPendingChanges && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <i className="ri-information-line text-blue-600" />
            <span className="text-sm text-blue-700">有 {pendingChanges.size} 个用户组的权限尚未保存</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={cancelChanges}
              className="px-3 py-1.5 text-xs text-slate-600 hover:text-slate-800">
              取消更改
            </button>
            <button onClick={saveChanges}
              className="px-3 py-1.5 text-xs bg-slate-900 text-white rounded-lg hover:bg-slate-800">
              保存更改
            </button>
          </div>
        </div>
      )}

      {/* 用户组列表 */}
      <div className="grid gap-4">
        {filteredGroups.map((group) => {
          const displayPerms = getDisplayPermissions(group);
          const isChanged = pendingChanges.has(group.id);

          return (
            <div key={group.id} className={`bg-white rounded-xl border ${isChanged ? 'border-blue-300 shadow-md' : 'border-slate-200'} p-5`}>
              {/* 头部：组信息 */}
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-600 flex items-center justify-center text-white">
                    <i className="ri-group-line" />
                  </div>
                  <div>
                    <h3 className="text-base font-semibold text-slate-800">{group.name}</h3>
                    <p className="text-sm text-slate-400">{group.description || '暂无描述'}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => handleOpenMembers(group)}
                    className="px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors flex items-center gap-1">
                    <i className="ri-user-line" /> 成员 ({group.member_count})
                  </button>
                  <button onClick={() => handleDeleteGroup(group.id)}
                    className="px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 rounded-lg transition-colors flex items-center gap-1">
                    <i className="ri-delete-bin-line" /> 删除
                  </button>
                </div>
              </div>

              {/* 成员预览 */}
              {group.member_count > 0 ? (
                <div className="mb-4">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-slate-500">成员：</span>
                    {groupMembers.filter(m => true).slice(0, 5).map(member => (
                      <span key={member.id} className="inline-flex items-center px-2 py-0.5 bg-slate-100 rounded-full text-xs text-slate-600">
                        {member.display_name}
                      </span>
                    ))}
                    {group.member_count > 5 && (
                      <span className="text-xs text-slate-400">+{group.member_count - 5} 人</span>
                    )}
                  </div>
                </div>
              ) : (
                <div className="mb-4 text-xs text-slate-400">暂无成员</div>
              )}

              {/* 权限标签 - 可折叠 */}
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-medium text-slate-500">组权限：</span>
                  {isChanged && <span className="text-xs text-blue-600">(已修改)</span>}
                </div>
                <div className="flex flex-wrap gap-2">
                  {ALL_PERMISSIONS.map((perm) => {
                    const hasPerm = displayPerms.includes(perm.key);
                    const changeStatus = getPermChangeStatus(group, perm.key);
                    return (
                      <button key={perm.key}
                        onClick={() => handlePermissionToggle(group.id, perm.key, displayPerms)}
                        className={`px-3 py-1.5 text-xs rounded-full transition-colors ${
                          hasPerm
                            ? changeStatus === 'added'
                              ? 'bg-blue-500 text-white border-2 border-blue-600 shadow-sm shadow-blue-200'
                              : changeStatus === 'removed'
                                ? 'bg-red-100 text-red-700 border-2 border-red-400 line-through'
                                : 'bg-emerald-100 text-emerald-700 border border-emerald-200'
                            : changeStatus === 'removed'
                              ? 'bg-red-50 text-red-400 border-2 border-red-300 line-through'
                              : 'bg-slate-100 text-slate-500 border border-slate-200 hover:bg-slate-200'
                        }`}>
                        {hasPerm ? '✓' : '+'} {perm.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          );
        })}

        {filteredGroups.length === 0 && (
          <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
            <i className="ri-group-line text-5xl text-slate-200 mb-4 block" />
            <p className="text-slate-500 mb-4">{searchQuery ? '未找到匹配的用户组' : '暂无用户组'}</p>
            {!searchQuery && (
              <button onClick={() => setShowCreateModal(true)}
                className="px-4 py-2 bg-slate-900 text-white text-sm rounded-lg hover:bg-slate-800">
                创建第一个用户组
              </button>
            )}
          </div>
        )}
      </div>

      {/* 创建用户组弹窗 */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-semibold text-slate-800 mb-4">创建用户组</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">组名称 <span className="text-red-500">*</span></label>
                <input type="text" value={newGroup.name}
                  onChange={(e) => setNewGroup({ ...newGroup, name: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="如：数据分析师" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">描述</label>
                <input type="text" value={newGroup.description}
                  onChange={(e) => setNewGroup({ ...newGroup, description: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="可选描述" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-2">初始权限</label>
                <div className="flex flex-wrap gap-2">
                  {ALL_PERMISSIONS.map((perm) => (
                    <button key={perm.key}
                      onClick={() => setNewGroup({ ...newGroup, permissions: togglePermission(perm.key, newGroup.permissions) })}
                      className={`px-3 py-1.5 text-xs rounded-full transition-colors ${newGroup.permissions.includes(perm.key) ? 'bg-emerald-100 text-emerald-700 border border-emerald-200' : 'bg-slate-100 text-slate-500 border border-slate-200 hover:bg-slate-200'}`}>
                      {newGroup.permissions.includes(perm.key) ? '✓' : '+'} {perm.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => { setShowCreateModal(false); setNewGroup({ name: '', description: '', permissions: [] }); }}
                className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700">取消</button>
              <button onClick={handleCreateGroup}
                className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800">创建</button>
            </div>
          </div>
        </div>
      )}

      {/* 成员管理弹窗 */}
      {showMembersModal && editingGroup && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-semibold text-slate-800 mb-1">组成员管理</h2>
            <p className="text-sm text-slate-500 mb-4">{editingGroup.name}</p>

            <div className="mb-4">
              <h4 className="text-xs font-semibold text-slate-400 uppercase mb-2">当前成员 ({groupMembers.length})</h4>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {groupMembers.map((member) => (
                  <div key={member.id} className="flex items-center justify-between px-3 py-2 bg-slate-50 rounded-lg">
                    <div className="flex items-center gap-2">
                      <div className={`w-6 h-6 rounded-full bg-gradient-to-br ${getAvatarGradient(member.username)} flex items-center justify-center text-white text-xs font-medium`}>
                        {member.display_name.charAt(0)}
                      </div>
                      <span className="text-sm font-medium text-slate-700">{member.display_name}</span>
                      <span className="text-xs text-slate-400">@{member.username}</span>
                    </div>
                    <button onClick={() => handleRemoveMember(editingGroup.id, member.id)}
                      className="text-xs text-red-600 hover:text-red-800">移除</button>
                  </div>
                ))}
                {groupMembers.length === 0 && <p className="text-sm text-slate-400 text-center py-4">暂无成员</p>}
              </div>
            </div>

            <div>
              <h4 className="text-xs font-semibold text-slate-400 uppercase mb-2">添加成员</h4>
              <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
                {users.filter(u => !groupMembers.find(m => m.id === u.id)).map((user) => (
                  <button key={user.id}
                    onClick={() => { handleAddMembers(editingGroup.id, [user.id]); setGroupMembers([...groupMembers, user]); }}
                    className="px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 rounded-full transition-colors">
                    + {user.display_name}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex justify-end mt-6">
              <button onClick={() => { setShowMembersModal(false); setEditingGroup(null); setGroupMembers([]); }}
                className="px-4 py-2 bg-slate-800 text-white text-sm rounded-lg hover:bg-slate-700">完成</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
