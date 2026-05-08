import { useEffect, useState, useCallback } from 'react';
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from 'recharts';
import {
  getTokenSummary,
  getUserTokenStats,
  type TokenSummary,
  type UserTokenStats,
} from '../../../api/token-stats';

// ── 颜色 ─────────────────────────────────────────────────────────
const CHART_COLORS = [
  '#3b82f6', '#6366f1', '#8b5cf6', '#ec4899',
  '#f59e0b', '#10b981', '#06b6d4', '#f97316',
];

// ── 数字格式化 ────────────────────────────────────────────────────
function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

// ── KPI 卡片 ──────────────────────────────────────────────────────
function KpiCard({
  label,
  value,
  sub,
  icon,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200/70 px-5 py-4 flex items-center gap-4">
      <div className="w-9 h-9 rounded-lg bg-slate-100 flex items-center justify-center flex-shrink-0">
        <i className={`${icon} text-slate-500 text-base`} />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-slate-400 mb-0.5">{label}</p>
        <p className="text-2xl font-semibold text-slate-900 leading-none">{value}</p>
        {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
      </div>
    </div>
  );
}

// ── 饼图自定义 Label ──────────────────────────────────────────────
const PieLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percentage }: any) => {
  if (percentage < 5) return null;
  const RADIAN = Math.PI / 180;
  const r = innerRadius + (outerRadius - innerRadius) * 0.55;
  const x = cx + r * Math.cos(-midAngle * RADIAN);
  const y = cy + r * Math.sin(-midAngle * RADIAN);
  return (
    <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={11} fontWeight={600}>
      {`${percentage}%`}
    </text>
  );
};

