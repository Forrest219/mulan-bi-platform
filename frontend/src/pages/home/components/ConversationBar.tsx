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
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useConversations, type Conversation } from '../../../store/conversationStore';
import { ConfirmModal } from '../../../components/ConfirmModal';
import { useAuth } from '../../../context/AuthContext';
import { LOGO_URL } from '../../../config';

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

export function ConversationBar({ collapsed, onToggleCollapse }: ConversationBarProps) {
  const { conversations, addConversation, deleteConversation, updateConversationTitle } =
    useConversations();
  const { user, logout } = useAuth();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [deleting, setDeleting] = useState(false);

  const navigate = useNavigate();
  const location = useLocation();

  // 当前对话 id（从 URL /chat/:id 或 /?conv= 解析）
  const currentId = location.pathname.startsWith('/chat/')
    ? location.pathname.split('/chat/')[1]
    : new URLSearchParams(location.search).get('conv');

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
    <aside
      id="sidebar"
      className={[
        'h-screen max-h-[100dvh] min-h-screen select-none',
        'fixed top-0 left-0 z-50 shrink-0 overflow-x-hidden',
        'text-sm text-gray-900 dark:text-gray-200',
        collapsed
          ? 'w-0 invisible'
          : 'w-[var(--sidebar-width)] bg-gray-50/70 dark:bg-gray-950/70',
        'transition-[width] duration-300',
      ].join(' ')}
    >
      {/* Inner flex container with my-auto */}
      <div className="my-auto flex flex-col justify-between h-screen max-h-[100dvh] w-[var(--sidebar-width)] overflow-x-hidden scrollbar-hidden">
        {/* Top section: sticky */}
        <div className="sticky top-0 px-[0.5625rem] pt-2 pb-1.5 z-10 bg-gray-50/70 dark:bg-gray-950/70">
          {/* Top: collapse button + brand + new icon */}
          <div className="flex items-center justify-between h-12 px-1 flex-shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <button
                onClick={onToggleCollapse}
                title="折叠侧边栏"
                aria-label="折叠侧边栏"
                className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-xl
                           text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-900
                           transition-colors duration-150"
              >
                <i className="ri-sidebar-fold-line text-base" />
              </button>
              <img
                src={LOGO_URL}
                alt=""
                aria-hidden="true"
                className="w-5 h-5 object-contain flex-shrink-0"
              />
              <span className="text-sm font-semibold text-gray-800 dark:text-gray-200 truncate">木兰平台</span>
            </div>
            <button
              onClick={handleNew}
              title="新对话  ⌘N"
              aria-label="新对话"
              className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-xl
                         text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-900
                         transition-colors duration-150"
            >
              <i className="ri-edit-box-line text-base" />
            </button>
          </div>

          {/* Search box */}
          <div className="px-1 pb-2">
            <div className="relative">
              <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
              <input
                type="text"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="搜索对话..."
                className="w-full pl-7 pr-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-900 border border-transparent
                           rounded-xl focus:outline-none focus:bg-white dark:focus:bg-gray-800 focus:border-gray-200 dark:focus:border-gray-700 placeholder-gray-400"
              />
            </div>
          </div>
        </div>

        {/* Conversation list: overflow-y-auto */}
        <div className="flex-1 overflow-y-auto px-2">
          {GROUP_ORDER.map((group) => {
            const items = grouped[group];
            if (!items || items.length === 0) return null;
            return (
              <div key={group} className="mb-3">
                <div className="text-xs text-gray-400 dark:text-gray-500 font-medium px-2 py-1">{group}</div>
                {items.map((conv) => (
                  <ConversationItem
                    key={conv.id}
                    conv={conv}
                    isActive={conv.id === currentId}
                    onSelect={() => {
                      if (location.pathname === '/') {
                        navigate(`/?conv=${conv.id}`);
                      } else {
                        navigate(`/chat/${conv.id}`);
                      }
                    }}
                    onDelete={() => setDeleteTarget(conv)}
                    onRename={updateConversationTitle}
                  />
                ))}
              </div>
            );
          })}

          {/* Load more (pagination, F-P1-6) */}
          {hasMore && (
            <button
              onClick={() => setPage((p) => p + 1)}
              className="w-full py-2 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-900
                         rounded-xl transition-colors"
            >
              加载更多（剩余 {filtered.length - page * PAGE_SIZE} 条）
            </button>
          )}

          {filtered.length === 0 && (
            <div className="text-xs text-gray-400 dark:text-gray-500 text-center py-8">
              {search ? '无匹配对话' : '暂无对话记录'}
            </div>
          )}
        </div>

        {/* Bottom: sticky */}
        <div className="sticky bottom-0 border-t border-gray-200/50 dark:border-gray-800/50 px-3 py-3 space-y-1 bg-gray-50/70 dark:bg-gray-950/70">
          {/* User info row */}
          <div className="flex items-center gap-2.5 px-2 py-2 rounded-xl hover:bg-gray-100 dark:hover:bg-gray-900 transition-colors cursor-pointer">
            <div className="w-8 h-8 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center shrink-0">
              <span className="text-xs text-gray-600 dark:text-gray-300 font-bold">
                {user?.display_name?.[0] ?? user?.username?.[0] ?? '?'}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm text-gray-800 dark:text-gray-200 font-semibold truncate">
                {user?.display_name ?? user?.username ?? '未知用户'}
              </div>
              <div className="text-xs text-gray-400 dark:text-gray-500">{user?.role ?? 'user'}</div>
            </div>
          </div>

          {/* Settings entry (admin only) */}
          {user?.role === 'admin' && (
            <Link
              to="/system/users"
              className="flex items-center gap-2 px-2 py-1.5 text-sm text-gray-500 dark:text-gray-400
                         rounded-xl hover:bg-gray-100 dark:hover:bg-gray-900 transition-colors"
            >
              <i className="ri-settings-3-line text-base" />
              设置
            </Link>
          )}

          {/* Logout */}
          <button
            onClick={async () => {
              await logout();
              navigate('/login');
            }}
            className="w-full flex items-center gap-2 px-2 py-1.5 text-sm text-gray-500 dark:text-gray-400
                       rounded-xl hover:bg-gray-100 dark:hover:bg-gray-900 transition-colors"
          >
            <i className="ri-logout-box-line text-base" />
            退出登录
          </button>
        </div>
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
    </aside>
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
