import React, { useEffect, useRef } from 'react';
import MessageBubble from '../../../components/chat/MessageBubble';
import { MessageActions } from './MessageActions';
import type { StreamingMessage, TableData } from '../../../hooks/useStreamingChat';
import type { AgentExplainability, McpProxyExplain, McpProxyRepairExplain } from '../../../api/agent';

interface HistoryMessage {
  role: 'user' | 'assistant';
  content: string;
  created_at?: string;
  response_type?: string | null;
  response_data?: unknown;
  error_detail?: unknown;
  run_id?: string | null;
  explainability?: AgentExplainability | null;
  trace_id?: string | null;
  sources_count?: number | null;
  top_sources?: string[] | null;
}

interface MessageListProps {
  messages: StreamingMessage[];
  mockContent?: string;
  isMockStreaming?: boolean;
  lastQuestion?: string;
  onRegenerate?: (question: string) => void;
  historyMessages?: HistoryMessage[];
  /** conversation_id for history messages — enables feedback via conversation_id alone */
  historyConversationId?: string | null;
  onSourceClick?: (sourceName: string) => void;
  /** T6: 加载更早的消息 */
  onLoadMore?: () => void;
  hasMore?: boolean;
  loadingMore?: boolean;
}

interface RenderItemOpts {
  key: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  isError?: boolean;
  errorCode?: string;
  errorHint?: string;
  thinking?: string;
  explainability?: AgentExplainability | null;
  responseData?: unknown;
  errorDetail?: unknown;
  traceId?: string | null;
  tableData?: TableData;
  chartData?: StreamingMessage['chartData'];
  sourcesCount?: number | null;
  topSources?: string[] | null;
  timestamp?: number | string | null;
  conversationId?: string | null;
  messageIndex?: number;
  question?: string;
  isLastAssistant?: boolean;
  onRegenerate?: (question: string) => void;
  onSourceClick?: (sourceName: string) => void;
}

function renderMessageItem(opts: RenderItemOpts) {
  const {
    key, role, content, isStreaming, isError, errorCode, errorHint, thinking,
    explainability, traceId, tableData, chartData, sourcesCount, topSources,
    timestamp, conversationId, messageIndex, question, isLastAssistant, onRegenerate, onSourceClick,
  } = opts;
  const mergedExplainability = mergeMcpProxyExplainability(
    explainability ?? undefined,
    opts.responseData,
    opts.errorDetail,
  );
  const timeStr = timestamp
    ? new Date(timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : null;
  const showActions = role === 'assistant' && !isStreaming && (traceId || conversationId);
  return (
    <div key={key} className="group">
      <MessageBubble
        role={role}
        content={content}
        isStreaming={isStreaming}
        isError={isError}
        errorCode={errorCode}
        errorHint={errorHint}
        thinking={thinking}
        explainability={mergedExplainability}
        traceId={traceId ?? undefined}
        tableData={tableData}
        chartData={chartData}
        sourcesCount={sourcesCount ?? undefined}
        topSources={topSources ?? undefined}
        onSourceClick={onSourceClick}
      />
      {/* Time + Actions in one flex row */}
      {(timeStr || showActions) && (
        <div className={`flex items-center mt-2 ${role === 'user' ? 'justify-end mr-2' : 'justify-between'}`}>
          {role === 'assistant' && timeStr && !isStreaming && (
            <p className="text-[10px] text-slate-400 ml-1">{timeStr}</p>
          )}
          {showActions && (
            <MessageActions
              content={content}
              conversationId={conversationId ?? null}
              messageIndex={messageIndex ?? 0}
              question={question ?? ''}
              traceId={traceId}
              onRegenerate={isLastAssistant ? onRegenerate : undefined}
            />
          )}
        </div>
      )}
      {role === 'user' && timeStr && !isStreaming && (
        <p className="text-[10px] text-slate-400 mt-1.5 text-right mr-2">{timeStr}</p>
      )}
    </div>
  );
}

function histTableData(msg: HistoryMessage): TableData | undefined {
  if (msg.response_type !== 'table' || !msg.response_data || typeof msg.response_data !== 'object') return undefined;
  const rd = msg.response_data as { fields?: string[]; rows?: (string | number | null)[][]; table_display?: unknown };
  const { fields, rows } = rd;
  if (!fields?.length || !rows?.length) return undefined;
  const col_types = fields.map((_, i) => {
    const sample = rows!.slice(0, 5).map((r) => r[i]).filter((v) => v != null && v !== '');
    return sample.length > 0 && sample.every((v) => typeof v === 'number') ? 'numeric' : 'string';
  }) as ('numeric' | 'string')[];
  const table_display = histTableDisplay(rd.table_display);
  return { fields, rows: rows!, col_types, ...(table_display ? { table_display } : {}) };
}

function histTableDisplay(value: unknown): TableData['table_display'] | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const columns = (value as { columns?: unknown }).columns;
  if (!Array.isArray(columns)) return undefined;
  return {
    columns: columns
      .filter((column): column is Record<string, unknown> => !!column && typeof column === 'object')
      .map((column) => ({
        key: typeof column.key === 'string' ? column.key : undefined,
        label: typeof column.label === 'string' ? column.label : undefined,
        semantic_type: typeof column.semantic_type === 'string' ? column.semantic_type : undefined,
        value_type: typeof column.value_type === 'string' ? column.value_type : undefined,
        align: column.align === 'left' || column.align === 'right' || column.align === 'center'
          ? column.align
          : undefined,
        format: column.format === 'plain' || column.format === 'number' || column.format === 'integer' || column.format === 'percent' || column.format === 'date'
          ? column.format
          : undefined,
      })),
  };
}

