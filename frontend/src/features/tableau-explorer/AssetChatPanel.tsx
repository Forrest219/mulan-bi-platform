/**
 * AssetChatPanel — Tableau 资产助手浮层对话面板（SPEC 41）
 *
 * 固定定位于右下角，宽 380px，最高 600px，圆角卡片，带阴影。
 * 使用 fetch + ReadableStream 读取 SSE（支持 POST 请求）。
 * 历史最多保留最近 10 轮（slice(-10)）。
 * connectionId 变化时自动清空 sessionStorage。
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config';

export interface AssetChatPanelProps {
  connectionId: number;
  onApplyFilter: (assetType: string) => void;
  onHighlightAssets: (assetIds: string[]) => void;
  onClose: () => void;
  currentFilter?: string;
  visibleAssetCount?: number;
}

// ── SSE 帧类型 ────────────────────────────────────────────────────────────────

interface TextFrame {
  type: 'text';
  delta: string;
}

interface ToolCallFrame {
  type: 'tool_call';
  tool: string;
  status: 'running';
}

interface AssetCard {
  id: string | number;
  name: string;
  asset_type: string;
  health_score: number | null;
  project_name: string;
  relevance_reason: string;
}

interface AssetsFrame {
  type: 'assets';
  assets: AssetCard[];
}

interface ActionFrame {
  type: 'action';
  action_type: 'apply_filter' | 'highlight_assets';
  payload: Record<string, unknown>;
  action_label: string;
}

interface DoneFrame {
  type: 'done';
}

interface ErrorFrame {
  type: 'error';
  code: string;
  message: string;
}

type SSEFrame = TextFrame | ToolCallFrame | AssetsFrame | ActionFrame | DoneFrame | ErrorFrame;

// ── 对话消息类型 ───────────────────────────────────────────────────────────────

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  // 助手消息额外字段
  assets?: AssetCard[];
  actions?: ActionFrame[];
  toolCalls?: string[];  // 正在执行的工具名列表
  isStreaming?: boolean;
}

const ASSET_TYPE_LABELS: Record<string, string> = {
  workbook: '工作簿',
  dashboard: '仪表板',
  view: '视图',
  datasource: '数据源',
};

const ASSET_TYPE_COLORS: Record<string, string> = {
  workbook: 'bg-blue-50 text-blue-600',
  dashboard: 'bg-purple-50 text-purple-600',
  view: 'bg-emerald-50 text-emerald-600',
  datasource: 'bg-orange-50 text-orange-600',
};

function healthColor(score: number | null): string {
  if (score == null) return 'text-slate-400';
  if (score >= 80) return 'text-emerald-600';
  if (score >= 50) return 'text-yellow-600';
  return 'text-red-500';
}

// ── 组件主体 ──────────────────────────────────────────────────────────────────

export function AssetChatPanel({
  connectionId,
  onApplyFilter,
  onHighlightAssets,
  onClose,
  currentFilter,
  visibleAssetCount,
}: AssetChatPanelProps) {
  const navigate = useNavigate();
  const chatKey = `tableau-asset-chat-${connectionId}`;

  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(chatKey) ?? '[]');
    } catch {
      return [];
    }
  });

  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 连接切换时清空历史
  useEffect(() => {
    setMessages(() => {
      try {
        return JSON.parse(sessionStorage.getItem(chatKey) ?? '[]');
      } catch {
        return [];
      }
    });
    // 中止上一个请求
    abortRef.current?.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionId]);

  // 历史持久化
  useEffect(() => {
    sessionStorage.setItem(chatKey, JSON.stringify(messages));
  }, [messages, chatKey]);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    setInput('');
    setIsLoading(true);

    // 添加用户消息
    const userMsg: ChatMessage = { role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);

    // 构建 history（截取最近 10 轮）
    const historyMessages = [...messages, userMsg]
      .slice(-10)
      .map(m => ({ role: m.role, content: m.content }));

    // 初始化助手消息占位
    const assistantMsg: ChatMessage = {
      role: 'assistant',
      content: '',
      assets: [],
      actions: [],
      toolCalls: [],
      isStreaming: true,
    };
    setMessages(prev => [...prev, assistantMsg]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(`${API_BASE}/api/tableau/assets/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        signal: controller.signal,
        body: JSON.stringify({
          message: text,
          connection_id: connectionId,
          history: historyMessages.slice(0, -1), // 不含当前消息
          context: {
            current_filter: currentFilter || null,
            visible_asset_count: visibleAssetCount || 0,
          },
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => null);
        const errMsg = err?.detail?.message || `请求失败（${response.status}）`;
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === 'assistant') {
            updated[updated.length - 1] = { ...last, content: errMsg, isStreaming: false };
          }
          return updated;
        });
        return;
      }

      if (!response.body) return;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const processFrame = (frame: SSEFrame) => {
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (!last || last.role !== 'assistant') return prev;

          const newLast = { ...last };

          switch (frame.type) {
            case 'text':
              newLast.content = (newLast.content || '') + frame.delta;
              break;
            case 'tool_call':
              newLast.toolCalls = [...(newLast.toolCalls || []), frame.tool];
              break;
            case 'assets':
              newLast.assets = frame.assets;
              break;
            case 'action':
              newLast.actions = [...(newLast.actions || []), frame];
              break;
            case 'done':
              newLast.isStreaming = false;
              newLast.toolCalls = [];
              break;
            case 'error':
              newLast.content = frame.message || '对话服务暂时不可用';
              newLast.isStreaming = false;
              break;
          }

          updated[updated.length - 1] = newLast;
          return updated;
        });
      };

      // 逐块读取，按行解析 SSE
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim();
            if (!data) continue;
            try {
              const frame: SSEFrame = JSON.parse(data);
              processFrame(frame);
            } catch {
              // 忽略 JSON 解析失败的行
            }
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        // 用户切换连接中止
      } else {
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === 'assistant') {
            updated[updated.length - 1] = {
              ...last,
              content: '对话服务暂时不可用，请稍后重试',
              isStreaming: false,
            };
          }
          return updated;
        });
      }
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, messages, connectionId, currentFilter, visibleAssetCount]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleApplyAction = (action: ActionFrame) => {
    if (action.action_type === 'apply_filter') {
      const assetType = action.payload.asset_type as string;
      onApplyFilter(assetType);
    } else if (action.action_type === 'highlight_assets') {
      const assetIds = action.payload.asset_ids as string[];
      onHighlightAssets(assetIds);
    }
  };

  return (
    <div
      className="fixed right-4 bottom-4 w-[380px] max-h-[600px] bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col z-40"
      style={{ zIndex: 40 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 shrink-0">
        <div className="flex items-center gap-2">
          <i className="ri-robot-2-line text-blue-500" />
          <span className="text-sm font-semibold text-slate-800">资产助手</span>
        </div>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-600 transition-colors"
          aria-label="关闭"
        >
          <i className="ri-close-line text-lg" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
        {messages.length === 0 && (
          <div className="text-center text-xs text-slate-400 mt-8">
            <i className="ri-chat-3-line text-2xl text-slate-300 block mb-2" />
            你好！我可以帮你搜索和分析 Tableau 资产。
            <br />
            例如：健康分低于 60 的仪表板
          </div>
        )}

        {messages.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] ${msg.role === 'user' ? '' : 'w-full'}`}>
              {/* 用户消息气泡 */}
              {msg.role === 'user' && (
                <div className="bg-blue-600 text-white text-xs px-3 py-2 rounded-2xl rounded-tr-sm">
                  {msg.content}
                </div>
              )}

              {/* 助手消息 */}
              {msg.role === 'assistant' && (
                <div className="space-y-2">
                  {/* 工具调用状态 */}
                  {msg.isStreaming && msg.toolCalls && msg.toolCalls.length > 0 && (
                    <div className="flex items-center gap-1.5 text-xs text-slate-400">
                      <i className="ri-loader-4-line animate-spin text-blue-400" />
                      正在搜索...
                    </div>
                  )}

                  {/* 文字内容 */}
                  {(msg.content || msg.isStreaming) && (
                    <div className="bg-slate-50 border border-slate-200 rounded-2xl rounded-tl-sm px-3 py-2 text-xs text-slate-700 leading-relaxed">
                      {msg.content}
                      {msg.isStreaming && (
                        <span className="inline-block w-1 h-3 bg-blue-400 ml-0.5 animate-pulse" />
                      )}
                    </div>
                  )}

                  {/* 资产卡片列表 */}
                  {msg.assets && msg.assets.length > 0 && (
                    <div className="space-y-1.5">
                      {msg.assets.map((asset, ai) => (
                        <div
                          key={ai}
                          onClick={() => navigate(`/assets/tableau/${asset.id}`)}
                          className="bg-white border border-slate-200 rounded-xl px-3 py-2.5 cursor-pointer hover:border-blue-300 hover:shadow-sm transition-all"
                        >
                          <div className="flex items-start justify-between gap-2 mb-1">
                            <span className="text-xs font-medium text-slate-800 leading-tight line-clamp-2">
                              {asset.name}
                            </span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded-full shrink-0 ${ASSET_TYPE_COLORS[asset.asset_type] || 'bg-slate-100 text-slate-600'}`}>
                              {ASSET_TYPE_LABELS[asset.asset_type] || asset.asset_type}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 text-[11px] text-slate-400">
                            {asset.project_name && (
                              <span className="truncate">{asset.project_name}</span>
                            )}
                            {asset.health_score != null && (
                              <span className={`font-medium shrink-0 ${healthColor(asset.health_score)}`}>
                                健康分 {asset.health_score}
                              </span>
                            )}
                          </div>
                          {asset.relevance_reason && (
                            <p className="text-[11px] text-slate-400 mt-0.5 leading-tight">
                              {asset.relevance_reason}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Action 按钮（用户确认后才触发） */}
                  {msg.actions && msg.actions.length > 0 && !msg.isStreaming && (
                    <div className="flex flex-wrap gap-1.5">
                      {msg.actions.map((action, ai) => (
                        <button
                          key={ai}
                          onClick={() => handleApplyAction(action)}
                          className="text-[11px] px-2.5 py-1 bg-blue-50 text-blue-600 rounded-lg border border-blue-200 hover:bg-blue-100 transition-colors"
                        >
                          {action.action_label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="px-3 py-3 border-t border-slate-100 shrink-0">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入问题，如：健康分低于 60 的仪表板"
            disabled={isLoading}
            rows={2}
            className="flex-1 resize-none text-xs border border-slate-200 rounded-xl px-3 py-2 focus:outline-none focus:border-blue-400 disabled:opacity-60 disabled:cursor-not-allowed placeholder-slate-300"
          />
          <button
            onClick={sendMessage}
            disabled={isLoading || !input.trim()}
            className="shrink-0 w-8 h-8 bg-blue-600 text-white rounded-xl flex items-center justify-center hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            aria-label="发送"
          >
            {isLoading ? (
              <i className="ri-loader-4-line animate-spin text-sm" />
            ) : (
              <i className="ri-send-plane-2-line text-sm" />
            )}
          </button>
        </div>
        <p className="text-[10px] text-slate-300 mt-1.5 text-center">
          Enter 发送 · Shift+Enter 换行
        </p>
      </div>
    </div>
  );
}
