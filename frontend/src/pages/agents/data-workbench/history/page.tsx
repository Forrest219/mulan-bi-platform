import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';

interface SessionItem {
  id: string;
  title: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface MessageItem {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  data_table: Record<string, unknown> | null;
  datasource_luid: string | null;
  created_at: string | null;
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '—';
  }
}

function DataTable({ data }: { data: Record<string, unknown> }) {
  const fields = (data.fields as Array<{ fieldCaption?: string; name?: string }>) ?? [];
  const rows = (data.rows as unknown[][]) ?? [];
  if (!fields.length) return null;

  return (
    <div className="mt-3 overflow-x-auto rounded border border-slate-200">
      <table className="min-w-full text-xs">
        <thead>
          <tr className="bg-slate-50">
            {fields.map((f, i) => (
              <th key={i} className="px-3 py-2 text-left font-medium text-slate-600 whitespace-nowrap">
                {f.fieldCaption ?? f.name ?? `列${i + 1}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 10).map((row, ri) => (
            <tr key={ri} className="border-t border-slate-100 hover:bg-slate-50">
              {(Array.isArray(row) ? row : [row]).map((cell, ci) => (
                <td key={ci} className="px-3 py-1.5 text-slate-700 whitespace-nowrap">
                  {cell === null || cell === undefined ? '—' : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 10 && (
        <div className="px-3 py-2 text-xs text-slate-400 border-t border-slate-100">
          共 {rows.length} 行，仅展示前 10 行
        </div>
      )}
    </div>
  );
}

export default function DataWorkbenchHistoryPage() {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [msgLoading, setMsgLoading] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [error, setError] = useState('');

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const resp = await fetch('/api/query/sessions', { credentials: 'include' });
      if (!resp.ok) throw new Error(`请求失败: ${resp.status}`);
      const data = await resp.json();
      setSessions(data.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const fetchMessages = useCallback(async (sessionId: string) => {
    setMsgLoading(true);
    setMessages([]);
    try {
      const resp = await fetch(`/api/query/sessions/${sessionId}/messages`, {
        credentials: 'include',
      });
      if (!resp.ok) throw new Error(`请求失败: ${resp.status}`);
      const data = await resp.json();
      setMessages(data.messages ?? []);
    } catch {
      setMessages([]);
    } finally {
      setMsgLoading(false);
    }
  }, []);

  const handleSelectSession = (id: string) => {
    setSelectedId(id);
    fetchMessages(id);
  };

  const handleDeleteSession = async (id: string) => {
    try {
      await fetch(`/api/query/sessions/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      setSessions(prev => prev.filter(s => s.id !== id));
      if (selectedId === id) {
        setSelectedId(null);
        setMessages([]);
      }
    } catch {
      // 静默处理
    } finally {
      setDeleteConfirm(null);
    }
  };

  const selectedSession = sessions.find(s => s.id === selectedId);

  return (
    <div className="flex h-full min-h-0 gap-4 p-6">
      {/* 左侧：会话列表 */}
      <div className="w-72 flex-shrink-0 flex flex-col bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
          <span className="text-sm font-semibold text-slate-800">历史对话</span>
          <Link
            to="/agents/data"
            className="text-xs text-indigo-600 hover:text-indigo-700 flex items-center gap-1"
          >
            <i className="ri-add-line" />
            新建
          </Link>
        </div>

        {loading ? (
          <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">
            加载中…
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center text-red-500 text-sm px-4 text-center">
            {error}
          </div>
        ) : sessions.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-2 text-slate-400 text-sm">
            <i className="ri-chat-history-line text-2xl" />
            <span>暂无历史对话</span>
          </div>
        ) : (
          <ul className="flex-1 overflow-y-auto divide-y divide-slate-100">
            {sessions.map(s => (
              <li key={s.id}>
                <button
                  onClick={() => handleSelectSession(s.id)}
                  className={`w-full text-left px-4 py-3 hover:bg-slate-50 transition-colors group ${
                    selectedId === s.id ? 'bg-indigo-50' : ''
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p
                      className={`text-sm truncate flex-1 ${
                        selectedId === s.id ? 'text-indigo-700 font-medium' : 'text-slate-700'
                      }`}
                    >
                      {s.title ?? '未命名对话'}
                    </p>
                    <button
                      onClick={e => {
                        e.stopPropagation();
                        setDeleteConfirm(s.id);
                      }}
                      className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-500 transition-opacity flex-shrink-0 mt-0.5"
                    >
                      <i className="ri-delete-bin-line text-sm" />
                    </button>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {formatDateTime(s.updated_at ?? s.created_at)}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 右侧：消息详情 */}
      <div className="flex-1 flex flex-col bg-white rounded-xl border border-slate-200 overflow-hidden min-w-0">
        {!selectedId ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-slate-400">
            <i className="ri-chat-2-line text-3xl" />
            <p className="text-sm">选择左侧对话查看详情</p>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100">
              <div>
                <span className="text-sm font-semibold text-slate-800">
                  {selectedSession?.title ?? '未命名对话'}
                </span>
                <span className="ml-3 text-xs text-slate-400">
                  {formatDateTime(selectedSession?.created_at ?? null)}
                </span>
              </div>
              <Link
                to="/agents/data"
                state={{ sessionId: selectedId }}
                className="text-xs text-indigo-600 hover:text-indigo-700 flex items-center gap-1"
              >
                <i className="ri-external-link-line" />
                继续对话
              </Link>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              {msgLoading ? (
                <div className="flex items-center justify-center py-8 text-slate-400 text-sm">
                  加载中…
                </div>
              ) : messages.length === 0 ? (
                <div className="flex items-center justify-center py-8 text-slate-400 text-sm">
                  暂无消息记录
                </div>
              ) : (
                messages.map(m => (
                  <div
                    key={m.id}
                    className={`flex gap-3 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}
                  >
                    <div
                      className={`w-7 h-7 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-semibold ${
                        m.role === 'user'
                          ? 'bg-indigo-100 text-indigo-600'
                          : 'bg-slate-100 text-slate-500'
                      }`}
                    >
                      {m.role === 'user' ? '我' : 'AI'}
                    </div>
                    <div
                      className={`flex-1 max-w-prose ${
                        m.role === 'user' ? 'items-end' : 'items-start'
                      } flex flex-col`}
                    >
                      <div
                        className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
                          m.role === 'user'
                            ? 'bg-indigo-600 text-white rounded-tr-sm'
                            : 'bg-slate-100 text-slate-800 rounded-tl-sm'
                        }`}
                      >
                        {m.content}
                      </div>
                      {m.data_table && m.role === 'assistant' && (
                        <DataTable data={m.data_table as Record<string, unknown>} />
                      )}
                      <span className="text-xs text-slate-400 mt-1 px-1">
                        {formatDateTime(m.created_at)}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </div>

      {/* 删除确认弹窗 */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
          <div className="bg-white rounded-xl shadow-xl p-6 w-80">
            <h3 className="text-sm font-semibold text-slate-800 mb-2">删除对话</h3>
            <p className="text-sm text-slate-500 mb-5">此操作不可恢复，确定删除该对话记录？</p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => handleDeleteSession(deleteConfirm)}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
