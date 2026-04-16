/**
 * ConversationBar — 左侧对话历史栏
 *
 * 组成：
 *   - 顶部：折叠按钮 + 新建对话按钮
 *   - 搜索框（本地过滤）
 *   - 对话列表（时间分组：今天 / 昨天 / 过去7天 / 更早）
 *   - 底部快捷导航
 *
 * P1 变更：
 * - 对话 item hover 显示 ... 菜单（重命名 / 删除）
 * - 重命名：inline 编辑，失焦调 updateConversationTitle
 * - 删除：ConfirmModal 确认，确认后调 deleteConversation，当前对话跳回 /
 * - > 100 条时分页加载（简单方案，不引入新依赖）
 * - 时间分组使用浏览器本地时区（C5）
 * - 导航：点击对话跳转 /chat/:id（useNavigate）
 */
import { useState, useMemo, useRef, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useConversations, type Conversation } from '../../../store/conversationStore';
import { ConfirmModal } from '../../../components/ConfirmModal';
import { useAuth } from '../../../context/AuthContext';

const PAGE_SIZE = 100;

interface ConversationBarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

// ─── 时间分组（本地时区）────────────────────────────────────────────────────

type TimeGroup = '今天' | '昨天' | '过去 7 天' | '更早';

function getTimeGroup(isoString: string): TimeGroup {
  const now = new Date();
  const date = new Date(isoString);

  const nowDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dateDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());

  const diffMs = nowDay.getTime() - dateDay.getTime();
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return '今天';
  if (diffDays === 1) return '昨天';
  if (diffDays <= 7) return '过去 7 天';
  return '更早';
}

const GROUP_ORDER: TimeGroup[] = ['今天', '昨天', '过去 7 天', '更早'];

// ─── Component ────────────────────────────────────────────────────────────────