// ── 主页面 ─────────────────────────────────────────────────────────
export default function TokenStatsPage() {
  const [summary, setSummary] = useState<TokenSummary | null>(null);
  const [users, setUsers] = useState<UserTokenStats[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [usersLoading, setUsersLoading] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [usersError, setUsersError] = useState<string | null>(null);

  // 日期筛选
  const today = new Date().toISOString().slice(0, 10);
  const thirtyDaysAgo = new Date(Date.now() - 29 * 86400_000).toISOString().slice(0, 10);
  const [startDate, setStartDate] = useState(thirtyDaysAgo);
  const [endDate, setEndDate] = useState(today);

  // 加载概览
  useEffect(() => {
    setSummaryLoading(true);
    setSummaryError(null);
    getTokenSummary()
      .then(setSummary)
      .catch((e) => setSummaryError(e.message))
      .finally(() => setSummaryLoading(false));
  }, []);

  // 加载用户明细
  const loadUsers = useCallback(() => {
    setUsersLoading(true);
    setUsersError(null);
    getUserTokenStats(startDate, endDate)
      .then((r) => setUsers(r.users))
      .catch((e) => setUsersError(e.message))
      .finally(() => setUsersLoading(false));
  }, [startDate, endDate]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const today_s = summary?.today;
  const byModel = summary?.by_model ?? [];
  const topUsers = summary?.top_users ?? [];

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-7xl mx-auto">
          <h1 className="text-lg font-semibold text-slate-900">Token 统计</h1>
          <p className="text-sm text-slate-400 mt-0.5">LLM 调用消耗监控 · 今日数据实时更新</p>
        </div>
      </div>
      <div className="px-8 py-7">
        <div className="max-w-7xl mx-auto space-y-6">

      {/* ── KPI 卡片行 ──────────────────────────────────── */}
      {summaryLoading ? (
        <div className="grid grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="bg-white rounded-xl border border-slate-200/70 h-20 animate-pulse" />
          ))}
        </div>
      ) : summaryError ? (
        <div className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
          <i className="ri-error-warning-line mr-1.5" />
          {summaryError}
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-4">
          <KpiCard
            icon="ri-coin-line"
            label="今日总 Token"
            value={fmt(today_s?.total_tokens ?? 0)}
            sub={`${(today_s?.total_tokens ?? 0).toLocaleString()} tokens`}
          />
          <KpiCard
            icon="ri-arrow-right-up-line"
            label="今日输入 Token"
            value={fmt(today_s?.prompt_tokens ?? 0)}
            sub="Prompt tokens"
          />
          <KpiCard
            icon="ri-arrow-left-down-line"
            label="今日输出 Token"
            value={fmt(today_s?.completion_tokens ?? 0)}
            sub="Completion tokens"
          />
        </div>
      )}

      {/* ── 图表行 ──────────────────────────────────────── */}
      {!summaryLoading && !summaryError && (
        <div className="grid grid-cols-2 gap-4">
          {/* 模型分布饼图 */}
          <div className="bg-white rounded-xl border border-slate-200/70 p-5">
            <p className="text-sm font-medium text-slate-700 mb-4">今日模型消耗分布</p>
            {byModel.length === 0 ? (
              <div className="h-52 flex items-center justify-center text-sm text-slate-400">暂无数据</div>
            ) : (
              <div className="flex gap-4 items-center">
                <div style={{ width: 200, height: 200, flexShrink: 0 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={byModel}
                        dataKey="total_tokens"
                        nameKey="model"
                        cx="50%"
                        cy="50%"
                        outerRadius={90}
                        labelLine={false}
                        label={PieLabel}
                      >
                        {byModel.map((_, idx) => (
                          <Cell key={idx} fill={CHART_COLORS[idx % CHART_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(v: number) => [`${v.toLocaleString()} tokens`, '消耗']}
                        contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                {/* 自定义图例 */}
                <div className="space-y-2 min-w-0">
                  {byModel.slice(0, 6).map((m, idx) => (
                    <div key={m.model} className="flex items-center gap-2 min-w-0">
                      <span
                        className="w-2 h-2 rounded-full flex-shrink-0"
                        style={{ background: CHART_COLORS[idx % CHART_COLORS.length] }}
                      />
                      <span className="text-xs text-slate-600 truncate max-w-[120px]" title={m.model}>
                        {m.model}
                      </span>
                      <span className="text-xs text-slate-400 flex-shrink-0 ml-auto pl-2">
                        {m.percentage}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Top 5 用户横向柱状图 */}
          <div className="bg-white rounded-xl border border-slate-200/70 p-5">
            <p className="text-sm font-medium text-slate-700 mb-4">今日高消耗用户 Top 5</p>
            {topUsers.length === 0 ? (
              <div className="h-52 flex items-center justify-center text-sm text-slate-400">暂无数据</div>
            ) : (
              <ResponsiveContainer width="100%" height={190}>
                <BarChart
                  data={topUsers}
                  layout="vertical"
                  margin={{ top: 0, right: 20, left: 0, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f1f5f9" />
                  <XAxis
                    type="number"
                    tickFormatter={fmt}
                    tick={{ fontSize: 11, fill: '#94a3b8' }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="username"
                    width={72}
                    tick={{ fontSize: 11, fill: '#64748b' }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    formatter={(v: number) => [`${v.toLocaleString()} tokens`, '消耗']}
                    contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
                  />
                  <Bar dataKey="total_tokens" fill="#3b82f6" radius={[0, 4, 4, 0]} maxBarSize={20} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      )}

      {/* ── 用户明细表 ────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-slate-200/70">
        {/* 表头工具栏 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
          <p className="text-sm font-medium text-slate-700">用户消耗统计</p>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">时间段</span>
            <input
              type="date"
              value={startDate}
              max={endDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
            />
            <span className="text-xs text-slate-300">—</span>
            <input
              type="date"
              value={endDate}
              min={startDate}
              max={today}
              onChange={(e) => setEndDate(e.target.value)}
              className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
            />
            <button
              onClick={loadUsers}
              className="text-xs px-3 py-1.5 bg-slate-900 text-white rounded-lg hover:bg-slate-700 transition-colors"
            >
              查询
            </button>
          </div>
        </div>

        {/* 表格 */}
        {usersLoading ? (
          <div className="space-y-px p-4">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="h-9 bg-slate-50 rounded animate-pulse" />
            ))}
          </div>
        ) : usersError ? (
          <div className="px-5 py-4 text-sm text-red-500">
            <i className="ri-error-warning-line mr-1.5" />
            {usersError}
          </div>
        ) : users.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-slate-400">该时间段内无 Token 消耗记录</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-400 border-b border-slate-100">
                <th className="text-left px-5 py-2.5 font-medium w-8">#</th>
                <th className="text-left px-5 py-2.5 font-medium">用户</th>
                <th className="text-right px-5 py-2.5 font-medium">总 Token</th>
                <th className="text-right px-5 py-2.5 font-medium">输入 Token</th>
                <th className="text-right px-5 py-2.5 font-medium">输出 Token</th>
                <th className="text-right px-5 py-2.5 font-medium">调用次数</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {users.map((u, idx) => {
                const pct = users[0]?.total_tokens
                  ? Math.round((u.total_tokens / users[0].total_tokens) * 100)
                  : 0;
                return (
                  <tr key={u.user_id ?? `sys-${idx}`} className="hover:bg-slate-50/60 transition-colors">
                    <td className="px-5 py-2.5 text-slate-400 text-xs">{idx + 1}</td>
                    <td className="px-5 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-6 h-6 rounded-full bg-slate-100 flex items-center justify-center flex-shrink-0">
                          <span className="text-xs text-slate-500 font-medium">
                            {(u.username || '?')[0].toUpperCase()}
                          </span>
                        </div>
                        <span className="text-slate-700 font-medium">{u.username}</span>
                        {/* 占比进度条 */}
                        <div className="flex-1 max-w-[80px] h-1 bg-slate-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-400 rounded-full"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-2.5 text-right text-slate-900 font-medium tabular-nums">
                      {u.total_tokens.toLocaleString()}
                    </td>
                    <td className="px-5 py-2.5 text-right text-slate-500 tabular-nums">
                      {u.prompt_tokens.toLocaleString()}
                    </td>
                    <td className="px-5 py-2.5 text-right text-slate-500 tabular-nums">
                      {u.completion_tokens.toLocaleString()}
                    </td>
                    <td className="px-5 py-2.5 text-right">
                      <span className="text-xs px-2 py-0.5 bg-slate-100 text-slate-500 rounded-full tabular-nums">
                        {u.call_count.toLocaleString()} 次
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
        </div>
      </div>
    </div>
  );
}
