import { useState, useEffect } from 'react';
import { ALL_PERMISSIONS, ROLE_DEFAULT_PERMISSIONS } from '../../../context/AuthContext';
import { API_BASE, getAvatarGradient } from '../../../config';

type UserRole = 'admin' | 'data_admin' | 'analyst' | 'user';

interface User {
  id: number;
  username: string;
  display_name: string;
  email: string | null;
  role: UserRole;
  permissions: string[];
  group_ids: number[];
  group_names: string[];
  is_active: boolean;
  created_at: string;
  last_login: string | null;
}

const ROLES: { key: UserRole; label: string }[] = [
  { key: 'admin', label: '管理员' },
  { key: 'data_admin', label: '数据管理员' },
  { key: 'analyst', label: '业务分析师' },
  { key: 'user', label: '普通用户' },
];

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return '从未登录';
  const date = new Date(dateStr.replace(' ', 'T'));
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (seconds < 60) return '刚刚';
  if (minutes < 60) return `${minutes}分钟前`;
  if (hours < 24) return `${hours}小时前`;
  if (days < 30) return `${days}天前`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}个月前`;
  return dateStr;
}

export default function UserManagementPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive'>('all');
  const [selectedUsers, setSelectedUsers] = useState<Set<number>>(new Set());
  const [showModal, setShowModal] = useState(false);
  const [showPermModal, setShowPermModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [newUser, setNewUser] = useState<{
    username: string;
    display_name: string;
    password: string;
    confirm_password: string;
    email: string;
    role: UserRole;
  }>({
    username: '',
    display_name: '',
    password: '',
    confirm_password: '',
    email: '',
    role: 'user'
  });
  const [editUserData, setEditUserData] = useState({ display_name: '', email: '' });
  const [formError, setFormError] = useState('');
  const [message, setMessage] = useState('');

  const fetchUsers = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/users/`, { credentials: 'include' });
      if (response.ok) {
        const data = await response.json();
        setUsers(data.users || []);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchUsers(); }, []);

  // 筛选用户
  const filteredUsers = users.filter(user => {
    const matchSearch = user.username.toLowerCase().includes(search.toLowerCase()) ||
                        user.display_name.toLowerCase().includes(search.toLowerCase()) ||
                        (user.email && user.email.toLowerCase().includes(search.toLowerCase()));
    const matchStatus = statusFilter === 'all' ||
                        (statusFilter === 'active' && user.is_active) ||
                        (statusFilter === 'inactive' && !user.is_active);
    return matchSearch && matchStatus;
  });

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedUsers.size === filteredUsers.length) {
      setSelectedUsers(new Set());
    } else {
      setSelectedUsers(new Set(filteredUsers.map(u => u.id)));
    }
  };

  const toggleSelect = (id: number) => {
    const newSet = new Set(selectedUsers);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedUsers(newSet);
  };

  // 批量启用
  const handleBulkEnable = async () => {
    for (const id of selectedUsers) {
      const user = users.find(u => u.id === id);
      if (user && !user.is_active) {
        const resp = await fetch(`${API_BASE}/api/users/${id}/toggle-active`, { method: 'PUT', credentials: 'include' });
        if (!resp.ok) throw new Error(`启用用户 ${id} 失败`);
      }
    }
    setSelectedUsers(new Set());
    fetchUsers();
  };

  // 批量禁用
  const handleBulkDisable = async () => {
    for (const id of selectedUsers) {
      const user = users.find(u => u.id === id);
      if (user && user.is_active) {
        const resp = await fetch(`${API_BASE}/api/users/${id}/toggle-active`, { method: 'PUT', credentials: 'include' });
        if (!resp.ok) throw new Error(`禁用用户 ${id} 失败`);
      }
    }
    setSelectedUsers(new Set());
    fetchUsers();
  };

  // 批量删除
  const handleBulkDelete = async () => {
    if (!confirm(`确定要删除 ${selectedUsers.size} 个用户吗？`)) return;
    for (const id of selectedUsers) {
      const resp = await fetch(`${API_BASE}/api/users/${id}`, { method: 'DELETE', credentials: 'include' });
      if (!resp.ok) throw new Error(`删除用户 ${id} 失败`);
    }
    setSelectedUsers(new Set());
    fetchUsers();
  };

  const resetForm = () => {
    setNewUser({ username: '', display_name: '', password: '', confirm_password: '', email: '', role: 'user' });
    setFormError('');
  };

  const handleCreateUser = async () => {
    if (!newUser.username.trim()) { setFormError('请输入用户名'); return; }
    if (!newUser.display_name.trim()) { setFormError('请输入显示名称'); return; }
    if (!newUser.password) { setFormError('请输入密码'); return; }
    if (newUser.password !== newUser.confirm_password) { setFormError('两次输入的密码不一致'); return; }
    if (newUser.password.length < 6) { setFormError('密码长度至少为6位'); return; }

    const response = await fetch(`${API_BASE}/api/users/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username: newUser.username, display_name: newUser.display_name, password: newUser.password, email: newUser.email || null, role: newUser.role })
    });

    if (response.ok) {
      setShowModal(false);
      resetForm();
      fetchUsers();
    } else {
      const error = await response.json();
      setFormError(error.detail || '创建失败');
    }
  };

  const handleToggleActive = async (userId: number) => {
    const response = await fetch(`${API_BASE}/api/users/${userId}/toggle-active`, { method: 'PUT', credentials: 'include' });
    if (!response.ok) throw new Error('切换用户状态失败');
    fetchUsers();
  };

  const handleUpdateRole = async (userId: number, role: string) => {
    const response = await fetch(`${API_BASE}/api/users/${userId}/role`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ role }) });
    if (!response.ok) throw new Error('更新用户角色失败');
    fetchUsers();
  };

  const handleDeleteUser = async (userId: number) => {
    if (!confirm('确定要删除该用户吗？')) return;
    const response = await fetch(`${API_BASE}/api/users/${userId}`, { method: 'DELETE', credentials: 'include' });
    if (!response.ok) throw new Error('删除用户失败');
    fetchUsers();
  };

  // 打开编辑弹窗
  const openEditModal = (user: User) => {
    setEditingUser(user);
    setEditUserData({ display_name: user.display_name, email: user.email || '' });
    setShowEditModal(true);
  };

  // 保存编辑
  const handleSaveEdit = async () => {
    if (!editingUser) return;
    const response = await fetch(`${API_BASE}/api/users/${editingUser.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ display_name: editUserData.display_name, email: editUserData.email || null })
    });
    if (response.ok) {
      setShowEditModal(false);
      setEditingUser(null);
      fetchUsers();
    } else {
      setMessage('更新失败');
    }
  };

  const openPermissionModal = (user: User) => {
    if (user.role === 'admin') { setMessage('管理员拥有所有权限，无需编辑'); return; }
    setEditingUser(user);
    setShowPermModal(true);
  };

  const handleUpdatePermissions = async (permissions: string[]) => {
    if (!editingUser) return;
    const response = await fetch(`${API_BASE}/api/users/${editingUser.id}/permissions`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ permissions })
    });
    if (response.ok) { setShowPermModal(false); setEditingUser(null); fetchUsers(); }
    else { setMessage('更新失败'); }
  };

  const handleTogglePermission = (permKey: string, currentPerms: string[]) =>
    currentPerms.includes(permKey) ? currentPerms.filter(p => p !== permKey) : [...currentPerms, permKey];

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;

  return (
    <div className="p-6">
      {message && <div className="mb-4 px-4 py-2 bg-amber-50 text-amber-700 border border-amber-200 rounded-lg text-sm">{message}</div>}
      {/* 页面标题栏 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">用户管理</h1>
          <p className="text-sm text-slate-400 mt-0.5">管理平台用户账号和权限</p>
        </div>
        <button onClick={() => { resetForm(); setShowModal(true); }}
          className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800 flex items-center gap-1.5">
          <i className="ri-add-line" /> 创建用户
        </button>
      </div>

      {/* 搜索和筛选 */}
      <div className="bg-white rounded-xl border border-slate-200 p-4 mb-4">
        <div className="flex items-center gap-4">
          {/* 搜索框 */}
          <div className="relative flex-1 max-w-xs">
            <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input type="text" placeholder="搜索用户名称或邮箱..."
              value={search} onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9 pr-4 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500" />
          </div>

          {/* 状态筛选 */}
          <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
            {(['all', 'active', 'inactive'] as const).map(status => (
              <button key={status}
                onClick={() => setStatusFilter(status)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  statusFilter === status ? 'bg-white text-slate-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                }`}>
                {status === 'all' ? '全部' : status === 'active' ? '启用' : '禁用'}
              </button>
            ))}
          </div>

          {/* 批量操作 */}
          {selectedUsers.size > 0 && (
            <div className="flex items-center gap-2 ml-auto">
              <span className="text-sm text-slate-500">已选择 {selectedUsers.size} 项</span>
              <button onClick={handleBulkEnable} className="px-3 py-1.5 text-xs bg-emerald-100 text-emerald-700 rounded-lg hover:bg-emerald-200">
                批量启用
              </button>
              <button onClick={handleBulkDisable} className="px-3 py-1.5 text-xs bg-orange-100 text-orange-700 rounded-lg hover:bg-orange-200">
                批量禁用
              </button>
              <button onClick={handleBulkDelete} className="px-3 py-1.5 text-xs bg-red-100 text-red-700 rounded-lg hover:bg-red-200">
                批量删除
              </button>
            </div>
          )}
        </div>
      </div>

      {/* 用户表格 */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="w-10 px-4 py-3">
                <input type="checkbox" checked={selectedUsers.size === filteredUsers.length && filteredUsers.length > 0}
                  onChange={toggleSelectAll} className="w-4 h-4 rounded border-slate-300" />
              </th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">用户</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">用户组</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">权限</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">角色</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">状态</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">上次登录</th>
              <th className="text-right text-xs font-semibold text-slate-500 uppercase px-4 py-3">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filteredUsers.map((user) => (
              <tr key={user.id} className={`hover:bg-slate-50/50 ${selectedUsers.has(user.id) ? 'bg-blue-50/30' : ''}`}>
                <td className="px-4 py-3">
                  <input type="checkbox" checked={selectedUsers.has(user.id)}
                    onChange={() => toggleSelect(user.id)} className="w-4 h-4 rounded border-slate-300" />
                </td>
                <td className="px-4 py-4">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-full bg-gradient-to-br ${getAvatarGradient(user.username)} flex items-center justify-center text-white text-sm font-semibold`}>
                      {user.display_name.charAt(0)}
                    </div>
                    <div>
                      <div className="text-base font-semibold text-slate-800">{user.display_name}</div>
                      <div className="text-xs text-slate-400">{user.email || '@' + user.username}</div>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {user.group_names && user.group_names.length > 0 ? (
                      user.group_names.map((name, i) => (
                        <span key={i} className="text-xs px-2 py-0.5 bg-slate-100 text-slate-600 rounded-full">{name}</span>
                      ))
                    ) : (
                      <span className="text-xs text-slate-400">-</span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <button onClick={() => openPermissionModal(user)}
                    className={`flex items-center gap-1 px-2 py-1 text-xs rounded-lg transition-colors ${user.role === 'admin' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-50 hover:bg-slate-100 text-slate-500'}`}>
                    <i className="ri-shield-line text-[10px]" />
                    {user.role === 'admin' ? '全部' : `${user.permissions?.length || 0}`}
                  </button>
                </td>
                <td className="px-4 py-3">
                  <select value={user.role} onChange={(e) => handleUpdateRole(user.id, e.target.value)}
                    className="text-xs border border-slate-200 rounded-lg px-2 py-1 bg-white">
                    {ROLES.map(r => (
                      <option key={r.key} value={r.key}>{r.label}</option>
                    ))}
                  </select>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs font-medium px-2 py-1 rounded-full ${user.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>
                    {user.is_active ? '启用' : '禁用'}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className="text-xs text-slate-400">{formatRelativeTime(user.last_login)}</span>
                </td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => openEditModal(user)} className="text-xs text-blue-600 hover:text-blue-800 mr-2">
                    编辑
                  </button>
                  <button onClick={() => handleToggleActive(user.id)} className="text-xs text-orange-600 hover:text-orange-800 mr-2">
                    {user.is_active ? '禁用' : '启用'}
                  </button>
                  <button onClick={() => handleDeleteUser(user.id)} className="text-xs text-red-600 hover:text-red-800">
                    删除
                  </button>
                </td>
              </tr>
            ))}
            {filteredUsers.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-slate-400">
                  <i className="ri-user-line text-3xl mb-2 block" />
                  {search || statusFilter !== 'all' ? '未找到匹配的用户' : '暂无用户'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 创建用户弹窗 */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-semibold text-slate-800 mb-4">创建新用户</h2>
            <div className="space-y-4">
              {formError && <div className="bg-red-50 border border-red-200 text-red-600 text-sm px-4 py-3 rounded-lg">{formError}</div>}
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">用户名 <span className="text-red-500">*</span></label>
                <input type="text" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500" placeholder="用于登录" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">显示名称 <span className="text-red-500">*</span></label>
                <input type="text" value={newUser.display_name} onChange={(e) => setNewUser({ ...newUser, display_name: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500" placeholder="显示名称" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">密码 <span className="text-red-500">*</span></label>
                <input type="password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500" placeholder="至少6位" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">确认密码 <span className="text-red-500">*</span></label>
                <input type="password" value={newUser.confirm_password} onChange={(e) => setNewUser({ ...newUser, confirm_password: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500" placeholder="再次输入密码" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">电子邮件 <span className="text-slate-400">(可选)</span></label>
                <input type="email" value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500" placeholder="example@company.com" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">角色</label>
                <select value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500">
                  {ROLES.map(r => (
                    <option key={r.key} value={r.key}>{r.label}</option>
                  ))}
                </select>
                <p className="text-xs text-slate-400 mt-1">
                  预设权限：{(ROLE_DEFAULT_PERMISSIONS[newUser.role] || []).length > 0
                    ? (ROLE_DEFAULT_PERMISSIONS[newUser.role] || []).map(k => ALL_PERMISSIONS.find(p => p.key === k)?.label || k).join('、')
                    : '无默认权限，可后续手动分配'}
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowModal(false)} className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700">取消</button>
              <button onClick={handleCreateUser} className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800">创建</button>
            </div>
          </div>
        </div>
      )}

      {/* 编辑用户弹窗 */}
      {showEditModal && editingUser && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-semibold text-slate-800 mb-1">编辑用户</h2>
            <p className="text-sm text-slate-500 mb-4">@{editingUser.username}</p>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">显示名称</label>
                <input type="text" value={editUserData.display_name}
                  onChange={(e) => setEditUserData({ ...editUserData, display_name: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">电子邮件 <span className="text-slate-400">(可选)</span></label>
                <input type="email" value={editUserData.email}
                  onChange={(e) => setEditUserData({ ...editUserData, email: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500" placeholder="example@company.com" />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => { setShowEditModal(false); setEditingUser(null); }}
                className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700">取消</button>
              <button onClick={handleSaveEdit}
                className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800">保存</button>
            </div>
          </div>
        </div>
      )}

      {/* 权限配置弹窗 */}
      {showPermModal && editingUser && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-semibold text-slate-800 mb-1">配置权限</h2>
            <p className="text-sm text-slate-500 mb-4">{editingUser.display_name} (@{editingUser.username})</p>
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {ALL_PERMISSIONS.map((perm) => {
                const isChecked = editingUser.permissions?.includes(perm.key);
                return (
                  <label key={perm.key} className="flex items-center gap-3 px-3 py-2.5 bg-slate-50 hover:bg-slate-100 rounded-lg cursor-pointer transition-colors">
                    <input type="checkbox" checked={isChecked}
                      onChange={() => {
                        const newPerms = handleTogglePermission(perm.key, editingUser.permissions || []);
                        setEditingUser({ ...editingUser, permissions: newPerms });
                      }}
                      className="w-4 h-4 text-blue-600 rounded border-slate-300" />
                    <div className="flex-1">
                      <span className="text-sm font-medium text-slate-700">{perm.label}</span>
                      <span className="text-xs text-slate-400 ml-2">{perm.key}</span>
                    </div>
                  </label>
                );
              })}
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => { setShowPermModal(false); setEditingUser(null); }}
                className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700">取消</button>
              <button onClick={() => handleUpdatePermissions(editingUser.permissions || [])}
                className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800">保存</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
