import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  LineChart, Line,
} from 'recharts';
import {
  getTokenSummary,
  getUserTokenStats,
  getTokenTrend,
  type TokenSummary,
  type UserTokenStats,
  type DailyTrend,
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

// ── 日期工具 ────────────────────────────────────────────────────
function today(): string {
  return new Date().toISOString().slice(0, 10);
}
function daysAgo(n: number): string {
  return new Date(Date.now() - n * 86400_000).toISOString().slice(0, 10);
}

type QuickRange = 'today' | '7d' | '30d' | 'custom';

const QUICK_RANGES: { key: QuickRange; label: string }[] = [
  { key: 'today', label: '今日' },
  { key: '7d',    label: '近7天' },
  { key: '30d',   label: '近30天' },
];

// ── KPI 卡片 ──────────────────────────────────────────────────────
function TrendBadge({ pct }: { pct: number | null | undefined }) {
  if (pct === null || pct === undefined) return null;
  const up = pct > 0;
  const down = pct < 0;
  const color = up ? 'text-red-500' : down ? 'text-emerald-500' : 'text-slate-400';
  const icon = up ? 'ri-arrow-up-line' : down ? 'ri-arrow-down-line' : 'ri-subtract-line';
  return (
    <span className={`text-xs font-medium flex items-center gap-0.5 ${color}`}>
      <i className={icon} />
      {Math.abs(pct).toFixed(1)}%
      <span className="text-slate-400 font-normal ml-0.5">较上期</span>
    </span>
  );
}

function KpiCard({
  icon,
  label,
  value,
  trend,
  sub,
}: {
  icon: string;
  label: string;
  value: string;
  trend?: number | null;
  sub?: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200/70 p-5 flex flex-col justify-between shadow-sm hover:shadow-md transition-shadow">
      {/* 第一行：标题 + 图标对角线 */}
      <div className="flex justify-between items-start mb-3">
        <span className="text-[13px] font-medium text-slate-500">{label}</span>
        <div className="w-8 h-8 rounded-lg bg-slate-50 border border-slate-100 flex items-center justify-center text-slate-400">
          <i className={`${icon} text-base`} />
        </div>
      </div>
      {/* 第二行：主数值 + 趋势（水平排列，趋势紧跟数值右侧） */}
      <div className="flex items-end justify-between">
        <div>
          <div className="text-3xl font-bold text-slate-800 tracking-tight leading-none">{value}</div>
          {sub && <div className="text-[12px] text-slate-400 mt-1.5">{sub}</div>}
        </div>
        <TrendBadge pct={trend} />
      </div>
    </div>
  );
}

// ── 饼图 Label ────────────────────────────────────────────────────
const PieLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percentage }: any) => {
  if (percentage < 5) return null;
  const RADIAN = Math.PI / 180;
  const r = innerRadius + (outerRadius - innerRadius) * 0.55;
  return (
    <text x={cx + r * Math.cos(-midAngle * RADIAN)} y={cy + r * Math.sin(-midAngle * RADIAN)}
      fill="white" textAnchor="middle" dominantBaseline="central" fontSize={11} fontWeight={600}>
      {`${percentage}%`}
    </text>
  );
};

