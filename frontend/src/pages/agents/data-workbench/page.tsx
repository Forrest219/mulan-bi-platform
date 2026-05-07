import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { agentConversationsApi, agentAdminApi } from '../../../api/agent';
import type { AgentConversationItem, AgentToolMetadata } from '../../../api/agent';

function formatDate(iso: string) {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

const CATEGORY_COLORS: Record<string, string> = {
  data: 'bg-blue-50 text-blue-700',
  visualization: 'bg-purple-50 text-purple-700',
  knowledge: 'bg-amber-50 text-amber-700',
  analysis: 'bg-emerald-50 text-emerald-700',
};

export default function DataWorkbenchPage() {
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<AgentConversationItem[]>([]);
  const [tools, setTools] = useState<AgentToolMetadata[]>([]);
  const [convLoading, setConvLoading] = useState(true);
  const [toolsLoading, setToolsLoading] = useState(true);
  const [convError, setConvError] = useState('');
  const [toolsError, setToolsError] = useState('');

  useEffect(() => {
    agentConversationsApi.list()
      .then(setConversations)
      .catch(() => setConvError('加载会话列表失败'))
      .finally(() => setConvLoading(false));

    agentAdminApi.getTools()
      .then(setTools)
      .catch(() => setToolsError('加载工具列表失败'))
      .finally(() => setToolsLoading(false));
  }, []);

  const activeCount = conversations.filter(c => c.status === 'active').length;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-bar-chart-2-line text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">Data Agent</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">数据分析和查询的智能交互工作台</p>
          </div>
          <button
            onClick={() => navigate('/')}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            <i className="ri-chat-new-line text-base" />
            开始新对话
          </button>
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto space-y-6">
        {/* Quick stats */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-white rounded-xl border border-slate-200 px-5 py-4">
            <p className="text-[12px] text-slate-400 uppercase tracking-wider mb-1">历史对话</p>
            <p className="text-2xl font-semibold text-slate-800">{convLoading ? '—' : conversations.length}</p>
          </div>
          <div className="bg-white rounded-xl border border-slate-200 px-5 py-4">
            <p className="text-[12px] text-slate-400 uppercase tracking-wider mb-1">活跃对话</p>
            <p className="text-2xl font-semibold text-emerald-600">{convLoading ? '—' : activeCount}</p>
          </div>
          <div className="bg-white rounded-xl border border-slate-200 px-5 py-4">
            <p className="text-[12px] text-slate-400 uppercase tracking-wider mb-1">可用工具</p>
            <p className="text-2xl font-semibold text-blue-600">{toolsLoading ? '—' : tools.length}</p>
          </div>
        </div>

        <div className="grid grid-cols-5 gap-6">
          {/* Conversations */}
          <div className="col-span-3 bg-white rounded-xl border border-slate-200">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-700">最近对话</h2>
              <span className="text-[12px] text-slate-400">最多显示 20 条</span>
            </div>
            {convLoading ? (
              <div className="px-5 py-8 text-center text-sm text-slate-400">加载中…</div>
            ) : convError ? (
              <div className="px-5 py-8 text-center text-sm text-red-500">{convError}</div>
            ) : conversations.length === 0 ? (
              <div className="px-5 py-12 text-center text-sm text-slate-400">
                <i className="ri-chat-3-line text-3xl text-slate-300 block mb-2" />
                暂无对话，点击「开始新对话」
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="text-left px-5 py-2.5 text-[11px] font-medium text-slate-400 uppercase tracking-wider">标题</th>
                    <th className="text-left px-3 py-2.5 text-[11px] font-medium text-slate-400 uppercase tracking-wider w-16">消息数</th>
                    <th className="text-left px-3 py-2.5 text-[11px] font-medium text-slate-400 uppercase tracking-wider w-36">最近更新</th>
                    <th className="w-16" />
                  </tr>
                </thead>
                <tbody>
                  {conversations.map(c => (
                    <tr key={c.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                      <td className="px-5 py-2.5 text-slate-700 max-w-0">
                        <span className="block truncate">{c.title || '（无标题）'}</span>
                      </td>
                      <td className="px-3 py-2.5 text-slate-500 text-center">{c.message_count}</td>
                      <td className="px-3 py-2.5 text-slate-400 text-[12px] whitespace-nowrap">{formatDate(c.updated_at)}</td>
                      <td className="px-3 py-2.5">
                        <button
                          onClick={() => navigate(`/chat/${c.id}`)}
                          className="text-blue-500 hover:text-blue-700 text-[12px] whitespace-nowrap"
                        >
                          继续 →
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Tools */}
          <div className="col-span-2 bg-white rounded-xl border border-slate-200">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="text-sm font-semibold text-slate-700">可用工具</h2>
            </div>
            {toolsLoading ? (
              <div className="px-5 py-8 text-center text-sm text-slate-400">加载中…</div>
            ) : toolsError ? (
              <div className="px-5 py-8 text-center text-sm text-red-500">{toolsError}</div>
            ) : tools.length === 0 ? (
              <div className="px-5 py-8 text-center text-sm text-slate-400">暂无工具</div>
            ) : (
              <div className="divide-y divide-slate-50">
                {tools.map(t => (
                  <div key={t.name} className="px-5 py-3">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-[12px] font-medium text-slate-700">{t.name}</span>
                      {t.category && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${CATEGORY_COLORS[t.category] ?? 'bg-slate-100 text-slate-600'}`}>
                          {t.category}
                        </span>
                      )}
                    </div>
                    <p className="text-[12px] text-slate-400 line-clamp-2">{t.description}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
        </div>
      </div>
    </div>
  );
}