function asObject(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  return value as Record<string, unknown>;
}

function parseObject(value: unknown): Record<string, unknown> | undefined {
  const direct = asObject(value);
  if (direct) return direct;
  if (typeof value !== 'string') return undefined;
  try {
    return asObject(JSON.parse(value));
  } catch {
    return undefined;
  }
}

function parseRepairs(value: unknown): McpProxyRepairExplain[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(asObject(item)))
    .map((item) => ({
      type: typeof item.type === 'string' ? item.type : undefined,
      path: typeof item.path === 'string' ? item.path : undefined,
      before: item.before,
      after: item.after,
      reason: typeof item.reason === 'string' ? item.reason : undefined,
    }));
}

function mcpProxyFromPayload(value: unknown): McpProxyExplain | undefined {
  const payload = parseObject(value);
  if (!payload) return undefined;
  const detail = asObject(asObject(payload.controlled_chain)?.detail);
  const source = detail?.chain_mode === 'mcp_proxy' ? detail : payload;
  if (source.chain_mode !== 'mcp_proxy') return undefined;
  const decision = typeof source.guardrail_decision === 'string' ? source.guardrail_decision : undefined;
  const rejectCode = typeof source.reject_code === 'string'
    ? source.reject_code
    : typeof payload.error_code === 'string'
      ? payload.error_code
      : null;
  return {
    chain_mode: 'mcp_proxy',
    guardrail_decision: decision,
    guardrail_repairs: parseRepairs(source.guardrail_repairs),
    reject_code: rejectCode,
    message: typeof payload.message === 'string' ? payload.message : null,
    user_hint: typeof payload.user_hint === 'string' ? payload.user_hint : null,
  };
}

function mergeMcpProxyExplainability(
  explainability: AgentExplainability | undefined,
  ...payloads: unknown[]
): AgentExplainability | undefined {
  const existing = explainability?.mcp_proxy;
  const next = payloads.map(mcpProxyFromPayload).find(Boolean) ?? existing;
  if (!next) return explainability;
  return {
    schema_version: explainability?.schema_version ?? 'p0.1',
    run_id: explainability?.run_id,
    trace_id: explainability?.trace_id,
    mode: explainability?.mode,
    phases: { ...(explainability?.phases ?? {}) },
    mcp_proxy: next,
  };
}

function histExplainability(msg: HistoryMessage): AgentExplainability | undefined {
  const base = msg.explainability ?? undefined;
  const merged = mergeMcpProxyExplainability(base, msg.response_data, msg.error_detail);
  if (merged) return merged;
  if (!msg.response_data || typeof msg.response_data !== 'object') return undefined;
  const embedded = (msg.response_data as { _explainability?: unknown })._explainability;
  if (!embedded || typeof embedded !== 'object') return undefined;
  return mergeMcpProxyExplainability(embedded as AgentExplainability, msg.response_data, msg.error_detail);
}

function histErrorCode(msg: HistoryMessage): string | undefined {
  if (msg.response_type !== 'error' && msg.response_type !== 'fallback') return undefined;
  const payload = parseObject(msg.error_detail) ?? parseObject(msg.response_data);
  return typeof payload?.error_code === 'string' ? payload.error_code : undefined;
}

function histErrorHint(msg: HistoryMessage): string | undefined {
  if (msg.response_type !== 'error' && msg.response_type !== 'fallback') return undefined;
  const payload = parseObject(msg.error_detail) ?? parseObject(msg.response_data);
  const hint = payload?.user_hint;
  if (typeof hint === 'string' && hint.trim()) return hint;
  const actions = payload?.suggested_actions;
  if (Array.isArray(actions) && typeof actions[0] === 'string') return actions[0];
  return undefined;
}

