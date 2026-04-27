/**
 * QueryPage — 自然语言问数页面
 *
 * 布局：左侧 SessionSidebar（260px，可折叠）+ 主区域（居中大留白）
 * URL: /query
 *
 * 主区域结构：
 *   - 顶部工具栏：连接选择 + 数据源选择
 *   - 中间：MessageList（消息流）
 *   - 底部固定：ChatInput
 *
 * 与运维路由（AppShellLayout）完全隔离，使用独立布局
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import SessionSidebar from '../../components/query/SessionSidebar';
import MessageList from '../../components/query/MessageList';
import ChatInput from '../../components/query/ChatInput';
import DataSourceSelector from '../../components/query/DataSourceSelector';
import { useQuerySession } from '../../hooks/useQuerySession';
import { useQuerySessions } from '../../hooks/useQuerySessions';
import { listConnections, type TableauConnection } from '../../api/tableau';
import type { QueryDatasource, QuerySession } from '../../api/query';
import { useAuth } from '../../context/AuthContext';
import { Link } from 'react-router-dom';

const SIDEBAR_STORAGE_KEY = 'mulan-query-sidebar-collapsed';
const SIDEBAR_WIDTH = 260;

export default function QueryPage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  // ── 侧边栏折叠状态（持久化） ──────────────────────────────────────────────
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_STORAGE_KEY, String(sidebarCollapsed));
    } catch {
      /* localStorage not available */
    }
  }, [sidebarCollapsed]);

  const handleToggleSidebar = useCallback(() => setSidebarCollapsed((c) => !c), []);

  // ── 连接列表（Tableau Connections） ──────────────────────────────────────
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [connectionsLoading, setConnectionsLoading] = useState(true);
  // P1-2：记录连接加载错误，给用户可见提示
  const [connectionsError, setConnectionsError] = useState<string | null>(null);
  const [selectedConnectionId, setSelectedConnectionId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setConnectionsLoading(true);
    setConnectionsError(null);
    listConnections(false)
      .then(({ connections: conns }) => {
        if (cancelled) return;
        const active = conns.filter((c) => c.is_active);
        setConnections(active);
        if (active.length === 1) {
          setSelectedConnectionId(active[0].id);
        }
      })
      .catch(() => {
        if (cancelled) return;
        setConnections([]);
        setConnectionsError('连接加载失败，请刷新');
      })
      .finally(() => {
        if (!cancelled) setConnectionsLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // ── 数据源选择 ───────────────────────────────────────────────────────────
  const [selectedDatasource, setSelectedDatasource] = useState<QueryDatasource | null>(null);

  // ── 会话状态 ─────────────────────────────────────────────────────────────
  const { sessions, loading: sessionsLoading, refresh: refreshSessions, removeSession } = useQuerySessions();
  const { sessionId, messages, loading: asking, sendMessage, loadSession, resetSession } =
    useQuerySession();

  // ── 当前会话 ID ref（避免闭包问题） ────────────────────────────────────
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  // ── 新建会话 ─────────────────────────────────────────────────────────────
  const handleNewSession = useCallback(() => {
    resetSession();
    setSelectedDatasource(null);
  }, [resetSession]);

  // ── 删除会话 ───────────────────────────────────────────────────────────────
  const handleDeleteSession = useCallback(
    async (session: QuerySession) => {
      // 若删除的是当前激活会话，先重置
      if (session.session_id === sessionIdRef.current) {
        resetSession();
        setSelectedDatasource(null);
      }
      await removeSession(session.session_id);
    },
    [removeSession, resetSession],
  );

  // ── 历史会话点击 ─────────────────────────────────────────────────────────
  const handleSelectSession = useCallback(
    async (session: QuerySession) => {
      if (session.session_id === sessionIdRef.current) return;
      await loadSession(session.session_id);
      // 若 session 绑定了 connection_id，自动选中
      if (session.connection_id) {
        setSelectedConnectionId(session.connection_id);
      }
    },
    [loadSession],
  );

  // ── 发送消息 ─────────────────────────────────────────────────────────────
  const handleSend = useCallback(
    async (message: string) => {
      if (!selectedConnectionId || !selectedDatasource) return;
      await sendMessage({
        message,
        connection_id: selectedConnectionId,
        datasource_luid: selectedDatasource.luid,
      });
      // 发送后刷新会话列表（新会话会出现在侧边栏）
      refreshSessions();
    },
    [selectedConnectionId, selectedDatasource, sendMessage, refreshSessions],
  );

  // ── 未登录态 ─────────────────────────────────────────────────────────────
  if (!user) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="bg-white rounded-xl border border-slate-200 p-10 w-full max-w-md text-center">
          <h1 className="text-xl font-bold text-slate-800 mb-4">请先登录</h1>
          <Link
            to="/login"
            className="inline-block px-6 py-2.5 bg-blue-700 text-white rounded-lg text-sm font-semibold hover:bg-blue-800 transition-colors"
          >
            去登录
          </Link>
        </div>
      </div>
    );
  }

  const canSend = !!selectedConnectionId && !!selectedDatasource && !asking;

  return (
    <div className="flex flex-row h-screen bg-white text-gray-900">
      {/* 左侧边栏 */}
      <SessionSidebar
        sessions={sessions}
        loading={sessionsLoading}
        currentSessionId={sessionId}
        collapsed={sidebarCollapsed}
        onToggleCollapse={handleToggleSidebar}
        onNewSession={handleNewSession}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
      />

      {/* 侧边栏折叠时的展开按钮 */}
      {sidebarCollapsed && (
        <button
          onClick={handleToggleSidebar}
          title="展开侧边栏"
          aria-label="展开侧边栏"
          className="fixed top-1/2 -translate-y-1/2 left-0 z-50 w-6 h-12 flex items-center justify-center
                     bg-gray-100 hover:bg-gray-200 rounded-r-lg shadow-md transition-colors"
        >
          <i className="ri-sidebar-fold-line text-gray-500 text-sm" />
        </button>
      )}

      {/* 主区域 */}
      <div
        className="flex-1 flex flex-col min-w-0 transition-[margin-left] duration-300"
        style={{ marginLeft: sidebarCollapsed ? 0 : SIDEBAR_WIDTH }}
      >
        {/* 顶部工具栏 */}
        <header className="shrink-0 border-b border-slate-100 bg-white px-6 py-3">
          <div className="max-w-3xl mx-auto flex items-center gap-4 flex-wrap">
            {/* 连接选择 */}
            <div className="flex items-center gap-2">
              <i className="ri-server-line text-sm text-slate-500 shrink-0" />
              {connectionsLoading ? (
                <span className="text-sm text-slate-400">
                  <i className="ri-loader-4-line animate-spin mr-1" />
                  加载连接...
                </span>
              ) : connectionsError ? (
                <span className="text-sm text-red-500">
                  <i className="ri-error-warning-line mr-1" />
                  {connectionsError}
                </span>
              ) : connections.length === 0 ? (
                <span className="text-sm text-slate-400">暂无可用连接</span>
              ) : connections.length === 1 ? (
                <span className="text-sm text-slate-600">{connections[0].name}</span>
              ) : (
                <select
                  value={selectedConnectionId ?? ''}
                  onChange={(e) => {
                    const id = e.target.value ? Number(e.target.value) : null;
                    setSelectedConnectionId(id);
                    setSelectedDatasource(null);
                  }}
                  aria-label="选择连接"
                  className="text-sm text-slate-700 bg-white border border-slate-200 rounded-lg px-2 py-1.5
                             focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400
                             transition-colors max-w-[180px]"
                >
                  <option value="">选择连接...</option>
                  {connections.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* 分隔符 */}
            <span className="text-slate-200 select-none">|</span>

            {/* 数据源选择 */}
            <DataSourceSelector
              connectionId={selectedConnectionId}
              value={selectedDatasource?.luid ?? null}
              onChange={setSelectedDatasource}
              disabled={asking}
            />

            {/* 新对话按钮（右侧） */}
            <button
              onClick={handleNewSession}
              className="ml-auto text-sm text-slate-500 hover:text-slate-700 flex items-center gap-1.5
                         px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors"
            >
              <i className="ri-edit-box-line text-base" />
              新对话
            </button>

            {/* 返回首页 */}
            <button
              onClick={() => navigate('/')}
              className="text-sm text-slate-500 hover:text-slate-700 flex items-center gap-1.5
                         px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors"
            >
              <i className="ri-home-4-line text-base" />
            </button>
          </div>
        </header>

        {/* 消息流（flex-1，可滚动） */}
        <main className="flex-1 overflow-y-auto pb-36">
          <MessageList messages={messages} loading={asking} />
        </main>

        {/* 底部输入框（fixed 定位跟随侧边栏） */}
        <div
          className="fixed bottom-0 right-0 z-20 pointer-events-none"
          style={{
            left: sidebarCollapsed ? 0 : SIDEBAR_WIDTH,
            transition: 'left 300ms',
          }}
        >
          <div className="h-3 w-full bg-gradient-to-t from-white to-white/0" aria-hidden="true" />
          <div className="bg-white pt-2 pb-5 pointer-events-auto">
            <div className="max-w-3xl mx-auto px-6">
              {!selectedDatasource && (
                <p className="text-xs text-slate-400 text-center mb-2">
                  {selectedConnectionId ? '请选择数据源后开始提问' : '请先选择连接和数据源'}
                </p>
              )}
              <ChatInput
                onSend={handleSend}
                disabled={!canSend}
                placeholder={
                  !selectedConnectionId
                    ? '请先在顶部选择连接...'
                    : !selectedDatasource
                    ? '请先在顶部选择数据源...'
                    : '输入问题，回车发送（Shift+Enter 换行）'
                }
              />
              <p className="mt-2 text-center text-[11px] text-slate-400">
                回答由 AI 生成，请核对关键数据后使用
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
