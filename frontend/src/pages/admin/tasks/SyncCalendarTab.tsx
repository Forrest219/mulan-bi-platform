import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchSyncOverview,
  type SyncFieldCompleteness,
  type SyncOverviewConnection,
  type SyncOverviewResponse,
  type SyncOverviewStatus,
  type SyncOverviewTimelineItem,
} from '../../../api/tasks';

const STATUS_STYLE: Record<string, { bg: string; text: string; label: string }> = {
  succeeded: { bg: 'bg-emerald-100', text: 'text-emerald-700', label: '成功' },
  completed: { bg: 'bg-emerald-100', text: 'text-emerald-700', label: '成功' },
  running: { bg: 'bg-blue-100', text: 'text-blue-700', label: '同步中' },
  pending: { bg: 'bg-slate-100', text: 'text-slate-500', label: '待同步' },
  failed: { bg: 'bg-red-100', text: 'text-red-700', label: '失败' },
  skipped: { bg: 'bg-amber-100', text: 'text-amber-700', label: '已跳过' },
  cancelled: { bg: 'bg-amber-100', text: 'text-amber-700', label: '已取消' },
  idle: { bg: 'bg-slate-100', text: 'text-slate-500', label: '空闲' },
  unknown: { bg: 'bg-slate-100', text: 'text-slate-500', label: '未知' },
};

const HEALTH_STYLE: Record<string, { bg: string; text: string; label: string }> = {
  healthy: { bg: 'bg-emerald-100', text: 'text-emerald-700', label: '健康' },
  warning: { bg: 'bg-amber-100', text: 'text-amber-700', label: '告警' },
  error: { bg: 'bg-red-100', text: 'text-red-700', label: '异常' },
  disabled: { bg: 'bg-slate-100', text: 'text-slate-500', label: '未启用' },
  unknown: { bg: 'bg-slate-100', text: 'text-slate-500', label: '未知' },
};

const EMPTY_FIELD_COMPLETENESS: SyncFieldCompleteness = {
  datasource_total: 0,
  datasource_with_fields: 0,
  fields_total: 0,
  empty: 0,
  failed: 0,
};

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function formatFieldCompleteness(value: SyncFieldCompleteness | null | undefined): string {
  const fields = value ?? EMPTY_FIELD_COMPLETENESS;
  if (fields.datasource_total === 0 && fields.fields_total === 0) return '—';
  return `${fields.datasource_with_fields}/${fields.datasource_total} 数据源，${fields.fields_total} 字段`;
}

function fieldCompletenessRate(value: SyncFieldCompleteness | null | undefined): number | null {
  if (!value || value.datasource_total === 0) return null;
  return Math.round((value.datasource_with_fields / value.datasource_total) * 100);
}

function StatusBadge({ status }: { status: SyncOverviewStatus | string | null | undefined }) {
  const cfg = STATUS_STYLE[status || 'unknown'] ?? STATUS_STYLE.unknown;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${cfg.bg} ${cfg.text}`}>
      {cfg.label}
    </span>
  );
}

function HealthBadge({ status }: { status: string | null | undefined }) {
  const cfg = HEALTH_STYLE[status || 'unknown'] ?? HEALTH_STYLE.unknown;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${cfg.bg} ${cfg.text}`}>
      {cfg.label}
    </span>
  );
}

function OverviewMetric({
  label,
  value,
  note,
  tone = 'text-slate-800',
}: {
  label: string;
  value: string | number;
  note?: string;
  tone?: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 px-4 py-3 min-h-[88px]">
      <div className="text-[11px] text-slate-400 mb-2">{label}</div>
      <div className={`text-[20px] leading-tight font-semibold ${tone}`}>{value}</div>
      {note && <div className="text-[11px] text-slate-400 mt-1.5">{note}</div>}
    </div>
  );
}

