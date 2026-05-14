import { useEffect, useMemo, useRef, useState } from 'react';
import {
  streamHelpAgent,
  type HelpAgentStreamEvent,
  type HelpDiagnosticProgressEvent,
} from '../../../api/helpAgent';
import { buildHelpPageContext } from './pageContext';

interface InlineDiagnosticPanelProps {
  runId: string;
  defaultQuestion?: string;
  visibleState?: {
    status?: string;
    error_code?: string;
    expanded?: boolean;
  };
}

interface ToolEvent {
  id: string;
  type: 'tool_call' | 'tool_result';
  tool: string;
  detail: string;
}

function formatMs(ms?: number | null): string {
  if (ms === null || ms === undefined) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function statusIcon(status: HelpDiagnosticProgressEvent['status']): string {
  if (status === 'completed') return 'ri-checkbox-circle-fill text-emerald-600';
  if (status === 'failed') return 'ri-error-warning-fill text-red-600';
  if (status === 'running') return 'ri-loader-4-line text-blue-600 animate-spin';
  if (status === 'skipped') return 'ri-skip-forward-line text-slate-400';
  return 'ri-time-line text-slate-400';
}

function getElapsedMs(step: HelpDiagnosticProgressEvent, now: number): number | null {
  if (typeof step.execution_time_ms === 'number') return step.execution_time_ms;
  if (step.status === 'running' && step.started_at) {
    const started = new Date(step.started_at).getTime();
    return Number.isFinite(started) ? Math.max(0, now - started) : null;
  }
  return null;
}

function upsertStep(
  steps: HelpDiagnosticProgressEvent[],
  next: HelpDiagnosticProgressEvent
): HelpDiagnosticProgressEvent[] {
  const index = steps.findIndex((step) => step.step_key === next.step_key);
  if (index === -1) return [...steps, next];
  const merged = { ...steps[index], ...next };
  return steps.map((step, i) => (i === index ? merged : step));
}

function summarizeTools(tools: ToolEvent[]): string {
  return tools.map((tool) => `${tool.type === 'tool_call' ? '调用' : '结果'} ${tool.tool}: ${tool.detail}`).join('\n');
}

export default function InlineDiagnosticPanel({
  runId,
  defaultQuestion = '请诊断这个 run 的失败原因和耗时瓶颈。',
  visibleState,
}: InlineDiagnosticPanelProps) {
  const [question, setQuestion] = useState(defaultQuestion);
  const [answer, setAnswer] = useState('');
  const [thinking, setThinking] = useState('');
  const [steps, setSteps] = useState<HelpDiagnosticProgressEvent[]>([]);
  const [tools, setTools] = useState<ToolEvent[]>([]);
  const [error, setError] = useState<{ message: string; user_hint?: string } | null>(null);
  const [running, setRunning] = useState(false);
  const [snapshotAt, setSnapshotAt] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!steps.some((step) => step.status === 'running')) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [steps]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const runningStep = useMemo(
    () => steps.find((step) => step.status === 'running'),
    [steps]
  );

  const runDiagnostic = async (nextQuestion = question) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setAnswer('');
    setThinking('');
    setSteps([]);
    setTools([]);
    setError(null);
    setSnapshotAt(null);

    const stream = streamHelpAgent(
      {
        question: nextQuestion,
        conversation_id: conversationId,
        entry_point: 'inline_panel',
        page_context: buildHelpPageContext({
          entryPoint: 'inline_panel',
          selection: { query_refs: { run_id: runId } },
          visibleState: { ...visibleState, expanded: true },
        }),
      },
      controller.signal
    );

    const reader = stream.getReader();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        handleEvent(value);
      }
    } finally {
      setRunning(false);
    }
  };

  const handleEvent = (event: HelpAgentStreamEvent) => {
    if (event.type === 'metadata') {
      setConversationId(event.conversation_id || null);
    } else if (event.type === 'thinking') {
      setThinking(event.content);
    } else if (event.type === 'diagnostic_progress') {
      setSteps((prev) => upsertStep(prev, event));
      if (event.snapshot_at) setSnapshotAt(event.snapshot_at);
      if (event.finished_at) setSnapshotAt(event.finished_at);
    } else if (event.type === 'tool_call') {
      setTools((prev) => [
        ...prev,
        { id: `${event.tool}-${prev.length}`, type: 'tool_call', tool: event.tool, detail: JSON.stringify(event.params ?? {}) },
      ]);
    } else if (event.type === 'tool_result') {
      setTools((prev) => [
        ...prev,
        { id: `${event.tool}-${prev.length}`, type: 'tool_result', tool: event.tool, detail: event.summary },
      ]);
      if (event.snapshot_at) setSnapshotAt(event.snapshot_at);
    } else if (event.type === 'token') {
      setAnswer((prev) => prev + event.content);
    } else if (event.type === 'done') {
      setAnswer((prev) => prev || event.answer);
      const data = event.response_data as { snapshot_completed_at?: string; snapshot_started_at?: string } | null;
      setSnapshotAt(data?.snapshot_completed_at ?? data?.snapshot_started_at ?? null);
    } else if (event.type === 'error') {
      setError({ message: event.message, user_hint: event.user_hint });
    }
  };

  const copySummary = () => {
    const stepSummary = steps
      .map((step) => {
        const elapsed = formatMs(getElapsedMs(step, now));
        return `[${step.status}] ${step.label}${elapsed ? ` (${elapsed})` : ''}${step.error_summary ? `: ${step.error_summary}` : ''}`;
      })
      .join('\n');
    const text = [
      `Run: ${runId}`,
      `快照时间: ${snapshotAt ? formatTime(snapshotAt) : '-'}`,
      stepSummary,
      answer,
      summarizeTools(tools),
    ].filter(Boolean).join('\n\n');
    void navigator.clipboard?.writeText(text);
  };

  const groupedSteps = useMemo(() => {
    const groups = new Map<string, HelpDiagnosticProgressEvent[]>();
    steps.forEach((step) => {
      const key = step.parent_step_key ?? step.parallel_group ?? `level-${step.level ?? 0}`;
      groups.set(key, [...(groups.get(key) ?? []), step]);
    });
    return Array.from(groups.entries());
  }, [steps]);

  return (
    <div className="mt-4 rounded-lg border border-blue-100 bg-white">
      <div className="px-4 py-3 border-b border-blue-100 bg-blue-50/60 flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-blue-600 text-white flex items-center justify-center shrink-0">
          <i className="ri-stethoscope-line" />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-800">Help Agent 诊断</div>
          <div className="text-xs text-slate-500 truncate">对象：run {runId} · 快照：{snapshotAt ? formatTime(snapshotAt) : '等待诊断'}</div>
        </div>
        <button
          type="button"
          onClick={() => runDiagnostic()}
          disabled={running}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          <i className={running ? 'ri-loader-4-line animate-spin' : 'ri-pulse-line'} />
          {running ? '诊断中' : '诊断'}
        </button>
      </div>

      <div className="p-4 space-y-4">
        <div className="flex gap-2">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={2}
            className="min-h-16 flex-1 resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 focus:border-blue-400 focus:outline-none"
            placeholder="继续追问当前 run..."
          />
          <button
            type="button"
            onClick={() => runDiagnostic(question)}
            disabled={running}
            className="w-10 h-10 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            title="继续追问"
          >
            <i className="ri-send-plane-2-line" />
          </button>
        </div>

        {(thinking || runningStep) && (
          <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
            {runningStep ? (
              <span>
                正在执行：{runningStep.label}
                {getElapsedMs(runningStep, now) !== null && ` · ${formatMs(getElapsedMs(runningStep, now))}`}
              </span>
            ) : thinking}
          </div>
        )}

        {steps.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-semibold text-slate-500">诊断步骤</div>
            {groupedSteps.map(([group, groupSteps]) => (
              <div
                key={group}
                className={`grid gap-2 ${groupSteps.length > 1 ? 'md:grid-cols-2' : 'grid-cols-1'}`}
              >
                {groupSteps.map((step) => {
                  const elapsed = getElapsedMs(step, now);
                  return (
                    <div key={step.step_key} className="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2">
                      <div className="flex items-center gap-2">
                        <i className={statusIcon(step.status)} />
                        <span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-700" title={step.label}>
                          {step.label}
                        </span>
                        <span className="text-[11px] text-slate-400">{formatMs(elapsed)}</span>
                      </div>
                      {(step.error_summary || step.message) && (
                        <div className="mt-1 text-xs text-red-600 break-words">{step.error_summary || step.message}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <div className="font-medium">{error.message}</div>
            {error.user_hint && <div className="mt-1 text-xs text-red-600">{error.user_hint}</div>}
          </div>
        )}

        {answer && (
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-3 text-sm leading-6 text-slate-700 whitespace-pre-wrap">
            {answer}
          </div>
        )}

        {tools.length > 0 && (
          <details className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium text-slate-500">工具详情</summary>
            <div className="mt-2 space-y-2">
              {tools.map((tool) => (
                <div key={tool.id} className="text-xs text-slate-600">
                  <span className="font-medium">{tool.type === 'tool_call' ? '调用' : '结果'} {tool.tool}</span>
                  <pre className="mt-1 max-h-24 overflow-auto rounded bg-white p-2 text-[11px] whitespace-pre-wrap">{tool.detail}</pre>
                </div>
              ))}
            </div>
          </details>
        )}

        <div className="flex items-center justify-end">
          <button
            type="button"
            onClick={copySummary}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
          >
            <i className="ri-file-copy-line" />
            复制诊断摘要
          </button>
        </div>
      </div>
    </div>
  );
}
