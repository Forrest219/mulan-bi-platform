import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  Database,
  GitBranch,
  ListChecks,
  Route,
  ShieldCheck,
  ShieldAlert,
  Wrench,
  XCircle,
} from 'lucide-react';
import type {
  AgentExplainability,
  ExecutionExplainStep,
  ExplainabilityPhase,
  ExplainabilityStatus,
  FallbackExplain,
  IntentExplain,
  McpProxyExplain,
  McpProxyRepairExplain,
  PlanExplain,
  PostprocessExplain,
} from '../../../api/agent';

interface AnalysisProcessBlockProps {
  explainability?: AgentExplainability | null;
  isStreaming?: boolean;
  compact?: boolean;
}

type PhaseView = {
  phase: ExplainabilityPhase;
  label: string;
  status: ExplainabilityStatus;
  summary: string;
  body: ReactNode;
};

const statusStyle: Record<ExplainabilityStatus, { text: string; icon: ReactNode; className: string }> = {
  pending: {
    text: '等待中',
    icon: <CircleDashed className="h-3.5 w-3.5" />,
    className: 'bg-slate-50 text-slate-500 border-slate-200',
  },
  running: {
    text: '执行中',
    icon: <CircleDashed className="h-3.5 w-3.5 animate-spin" />,
    className: 'bg-blue-50 text-blue-600 border-blue-100',
  },
  completed: {
    text: '完成',
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    className: 'bg-emerald-50 text-emerald-600 border-emerald-100',
  },
  failed: {
    text: '失败',
    icon: <XCircle className="h-3.5 w-3.5" />,
    className: 'bg-red-50 text-red-600 border-red-100',
  },
  skipped: {
    text: '跳过',
    icon: <CircleDashed className="h-3.5 w-3.5" />,
    className: 'bg-slate-50 text-slate-400 border-slate-200',
  },
};

const phaseIcon: Record<ExplainabilityPhase, ReactNode> = {
  intent: <ShieldCheck className="h-4 w-4" />,
  plan: <Route className="h-4 w-4" />,
  execution: <Wrench className="h-4 w-4" />,
  postprocess: <ListChecks className="h-4 w-4" />,
  fallback: <GitBranch className="h-4 w-4" />,
};

function textList(items?: string[], empty = '未指定') {
  if (!items?.length) return empty;
  return items.join('、');
}

function formatMs(value?: number) {
  if (value == null) return null;
  if (value < 1000) return `${value}ms`;
  return `${(value / 1000).toFixed(1)}s`;
}

function Confidence({ value }: { value?: number }) {
  if (value == null) return null;
  const percent = Math.round(value * 100);
  return (
    <span className="inline-flex items-center rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
      置信度 {percent}%
    </span>
  );
}

function InlineMeta({ children }: { children: ReactNode }) {
  return <span className="inline-flex items-center rounded bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500">{children}</span>;
}

function valueText(value: unknown) {
  if (value == null || value === '') return null;
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  return null;
}

function repairSummary(repair: McpProxyRepairExplain): string | null {
  const before = valueText(repair.before);
  const after = valueText(repair.after);
  if ((repair.type === 'field_mapping' || repair.type === 'field_case') && before && after) {
    return `已将 ${before} 映射为 ${after}`;
  }
  if ((repair.type === 'limit_default' || repair.type === 'limit_clamp') && after) {
    return `已限制最多返回 ${after} 行`;
  }
  if (repair.type === 'enum_case' && before && after) {
    return `已将 ${before} 规范为 ${after}`;
  }
  if (after && repair.path?.toLowerCase().includes('limit')) {
    return `已限制最多返回 ${after} 行`;
  }
  return repair.reason ? `已进行安全修正：${repair.reason}` : null;
}

function rejectSummary(mcpProxy: McpProxyExplain): string | null {
  if (mcpProxy.reject_code === 'MCP_ARGS_UNSAFE_DETAIL_SCAN') return '已阻止未受控明细扫描';
  if (mcpProxy.reject_code === 'MCP_ARGS_UNSAFE_OPERATION') return '已阻止危险操作';
  if (mcpProxy.reject_code === 'MCP_ARGS_DATASOURCE_FORBIDDEN') return '已阻止未授权数据源访问';
  if (mcpProxy.reject_code === 'MCP_ARGS_RESULT_TOO_WIDE') return '已阻止过宽结果查询';
  if (mcpProxy.reject_code === 'MCP_ARGS_UNKNOWN_FIELD') return '已阻止无法确认字段的查询';
  return mcpProxy.message ?? mcpProxy.user_hint ?? null;
}

