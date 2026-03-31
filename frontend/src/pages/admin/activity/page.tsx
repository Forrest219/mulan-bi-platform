import { useState, useEffect } from 'react';
import { API_BASE, getAvatarGradient } from '../../../config';

interface User {
  id: number;
  username: string;
  display_name: string;
  tag: string;
  tag_emoji: string;
  tag_color: string;
  days_since_login: number;
}

interface Log {
  id: number;
  op_time: string;
  operator: string;
  operation_type: string;
  target: string;
  status: string;
  details: string;
}

type TimeRange = '7d' | '30d' | 'all';
type OpType = 'all' | 'login' | 'logout' | 'other';

export default function ActivityPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [logs, setLogs] = useState<Log[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState<TimeRange>('7d');
  const [opTypeFilter, setOpTypeFilter] = useState<OpType>('all');

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    try {
      const [usersResp, logsResp, statsResp] = await Promise.all([
        fetch(`${API_BASE}/api/permissions/users`, { credentials: 'include' }),
        fetch(`${API_BASE}/api/activity/logs?limit=100`, { credentials: 'include' }),
        fetch(`${API_BASE}/api/activity/stats`, { credentials: 'include' })
      ]);
      const usersData = await usersResp.json();
      const logsData = await logsResp.json();
      const statsData = await statsResp.json();
      setUsers(usersData.users || []);
      setLogs(logsData.logs || []);
      setStats(statsData);
    } finally {
      setLoading(false);
    }
  };

  // 筛选日志
  const filteredLogs = logs.filter(log => {
    // 操作类型筛选
    if (opTypeFilter !== 'all') {
      if (opTypeFilter === 'login' && log.operation_type !== 'login') return false;
      if (opTypeFilter === 'logout' && log.operation_type !== 'logout') return false;
      if (opTypeFilter === 'other' && (log.operation_type === 'login' || log.operation_type === 'logout')) return false;
    }

    // 时间范围筛选
    if (timeRange !== 'all') {
      const logDate = new Date(log.op_time.replace(' ', 'T'));
      const now = new Date();
      const diffDays = Math.floor((now.getTime() - logDate.getTime()) / (1000 * 60 * 60 * 24));
      if (timeRange === '7d' && diffDays > 7) return false;
      if (timeRange === '30d' && diffDays > 30) return false;
    }

    return true;
  });

  // 统计数据
  const recentStats = {
    total: filteredLogs.length,
    loginCount: filteredLogs.filter(l => l.operation_type === 'login').length,
    logoutCount: filteredLogs.filter(l => l.operation_type === 'logout').length,
    failCount: filteredLogs.filter(l => l.status === 'fail').length,
  };

  const getTagBadgeClass = (color: string) => {
    const map: Record<string, string> = {
      emerald: 'bg-emerald-100 text-emerald-700',
      blue: 'bg-blue-100 text-blue-700',
      orange: 'bg-orange-100 text-orange-700',
      gray: 'bg-slate-100 text-slate-600',
      red: 'bg-red-100 text-red-700'
    };
    return map[color] || 'bg-slate-100 text-slate-600';
  };

  const getTagBgLight = (color: string) => {
    const map: Record<string, string> = {
      emerald: 'bg-emerald-50',
      blue: 'bg-blue-50',
      orange: 'bg-orange-50',
      gray: 'bg-slate-50',
      red: 'bg-red-50'
    };
    return map[color] || 'bg-slate-50';
  };

  const formatTime = (dateStr: string) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr.replace(' ', 'T'));
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (minutes < 1) return '刚刚';
    if (minutes < 60) return `${minutes}分钟前`;
    if (hours < 24) return `${hours}小时前`;
    return `${days}天前`;
  };

  const formatDate = (dateStr: string) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr.replace(' ', 'T'));
    return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;

  return (
    <div className="p-6">
      {/* 页面标题栏 */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-slate-800">访问日志</h1>
        <p className="text-sm text-slate-400 mt-0.5">用户活动统计和登录记录</p>
      </div>

      {/* 筛选栏 */}
      <div className="bg-white rounded-xl border border-slate-200 p-4 mb-4">
        <div className="flex items-center gap-6">
          {/* 时间范围 */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-500">时间范围：</span>
            <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
              {([['7d', '近7天'], ['30d', '近30天'], ['all', '全部']] as [TimeRange, string][]).map(([value, label]) => (
                <button key={value}
                  onClick={() => setTimeRange(value)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                    timeRange === value ? 'bg-white text-slate-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  }`}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* 操作类型 */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-500">操作类型：</span>
            <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
              {([['all', '全部'], ['login', '登录'], ['logout', '登出'], ['other', '其他']] as [OpType, string][]).map(([value, label]) => (
                <button key={value}
                  onClick={() => setOpTypeFilter(value)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                    opTypeFilter === value ? 'bg-white text-slate-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  }`}>
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 统计卡片 */}
      {stats && (
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-blue-100 rounded-lg">
                <i className="ri-user-line text-blue-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">{stats.total_users}</div>
                <div className="text-xs text-slate-500">总用户数</div>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-emerald-100 rounded-lg">
                <i className="ri-user-star-line text-emerald-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">{stats.active_users}</div>
                <div className="text-xs text-slate-500">活跃用户</div>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-purple-100 rounded-lg">
                <i className="ri-percent-line text-purple-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">{stats.active_rate}%</div>
                <div className="text-xs text-slate-500">活跃率</div>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 flex items-center justify-center rounded-lg ${recentStats.failCount > 0 ? 'bg-red-100' : 'bg-slate-100'}`}>
                <i className={`${recentStats.failCount > 0 ? 'ri-error-warning-line text-red-600' : 'ri-time-line text-slate-600'}`} />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">{recentStats.failCount > 0 ? recentStats.failCount : recentStats.total}</div>
                <div className="text-xs text-slate-500">
                  {recentStats.failCount > 0 ? `失败操作 (${recentStats.failCount})` : '操作记录'}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-6">
        {/* 左侧：用户状态分布 + 用户列表 */}
        <div className="col-span-1 space-y-4">
          {/* 用户状态分布 */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100">
              <h3 className="text-sm font-semibold text-slate-700">用户状态分布</h3>
            </div>
            <div className="p-4 space-y-3">
              {stats?.tag_counts && Object.entries(stats.tag_counts).map(([tag, count]) => {
                const user = users.find(u => u.tag === tag);
                const color = user?.tag_color || 'gray';
                const emoji = user?.tag_emoji || '❓';
                const percentage = stats.total_users > 0 ? ((count as number) / stats.total_users * 100) : 0;

                return (
                  <div key={tag} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-base">{emoji}</span>
                      <span className="text-sm text-slate-600">{tag}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-700">{count as number}</span>
                      <div className={`w-16 h-2 rounded-full ${getTagBgLight(color)}`}>
                        <div className="h-full rounded-full bg-current opacity-40" style={{ width: `${percentage}%` }} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 用户列表 */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100">
              <h3 className="text-sm font-semibold text-slate-700">用户列表</h3>
            </div>
            <div className="divide-y divide-slate-100 max-h-80 overflow-y-auto">
              {users.map((user) => (
                <div key={user.id} className="px-4 py-2.5 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className={`w-7 h-7 rounded-full bg-gradient-to-br ${getAvatarGradient(user.username)} flex items-center justify-center text-white text-xs font-medium`}>
                      {user.display_name.charAt(0)}
                    </div>
                    <div>
                      <div className="text-sm font-medium text-slate-700">{user.display_name}</div>
                      <div className="text-xs text-slate-400">@{user.username}</div>
                    </div>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${getTagBadgeClass(user.tag_color)}`}>
                    {user.tag_emoji} {user.tag}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 右侧：操作日志 */}
        <div className="col-span-2">
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-700">操作日志</h3>
              <span className="text-xs text-slate-400">共 {filteredLogs.length} 条记录</span>
            </div>
            <div className="divide-y divide-slate-100 max-h-[600px] overflow-y-auto">
              {filteredLogs.map((log) => (
                <div key={log.id} className={`px-4 py-3 flex items-start gap-3 hover:bg-slate-50/50 ${log.status === 'fail' ? 'bg-red-50/30' : ''}`}>
                  <div className={`w-8 h-8 flex items-center justify-center rounded-full ${
                    log.operation_type === 'login' ? 'bg-blue-100 text-blue-600' :
                    log.operation_type === 'logout' ? 'bg-slate-100 text-slate-600' :
                    log.status === 'fail' ? 'bg-red-100 text-red-600' :
                    'bg-emerald-100 text-emerald-600'
                  }`}>
                    <i className={log.operation_type === 'login' ? 'ri-login-box-line' :
                      log.operation_type === 'logout' ? 'ri-logout-box-line' :
                      log.status === 'fail' ? 'ri-error-warning-line' :
                      'ri-file-list-3-line'} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className={`text-sm font-medium ${log.status === 'fail' ? 'text-red-700' : 'text-slate-700'}`}>
                        {log.operation_type === 'login' ? '用户登录' :
                         log.operation_type === 'logout' ? '用户登出' :
                         log.operation_type}
                      </span>
                      <span className="text-xs text-slate-400">{formatDate(log.op_time)}</span>
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">
                      操作者: {log.operator} {log.target ? `→ ${log.target}` : ''}
                    </div>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    log.status === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
                  }`}>
                    {log.status === 'success' ? '成功' : '失败'}
                  </span>
                </div>
              ))}
              {filteredLogs.length === 0 && (
                <div className="p-8 text-center text-slate-400">
                  <i className="ri-file-list-3-line text-3xl mb-2 block" />
                  暂无操作日志
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
