/**
 * AgentMonitorPage -- /system/agent-monitor
 *
 * Agent 监控管理页：展示调用量、成功率、P95 耗时、反馈汇总、
 * 热门工具、近期运行列表及步骤详情。
 *
 * 后端 API：
 *   GET /api/admin/agent/stats
 *   GET /api/admin/agent/runs
 *   GET /api/admin/agent/runs/{run_id}/steps
 */
import { Fragment, useState, useEffect, useCallback, type MouseEvent } from 'react';
import {
  agentAdminApi,
  type AgentStats,
  type AgentRun,
  type AgentStep,
  type AgentToolMetadata,
  type AgentSessionItem,
} from '../../../api/agent';
import { API_BASE } from '../../../config';
import InlineDiagnosticPanel from '../../agents/help-agent/InlineDiagnosticPanel';

// ─── Types ───────────────────────────────────────────────────────────────────

type StatusFilter = 'all' | 'running' | 'completed' | 'failed';
type ActiveTab = 'overview' | 'tools' | 'sessions';
type OverviewTable = 'runs' | 'nlq';

interface NlqLogItem {
  id: number;
  run_id?: string;
  username: string | null;
  question: string;
  intent: string | null;
  response_type: string | null;
  datasource_luid: string | null;
  execution_time_ms: number | null;
  error_code: string | null;
  success: boolean;
  created_at: string;
}

interface NlqLogListResponse {
  items: NlqLogItem[];
  total: number;
  page: number;
  page_size: number;
}