function guardrailDecisionText(decision?: string) {
  if (decision === 'allow') return 'Guardrail 已通过';
  if (decision === 'repair') return 'Guardrail 已克制修正';
  if (decision === 'reject') return 'Guardrail 已阻止';
  return decision ? `Guardrail ${decision}` : 'Guardrail 已检查';
}

function McpProxyBody({ mcpProxy }: { mcpProxy?: McpProxyExplain }) {
  if (!mcpProxy || mcpProxy.chain_mode !== 'mcp_proxy') return null;

  const repairSummaries = (mcpProxy.guardrail_repairs ?? [])
    .map(repairSummary)
    .filter((item): item is string => Boolean(item));
  const reject = mcpProxy.guardrail_decision === 'reject' ? rejectSummary(mcpProxy) : null;

  return (
    <div className="mt-2 rounded-md border border-sky-100 bg-sky-50/70 px-2.5 py-2 text-xs text-slate-600" data-testid="analysis-mcp-proxy">
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <span className="inline-flex items-center gap-1 rounded border border-sky-200 bg-white px-1.5 py-0.5 text-[10px] font-medium text-sky-700">
          <ShieldAlert className="h-3 w-3" />
          MCP Proxy 链路
        </span>
        <InlineMeta>{guardrailDecisionText(mcpProxy.guardrail_decision)}</InlineMeta>
      </div>
      {repairSummaries.length ? (
        <div className="space-y-1 text-[11px] text-slate-600">
          {repairSummaries.slice(0, 4).map((summary, index) => (
            <div key={`${summary}-${index}`}>{summary}</div>
          ))}
        </div>
      ) : null}
      {reject && <p className="text-[11px] leading-relaxed text-amber-700">{reject}</p>}
      {mcpProxy.guardrail_decision === 'allow' && !repairSummaries.length && !reject && (
        <p className="text-[11px] text-slate-500">参数已通过安全、字段、权限与规模检查。</p>
      )}
    </div>
  );
}

