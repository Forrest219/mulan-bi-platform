import { useState, useEffect } from 'react';
import { ALL_PERMISSIONS } from '../../../context/AuthContext';
import { API_BASE } from '../../../config';

interface User {
  id: number;
  username: string;
  display_name: string;
  role: string;
  permissions: string[];
  group_ids: number[];
  group_names: string[];
  tag_emoji: string;
}

interface Group {
  id: number;
  name: string;
  permissions: string[];
  member_count: number;
}

export default function PermissionsPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    try {
      const [usersResp, groupsResp] = await Promise.all([
        fetch(`${API_BASE}/api/permissions/users`, { credentials: 'include' }),
        fetch(`${API_BASE}/api/permissions/groups`, { credentials: 'include' })
      ]);
      const usersData = await usersResp.json();
      const groupsData = await groupsResp.json();
      setUsers(usersData.users || []);
      setGroups(groupsData.groups || []);
    } finally {
      setLoading(false);
    }
  };

  // 过滤掉管理员
  const normalUsers = users.filter(u => u.role !== 'admin');

  // 分离：组用户（通过组获得权限）vs 独立权限用户
  const groupInheritedUsers = normalUsers.filter(u => u.group_ids && u.group_ids.length > 0);
  const independentUsers = normalUsers.filter(u => !u.group_ids || u.group_ids.length === 0);

  // 获取用户最终权限
  const getUserEffectivePermissions = (user: User) => {
    return user.permissions || [];
  };

  // 检查用户是否有某权限
  const userHasPermission = (user: User, permKey: string) => {
    return getUserEffectivePermissions(user).includes(permKey);
  };

  // 检查组是否有某权限
  const groupHasPermission = (group: Group, permKey: string) => {
    return group.permissions && group.permissions.includes(permKey);
  };

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;

  return (
    <div className="p-6">
      {/* 页面标题栏 */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-slate-800">权限总览</h1>
        <p className="text-sm text-slate-400 mt-0.5">查看各模块权限的用户和组分布</p>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 flex items-center justify-center bg-emerald-100 rounded-lg">
              <i className="ri-group-line text-emerald-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-800">{groups.length}</div>
              <div className="text-xs text-slate-500">用户组</div>
            </div>
          </div>
          <div className="text-xs text-slate-400 mt-2">共 {groups.reduce((acc, g) => acc + (g.member_count || 0), 0)} 位成员</div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 flex items-center justify-center bg-blue-100 rounded-lg">
              <i className="ri-user-follow-line text-blue-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-800">{groupInheritedUsers.length}</div>
              <div className="text-xs text-slate-500">组用户</div>
            </div>
          </div>
          <div className="text-xs text-slate-400 mt-2">通过用户组获得权限</div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 flex items-center justify-center bg-purple-100 rounded-lg">
              <i className="ri-user-settings-line text-purple-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-800">{independentUsers.length}</div>
              <div className="text-xs text-slate-500">独立用户</div>
            </div>
          </div>
          <div className="text-xs text-slate-400 mt-2">直接配置权限</div>
        </div>
      </div>

      {/* 权限矩阵 */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3 w-40">权限模块</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">用户组</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">组用户</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">独立用户</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {ALL_PERMISSIONS.map((perm) => {
              const groupsWithPerm = groups.filter(g => groupHasPermission(g, perm.key));
              const usersWithPermFromGroups = groupInheritedUsers.filter(u => userHasPermission(u, perm.key));
              const usersWithPermIndependent = independentUsers.filter(u => userHasPermission(u, perm.key));

              return (
                <tr key={perm.key} className="hover:bg-slate-50/50">
                  <td className="px-4 py-4">
                    <div className="flex items-center gap-2.5">
                      <span className={`w-2 h-2 rounded-full ${groupsWithPerm.length > 0 || usersWithPermFromGroups.length > 0 || usersWithPermIndependent.length > 0 ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                      <span className="text-sm font-medium text-slate-700">{perm.label}</span>
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <div className="flex flex-wrap gap-1.5">
                      {groupsWithPerm.length > 0 ? groupsWithPerm.map((group) => (
                        <span key={group.id}
                          className="inline-flex items-center px-2 py-1 text-xs bg-emerald-50 text-emerald-700 rounded-full">
                          <i className="ri-group-line mr-1" />{group.name}
                        </span>
                      )) : <span className="text-xs text-slate-400">-</span>}
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <div className="flex flex-wrap gap-1.5">
                      {usersWithPermFromGroups.length > 0 ? usersWithPermFromGroups.map((user) => (
                        <span key={user.id}
                          className="inline-flex items-center px-2 py-1 text-xs bg-blue-50 text-blue-700 rounded-full"
                          title={`属于: ${user.group_names?.join(', ')}`}>
                          {user.tag_emoji} {user.display_name}
                        </span>
                      )) : <span className="text-xs text-slate-400">-</span>}
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <div className="flex flex-wrap gap-1.5">
                      {usersWithPermIndependent.length > 0 ? usersWithPermIndependent.map((user) => (
                        <span key={user.id}
                          className="inline-flex items-center px-2 py-1 text-xs bg-purple-50 text-purple-700 rounded-full">
                          {user.tag_emoji} {user.display_name}
                        </span>
                      )) : <span className="text-xs text-slate-400">-</span>}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