// ── 主页面 ─────────────────────────────────────────────────────────
export default function TokenStatsPage() {
  const [quickRange, setQuickRange] = useState<QuickRange>('7d');
  const [startDate, setStartDate] = useState(daysAgo(6));
  const [endDate, setEndDate] = useState(today());

  const [summary, setSummary] = useState<TokenSummary | null>(null);
  const [users, setUsers] = useState<UserTokenStats[]>([]);
  const [trend, setTrend] = useState<DailyTrend[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [usersLoading, setUsersLoading] = useState(true);
  const [trendLoading, setTrendLoading] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [usersError, setUsersError] = useState<string | null>(null);

  // 加载概览
  const loadSummary = useCallback(() => {
    setSummaryLoading(true);
    setSummaryError(null);
    getTokenSummary(startDate, endDate)
      .then(setSummary)
      .catch((e) => setSummaryError(e.message))
      .finally(() => setSummaryLoading(false));
  }, [startDate, endDate]);

  // 加载趋势
  const loadTrend = useCallback(() => {
    setTrendLoading(true);
    getTokenTrend(startDate, endDate)
      .then(setTrend)
      .catch(() => setTrend([]))
      .finally(() => setTrendLoading(false));
  }, [startDate, endDate]);

  // 加载用户明细
  const loadUsers = useCallback(() => {
    setUsersLoading(true);
    setUsersError(null);
    getUserTokenStats(startDate, endDate)
      .then((r) => setUsers(r.users))
      .catch((e) => setUsersError(e.message))
      .finally(() => setUsersLoading(false));
  }, [startDate, endDate]);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { loadTrend(); }, [loadTrend]);
  useEffect(() => { loadUsers(); }, [loadUsers]);

  // 快捷选择联动日期（立即触发请求）
  const applyQuickRange = useCallback((key: QuickRange) => {
    setQuickRange(key);
    if (key === 'today') {
      setStartDate(today()); setEndDate(today());
    } else if (key === '7d') {
      setStartDate(daysAgo(6)); setEndDate(today());
    } else if (key === '30d') {
      setStartDate(daysAgo(29)); setEndDate(today());
    }
    setTimeout(() => { loadSummary(); loadTrend(); loadUsers(); }, 0);
  }, [loadSummary, loadTrend, loadUsers]);

  const today_s = summary?.summary;
  const byModel = summary?.by_model ?? [];
  const topUsers = summary?.top_users ?? [];

  // 趋势图数据（最近14天用于参考，但展示选中范围）
  const chartData = useMemo(() => {
    if (!trend.length) return [];
    return trend.map(d => ({
      date: d.date.slice(5), // MM-DD
      total: d.total_tokens,
    }));
  }, [trend]);

  const handleQuery = useCallback(() => {
    setQuickRange('custom');
    loadSummary();
    loadTrend();
    loadUsers();
  }, [loadSummary, loadTrend, loadUsers]);

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 页头 */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-coin-line text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">Token 统计</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">LLM 调用消耗监控</p>
          </div>

          {/* 全局时间过滤器 */}
          <div className="flex items-center gap-2">
            {/* 快捷选项 */}
            <div className="flex gap-1">
              {QUICK_RANGES.map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => applyQuickRange(key)}
                  className={`px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${
                    quickRange === key
                      ? 'bg-slate-800 text-white'
                      : 'text-slate-500 hover:bg-slate-100'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {/* 日期范围 — 变更即自动刷新 */}
            <input
              type="date"
              value={startDate}
              max={endDate}
              onChange={(e) => {
                setStartDate(e.target.value);
                setQuickRange('custom');
                setTimeout(() => { loadSummary(); loadTrend(); loadUsers(); }, 0);
              }}
              onKeyDown={(e) => e.key === 'Enter' && (() => { setQuickRange('custom'); loadSummary(); loadTrend(); loadUsers(); })()}
              className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
            />
            <span className="text-xs text-slate-300">—</span>
            <input
              type="date"
              value={endDate}
              min={startDate}
              max={today()}
              onChange={(e) => {
                setEndDate(e.target.value);
                setQuickRange('custom');
                setTimeout(() => { loadSummary(); loadTrend(); loadUsers(); }, 0);
              }}
              onKeyDown={(e) => e.key === 'Enter' && (() => { setQuickRange('custom'); loadSummary(); loadTrend(); loadUsers(); })()}
              className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
            />
            <button
              onClick={() => { setQuickRange('custom'); loadSummary(); loadTrend(); loadUsers(); }}
              className="text-xs px-3 py-1.5 bg-white border border-slate-200 text-slate-500 rounded-lg hover:bg-slate-50 hover:border-slate-300 transition-colors"
            >
              查询
            </button>
          </div>
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto space-y-6">

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
                label="总 Token"
                value={fmt(today_s?.total_tokens ?? 0)}
                trend={summary?.summary?.total_trend_pct ?? undefined}
                sub={`${(today_s?.total_tokens ?? 0).toLocaleString()} tokens`}
              />
              <KpiCard
                icon="ri-arrow-right-up-line"
                label="输入 Token"
                value={fmt(today_s?.prompt_tokens ?? 0)}
                trend={summary?.summary?.prompt_trend_pct ?? undefined}
                sub={`${(today_s?.prompt_tokens ?? 0).toLocaleString()} tokens`}
              />
              <KpiCard
                icon="ri-arrow-left-down-line"
                label="输出 Token"
                value={fmt(today_s?.completion_tokens ?? 0)}
                trend={summary?.summary?.completion_trend_pct ?? undefined}
                sub={`${(today_s?.completion_tokens ?? 0).toLocaleString()} tokens`}
              />
            </div>
          )}

          {/* ── 趋势图（全宽折线图）─────────────────────────── */}
          {!summaryLoading && !summaryError && (
            <div className="bg-white rounded-xl border border-slate-200/70 p-5">
              <p className="text-sm font-medium text-slate-700 mb-4">每日 Token 消耗趋势</p>
              {trendLoading ? (
                <div className="h-40 animate-pulse bg-slate-50 rounded-lg" />
              ) : chartData.length === 0 ? (
                <div className="h-40 flex items-center justify-center text-sm text-slate-400">暂无数据</div>
              ) : (
                <ResponsiveContainer width="100%" height={160}>
                  <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 11, fill: '#94a3b8' }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tickFormatter={fmt}
                      tick={{ fontSize: 11, fill: '#94a3b8' }}
                      axisLine={false}
                      tickLine={false}
                      width={48}
                    />
                    <Tooltip
                      formatter={(v: number) => [`${v.toLocaleString()} tokens`, '消耗']}
                      contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="total"
                      stroke="#3b82f6"
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 4, fill: '#3b82f6' }}
                      connectNulls={true}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          )}

          {/* ── 图表行 ──────────────────────────────────────── */}
          {!summaryLoading && !summaryError && (
            <div className="grid grid-cols-2 gap-4">
              {/* 模型分布饼图 */}
              <div className="bg-white rounded-xl border border-slate-200/70 p-5">
                <p className="text-sm font-medium text-slate-700 mb-4">模型消耗分布</p>
                {byModel.length === 0 ? (
                  <div className="h-52 flex items-center justify-center text-sm text-slate-400">暂无数据</div>
                ) : (
                  <div className="flex gap-4 items-center">
                    <div style={{ width: 180, height: 180, flexShrink: 0 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={byModel}
                            dataKey="total_tokens"
                            nameKey="model"
                            cx="50%"
                            cy="50%"
                            outerRadius={80}
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
                    <div className="space-y-2 min-w-0 flex-1">
                      {byModel.slice(0, 6).map((m, idx) => (
                        <div key={m.model} className="flex items-center gap-2 min-w-0">
                          <span
                            className="w-2 h-2 rounded-full flex-shrink-0"
                            style={{ background: CHART_COLORS[idx % CHART_COLORS.length] }}
                          />
                          <span className="text-xs text-slate-600 truncate max-w-[100px]" title={m.model}>
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

              {/* Top5 用户横向柱状图 */}
              <div className="bg-white rounded-xl border border-slate-200/70 p-5">
                <p className="text-sm font-medium text-slate-700 mb-4">高消耗用户 Top 5</p>
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
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
              <p className="text-sm font-medium text-slate-700">用户消耗统计</p>
            </div>

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
                    const maxTokens = users[0]?.total_tokens ?? 1;
                    const pct = Math.round((u.total_tokens / maxTokens) * 100);
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
                            <div className="flex-1 max-w-[80px] h-1 bg-slate-100 rounded-full overflow-hidden">
                              <div className="h-full bg-blue-400 rounded-full" style={{ width: `${pct}%` }} />
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