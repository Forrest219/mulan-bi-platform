import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { buildSearchEntries, searchEntries } from '../../config/sitemap';
import { getAvatarGradient } from '../../config';
import {
  type AppNotification,
  getUnreadCount,
  listNotifications,
  markNotificationRead,
  markNotificationUnread,
  markAllNotificationsRead,
  deleteNotification,
} from '../../api/notifications';

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}天前`;
  return new Date(dateStr).toLocaleDateString('zh-CN');
}

function getNotifIconStyle(title: string, level: string) {
  if (title.includes('[P0]') || level === 'error') {
    return { icon: 'ri-alarm-warning-fill', bg: 'bg-red-100', color: 'text-red-500' };
  }
  if (title.includes('巡检') || title.includes('完成') || title.includes('成功')) {
    return { icon: 'ri-checkbox-circle-fill', bg: 'bg-emerald-100', color: 'text-emerald-500' };
  }
  if (title.includes('审核')) {
    return { icon: 'ri-information-fill', bg: 'bg-blue-100', color: 'text-blue-500' };
  }
  if (level === 'warning') {
    return { icon: 'ri-error-warning-fill', bg: 'bg-amber-100', color: 'text-amber-500' };
  }
  return { icon: 'ri-notification-3-line', bg: 'bg-slate-100', color: 'text-slate-400' };
}

interface AppHeaderProps {
  onOpenHelpAgent?: () => void;
}

export default function AppHeader({ onOpenHelpAgent }: AppHeaderProps) {
  const { user, logout, hasPermission } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [notifLoading, setNotifLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchFocused, setSearchFocused] = useState(false);

  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const entries = buildSearchEntries(user?.role ?? 'user', hasPermission);
    return searchEntries(entries, searchQuery);
  }, [searchQuery, user?.role, hasPermission]);

  const avatarGradient = getAvatarGradient(user?.display_name ?? 'A');

  const fetchUnread = useCallback(async () => {
    try {
      const count = await getUnreadCount();
      setUnreadCount(count);
    } catch (_e) { /* silent */ }
  }, []);

  const fetchNotifs = useCallback(async () => {
    setNotifLoading(true);
    try {
      const { items } = await listNotifications(1, 15);
      setNotifications(items);
    } catch (_e) { /* silent */ }
    finally { setNotifLoading(false); }
  }, []);

  useEffect(() => {
    fetchUnread();
    const timer = setInterval(fetchUnread, 60_000);
    return () => clearInterval(timer);
  }, [fetchUnread]);

  useEffect(() => {
    if (notifOpen) fetchNotifs();
  }, [notifOpen, fetchNotifs]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && searchFocused) {
        setSearchQuery('');
        setSearchFocused(false);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchFocused(true);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [searchFocused]);

  useEffect(() => {
    if (searchFocused) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [searchFocused]);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const handleNotifClick = async (n: AppNotification) => {
    if (!n.is_read) {
      await markNotificationRead(n.id);
      setNotifications(prev => prev.map(x => x.id === n.id ? { ...x, is_read: true } : x));
      setUnreadCount(prev => Math.max(0, prev - 1));
    }
    setNotifOpen(false);
    if (n.link) navigate(n.link);
  };

  const handleQuickToggle = async (n: AppNotification) => {
    if (n.is_read) {
      await markNotificationUnread(n.id);
      setNotifications(prev => prev.map(x => x.id === n.id ? { ...x, is_read: false } : x));
      setUnreadCount(prev => prev + 1);
    } else {
      await markNotificationRead(n.id);
      setNotifications(prev => prev.map(x => x.id === n.id ? { ...x, is_read: true } : x));
      setUnreadCount(prev => Math.max(0, prev - 1));
    }
  };

  const handleQuickDelete = async (id: number) => {
    await deleteNotification(id);
    setNotifications(prev => {
      const deleted = prev.find(x => x.id === id);
      if (deleted && !deleted.is_read) {
        setUnreadCount(c => Math.max(0, c - 1));
      }
      return prev.filter(x => x.id !== id);
    });
  };

  const handleMarkAllRead = async () => {
    await markAllNotificationsRead();
    setNotifications(prev => prev.map(x => ({ ...x, is_read: true })));
    setUnreadCount(0);
  };

  const handleOpenHelpAgent = () => {
    setNotifOpen(false);
    setMenuOpen(false);
    onOpenHelpAgent?.();
  };

  const badgeLabel = unreadCount > 99 ? '99+' : String(unreadCount);

  return (
    <header className="h-[58px] bg-white border-b border-slate-200 flex items-center justify-between px-4 gap-3 shrink-0 z-30">
      {/* 左半部分：操作组 */}
      <div className="flex items-center gap-2">
        {/* 全局搜索 */}
        <div className="relative">
          <button
            onClick={() => setSearchFocused(true)}
            className="flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-lg bg-slate-50 border border-slate-200 hover:border-slate-300 hover:bg-white transition-colors text-slate-400 hover:text-slate-500"
            aria-label="搜索功能页面"
          >
            <i className="ri-search-line text-sm shrink-0" />
            <span className="text-[13px] whitespace-nowrap">搜索功能页面…</span>
            <kbd className="ml-1 px-1.5 py-0.5 text-[10px] bg-slate-100 border border-slate-200 rounded text-slate-400 font-mono">⌘K</kbd>
          </button>

          {searchFocused && (
            <>
              <div
                className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
                onClick={() => { setSearchFocused(false); setSearchQuery(''); }}
                aria-hidden="true"
              />
              <div
                role="dialog"
                aria-modal="true"
                aria-label="搜索功能页面"
                className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]"
              >
                <div
                  className="w-full max-w-[620px] bg-white rounded-2xl shadow-2xl border border-slate-200/80 overflow-hidden"
                  onClick={e => e.stopPropagation()}
                >
                  <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-100">
                    <i className="ri-search-line text-xl text-slate-400 shrink-0" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={e => setSearchQuery(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Escape') {
                          setSearchQuery('');
                          setSearchFocused(false);
                        }
                      }}
                      placeholder="搜索功能页面、快捷命令…"
                      autoFocus
                      className="flex-1 h-12 text-base bg-transparent focus:outline-none text-slate-800 placeholder-slate-400"
                    />
                    <span className="text-xs text-slate-400 bg-slate-100 px-2 py-1 rounded-md">ESC</span>
                  </div>

                  <div className="max-h-[28rem] overflow-y-auto">
                    {searchResults.length > 0 ? (
                      <>
                        <div className="px-4 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider bg-slate-50/50">
                          功能操作
                        </div>
                        {searchResults.map(entry => (
                          <button
                            key={entry.key}
                            onMouseDown={e => {
                              e.preventDefault();
                              navigate(entry.path);
                              setSearchQuery('');
                              setSearchFocused(false);
                            }}
                            className="w-full flex items-start gap-3 px-4 py-3 hover:bg-slate-50 transition-colors"
                          >
                            <i className={`${entry.icon} text-lg text-slate-400 shrink-0 mt-0.5`} />
                            <div className="flex-1 min-w-0 text-left">
                              <div>
                                {entry.group && (
                                  <span className="text-sm text-slate-400">{entry.group} / </span>
                                )}
                                <span className="text-sm text-slate-700">{entry.label}</span>
                              </div>
                              {entry.description && (
                                <div className="text-xs text-slate-400 mt-0.5 line-clamp-1">{entry.description}</div>
                              )}
                            </div>
                            <i className="ri-arrow-right-up-line text-sm text-slate-300 shrink-0 mt-1" />
                          </button>
                        ))}
                      </>
                    ) : searchQuery ? (
                      <div className="py-12 text-center text-sm text-slate-400">无匹配结果</div>
                    ) : (
                      <div className="px-4 py-3">
                        <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">快捷入口</div>
                        <div className="space-y-1">
                          {[
                            { label: 'Tableau 资产', path: '/tableau/assets', icon: 'ri-bar-chart-box-line' },
                            { label: '数据质量', path: '/governance/dqc', icon: 'ri-shield-check-line' },
                            { label: 'LLM 配置', path: '/system/llm', icon: 'ri-brain-line' },
                            { label: '同步日志', path: '/tableau/sync-logs', icon: 'ri-time-line' },
                            { label: '用户管理', path: '/system/users', icon: 'ri-user-settings-line' },
                            { label: 'MCP 配置', path: '/system/mcp-configs', icon: 'ri-plug-line' },
                          ].map(item => (
                            <button
                              key={item.path}
                              onMouseDown={e => {
                                e.preventDefault();
                                navigate(item.path);
                                setSearchQuery('');
                                setSearchFocused(false);
                              }}
                              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-50 transition-colors text-left"
                            >
                              <i className={`${item.icon} text-base text-slate-400 shrink-0`} />
                              <span className="text-sm text-slate-600">{item.label}</span>
                            </button>
                          ))}
                        </div>
                        <div className="mt-3 pt-2.5 border-t border-slate-100">
                          <div className="flex items-center justify-center gap-2 text-xs text-slate-400">
                            <i className="ri-search-line text-base" />
                            <span>输入关键词搜索功能页面</span>
                            <span className="text-slate-300">·</span>
                            <kbd className="px-1.5 py-0.5 bg-slate-100 rounded text-slate-500 font-mono text-[10px]">⌘K</kbd>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* 右半部分：用户状态组 */}
      <div className="flex items-center gap-2">
        {/* Help Agent */}
        {onOpenHelpAgent && (
          <button
            type="button"
            onClick={handleOpenHelpAgent}
            className="relative w-8 h-8 flex items-center justify-center rounded-lg hover:bg-slate-100 transition-colors text-slate-500 hover:text-blue-600"
            title="打开 Help Agent"
            aria-label="打开 Help Agent"
          >
            <i className="ri-robot-2-line text-[18px]" />
          </button>
        )}

        {/* 通知铃铛 */}
        <div className="relative">
          <button
            onClick={() => { setNotifOpen(o => !o); setMenuOpen(false); }}
            className="relative w-8 h-8 flex items-center justify-center rounded-lg hover:bg-slate-100 transition-colors"
            aria-label="消息通知"
          >
            <i className={`text-[18px] ${unreadCount > 0 ? 'ri-notification-3-fill text-blue-500' : 'ri-notification-3-line text-slate-500'}`} />
            {unreadCount > 0 && (
              <span className="absolute top-0.5 right-0.5 min-w-[16px] h-4 px-0.5 bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center leading-none">
                {badgeLabel}
              </span>
            )}
          </button>

          {notifOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setNotifOpen(false)} />
              <div className="absolute right-0 top-full mt-2 w-80 bg-white border border-slate-200 rounded-xl shadow-xl z-50 flex flex-col overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 shrink-0">
                  <span className="text-[13px] font-semibold text-slate-700">
                    消息通知
                    {unreadCount > 0 && (
                      <span className="ml-1.5 text-[11px] text-blue-500 font-normal">{unreadCount} 条未读</span>
                    )}
                  </span>
                  <button
                    onClick={handleMarkAllRead}
                    disabled={unreadCount === 0}
                    className="text-[12px] font-medium text-blue-600 hover:text-blue-800 hover:bg-blue-50 rounded-md px-2 py-1 transition-colors disabled:text-slate-300 disabled:cursor-default"
                  >
                    全部标记为已读
                  </button>
                </div>

                <div className="max-h-[360px] overflow-y-auto">
                  {notifLoading ? (
                    <div className="py-10 text-center text-[13px] text-slate-400">加载中…</div>
                  ) : notifications.length === 0 ? (
                    <div className="py-10 text-center">
                      <i className="ri-notification-off-line text-2xl text-slate-300 block mb-2" />
                      <span className="text-[13px] text-slate-400">暂无消息</span>
                    </div>
                  ) : (
                    notifications.map(n => {
                      const { icon, bg: iconBg, color: iconColor } = getNotifIconStyle(n.title, n.level);
                      const isP0 = n.title.includes('[P0]') || n.level === 'error';
                      const rowBg = isP0
                        ? 'bg-red-50 hover:bg-red-100/60'
                        : n.is_read
                          ? 'bg-white hover:bg-slate-50'
                          : 'bg-blue-50/30 hover:bg-blue-50/60';
                      return (
                        <div
                          key={n.id}
                          className={`group relative w-full text-left px-4 py-3.5 flex items-start gap-3 border-b border-slate-50 last:border-b-0 transition-colors cursor-pointer ${rowBg}`}
                          onClick={() => handleNotifClick(n)}
                        >
                          <div className={`mt-0.5 w-7 h-7 rounded-full ${iconBg} flex items-center justify-center shrink-0`}>
                            <i className={`${icon} text-sm ${iconColor}`} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className={`text-[12px] leading-snug flex-1 truncate ${n.is_read ? 'text-slate-500' : 'text-slate-800 font-semibold'}`}>
                                {n.title}
                              </span>
                            </div>
                          </div>

                          <div className="relative w-[72px] h-5 flex items-center justify-end">
                            <span className="absolute right-0 text-[11px] text-slate-400 group-hover:hidden">{formatRelativeTime(n.created_at)}</span>
                            <div className="absolute right-0 hidden group-hover:flex items-center gap-1">
                              <button
                                onClick={(e) => { e.stopPropagation(); handleQuickToggle(n); }}
                                className="w-7 h-7 flex items-center justify-center rounded-full hover:bg-slate-200 text-slate-400 hover:text-blue-500 transition-colors"
                                title={n.is_read ? '标为未读' : '标为已读'}
                              >
                                <i className={n.is_read ? 'ri-mail-line text-sm' : 'ri-mail-check-line text-sm'} />
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); handleQuickDelete(n.id); }}
                                className="w-7 h-7 flex items-center justify-center rounded-full hover:bg-red-50 text-slate-400 hover:text-red-500 transition-colors"
                                title="删除"
                              >
                                <i className="ri-delete-bin-line text-sm" />
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>

                <div className="border-t border-slate-100 shrink-0 bg-[#F9FAFB] rounded-b-xl">
                  <Link
                    to="/notifications"
                    onClick={() => setNotifOpen(false)}
                    className="flex items-center justify-center gap-1.5 w-full py-2.5 text-[12px] text-slate-500 hover:text-blue-500 hover:bg-slate-100/60 transition-colors rounded-b-xl"
                  >
                    查看全部消息
                    <i className="ri-arrow-right-s-line text-[13px]" />
                  </Link>
                </div>
              </div>
            </>
          )}
        </div>

        {/* 用户信息 */}
        <div className="relative">
          <button
            onClick={() => { setMenuOpen(o => !o); setNotifOpen(false); }}
            className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-slate-50 transition-colors"
          >
            {user?.avatar_url ? (
              <img
                src={user.avatar_url}
                alt="头像"
                className="w-7 h-7 rounded-full object-cover shrink-0"
              />
            ) : (
              <div className={`w-7 h-7 rounded-full bg-gradient-to-br ${avatarGradient} flex items-center justify-center shrink-0`}>
                <span className="text-white text-xs font-bold">
                  {user?.display_name?.charAt(0) ?? 'A'}
                </span>
              </div>
            )}
            <span className="hidden sm:block text-[12px] font-medium text-slate-600 leading-none">
              {user?.display_name ?? '用户'}
            </span>
            <i className="ri-arrow-down-s-line text-slate-400 text-sm" />
          </button>

          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 top-full mt-1 w-52 bg-white border border-slate-200 rounded-xl shadow-xl z-50 py-1.5">
                <Link
                  to="/account"
                  onClick={() => setMenuOpen(false)}
                  className="flex items-center gap-2.5 px-3.5 py-2 text-[13px] text-slate-700 hover:bg-slate-50 transition-colors"
                >
                  <i className="ri-user-3-line text-[15px] text-slate-500" />
                  账号设置
                </Link>
                <div className="my-1 border-t border-slate-100" />
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-2.5 px-3.5 py-2 text-[13px] text-red-500 hover:bg-red-50 transition-colors"
                >
                  <i className="ri-logout-box-r-line text-[15px]" />
                  退出登录
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
