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
import { useState, useEffect, useCallback } from 'react';
import { agentAdminApi, type AgentStats, type AgentRun, type AgentRunsResponse, type AgentStep } from '../../../api/agent';

// ─── Types ───────────────────────────────────────────────────────────────────

type StatusFilter = 'all' | 'running' | 'completed' | 'error';

// ─── Helpers ─────────────────────────────────────────────────────────────────

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

function statusBadge(status: string) {
  const map: Record<string, { bg: string; text: string; label: string }> = {
    running: { bg: 'bg-blue-50', text: 'text-blue-700', label: '运行中' },
    completed: { bg: 'bg-emerald-50', text: 'text-emerald-700', label: '成功' },
    error: { bg: 'bg-red-50', text: 'text-red-700', label: '失败' },
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
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [offset, setOffset] = useState(0);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [stepsLoading, setStepsLoading] = useState(false);

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

  useEffect(() => {
    Promise.all([fetchStats(), fetchRuns()]).finally(() => setLoading(false));
  }, [fetchStats, fetchRuns]);

  // 点击行展开/折叠步骤
  const toggleExpand = (runId: string) => {
    if (expandedRunId === runId) {
      setExpandedRunId(null);
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
    setSteps([]);
  };

  const totalPages = Math.ceil(runsTotal / LIMIT);
  const currentPage = Math.floor(offset / LIMIT) + 1;

  if (loading) {
    return <div className="p-8 text-center text-slate-400">加载中...</div>;
  }

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-slate-800">Agent 监控</h1>
        <p className="text-sm text-slate-400 mt-0.5">
          Data Agent 调用量、成功率、耗时与反馈统计
        </p>
      </div>

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
            <div className="p-4 flex items-center gap-6">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 flex items-center justify-center bg-emerald-100 rounded-full">
                  <i className="ri-thumb-up-line text-emerald-600 text-sm" />
                </div>
                <div>
                  <div className="text-lg font-bold text-slate-800">
                    {stats.feedback_summary.up}
                  </div>
                  <div className="text-xs text-slate-500">点赞</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 flex items-center justify-center bg-red-100 rounded-full">
                  <i className="ri-thumb-down-line text-red-600 text-sm" />
                </div>
                <div>
                  <div className="text-lg font-bold text-slate-800">
                    {stats.feedback_summary.down}
                  </div>
                  <div className="text-xs text-slate-500">点踩</div>
                </div>
              </div>
              {(stats.feedback_summary.up + stats.feedback_summary.down) > 0 && (
                <div className="ml-auto text-sm text-slate-500">
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

      {/* 运行列表 */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        {/* 标题 + 筛选 */}
        <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h3 className="text-sm font-semibold text-slate-700">近期运行</h3>
            <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
              {(
                [
                  ['all', '全部'],
                  ['completed', '成功'],
                  ['error', '失败'],
                  ['running', '运行中'],
                ] as [StatusFilter, string][]
              ).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => handleStatusChange(value)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                    statusFilter === value
                      ? 'bg-white text-slate-700 shadow-sm'
                      : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <span className="text-xs text-slate-400">共 {runsTotal} 条</span>
        </div>

        {/* 表格 */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-slate-500 text-xs">
                <th className="text-left px-4 py-2.5 font-medium">时间</th>
                <th className="text-left px-4 py-2.5 font-medium">用户</th>
                <th className="text-left px-4 py-2.5 font-medium">问题</th>
                <th className="text-left px-4 py-2.5 font-medium">状态</th>
                <th className="text-left px-4 py-2.5 font-medium">耗时</th>
                <th className="text-left px-4 py-2.5 font-medium">工具</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {runs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                    <i className="ri-robot-line text-3xl mb-2 block" />
                    暂无运行记录
                  </td>
                </tr>
              ) : (
                runs.map((run) => (
                  <>
                    <tr
                      key={run.id}
                      className={`hover:bg-slate-50/50 cursor-pointer transition-colors ${
                        expandedRunId === run.id ? 'bg-cyan-50/30' : ''
                      }`}
                      onClick={() => toggleExpand(run.id)}
                    >
                      <td className="px-4 py-3 text-slate-500 whitespace-nowrap">
                        {formatDate(run.created_at)}
                      </td>
                      <td className="px-4 py-3 text-slate-700 whitespace-nowrap">
                        #{run.user_id}
                      </td>
                      <td className="px-4 py-3 text-slate-700 max-w-xs truncate" title={run.question}>
                        {run.question}
                      </td>
                      <td className="px-4 py-3">{statusBadge(run.status)}</td>
                      <td className="px-4 py-3 text-slate-500 whitespace-nowrap">
                        {formatMs(run.execution_time_ms)}
                      </td>
                      <td className="px-4 py-3">
                        {run.tools_used && run.tools_used.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {run.tools_used.slice(0, 3).map((t) => (
                              <span
                                key={t}
                                className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded"
                              >
                                {t}
                              </span>
                            ))}
                            {run.tools_used.length > 3 && (
                              <span className="text-xs text-slate-400">
                                +{run.tools_used.length - 3}
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-xs text-slate-400">-</span>
                        )}
                      </td>
                    </tr>
                    {/* 展开的步骤详情 */}
                    {expandedRunId === run.id && (
                      <tr key={`${run.id}-steps`}>
                        <td colSpan={6} className="px-0 py-0">
                          <div className="bg-slate-50/80 border-t border-slate-200 px-6 py-4">
                            <h4 className="text-xs font-semibold text-slate-500 mb-3">
                              执行步骤
                            </h4>
                            {stepsLoading ? (
                              <div className="text-sm text-slate-400 py-2">加载中...</div>
                            ) : steps.length === 0 ? (
                              <div className="text-sm text-slate-400 py-2">暂无步骤记录</div>
                            ) : (
                              <div className="space-y-2">
                                {steps.map((step) => (
                                  <div
                                    key={step.id}
                                    className="bg-white rounded-lg border border-slate-200 p-3"
                                  >
                                    <div className="flex items-center gap-3 mb-1.5">
                                      <span className="text-xs text-slate-400 w-6 text-center">
                                        #{step.step_number}
                                      </span>
                                      {stepTypeBadge(step.step_type)}
                                      {step.tool_name && (
                                        <span className="text-xs bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded">
                                          {step.tool_name}
                                        </span>
                                      )}
                                      <span className="text-xs text-slate-400 ml-auto">
                                        {formatMs(step.execution_time_ms)}
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
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {totalPages > 1 && (
          <div className="px-4 py-3 border-t border-slate-100 flex items-center justify-between">
            <span className="text-xs text-slate-400">
              第 {currentPage} / {totalPages} 页
            </span>
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
      </div>
    </div>
  );
}