export function ConversationBar({ collapsed: _collapsed, onToggleCollapse }: ConversationBarProps) {
  const { conversations, addConversation, deleteConversation, updateConversationTitle } =
    useConversations();
  const { user, logout } = useAuth();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [deleting, setDeleting] = useState(false);

  const navigate = useNavigate();
  const location = useLocation();

  // 当前对话 id（从 URL /chat/:id 解析）
  const currentId = location.pathname.startsWith('/chat/')
    ? location.pathname.split('/chat/')[1]
    : null;

  const handleNew = useCallback(async () => {
    const id = await addConversation();
    navigate(`/chat/${id}`);
  }, [addConversation, navigate]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter(
      (c) =>
        c.title.toLowerCase().includes(q) ||
        c.messages.some((m) => m.content.toLowerCase().includes(q))
    );
  }, [conversations, search]);

  // 分页（P1-6：> 100 条时分页）
  const paged = useMemo(() => filtered.slice(0, page * PAGE_SIZE), [filtered, page]);

  const grouped = useMemo(() => {
    const map: Partial<Record<TimeGroup, Conversation[]>> = {};
    for (const conv of paged) {
      const group = getTimeGroup(conv.updated_at);
      if (!map[group]) map[group] = [];
      map[group]!.push(conv);
    }
    return map;
  }, [paged]);

  const hasMore = filtered.length > page * PAGE_SIZE;

  const handleDeleteConfirm = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteConversation(deleteTarget.id);
      if (currentId === deleteTarget.id) {
        navigate('/');
      }
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  }, [deleteTarget, deleteConversation, currentId, navigate]);

  return (
    <div
      className="bg-slate-50 border-r border-slate-200 flex flex-col h-full"
      style={{ minHeight: '100vh' }}
    >
      {/* 顶部：折叠 + 新建 */}
      <div className="flex items-center gap-2 px-3 pt-4 pb-2">
        <button
          onClick={onToggleCollapse}
          className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-slate-200 transition-colors text-slate-500"
          aria-label="折叠对话历史"
        >
          <i className="ri-layout-left-line text-base" />
        </button>
        <button
          onClick={handleNew}
          className="flex-1 flex items-center gap-1.5 px-3 py-1.5 text-sm text-slate-600
                     border border-slate-200 rounded-lg hover:bg-white hover:shadow-sm transition-all"
        >
          <i className="ri-add-line text-base" />
          新对话
          <span className="ml-auto text-[10px] text-slate-300 select-none">⌘N</span>
        </button>
      </div>

      {/* 搜索框 */}
      <div className="px-3 pb-2">
        <div className="relative">
          <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="搜索对话..."
            className="w-full pl-7 pr-3 py-1.5 text-sm bg-white border border-slate-200
                       rounded-lg focus:outline-none focus:border-blue-300 placeholder-slate-400"
          />
        </div>
      </div>

      {/* 对话列表 */}
      <div className="flex-1 overflow-y-auto px-2">
        {GROUP_ORDER.map((group) => {
          const items = grouped[group];
          if (!items || items.length === 0) return null;
          return (
            <div key={group} className="mb-3">
              <div className="text-xs text-slate-400 font-medium px-2 py-1">{group}</div>
              {items.map((conv) => (
                <ConversationItem
                  key={conv.id}
                  conv={conv}
                  isActive={conv.id === currentId}
                  onSelect={() => navigate(`/chat/${conv.id}`)}
                  onDelete={() => setDeleteTarget(conv)}
                  onRename={updateConversationTitle}
                />
              ))}
            </div>
          );
        })}

        {/* 加载更多（分页，F-P1-6） */}
        {hasMore && (
          <button
            onClick={() => setPage((p) => p + 1)}
            className="w-full py-2 text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-100
                       rounded-lg transition-colors"
          >
            加载更多（剩余 {filtered.length - page * PAGE_SIZE} 条）
          </button>
        )}

        {filtered.length === 0 && (
          <div className="text-xs text-slate-400 text-center py-8">
            {search ? '无匹配对话' : '暂无对话记录'}
          </div>
        )}
      </div>

      {/* 底部：用户信息 + 设置 + 退出 */}
      <div className="border-t border-slate-200 px-3 py-3 space-y-1">
        {/* 用户信息行 */}
        <div className="flex items-center gap-2 px-2 py-1.5">
          <div className="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
            <span className="text-[11px] text-blue-600 font-semibold">
              {user?.display_name?.[0] ?? user?.username?.[0] ?? '?'}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[13px] text-slate-700 font-medium truncate">
              {user?.display_name ?? user?.username ?? '未知用户'}
            </div>
            <div className="text-[11px] text-slate-400">{user?.role ?? 'user'}</div>
          </div>
        </div>

        {/* 设置入口 */}
        <a
          href="/system/users"
          className="flex items-center gap-2 px-2 py-1.5 text-sm text-slate-500
                     rounded-lg hover:bg-slate-100 hover:text-slate-700 transition-colors"
        >
          <i className="ri-settings-3-line text-base" />
          设置
        </a>

        {/* 退出登录 */}
        <button
          onClick={async () => {
            await logout();
            navigate('/login');
          }}
          className="w-full flex items-center gap-2 px-2 py-1.5 text-sm text-slate-500
                     rounded-lg hover:bg-slate-100 hover:text-slate-700 transition-colors"
        >
          <i className="ri-logout-box-line text-base" />
          退出登录
        </button>
      </div>

      {/* 删除确认弹窗 */}
      <ConfirmModal
        open={!!deleteTarget}
        title="删除对话"
        message={`确定删除「${deleteTarget?.title ?? ''}」吗？此操作不可撤销。`}
        confirmLabel="删除"
        variant="danger"
        loading={deleting}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

// ─── ConversationItem ─────────────────────────────────────────────────────────

interface ConversationItemProps {
  conv: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onRename: (id: string, title: string) => Promise<void>;
}

function ConversationItem({ conv, isActive, onSelect, onDelete, onRename }: ConversationItemProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(conv.title);
  const menuRef = useRef<HTMLDivElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const handleMenuToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    setMenuOpen((o) => !o);
  };

  const handleRenameStart = (e: React.MouseEvent) => {
    e.stopPropagation();
    setMenuOpen(false);
    setRenameValue(conv.title);
    setRenaming(true);
    // 等下一帧聚焦
    setTimeout(() => renameInputRef.current?.focus(), 0);
  };

  const handleRenameBlur = async () => {
    const trimmed = renameValue.trim();
    if (trimmed && trimmed !== conv.title) {
      await onRename(conv.id, trimmed);
    }
    setRenaming(false);
  };

  const handleRenameKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      renameInputRef.current?.blur();
    }
    if (e.key === 'Escape') {
      setRenameValue(conv.title);
      setRenaming(false);
    }
  };

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setMenuOpen(false);
    onDelete();
  };

  return (
    <div
      className={`group relative flex items-center gap-1 px-2 py-1.5 rounded-lg cursor-pointer
                  transition-colors text-sm ${
                    isActive
                      ? 'bg-blue-50 text-blue-700'
                      : 'text-slate-600 hover:bg-slate-100'
                  }`}
      onClick={() => {
        if (!renaming) onSelect();
      }}
    >
      {renaming ? (
        <input
          ref={renameInputRef}
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onBlur={handleRenameBlur}
          onKeyDown={handleRenameKeyDown}
          onClick={(e) => e.stopPropagation()}
          className="flex-1 text-sm bg-white border border-blue-300 rounded px-1 py-0 focus:outline-none"
        />
      ) : (
        <span className="flex-1 truncate">{conv.title}</span>
      )}

      {/* ... 菜单按钮 */}
      {!renaming && (
        <div className="relative" ref={menuRef}>
          <button
            onClick={handleMenuToggle}
            className="opacity-0 group-hover:opacity-100 w-5 h-5 flex items-center justify-center
                       rounded hover:bg-slate-200 transition-all text-slate-400"
            aria-label="更多操作"
          >
            <i className="ri-more-2-line text-xs" />
          </button>

          {menuOpen && (
            <>
              {/* 点击外部关闭 */}
              <div
                className="fixed inset-0 z-40"
                onClick={(e) => { e.stopPropagation(); setMenuOpen(false); }}
              />
              <div
                className="absolute right-0 top-6 z-50 bg-white border border-slate-200 rounded-lg
                           shadow-lg py-1 w-28 text-sm"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  onClick={handleRenameStart}
                  className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-slate-50
                             text-slate-600 transition-colors"
                >
                  <i className="ri-pencil-line text-xs" />
                  重命名
                </button>
                <button
                  onClick={handleDeleteClick}
                  className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-red-50
                             text-red-500 transition-colors"
                >
                  <i className="ri-delete-bin-line text-xs" />
                  删除
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