function TimelineGroup({ title, items }: { title: string; items: SyncOverviewTimelineItem[] }) {
  return (
    <div className="min-w-0">
      <div className="px-4 py-3 border-b border-slate-100 bg-slate-50">
        <div className="flex items-center justify-between">
          <h3 className="text-[12px] font-semibold text-slate-700">{title}</h3>
          <span className="text-[11px] text-slate-400">{items.length} 项</span>
        </div>
      </div>
      <div className="divide-y divide-slate-100">
        {items.length === 0 ? (
          <div className="px-4 py-10 text-center text-[13px] text-slate-400">暂无同步项</div>
        ) : (
          items.map((item, idx) => (
            <div key={`${item.scheduled_at}-${item.connection_id}-${idx}`} className="px-4 py-3 hover:bg-slate-50/60">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[13px] font-medium text-slate-700 truncate">{item.connection_name}</div>
                  <div className="text-[12px] text-slate-400 mt-0.5 truncate">同步规则：{item.schedule_name || '未绑定'}</div>
                  {item.warning && <div className="text-[11px] text-amber-600 mt-1 truncate">{item.warning}</div>}
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[12px] font-mono text-slate-600">{formatTime(item.scheduled_at)}</div>
                  <div className="mt-1">
                    <StatusBadge status={item.status} />
                  </div>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function ConnectionWarnings({ connection }: { connection: SyncOverviewConnection }) {
  if (!connection.warnings || connection.warnings.length === 0) return null;
  return (
    <div className="mt-1 text-[11px] text-amber-600">
      {connection.warnings.slice(0, 2).join('；')}
    </div>
  );
}

export default function SyncCalendarTab() {
  const [data, setData] = useState<SyncOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await fetchSyncOverview();
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载同步日历失败');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const timeline = data?.timeline ?? { today: [], tomorrow: [], future_48h: [] };
  const totalTimelineItems = timeline.today.length + timeline.tomorrow.length + timeline.future_48h.length;
  const isEmpty = !loading && !error && (!data || (data.connections.length === 0 && totalTimelineItems === 0));

  const healthWarnings = useMemo(() => {
    const warnings = data?.health?.warnings ?? [];
    return warnings.filter(Boolean);
  }, [data?.health?.warnings]);

  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 py-16 text-center text-[13px] text-slate-400">
        <i className="ri-loader-4-line animate-spin mr-2" />
        同步日历加载中…
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 px-6 py-10 text-center">
        <i className="ri-error-warning-line text-3xl text-red-400 block mb-2" />
        <div className="text-[13px] text-red-600 mb-4">{error}</div>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] rounded-lg bg-slate-800 text-white hover:bg-slate-700"
        >
          <i className="ri-refresh-line" />
          重试
        </button>
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 px-6 py-16 text-center">
        <i className="ri-calendar-check-line text-3xl text-slate-300 block mb-2" />
        <div className="text-[13px] text-slate-500">暂无同步日历数据</div>
        <div className="text-[12px] text-slate-400 mt-1">开启连接自动同步并绑定同步规则后，这里会显示下次同步和字段完整度。</div>
      </div>
    );
  }

  const summary = data?.summary;
  const fieldRate = fieldCompletenessRate(summary?.field_completeness);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[13px] font-semibold text-slate-700">同步日历</h2>
          <p className="text-[12px] text-slate-400 mt-0.5">Tableau 自动同步安排与字段同步结果</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors"
        >
          <i className="ri-refresh-line" />
          刷新
        </button>
      </div>

      {healthWarnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 text-amber-700 text-[12px] rounded-lg px-4 py-3">
          {healthWarnings.join('；')}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        <OverviewMetric label="下次同步" value={formatDateTime(summary?.next_sync_at)} note="最近一项自动同步计划" />
        <OverviewMetric label="明天同步数" value={summary?.tomorrow_sync_count ?? 0} note="按当前同步规则计算" />
        <OverviewMetric
          label="最近同步状态"
          value={STATUS_STYLE[summary?.latest_sync_status || 'unknown']?.label ?? '未知'}
          note={formatDateTime(summary?.latest_sync_at)}
          tone={summary?.latest_sync_status === 'failed' ? 'text-red-600' : 'text-slate-800'}
        />
        <OverviewMetric
          label="字段完整度"
          value={fieldRate == null ? '—' : `${fieldRate}%`}
          note={formatFieldCompleteness(summary?.field_completeness)}
          tone={fieldRate != null && fieldRate < 100 ? 'text-amber-600' : 'text-slate-800'}
        />
      </div>

      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
          <h3 className="text-[12px] font-semibold text-slate-700">连接列表</h3>
          <span className="text-[11px] text-slate-400">{data?.connections.length ?? 0} 个连接</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px]">
            <thead>
              <tr className="border-b border-slate-100">
                {['连接名', '同步规则', '下次同步', '上次同步', '字段完整度', '健康/告警'].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-[11px] font-medium text-slate-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data?.connections.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-[13px] text-slate-400">暂无连接数据</td>
                </tr>
              ) : (
                data?.connections.map((connection) => {
                  const connectionFieldRate = fieldCompletenessRate(connection.field_completeness);
                  return (
                    <tr key={connection.id} className="hover:bg-slate-50/60">
                      <td className="px-4 py-3">
                        <div className="text-[13px] font-medium text-slate-700">{connection.name}</div>
                        <div className="text-[11px] text-slate-400 mt-0.5">{connection.site || connection.server_url || '—'}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-[12px] text-slate-700">{connection.sync_rule?.name || '未绑定'}</div>
                        <div className="text-[11px] text-slate-400 mt-0.5">{connection.sync_rule?.cron_description || connection.sync_rule?.cron_expr || '—'}</div>
                      </td>
                      <td className="px-4 py-3 text-[12px] text-slate-600">{formatDateTime(connection.next_sync_at)}</td>
                      <td className="px-4 py-3">
                        <div className="text-[12px] text-slate-600">{formatDateTime(connection.last_sync?.finished_at ?? connection.last_sync?.started_at)}</div>
                        <div className="mt-1"><StatusBadge status={connection.last_sync?.status} /></div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-[12px] text-slate-700">{formatFieldCompleteness(connection.field_completeness)}</div>
                        <div className="text-[11px] text-slate-400 mt-0.5">
                          {connectionFieldRate == null ? '—' : `${connectionFieldRate}%`}
                          {connection.field_completeness.failed > 0 ? `，失败 ${connection.field_completeness.failed}` : ''}
                          {connection.field_completeness.empty > 0 ? `，空 ${connection.field_completeness.empty}` : ''}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <HealthBadge status={connection.health_status} />
                        <ConnectionWarnings connection={connection} />
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
          <h3 className="text-[12px] font-semibold text-slate-700">时间线</h3>
          <span className="text-[11px] text-slate-400">今天、明天、未来 48h</span>
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-3 divide-y xl:divide-y-0 xl:divide-x divide-slate-100">
          <TimelineGroup title="今天" items={timeline.today} />
          <TimelineGroup title="明天" items={timeline.tomorrow} />
          <TimelineGroup title="未来 48h" items={timeline.future_48h} />
        </div>
      </div>
    </div>
  );
}
