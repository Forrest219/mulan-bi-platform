/**
 * SessionSidebar — 问数模块左侧边栏
 *
 * 组成：
 *   - 顶部：折叠按钮 + 「新对话」按钮
 *   - 会话列表（按 updated_at 倒序，时间分组）
 *   - 点击会话：触发 onSelectSession 回调
 *
 * Props 驱动，无业务状态
 */
import { memo, useMemo } from 'react';
import type { QuerySession } from '../../api/query';

// ─── 时间分组（本地时区）────────────────────────────────────────────────────

type TimeGroup = '今天' | '昨天' | '过去 7 天' | '更早';

function getTimeGroup(isoString: string): TimeGroup {
  const now = new Date();
  const date = new Date(isoString);
  const nowDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dateDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.round((nowDay.getTime() - dateDay.getTime()) / 86400000);
  if (diffDays === 0) return '今天';
  if (diffDays === 1) return '昨天';
  if (diffDays <= 7) return '过去 7 天';
  return '更早';
}

const GROUP_ORDER: TimeGroup[] = ['今天', '昨天', '过去 7 天', '更早'];

// ─── Props ────────────────────────────────────────────────────────────────────

interface SessionSidebarProps {
  sessions: QuerySession[];
  loading: boolean;
  currentSessionId: string | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNewSession: () => void;
  onSelectSession: (session: QuerySession) => void;
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function SessionSidebar({
  sessions,
  loading,
  currentSessionId,
  collapsed,
  onToggleCollapse,
  onNewSession,
  onSelectSession,
}: SessionSidebarProps) {
  const grouped = useMemo(() => {
    const map: Partial<Record<TimeGroup, QuerySession[]>> = {};
    for (const s of sessions) {
      const group = getTimeGroup(s.updated_at);
      if (!map[group]) map[group] = [];
      map[group]!.push(s);
    }
    return map;
  }, [sessions]);

  return (
    <aside
      className={[
        'h-screen max-h-[100dvh] min-h-screen select-none',
        'fixed top-0 left-0 z-50 shrink-0 overflow-x-hidden',
        'text-sm text-gray-900',
        collapsed
          ? 'w-0 invisible'
          : 'w-[260px] bg-gray-50/70 border-r border-gray-100',
        'transition-[width] duration-300',
      ].join(' ')}
    >
      <div className="flex flex-col h-screen max-h-[100dvh] w-[260px] overflow-x-hidden">
        {/* 顶部操作栏 */}
        <div className="sticky top-0 px-2 pt-2 pb-2 z-10 bg-gray-50/70">
          <div className="flex items-center justify-between h-12 px-1">
            <div className="flex items-center gap-2">
              <button
                onClick={onToggleCollapse}
                title="折叠侧边栏"
                aria-label="折叠侧边栏"
                className="w-8 h-8 flex items-center justify-center rounded-xl text-gray-400
                           hover:bg-gray-100 transition-colors duration-150"
              >
                <i className="ri-sidebar-fold-line text-base" />
              </button>
              <span className="text-sm font-semibold text-gray-800">问数历史</span>
            </div>
            <button
              onClick={onNewSession}
              title="新对话"
              aria-label="新对话"
              className="w-8 h-8 flex items-center justify-center rounded-xl text-gray-400
                         hover:bg-gray-100 transition-colors duration-150"
            >
              <i className="ri-edit-box-line text-base" />
            </button>
          </div>
        </div>

        {/* 会话列表 */}
        <div className="flex-1 overflow-y-auto px-2 pb-4">
          {loading && (
            <div className="flex items-center justify-center py-8 text-slate-300 text-xs">
              <i className="ri-loader-4-line animate-spin mr-1.5" />
              加载中...
            </div>
          )}

          {!loading && sessions.length === 0 && (
            <div className="text-xs text-gray-400 text-center py-8">
              暂无问数记录
            </div>
          )}

          {!loading && GROUP_ORDER.map((group) => {
            const items = grouped[group];
            if (!items || items.length === 0) return null;
            return (
              <div key={group} className="mb-3">
                <div className="text-xs text-gray-400 font-medium px-2 py-1">{group}</div>
                {items.map((session) => (
                  <SessionItem
                    key={session.session_id}
                    session={session}
                    isActive={session.session_id === currentSessionId}
                    onSelectSession={onSelectSession}
                  />
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
}

// ─── SessionItem ──────────────────────────────────────────────────────────────

interface SessionItemProps {
  session: QuerySession;
  isActive: boolean;
  /** P1-3：接收稳定引用的 handler，避免内联箭头让 memo 失效 */
  onSelectSession: (session: QuerySession) => void;
}

// P1-3：memo 防止 SessionSidebar 重渲染时未变化的列表项重新渲染
const SessionItem = memo(function SessionItem({ session, isActive, onSelectSession }: SessionItemProps) {
  return (
    <button
      onClick={() => onSelectSession(session)}
      className={[
        'w-full text-left flex items-center gap-2 px-2 py-2 rounded-lg cursor-pointer',
        'transition-colors text-sm',
        isActive
          ? 'bg-blue-50 text-blue-700'
          : 'text-slate-600 hover:bg-slate-100',
      ].join(' ')}
    >
      <i className={`ri-chat-3-line text-base shrink-0 ${isActive ? 'text-blue-500' : 'text-slate-400'}`} />
      <div className="flex-1 min-w-0">
        <div className="truncate text-sm">{session.title || '未命名对话'}</div>
        {session.datasource_name && (
          <div className="truncate text-xs text-slate-400 mt-0.5">{session.datasource_name}</div>
        )}
      </div>
    </button>
  );
});