const INTENT_OPTIONS = [
  { value: '', label: '全部意图' },
  { value: 'vizql', label: 'VizQL 查询' },
  { value: 'text', label: '文本回答' },
  { value: 'clarification', label: '澄清追问' },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function toDatetimeLocal(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function defaultRange(): { start: string; end: string } {
  const now = new Date();
  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  return { start: toDatetimeLocal(yesterday), end: toDatetimeLocal(now) };
}

function formatDateTime(dateStr: string): string {
  if (!dateStr) return '-';
  try {
    const d = new Date(dateStr);
    return d.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

function truncate(text: string, maxLen = 80): string {
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text;
}

function shortRunId(id: string): string {
  if (!id) return '-';
  if (id.length <= 16) return id;
  return `${id.slice(0, 8)}...${id.slice(-4)}`;
}

function copyRunId(id: string, e: MouseEvent<HTMLButtonElement>) {
  e.stopPropagation();
  void navigator.clipboard?.writeText(id);
}

function RunIdCell({ id }: { id: string }) {
  return (
    <div className="flex items-center gap-1.5 whitespace-nowrap">
      <code className="text-[11px] font-mono text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded" title={id}>
        {shortRunId(id)}
      </code>
      <button
        type="button"
        onClick={(e) => copyRunId(id, e)}
        className="w-6 h-6 inline-flex items-center justify-center rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100"
        title="复制 run_id"
      >
        <i className="ri-file-copy-line text-xs" />
      </button>
    </div>
  );
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-';
  const d = new Date(dateStr);
  return d.toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatMs(ms: number | null): string {
  if (ms === null || ms === undefined) return '-';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatStepMs(step: AgentStep): string {
  const value = formatMs(step.execution_time_ms);
  return step.duration_source === 'derived' && value !== '-' ? `≈${value}` : value;
}

function stepDurationTitle(step: AgentStep): string {
  if (step.duration_source === 'recorded') return '真实记录耗时';
  if (step.duration_source === 'derived') return '历史记录按步骤时间戳推导';
  return '无耗时记录';
}

function stepDurationClass(ms: number | null): string {
  if (ms === null || ms === undefined) return 'text-slate-300';
  if (ms >= 15000) return 'text-red-600 bg-red-50';
  if (ms >= 5000) return 'text-amber-700 bg-amber-50';
  return 'text-slate-500 bg-slate-50';
}

function StepDurationSummary({ steps, totalMs }: { steps: AgentStep[]; totalMs: number | null }) {
  const timedSteps = steps.filter((step) => step.execution_time_ms !== null && step.execution_time_ms !== undefined);
  const slowest = timedSteps.reduce<AgentStep | null>((current, step) => {
    if (!current) return step;
    return (step.execution_time_ms ?? 0) > (current.execution_time_ms ?? 0) ? step : current;
  }, null);
  const thinkingMs = timedSteps
    .filter((step) => step.step_type === 'thinking')
    .reduce((sum, step) => sum + (step.execution_time_ms ?? 0), 0);
  const toolMs = timedSteps
    .filter((step) => step.step_type === 'tool_result')
    .reduce((sum, step) => sum + (step.execution_time_ms ?? 0), 0);

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
      <div className="bg-white border border-slate-200 rounded-lg px-3 py-2">
        <div className="text-[11px] text-slate-400">总耗时</div>
        <div className="text-sm font-semibold text-slate-700">{formatMs(totalMs)}</div>
      </div>
      <div className="bg-white border border-slate-200 rounded-lg px-3 py-2">
        <div className="text-[11px] text-slate-400">最慢步骤</div>
        <div className="text-sm font-semibold text-slate-700">
          {slowest ? `#${slowest.step_number} ${formatStepMs(slowest)}` : '-'}
        </div>
      </div>
      <div className="bg-white border border-slate-200 rounded-lg px-3 py-2">
        <div className="text-[11px] text-slate-400">Thinking</div>
        <div className="text-sm font-semibold text-slate-700">{formatMs(thinkingMs)}</div>
      </div>
      <div className="bg-white border border-slate-200 rounded-lg px-3 py-2">
        <div className="text-[11px] text-slate-400">工具执行</div>
        <div className="text-sm font-semibold text-slate-700">{formatMs(toolMs)}</div>
      </div>
    </div>
  );
}

function statusBadge(status: string) {
  const map: Record<string, { bg: string; text: string; label: string }> = {
    running: { bg: 'bg-blue-50', text: 'text-blue-700', label: '运行中' },
    completed: { bg: 'bg-emerald-50', text: 'text-emerald-700', label: '成功' },
    failed: { bg: 'bg-red-50', text: 'text-red-700', label: '失败' },
  };
  const s = map[status] || { bg: 'bg-slate-50', text: 'text-slate-600', label: status };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${s.bg} ${s.text}`}>
      {s.label}
    </span>
  );
}

function stepTypeBadge(stepType: string) {
  const map: Record<string, { bg: string; text: string }> = {
    thinking: { bg: 'bg-purple-50', text: 'text-purple-700' },
    tool_call: { bg: 'bg-blue-50', text: 'text-blue-700' },
    tool_result: { bg: 'bg-cyan-50', text: 'text-cyan-700' },
    answer: { bg: 'bg-emerald-50', text: 'text-emerald-700' },
    error: { bg: 'bg-red-50', text: 'text-red-700' },
  };
  const s = map[stepType] || { bg: 'bg-slate-50', text: 'text-slate-600' };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${s.bg} ${s.text}`}>
      {stepType}
    </span>
  );
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function AgentMonitorPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');
  const [overviewTable, setOverviewTable] = useState<OverviewTable>('runs');
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [offset, setOffset] = useState(0);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [diagnosticRunId, setDiagnosticRunId] = useState<string | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [stepsLoading, setStepsLoading] = useState(false);

  // Tool discovery state
  const [tools, setTools] = useState<AgentToolMetadata[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);

  // Sessions state
  const [sessions, setSessions] = useState<AgentSessionItem[]>([]);
  const [sessionsTotal, setSessionsTotal] = useState(0);
  const [sessionsOffset, setSessionsOffset] = useState(0);
  const [sessionsLoading, setSessionsLoading] = useState(false);

  // Query logs state
  const [queryItems, setQueryItems] = useState<NlqLogItem[]>([]);
  const [queryTotal, setQueryTotal] = useState(0);
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryErrorMsg, setQueryErrorMsg] = useState('');
  const [queryStatus, setQueryStatus] = useState<'all' | 'success' | 'failed'>('all');
  const [queryIntent, setQueryIntent] = useState('');
  const { start: defaultStart, end: defaultEnd } = defaultRange();
  const [queryStartTime, setQueryStartTime] = useState(defaultStart);
  const [queryEndTime, setQueryEndTime] = useState(defaultEnd);
  const [queryPage, setQueryPage] = useState(1);
  const queryPageSize = 20;

  const LIMIT = 20;

  const fetchStats = useCallback(async () => {
    try {
      const data = await agentAdminApi.getStats();
      setStats(data);
    } catch (err) {
      console.error('获取 Agent 统计失败', err);
    }
  }, []);

  const fetchRuns = useCallback(async () => {
    try {
      const data = await agentAdminApi.getRuns({
        limit: LIMIT,
        offset,
        status: statusFilter !== 'all' ? statusFilter : undefined,
      });
      setRuns(data.items);
      setRunsTotal(data.total);
    } catch (err) {
      console.error('获取 Agent 运行列表失败', err);
    }
  }, [offset, statusFilter]);

  const fetchSteps = useCallback(async (runId: string) => {
    setStepsLoading(true);
    try {
      const data = await agentAdminApi.getRunSteps(runId);
      setSteps(data);
    } catch (err) {
      console.error('获取步骤详情失败', err);
    } finally {
      setStepsLoading(false);
    }
  }, []);

  const fetchTools = useCallback(async () => {
    setToolsLoading(true);
    try {
      const data = await agentAdminApi.getTools();
      setTools(data);
    } catch (err) {
      console.error('获取工具列表失败', err);
    } finally {
      setToolsLoading(false);
    }
  }, []);

  const fetchSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const data = await agentAdminApi.getSessions({
        limit: LIMIT,
        offset: sessionsOffset,
      });
      setSessions(data.items);
      setSessionsTotal(data.total);
    } catch (err) {
      console.error('获取会话列表失败', err);
    } finally {
      setSessionsLoading(false);
    }
  }, [sessionsOffset]);

  const fetchQueryLogs = useCallback(async () => {
    setQueryLoading(true);
    setQueryErrorMsg('');
    try {
      const params = new URLSearchParams({
        page: String(queryPage),
        page_size: String(queryPageSize),
      });
      if (queryStatus !== 'all') params.set('status', queryStatus);
      if (queryIntent) params.set('intent', queryIntent);
      if (queryStartTime) params.set('start_time', queryStartTime);
      if (queryEndTime) params.set('end_time', queryEndTime);

      const resp = await fetch(`${API_BASE}/api/admin/query/logs?${params}`, {
        credentials: 'include',
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        setQueryErrorMsg(err.detail?.message || err.detail || '获取查数日志失败');
        return;
      }
      const data: NlqLogListResponse = await resp.json();
      setQueryItems(data.items);
      setQueryTotal(data.total);
    } catch {
      setQueryErrorMsg('网络错误，请稍后重试');
    } finally {
      setQueryLoading(false);
    }
  }, [queryStatus, queryIntent, queryStartTime, queryEndTime, queryPage]);

  useEffect(() => {
    Promise.all([fetchStats(), fetchRuns()]).finally(() => setLoading(false));
  }, [fetchStats, fetchRuns]);

  // 切换到工具 tab 时加载
  useEffect(() => {
    if (activeTab === 'tools' && tools.length === 0) {
      fetchTools();
    }
  }, [activeTab, tools.length, fetchTools]);

  // 切换到会话 tab 时加载
  useEffect(() => {
    if (activeTab === 'sessions') {
      fetchSessions();
    }
  }, [activeTab, fetchSessions]);

  // 切换到查询日志视图时加载，筛选变化时重新加载
  useEffect(() => {
    if (activeTab === 'overview' && overviewTable === 'nlq') {
      fetchQueryLogs();
    }
  }, [activeTab, overviewTable, fetchQueryLogs]);

  // 筛选变化时重置页码
  useEffect(() => {
    setQueryPage(1);
  }, [queryStatus, queryIntent, queryStartTime, queryEndTime]);

  // 点击行展开/折叠步骤
  const toggleExpand = (runId: string) => {
    if (expandedRunId === runId) {
      setExpandedRunId(null);
      setDiagnosticRunId(null);
      setSteps([]);
    } else {
      setExpandedRunId(runId);
      fetchSteps(runId);
    }
  };

  // 筛选切换时重置 offset
  const handleStatusChange = (s: StatusFilter) => {
    setStatusFilter(s);
    setOffset(0);
    setExpandedRunId(null);
    setDiagnosticRunId(null);
    setSteps([]);
  };

  const totalPages = Math.ceil(runsTotal / LIMIT);
  const currentPage = Math.floor(offset / LIMIT) + 1;

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-400 text-sm">加载中...</div>
      </div>
    );
  }

  const TABS_CONFIG: [ActiveTab, string][] = [
    ['overview', '总览'],
    ['tools', '工具列表'],
    ['sessions', '会话管理'],
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 页面标题 */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-robot-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">Agent 监控</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">
            Data Agent 调用量、成功率、耗时与反馈统计
          </p>
        </div>
      </div>

      {/* Tab 导航 */}
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-6xl mx-auto">
          <div className="flex gap-1 py-2">
            {TABS_CONFIG.map(([value, label]) => (
              <button
                key={value}
                onClick={() => setActiveTab(value)}
                className={`px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${
                  activeTab === value
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto">

      {/* Tab: 总览 */}
      {activeTab === 'overview' && (
        <>
      {/* 统计卡片 */}
      {stats && (
        <div className="grid grid-cols-5 gap-4 mb-6">
          {/* 总调用量 */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-blue-100 rounded-lg">
                <i className="ri-play-circle-line text-blue-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">{stats.total_runs}</div>
                <div className="text-xs text-slate-500">总调用量</div>
              </div>
            </div>
          </div>

          {/* 成功率 */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-emerald-100 rounded-lg">
                <i className="ri-percent-line text-emerald-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">
                  {(stats.success_rate * 100).toFixed(1)}%
                </div>
                <div className="text-xs text-slate-500">成功率</div>
              </div>
            </div>
          </div>

          {/* 平均耗时 */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-orange-100 rounded-lg">
                <i className="ri-time-line text-orange-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">
                  {formatMs(stats.avg_execution_time_ms)}
                </div>
                <div className="text-xs text-slate-500">平均耗时</div>
              </div>
            </div>
          </div>

          {/* P95 耗时 */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-purple-100 rounded-lg">
                <i className="ri-speed-line text-purple-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">
                  {formatMs(stats.p95_execution_time_ms)}
                </div>
                <div className="text-xs text-slate-500">P95 耗时</div>
              </div>
            </div>
          </div>

          {/* 今日调用 */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-cyan-100 rounded-lg">
                <i className="ri-calendar-todo-line text-cyan-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">{stats.runs_today}</div>
                <div className="text-xs text-slate-500">今日调用</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 反馈 + 热门工具 */}
      {stats && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          {/* 反馈汇总 */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100">
              <h3 className="text-sm font-semibold text-slate-700">用户反馈</h3>
            </div>
            <div className="flex flex-col">
              <div className="grid grid-cols-2 divide-x divide-slate-100">
                <div className="py-5 flex flex-col items-center gap-1.5">
                  <div className="w-8 h-8 flex items-center justify-center bg-emerald-100 rounded-full">
                    <i className="ri-thumb-up-line text-emerald-600 text-sm" />
                  </div>
                  <div className="text-lg font-bold text-slate-800">{stats.feedback_summary.up}</div>
                  <div className="text-xs text-slate-500">点赞</div>
                </div>
                <div className="py-5 flex flex-col items-center gap-1.5">
                  <div className="w-8 h-8 flex items-center justify-center bg-red-100 rounded-full">
                    <i className="ri-thumb-down-line text-red-600 text-sm" />
                  </div>
                  <div className="text-lg font-bold text-slate-800">{stats.feedback_summary.down}</div>
                  <div className="text-xs text-slate-500">报错</div>
                </div>
              </div>
              {(stats.feedback_summary.up + stats.feedback_summary.down) > 0 && (
                <div className="px-4 py-2 border-t border-slate-100 text-xs text-center text-slate-500">
                  满意率{' '}
                  <span className="font-semibold text-slate-700">
                    {(
                      (stats.feedback_summary.up /
                        (stats.feedback_summary.up + stats.feedback_summary.down)) *
                      100
                    ).toFixed(1)}
                    %
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* 热门工具 */}
          <div className="col-span-2 bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100">
              <h3 className="text-sm font-semibold text-slate-700">热门工具 Top 10</h3>
            </div>
            <div className="p-4">
              {stats.top_tools.length === 0 ? (
                <div className="text-sm text-slate-400">暂无数据</div>
              ) : (
                <div className="space-y-2">
                  {stats.top_tools.map((tool) => {
                    const maxCount = stats.top_tools[0]?.count || 1;
                    const pct = (tool.count / maxCount) * 100;
                    return (
                      <div key={tool.name} className="flex items-center gap-3">
                        <span className="text-xs text-slate-600 w-28 truncate shrink-0" title={tool.name}>
                          {tool.name}
                        </span>
                        <div className="flex-1 bg-slate-100 rounded-full h-2">
                          <div
                            className="bg-cyan-500 h-2 rounded-full transition-all"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-xs text-slate-500 w-12 text-right shrink-0">
                          {tool.count}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 运行记录 / 查询日志 */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        {/* 标题栏：视图切换 + 条件筛选 */}
        <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-3 flex-wrap">
          {/* 视图切换 */}
          <div className="flex gap-1">
            {([['runs', '运行记录'], ['nlq', '查询日志']] as [OverviewTable, string][]).map(([v, label]) => (
              <button
                key={v}
                onClick={() => setOverviewTable(v)}
                className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors ${
                  overviewTable === v
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* runs 视图：状态筛选 */}
          {overviewTable === 'runs' && (
            <div className="flex gap-1">
              {(
                [
                  ['all', '全部'],
                  ['completed', '成功'],
                  ['failed', '失败'],
                  ['running', '运行中'],
                ] as [StatusFilter, string][]
              ).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => handleStatusChange(value)}
                  className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors ${
                    statusFilter === value
                      ? 'bg-slate-700 text-white'
                      : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          <span className="ml-auto text-xs text-slate-400">
            共 {overviewTable === 'runs' ? runsTotal : queryTotal} 条
          </span>
        </div>

        {/* nlq 视图：筛选栏 */}
        {overviewTable === 'nlq' && (
          <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/50 flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-1 bg-white border border-slate-200 rounded-lg p-0.5">
              {(['all', 'success', 'failed'] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setQueryStatus(s)}
                  className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors ${
                    queryStatus === s
                      ? 'bg-slate-800 text-white'
                      : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  {s === 'all' ? '全部' : s === 'success' ? '成功' : '失败'}
                </button>
              ))}
            </div>
            <select
              value={queryIntent}
              onChange={(e) => setQueryIntent(e.target.value)}
              className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:border-blue-400"
            >
              {INTENT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <div className="flex items-center gap-1.5">
              <input
                type="datetime-local"
                value={queryStartTime}
                onChange={(e) => setQueryStartTime(e.target.value)}
                className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:border-blue-400"
              />
              <span className="text-slate-400 text-xs">至</span>
              <input
                type="datetime-local"
                value={queryEndTime}
                onChange={(e) => setQueryEndTime(e.target.value)}
                className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:border-blue-400"
              />
            </div>
            <button
              onClick={() => { const r = defaultRange(); setQueryStartTime(r.start); setQueryEndTime(r.end); }}
              className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
            >
              过去24小时
            </button>
            <button
              onClick={() => fetchQueryLogs()}
              className="ml-auto text-xs text-slate-400 hover:text-slate-600 flex items-center gap-1 transition-colors"
            >
              <i className="ri-refresh-line" />刷新
            </button>
          </div>
        )}

        {/* nlq 错误提示 */}
        {overviewTable === 'nlq' && queryErrorMsg && (
          <div className="mx-4 mt-3 px-3 py-2 border rounded-lg text-xs bg-red-50 text-red-700 border-red-200">
            {queryErrorMsg}
          </div>
        )}

        {/* 表格：runs */}
        {overviewTable === 'runs' && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 text-slate-500 text-xs">
                    <th className="text-left px-4 py-2.5 font-medium">Run ID</th>
                    <th className="text-left px-4 py-2.5 font-medium">时间</th>
                    <th className="text-left px-4 py-2.5 font-medium">用户</th>
                    <th className="text-left px-4 py-2.5 font-medium">问题</th>
                    <th className="text-left px-4 py-2.5 font-medium">状态</th>
                    <th className="text-left px-4 py-2.5 font-medium">耗时</th>
                    <th className="text-left px-4 py-2.5 font-medium">反馈</th>
                    <th className="text-left px-4 py-2.5 font-medium">工具</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {runs.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="px-4 py-8 text-center text-slate-400">
                        <i className="ri-robot-line text-3xl mb-2 block" />
                        暂无运行记录
                      </td>
                    </tr>
                  ) : (
                    runs.map((run) => (
                      <Fragment key={run.id}>
                        <tr
                          className={`hover:bg-slate-50/50 cursor-pointer transition-colors ${
                            expandedRunId === run.id ? 'bg-cyan-50/30' : ''
                          }`}
                          onClick={() => toggleExpand(run.id)}
                        >
                          <td className="px-4 py-3">
                            <RunIdCell id={run.id} />
                          </td>
                          <td className="px-4 py-3 text-slate-500 whitespace-nowrap">
                            {formatDate(run.created_at)}
                          </td>
                          <td className="px-4 py-3 text-slate-700 whitespace-nowrap">
                            {run.username ?? `#${run.user_id}`}
                          </td>
                          <td className="px-4 py-3 text-slate-700 max-w-xs truncate" title={run.question}>
                            {run.question}
                          </td>
                          <td className="px-4 py-3">{statusBadge(run.status)}</td>
                          <td className="px-4 py-3 text-slate-500 whitespace-nowrap">
                            {formatMs(run.execution_time_ms)}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap">
                            {run.feedback === 'up' && (
                              <span className="inline-flex items-center gap-1 text-xs text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                                <i className="ri-thumb-up-line" />有用
                              </span>
                            )}
                            {run.feedback === 'down' && (
                              <span className="inline-flex items-center gap-1 text-xs text-red-500 bg-red-50 px-1.5 py-0.5 rounded">
                                <i className="ri-error-warning-line" />报错
                              </span>
                            )}
                            {!run.feedback && <span className="text-xs text-slate-300">-</span>}
                          </td>
                          <td className="px-4 py-3">
                            {run.tools_used && run.tools_used.length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {run.tools_used.slice(0, 3).map((t) => (
                                  <span key={t} className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded">
                                    {t}
                                  </span>
                                ))}
                                {run.tools_used.length > 3 && (
                                  <span className="text-xs text-slate-400">+{run.tools_used.length - 3}</span>
                                )}
                              </div>
                            ) : (
                              <span className="text-xs text-slate-400">-</span>
                            )}
                          </td>
                        </tr>
                        {expandedRunId === run.id && (
                          <tr>
                            <td colSpan={8} className="px-0 py-0">
                              <div className="bg-slate-50/80 border-t border-slate-200 px-6 py-4">
                                <div className="flex items-center justify-between gap-3 mb-3">
                                  <h4 className="text-xs font-semibold text-slate-500">执行步骤</h4>
                                  <button
                                    type="button"
                                    onClick={() => setDiagnosticRunId((current) => (current === run.id ? null : run.id))}
                                    className="inline-flex items-center gap-1.5 rounded-md border border-blue-200 bg-white px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50"
                                  >
                                    <i className="ri-stethoscope-line" />
                                    诊断
                                  </button>
                                </div>
                                {stepsLoading ? (
                                  <div className="text-sm text-slate-400 py-2">加载中...</div>
                                ) : steps.length === 0 ? (
                                  <div className="text-sm text-slate-400 py-2">暂无步骤记录</div>
                                ) : (
                                  <div className="space-y-2">
                                    <StepDurationSummary steps={steps} totalMs={run.execution_time_ms} />
                                    {steps.map((step) => (
                                      <div key={step.id} className="bg-white rounded-lg border border-slate-200 p-3">
                                        <div className="flex items-center gap-3 mb-1.5">
                                          <span className="text-xs text-slate-400 w-6 text-center">#{step.step_number}</span>
                                          {stepTypeBadge(step.step_type)}
                                          {step.tool_name && (
                                            <span className="text-xs bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded">
                                              {step.tool_name}
                                            </span>
                                          )}
                                          <span
                                            className={`text-xs px-1.5 py-0.5 rounded ml-auto ${stepDurationClass(step.execution_time_ms)}`}
                                            title={stepDurationTitle(step)}
                                          >
                                            {formatStepMs(step)}
                                          </span>
                                        </div>
                                        {step.content && (
                                          <div className="text-xs text-slate-600 ml-9 whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
                                            {step.content}
                                          </div>
                                        )}
                                        {step.tool_result_summary && (
                                          <div className="text-xs text-slate-500 ml-9 mt-1 whitespace-pre-wrap break-words max-h-24 overflow-y-auto bg-slate-50 rounded p-2">
                                            {step.tool_result_summary}
                                          </div>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}
                                {diagnosticRunId === run.id && (
                                  <InlineDiagnosticPanel
                                    runId={run.id}
                                    defaultQuestion="请诊断这个 run 的失败原因和耗时瓶颈。"
                                    visibleState={{ status: run.status, expanded: true }}
                                  />
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && (
              <div className="px-4 py-3 border-t border-slate-100 flex items-center justify-between">
                <span className="text-xs text-slate-400">第 {currentPage} / {totalPages} 页</span>
                <div className="flex items-center gap-2">
                  <button
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - LIMIT))}
                    className="px-3 py-1.5 text-xs rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    上一页
                  </button>
                  <button
                    disabled={offset + LIMIT >= runsTotal}
                    onClick={() => setOffset(offset + LIMIT)}
                    className="px-3 py-1.5 text-xs rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    下一页
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {/* 表格：nlq */}
        {overviewTable === 'nlq' && (
          <>
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50 text-slate-500 text-xs">
                  <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">Run ID</th>
                  <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">时间</th>
                  <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">用户</th>
                  <th className="text-left px-4 py-2.5 font-medium">问题</th>
                  <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">意图</th>
                  <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">耗时</th>
                  <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {queryLoading ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-slate-400">
                      <i className="ri-loader-4-line text-2xl animate-spin mb-2 block" />加载中...
                    </td>
                  </tr>
                ) : queryItems.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-slate-400">
                      <i className="ri-file-list-3-line text-3xl mb-2 block" />暂无记录
                    </td>
                  </tr>
                ) : (
                  queryItems.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-50/50">
                      <td className="px-4 py-3">
                        <RunIdCell id={log.run_id ?? `nlq-${log.id}`} />
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                        {formatDateTime(log.created_at)}
                      </td>
                      <td className="px-4 py-3 text-sm font-medium text-slate-700">{log.username ?? '-'}</td>
                      <td className="px-4 py-3 max-w-sm">
                        <span className="text-sm text-slate-800 block truncate" title={log.question}>
                          {truncate(log.question)}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {log.intent ? (
                          <span className="text-xs px-2 py-1 bg-blue-50 text-blue-700 border border-blue-200 rounded-full">
                            {log.intent}
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                        {log.execution_time_ms == null ? '-' : log.execution_time_ms < 1000 ? `${log.execution_time_ms}ms` : `${(log.execution_time_ms / 1000).toFixed(1)}s`}
                      </td>
                      <td className="px-4 py-3">
                        {log.success ? (
                          <span className="text-xs font-medium px-2 py-1 rounded-full bg-emerald-50 text-emerald-700">成功</span>
                        ) : (
                          <span className="text-xs font-medium px-2 py-1 rounded-full bg-red-50 text-red-600" title={log.error_code ?? undefined}>
                            失败{log.error_code ? `·${log.error_code}` : ''}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
            {Math.ceil(queryTotal / queryPageSize) > 1 && (
              <div className="px-4 py-3 border-t border-slate-100 flex items-center justify-between">
                <span className="text-xs text-slate-400">
                  共 {queryTotal} 条，第 {queryPage} / {Math.ceil(queryTotal / queryPageSize)} 页
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setQueryPage((p) => Math.max(1, p - 1))}
                    disabled={queryPage === 1}
                    className="px-3 py-1.5 text-xs border border-slate-200 rounded-lg disabled:opacity-40 hover:bg-slate-50 transition-colors"
                  >
                    上一页
                  </button>
                  <button
                    onClick={() => setQueryPage((p) => Math.min(Math.ceil(queryTotal / queryPageSize), p + 1))}
                    disabled={queryPage === Math.ceil(queryTotal / queryPageSize)}
                    className="px-3 py-1.5 text-xs border border-slate-200 rounded-lg disabled:opacity-40 hover:bg-slate-50 transition-colors"
                  >
                    下一页
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
        </>
      )}

      {/* Tab: 工具列表 */}
      {activeTab === 'tools' && (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-700">可用工具</h3>
            <span className="text-xs text-slate-400">共 {tools.length} 个工具</span>
          </div>
          {toolsLoading ? (
            <div className="p-8 text-center text-slate-400">加载中...</div>
          ) : tools.length === 0 ? (
            <div className="p-8 text-center text-slate-400">暂无已注册的工具</div>
          ) : (
            <div className="divide-y divide-slate-100">
              {tools.map((tool) => (
                <div key={tool.name} className="px-4 py-4 hover:bg-slate-50/50 transition-colors">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="text-sm font-medium text-slate-800">{tool.name}</span>
                    <span className="text-xs bg-cyan-50 text-cyan-700 px-2 py-0.5 rounded-full">
                      {tool.category}
                    </span>
                    <span className="text-xs text-slate-400">v{tool.version}</span>
                  </div>
                  <p className="text-xs text-slate-600 mb-2">{tool.description}</p>
                  <div className="flex items-center gap-4">
                    {tool.dependencies.length > 0 && (
                      <div className="flex items-center gap-1">
                        <span className="text-xs text-slate-400">依赖:</span>
                        {tool.dependencies.map((dep) => (
                          <span
                            key={dep}
                            className="text-xs bg-orange-50 text-orange-600 px-1.5 py-0.5 rounded"
                          >
                            {dep}
                          </span>
                        ))}
                      </div>
                    )}
                    {tool.tags.length > 0 && (
                      <div className="flex items-center gap-1">
                        <span className="text-xs text-slate-400">标签:</span>
                        {tool.tags.map((tag) => (
                          <span
                            key={tag}
                            className="text-xs bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab: 会话管理 */}
      {activeTab === 'sessions' && (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-700">Agent 会话</h3>
            <span className="text-xs text-slate-400">共 {sessionsTotal} 个会话</span>
          </div>
          {sessionsLoading ? (
            <div className="p-8 text-center text-slate-400">加载中...</div>
          ) : sessions.length === 0 ? (
            <div className="p-8 text-center text-slate-400">
              <i className="ri-chat-3-line text-3xl mb-2 block" />
              暂无会话记录
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50 text-slate-500 text-xs">
                      <th className="text-left px-4 py-2.5 font-medium">更新时间</th>
                      <th className="text-left px-4 py-2.5 font-medium">用户</th>
                      <th className="text-left px-4 py-2.5 font-medium">标题</th>
                      <th className="text-left px-4 py-2.5 font-medium">状态</th>
                      <th className="text-left px-4 py-2.5 font-medium">消息数</th>
                      <th className="text-left px-4 py-2.5 font-medium">数据源</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {sessions.map((s) => (
                      <tr key={s.id} className="hover:bg-slate-50/50 transition-colors">
                        <td className="px-4 py-3 text-slate-500 whitespace-nowrap">
                          {formatDate(s.updated_at)}
                        </td>
                        <td className="px-4 py-3 text-slate-700 whitespace-nowrap">
                          #{s.user_id}
                        </td>
                        <td className="px-4 py-3 text-slate-700 max-w-xs truncate" title={s.title ?? ''}>
                          {s.title || <span className="text-slate-400">无标题</span>}
                        </td>
                        <td className="px-4 py-3">{statusBadge(s.status)}</td>
                        <td className="px-4 py-3 text-slate-600">{s.message_count}</td>
                        <td className="px-4 py-3 text-slate-500">
                          {s.connection_id ? `#${s.connection_id}` : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* 会话分页 */}
              {Math.ceil(sessionsTotal / LIMIT) > 1 && (
                <div className="px-4 py-3 border-t border-slate-100 flex items-center justify-between">
                  <span className="text-xs text-slate-400">
                    第 {Math.floor(sessionsOffset / LIMIT) + 1} / {Math.ceil(sessionsTotal / LIMIT)} 页
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      disabled={sessionsOffset === 0}
                      onClick={() => setSessionsOffset(Math.max(0, sessionsOffset - LIMIT))}
                      className="px-3 py-1.5 text-xs rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      上一页
                    </button>
                    <button
                      disabled={sessionsOffset + LIMIT >= sessionsTotal}
                      onClick={() => setSessionsOffset(sessionsOffset + LIMIT)}
                      className="px-3 py-1.5 text-xs rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      下一页
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      </div>
    </div>
      </div>
  );
}
