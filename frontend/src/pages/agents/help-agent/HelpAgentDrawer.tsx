import { useEffect, useMemo, useRef, useState } from 'react';
import {
  streamHelpAgent,
  type HelpAgentEntryPoint,
  type HelpAgentStreamEvent,
  type HelpDiagnosticProgressEvent,
} from '../../../api/helpAgent';
import { buildHelpPageContext } from './pageContext';

interface HelpAgentDrawerProps {
  open: boolean;
  onClose: () => void;
  entryPoint?: HelpAgentEntryPoint;
  embedded?: boolean;
  initialQuestion?: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

interface ToolEvent {
  id: string;
  type: 'tool_call' | 'tool_result';
  tool: string;
  detail: string;
}

function formatTime(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatMs(ms?: number | null): string {
  if (ms === null || ms === undefined) return '';
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function pageLabel(path: string): string {
  if (path.includes('/agents/agent-monitor')) return 'Agent 监控';
  if (path.includes('/agents/help')) return 'Help Agent';
  if (path.includes('/agents/skills')) return '技能中心';
  if (path.includes('/system/tasks')) return '任务管理';
  if (path.includes('/system/data-connections')) return '数据连接';
  return document.title || path || '当前页面';
}

function statusClass(status: HelpDiagnosticProgressEvent['status']): string {
  if (status === 'completed') return 'text-emerald-700 bg-emerald-50';
  if (status === 'failed') return 'text-red-700 bg-red-50';
  if (status === 'running') return 'text-blue-700 bg-blue-50';
  if (status === 'skipped') return 'text-slate-500 bg-slate-100';
  return 'text-slate-500 bg-slate-50';
}

function upsertStep(
  steps: HelpDiagnosticProgressEvent[],
  next: HelpDiagnosticProgressEvent
): HelpDiagnosticProgressEvent[] {
  const index = steps.findIndex((step) => step.step_key === next.step_key);
  if (index === -1) return [...steps, next];
  return steps.map((step, i) => (i === index ? { ...step, ...next } : step));
}

export default function HelpAgentDrawer({
  open,
  onClose,
  entryPoint = 'global_drawer',
  embedded = false,
  initialQuestion = '',
}: HelpAgentDrawerProps) {
  const [input, setInput] = useState(initialQuestion);
  const [messages, setMessages] = useState<Message[]>([]);
  const [thinking, setThinking] = useState('');
  const [steps, setSteps] = useState<HelpDiagnosticProgressEvent[]>([]);
  const [tools, setTools] = useState<ToolEvent[]>([]);
  const [error, setError] = useState<{ message: string; user_hint?: string } | null>(null);
  const [running, setRunning] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const context = useMemo(() => buildHelpPageContext({ entryPoint }), [entryPoint, open]);

  useEffect(() => {
    if (open) setInput((prev) => prev || initialQuestion);
  }, [initialQuestion, open]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [messages, thinking, steps, tools, error]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  if (!open && !embedded) return null;

  const currentAssistantId = [...messages].reverse().find((msg) => msg.role === 'assistant')?.id;

  const appendAssistant = (content: string) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last?.role === 'assistant') {
        return prev.map((msg) => (msg.id === last.id ? { ...msg, content: msg.content + content } : msg));
      }
      return [...prev, { id: `assistant-${Date.now()}`, role: 'assistant', content }];
    });
  };

