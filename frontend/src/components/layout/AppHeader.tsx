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
  markAllNotificationsRead,
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

export default function AppHeader() {
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

  const handleMarkAllRead = async () => {
    await markAllNotificationsRead();
    setNotifications(prev => prev.map(x => ({ ...x, is_read: true })));
    setUnreadCount(0);
  };

  const badgeLabel = unreadCount > 99 ? '99+' : String(unreadCount);

  return (
    <header className="h-[58px] bg-white border-b border-slate-200 flex items-center pl-4 pr-4 gap-4 shrink-0 z-30">

      {/* 全局搜索 */}
      <div className="flex-1 max-w-md mx-auto relative">
        <div className="relative">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onFocus={() => setSearchFocused(true)}
            onBlur={() => setSearchFocused(false)}
            onKeyDown={e => {
              if (e.key === 'Escape') {
                setSearchQuery('');
                setSearchFocused(false);
                (e.target as HTMLInputElement).blur();
              }
            }}
            placeholder="搜索功能页面…"
            className="w-full pl-9 pr-4 py-1.5 text-[13px] bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent text-slate-600 placeholder-slate-400"
          />
        </div>

        {searchFocused && searchResults.length > 0 && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-slate-200 rounded-xl shadow-xl z-50 overflow-hidden">
            <div className="px-3 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-100">
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
                className="w-full flex items-center gap-2.5 px-3 py-2.5 hover:bg-slate-50 transition-colors"
              >
                <i className={`${entry.icon} text-[14px] text-slate-400 shrink-0`} />
                <div className="flex-1 min-w-0 text-left">
                  {entry.group && (
                    <span className="text-[12px] text-slate-400">{entry.group} / </span>
                  )}
                  <span className="text-[13px] text-slate-700">{entry.label}</span>
                </div>
                <i className="ri-arrow-right-up-line text-[11px] text-slate-300 shrink-0" />
              </button>
            ))}
          </div>
        )}
      </div>

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
              {/* 头部 */}
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
                  className="text-[12px] text-blue-500 hover:text-blue-700 transition-colors disabled:text-slate-300 disabled:cursor-default"
                >
                  全部标记为已读
                </button>
              </div>

              {/* 消息列表 */}
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
                      <button
                        key={n.id}
                        onClick={() => handleNotifClick(n)}
                        className={`w-full text-left px-4 py-3.5 flex items-start gap-3 border-b border-slate-50 last:border-b-0 transition-colors ${rowBg}`}
                      >
                        <div className={`mt-0.5 w-7 h-7 rounded-full ${iconBg} flex items-center justify-center shrink-0`}>
                          <i className={`${icon} text-sm ${iconColor}`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start gap-1.5">
                            <span className={`text-[12px] leading-snug flex-1 ${n.is_read ? 'text-slate-500' : 'text-slate-800 font-medium'}`}>
                              {n.title}
                            </span>
                            {!n.is_read && (
                              <span className="mt-1 w-1.5 h-1.5 rounded-full bg-blue-500 shrink-0" />
                            )}
                          </div>
                          <div className="text-[11px] text-slate-400 mt-1.5">{formatRelativeTime(n.created_at)}</div>
                        </div>
                      </button>
                    );
                  })
                )}
              </div>

              {/* 底部固定链接 */}
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
          <div className={`w-7 h-7 rounded-full bg-gradient-to-br ${avatarGradient} flex items-center justify-center shrink-0`}>
            <span className="text-white text-xs font-bold">
              {user?.display_name?.charAt(0) ?? 'A'}
            </span>
          </div>
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
                to="/account/profile"
                onClick={() => setMenuOpen(false)}
                className="flex items-center gap-2.5 px-3.5 py-2 text-[13px] text-slate-700 hover:bg-slate-50 transition-colors"
              >
                <i className="ri-user-3-line text-[15px] text-slate-500" />
                个人中心
              </Link>
              <Link
                to="/account/password"
                onClick={() => setMenuOpen(false)}
                className="flex items-center gap-2.5 px-3.5 py-2 text-[13px] text-slate-700 hover:bg-slate-50 transition-colors"
              >
                <i className="ri-lock-password-line text-[15px] text-slate-500" />
                修改密码
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
    </header>
  );
}