function MessageList({ messages, mockContent, isMockStreaming, lastQuestion, onRegenerate, historyMessages, historyConversationId, onSourceClick, onLoadMore, hasMore, loadingMore }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, mockContent]);

  const hasContent = (historyMessages?.length ?? 0) > 0 ||
    messages.length > 0 ||
    isMockStreaming ||
    !!mockContent;

  if (!hasContent) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-300 select-none">
        <i className="ri-chat-3-line text-4xl mb-3 opacity-50" />
        <p className="text-sm">输入问题开始对话</p>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto w-full px-4">
      <div className="flex flex-col gap-4 py-6">

        {/* T6: 加载更早的消息按钮 */}
        {hasMore && (
          <div className="flex justify-center">
            <button
              onClick={onLoadMore}
              disabled={loadingMore}
              className="text-sm text-blue-500 hover:underline disabled:opacity-50 flex items-center gap-1"
            >
              {loadingMore ? (
                <>
                  <span className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin inline-block" />
                  加载中...
                </>
              ) : '↑ 加载更早的消息'}
            </button>
          </div>
        )}

        {/* 历史消息（URL conv= 恢复） */}
        {historyMessages && historyMessages.length > 0 && (() => {
          const lastHistAssistantIdx = historyMessages.reduce(
            (acc, m, i) => (m.role === 'assistant' ? i : acc),
            -1
          );
          let lastHistUserQuestion = '';
          return historyMessages.map((msg, idx) => {
            if (msg.role === 'user') lastHistUserQuestion = msg.content;
            const q = lastHistUserQuestion;
            return renderMessageItem({
              key: `history-${idx}`,
              role: msg.role,
              content: msg.content,
              isStreaming: false,
              isError: msg.role === 'assistant' && (msg.response_type === 'error' || msg.response_type === 'fallback'),
              errorCode: histErrorCode(msg),
              errorHint: histErrorHint(msg),
              tableData: histTableData(msg),
              explainability: histExplainability(msg),
              responseData: msg.response_data,
              errorDetail: msg.error_detail,
              traceId: msg.run_id ?? msg.trace_id,
              conversationId: historyConversationId ?? null,
              sourcesCount: msg.sources_count,
              topSources: msg.top_sources,
              timestamp: msg.created_at,
              messageIndex: idx,
              question: q,
              isLastAssistant: idx === lastHistAssistantIdx,
              onRegenerate,
              onSourceClick,
            });
          });
        })()}

        {/* 真实路径：遍历 SSE 流消息 */}
        {messages.length > 0 && (() => {
          const lastAssistantIndex = messages.reduce(
            (acc, m, i) => (m.role === 'assistant' ? i : acc),
            -1
          );
          let lastUserQuestion = '';
          return messages.map((msg, msgIndex) => {
            if (msg.role === 'user') lastUserQuestion = msg.content;
            const questionForAction = lastUserQuestion;
            const structuredMsg = msg as StreamingMessage & { responseData?: unknown; errorDetail?: unknown };
            return renderMessageItem({
              key: msg.id,
              role: msg.role,
              content: msg.content,
              isStreaming: msg.isStreaming,
              isError: msg.isError,
              errorCode: msg.errorCode,
              errorHint: msg.errorHint,
              thinking: msg.thinking,
              explainability: msg.explainability,
              responseData: structuredMsg.responseData,
              errorDetail: structuredMsg.errorDetail,
              traceId: msg.traceId,
              tableData: msg.tableData,
              chartData: msg.chartData,
              sourcesCount: msg.metadata?.sources_count,
              topSources: msg.metadata?.top_sources,
              timestamp: msg.timestamp,
              conversationId: msg.conversationId,
              messageIndex: msgIndex,
              question: questionForAction,
              isLastAssistant: msgIndex === lastAssistantIndex,
              onRegenerate,
              onSourceClick,
            });
          });
        })()}

        {/* Mock 路径 */}
        {(isMockStreaming || mockContent) && (
          <>
            {lastQuestion && (
              <div className="flex justify-end">
                <div className="bg-blue-600 text-white rounded-xl px-4 py-3 max-w-[85%] text-sm">
                  <span className="whitespace-pre-wrap">{lastQuestion}</span>
                </div>
              </div>
            )}
            <div className="flex justify-start">
              <div className="max-w-[85%]">
                <div className="flex items-center gap-1 mb-1">
                  <i className="ri-robot-2-line w-4 h-4 text-slate-400" />
                  <span className="text-xs text-slate-400">木兰</span>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 text-sm leading-relaxed text-slate-800 shadow-sm">
                  {isMockStreaming && !mockContent && (
                    <span className="inline-flex items-center gap-1.5 text-slate-400">
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:0ms]" />
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:150ms]" />
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:300ms]" />
                    </span>
                  )}
                  {mockContent && (
                    <span className="whitespace-pre-wrap">
                      {mockContent}
                      {isMockStreaming && (
                        <span className="inline-flex gap-0.5 ml-1 align-middle">
                          {[0, 150, 300].map((delay) => (
                            <span
                              key={delay}
                              className="w-1 h-1 rounded-full bg-slate-400 animate-bounce"
                              style={{ animationDelay: `${delay}ms` }}
                            />
                          ))}
                        </span>
                      )}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </>
        )}

        <div ref={bottomRef} />

      </div>
    </div>
  );
}

export default React.memo(MessageList);