  const replaceAssistantIfEmpty = (content: string) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last?.role === 'assistant' && !last.content) {
        return prev.map((msg) => (msg.id === last.id ? { ...msg, content } : msg));
      }
      if (last?.role === 'assistant') return prev;
      return [...prev, { id: `assistant-${Date.now()}`, role: 'assistant', content }];
    });
  };

  const handleEvent = (event: HelpAgentStreamEvent) => {
    if (event.type === 'metadata') {
      setConversationId(event.conversation_id || null);
    } else if (event.type === 'thinking') {
      setThinking(event.content);
    } else if (event.type === 'diagnostic_progress') {
      setSteps((prev) => upsertStep(prev, event));
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
    } else if (event.type === 'token') {
      appendAssistant(event.content);
    } else if (event.type === 'done') {
      replaceAssistantIfEmpty(event.answer);
    } else if (event.type === 'error') {
      setError({ message: event.message, user_hint: event.user_hint });
    }
  };

  const send = async () => {
    const question = input.trim();
    if (!question || running) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setInput('');
    setThinking('');
    setSteps([]);
    setTools([]);
    setError(null);
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: 'user', content: question },
      { id: `assistant-${Date.now()}`, role: 'assistant', content: '' },
    ]);

    const stream = streamHelpAgent(
      {
        question,
        conversation_id: conversationId,
        entry_point: entryPoint,
        page_context: buildHelpPageContext({ entryPoint }),
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

  const content = (
    <div className="h-full flex flex-col bg-white">
      <div className="shrink-0 border-b border-slate-200 px-4 py-3 flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-slate-900 text-white flex items-center justify-center">
          <i className="ri-question-answer-line" />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-800">Help Agent</div>
          <div className="text-xs text-slate-400 truncate">当前页面：{pageLabel(context.path)}</div>
        </div>
        {!embedded && (
          <button
            type="button"
            onClick={onClose}
            className="ml-auto w-8 h-8 rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            title="关闭"
          >
            <i className="ri-close-line text-lg" />
          </button>
        )}
      </div>

      <div ref={bodyRef} className="flex-1 min-h-0 overflow-y-auto px-4 py-4 space-y-4 bg-slate-50">
        {messages.length === 0 && (
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="text-sm font-medium text-slate-800 mb-2">可以直接描述你遇到的问题</div>
            <div className="grid gap-2">
              {['为什么刚才问答失败？', '这个页面该怎么排查问题？', '最近有没有失败的 Agent run？'].map((sample) => (
                <button
                  key={sample}
                  type="button"
                  onClick={() => setInput(sample)}
                  className="text-left rounded-md border border-slate-200 px-3 py-2 text-xs text-slate-600 hover:bg-slate-50"
                >
                  {sample}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[92%] rounded-lg px-3 py-2 text-sm leading-6 whitespace-pre-wrap ${
                message.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white border border-slate-200 text-slate-700'
              }`}
            >
              {message.content || (message.id === currentAssistantId && running ? '...' : '')}
            </div>
          </div>
        ))}

        {(thinking || running) && (
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
            {thinking || '正在准备诊断...'}
          </div>
        )}

        {steps.length > 0 && (
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="mb-2 text-xs font-semibold text-slate-500">诊断进度</div>
            <div className="space-y-1.5">
              {steps.map((step) => (
                <div key={step.step_key} className="flex items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-[11px] ${statusClass(step.status)}`}>{step.status}</span>
                  <span className="min-w-0 flex-1 truncate text-xs text-slate-700" title={step.label}>{step.label}</span>
                  <span className="text-[11px] text-slate-400">{formatMs(step.execution_time_ms)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <div className="font-medium">{error.message}</div>
            {error.user_hint && <div className="mt-1 text-xs text-red-600">{error.user_hint}</div>}
          </div>
        )}

        {tools.length > 0 && (
          <details className="rounded-lg border border-slate-200 bg-white px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium text-slate-500">工具详情</summary>
            <div className="mt-2 space-y-2">
              {tools.map((tool) => (
                <div key={tool.id} className="text-xs text-slate-600">
                  <div className="font-medium">{tool.type === 'tool_call' ? '调用' : '结果'} {tool.tool}</div>
                  <pre className="mt-1 max-h-24 overflow-auto rounded bg-slate-50 p-2 text-[11px] whitespace-pre-wrap">{tool.detail}</pre>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>

      <div className="shrink-0 border-t border-slate-200 bg-white p-3">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          rows={3}
          className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 focus:border-blue-400 focus:outline-none"
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-[11px] text-slate-400">不会采集 cookie、token、secret 或页面大段文本</span>
          <button
            type="button"
            onClick={() => void send()}
            disabled={running || !input.trim()}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <i className={running ? 'ri-loader-4-line animate-spin' : 'ri-send-plane-2-line'} />
            发送
          </button>
        </div>
      </div>
    </div>
  );

  if (embedded) {
    return <div className="h-full min-h-[560px] rounded-lg border border-slate-200 overflow-hidden">{content}</div>;
  }

  return (
    <div className="fixed inset-0 z-[80] flex justify-end">
      <div className="absolute inset-0 bg-black/25" onClick={onClose} />
      <aside className="relative h-full w-full bg-white shadow-2xl sm:w-[460px] lg:w-[500px]">
        {content}
      </aside>
    </div>
  );
}