function IntentBody({ intent }: { intent?: IntentExplain }) {
  if (!intent) return null;
  const decision = intent.guardrail?.decision;
  return (
    <div className="space-y-2 text-xs text-slate-600">
      <div className="flex flex-wrap items-center gap-1.5">
        <InlineMeta>任务 {intent.intent}</InlineMeta>
        <InlineMeta>策略 {intent.strategy}</InlineMeta>
        <Confidence value={intent.confidence} />
        {decision && <InlineMeta>Guardrail {decision}</InlineMeta>}
      </div>
      {intent.guardrail?.message && <p className="leading-relaxed text-slate-500">{intent.guardrail.message}</p>}
      {intent.entities?.length ? (
        <div className="flex flex-wrap gap-1.5">
          {intent.entities.map((entity, index) => (
            <span key={`${entity.type}-${entity.name}-${index}`} className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500">
              {entity.type}: {entity.canonical ?? entity.name}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PlanBody({ plan }: { plan?: PlanExplain }) {
  if (!plan) return null;
  const ctx = plan.query_plan_context;
  return (
    <div className="space-y-2 text-xs text-slate-600">
      <div className="grid gap-1.5 sm:grid-cols-2">
        <div className="flex items-center gap-1.5">
          <Database className="h-3.5 w-3.5 text-slate-400" />
          <span>{plan.datasource?.name ?? plan.datasource?.connection_id ?? '未指定数据源'}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <BarChart3 className="h-3.5 w-3.5 text-slate-400" />
          <span>{plan.pushdown.enabled ? `下推到 ${plan.pushdown.target}` : '未启用下推'}</span>
        </div>
      </div>
      {ctx && (
        <div className="grid gap-1 text-[11px] text-slate-500 sm:grid-cols-2">
          <div>指标：{textList(ctx.metrics)}</div>
          <div>维度：{textList(ctx.dimensions)}</div>
          <div>过滤：{textList(ctx.filters)}</div>
          <div>粒度：{ctx.grain ?? '未指定'}{ctx.limit ? `，最多 ${ctx.limit} 行` : ''}</div>
        </div>
      )}
      {plan.semantic_operators?.length ? (
        <div className="flex flex-wrap gap-1.5">
          {plan.semantic_operators.map((op) => (
            <span key={op.id} className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500">
              {op.label || op.op}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ExecutionStepRow({ step }: { step: ExecutionExplainStep }) {
  const stepStatus: ExplainabilityStatus = step.status === 'success'
    ? 'completed'
    : step.status === 'failed'
      ? 'failed'
      : step.status === 'skipped'
        ? 'skipped'
        : step.status === 'running'
          ? 'running'
          : 'pending';
  const style = statusStyle[stepStatus];
  return (
    <li className="grid grid-cols-[20px_1fr_auto] gap-2 text-xs text-slate-600">
      <span className={`mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full border ${style.className}`}>
        {style.icon}
      </span>
      <span className="min-w-0">
        <span className="font-medium text-slate-700">{step.title}</span>
        {step.detail && <span className="ml-1 text-slate-500">{step.detail}</span>}
        {step.result_preview && <span className="block truncate text-[11px] text-slate-400">{step.result_preview}</span>}
      </span>
      {formatMs(step.duration_ms) && <span className="text-[10px] text-slate-400">{formatMs(step.duration_ms)}</span>}
    </li>
  );
}

function ExecutionBody({ steps }: { steps?: ExecutionExplainStep[] }) {
  if (!steps?.length) return null;
  return (
    <ol className="space-y-2">
      {steps.slice(0, 8).map((step) => <ExecutionStepRow key={step.step_id} step={step} />)}
      {steps.length > 8 && <li className="text-[11px] text-slate-400">还有 {steps.length - 8} 个步骤未显示</li>}
    </ol>
  );
}

function PostprocessBody({ postprocess }: { postprocess?: PostprocessExplain }) {
  if (!postprocess) return null;
  return (
    <div className="space-y-2 text-xs text-slate-600">
      <div className="flex flex-wrap gap-1.5">
        <InlineMeta>类型 {postprocess.response_type}</InlineMeta>
        {postprocess.row_count != null && <InlineMeta>结果 {postprocess.row_count} 行</InlineMeta>}
        {postprocess.displayed_row_count != null && <InlineMeta>展示 {postprocess.displayed_row_count} 行</InlineMeta>}
        {postprocess.chart_generated && <InlineMeta>已生成图表</InlineMeta>}
      </div>
      {postprocess.field_substitutions?.length ? (
        <div className="space-y-1 text-[11px] text-slate-500">
          {postprocess.field_substitutions.map((item, index) => (
            <div key={`${item.requested}-${item.used}-${index}`}>
              字段替代：{item.requested} {'->'} {item.used}{item.reason ? `，${item.reason}` : ''}
            </div>
          ))}
        </div>
      ) : null}
      {postprocess.warnings?.length ? (
        <div className="space-y-1 text-[11px] text-amber-600">
          {postprocess.warnings.map((warning) => <div key={warning.code}>{warning.message}</div>)}
        </div>
      ) : null}
    </div>
  );
}

function FallbackBody({ fallback }: { fallback?: FallbackExplain }) {
  if (!fallback) return null;
  if (!fallback.occurred) {
    return <p className="text-xs text-slate-500">未发生降级。</p>;
  }
  return (
    <div className="space-y-2 text-xs text-slate-600">
      {fallback.chain.map((item, index) => (
        <div key={`${item.from}-${item.to}-${index}`} className="flex flex-wrap items-center gap-1.5">
          <InlineMeta>{item.from} {'->'} {item.to}</InlineMeta>
          <span className="text-[11px] text-slate-500">{item.reason_code}: {item.message}</span>
        </div>
      ))}
      <div className="text-[11px] text-slate-500">最终来源：{fallback.final_source}</div>
      {fallback.user_visible_message && <p className="leading-relaxed text-slate-500">{fallback.user_visible_message}</p>}
    </div>
  );
}

function inferStatus(payload: unknown, fallbackStatus: ExplainabilityStatus): ExplainabilityStatus {
  if (!payload || typeof payload !== 'object') return fallbackStatus;
  const status = (payload as { status?: ExplainabilityStatus }).status;
  return status ?? fallbackStatus;
}

function executionStatusToView(status: 'running' | 'completed' | 'failed' | 'cancelled' | undefined, defaultStatus: ExplainabilityStatus): ExplainabilityStatus {
  if (status === 'completed') return 'completed';
  if (status === 'failed' || status === 'cancelled') return 'failed';
  if (status === 'running') return 'running';
  return defaultStatus;
}

function buildViews(explainability: AgentExplainability, isStreaming?: boolean): PhaseView[] {
  const fallbackOccurred = explainability.phases.fallback?.occurred === true;
  const defaultStatus: ExplainabilityStatus = isStreaming ? 'running' : 'completed';
  return [
    {
      phase: 'intent',
      label: '意图',
      status: inferStatus(explainability.phases.intent, explainability.phases.intent ? 'completed' : 'pending'),
      summary: explainability.phases.intent?.intent ?? '等待识别',
      body: <IntentBody intent={explainability.phases.intent} />,
    },
    {
      phase: 'plan',
      label: '计划',
      status: inferStatus(explainability.phases.plan, explainability.phases.plan ? 'completed' : 'pending'),
      summary: explainability.phases.plan?.pushdown?.enabled
        ? `下推到 ${explainability.phases.plan.pushdown.target}`
        : '查询计划',
      body: <PlanBody plan={explainability.phases.plan} />,
    },
    {
      phase: 'execution',
      label: '执行',
      status: executionStatusToView(explainability.phases.execution?.status, defaultStatus),
      summary: explainability.phases.execution?.steps?.length
        ? `${explainability.phases.execution.steps.length} 个步骤`
        : '等待工具执行',
      body: <ExecutionBody steps={explainability.phases.execution?.steps} />,
    },
    {
      phase: 'postprocess',
      label: '后处理',
      status: inferStatus(explainability.phases.postprocess, explainability.phases.postprocess ? 'completed' : 'pending'),
      summary: explainability.phases.postprocess?.response_type ?? '结果整理',
      body: <PostprocessBody postprocess={explainability.phases.postprocess} />,
    },
    {
      phase: 'fallback',
      label: '降级',
      status: fallbackOccurred ? 'completed' : 'skipped',
      summary: fallbackOccurred ? `发生降级，最终 ${explainability.phases.fallback?.final_source}` : '未发生降级',
      body: <FallbackBody fallback={explainability.phases.fallback} />,
    },
  ];
}

export default function AnalysisProcessBlock({ explainability, isStreaming = false, compact = true }: AnalysisProcessBlockProps) {
  const [open, setOpen] = useState(!compact && Boolean(explainability));
  const views = useMemo(() => explainability ? buildViews(explainability, isStreaming) : [], [explainability, isStreaming]);

  if (!explainability) return null;

  const fallbackOccurred = explainability.phases.fallback?.occurred === true;
  const mcpProxy = explainability.mcp_proxy;
  const isMcpProxy = mcpProxy?.chain_mode === 'mcp_proxy';
  const completedCount = views.filter((item) => item.status === 'completed' || item.status === 'skipped').length;
  const intent = explainability.phases.intent?.intent;
  const pushdownTarget = explainability.phases.plan?.pushdown?.enabled ? explainability.phases.plan.pushdown.target : null;

  return (
    <div className="not-prose mt-3 rounded-lg border border-slate-200 bg-slate-50/70 text-slate-700" data-testid="analysis-process-block">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
        aria-expanded={open}
        data-testid="analysis-process-toggle"
      >
        <span className="flex min-w-0 flex-wrap items-center gap-1.5">
          <span className="font-medium text-slate-700">查看分析过程</span>
          {intent && <span className="rounded bg-white px-1.5 py-0.5 text-[10px] text-slate-500">识别为 {intent}</span>}
          {pushdownTarget && <span className="rounded bg-white px-1.5 py-0.5 text-[10px] text-slate-500">下推 {pushdownTarget}</span>}
          {isMcpProxy && <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-700">mcp_proxy</span>}
          <span className="rounded bg-white px-1.5 py-0.5 text-[10px] text-slate-500">{completedCount}/5</span>
          {fallbackOccurred && (
            <span className="inline-flex items-center gap-1 rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700" data-testid="analysis-fallback-badge">
              <AlertTriangle className="h-3 w-3" />
              发生降级
            </span>
          )}
        </span>
        <ChevronDown className={`h-4 w-4 flex-shrink-0 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="border-t border-slate-200 px-3 py-3" data-testid="analysis-process-detail">
          <div className="space-y-3">
            <McpProxyBody mcpProxy={mcpProxy} />
            {views.map((item) => {
              const style = statusStyle[item.status] ?? statusStyle.pending;
              return (
                <section key={item.phase} className="grid grid-cols-[24px_1fr] gap-2" data-testid={`analysis-phase-${item.phase}`}>
                  <div className={`mt-0.5 inline-flex h-6 w-6 items-center justify-center rounded-full border ${style.className}`}>
                    {phaseIcon[item.phase]}
                  </div>
                  <div className="min-w-0">
                    <div className="mb-1 flex flex-wrap items-center gap-1.5">
                      <h4 className="text-xs font-semibold text-slate-700">{item.label}</h4>
                      <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] ${style.className}`}>
                        {style.icon}
                        {style.text}
                      </span>
                      <span className="text-[11px] text-slate-400">{item.summary}</span>
                    </div>
                    {item.body}
                  </div>
                </section>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
