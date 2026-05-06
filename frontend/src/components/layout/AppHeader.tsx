import { useState, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
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

const LEVEL_BORDER: Record<string, string> = {
  info: 'border-l-blue-400',
  warning: 'border-l-amber-400',
  error: 'border-l-red-400',
};

export default function AppHeader() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [notifLoading, setNotifLoading] = useState(false);

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

      {/* 全局搜索（占位，后续迭代） */}
      <div className="flex-1 max-w-md mx-auto">
        <div className="relative">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
          <input
            type="text"
            placeholder="搜索对话、资产、指标…"
            className="w-full pl-9 pr-4 py-1.5 text-[13px] bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent text-slate-600 placeholder-slate-400"
          />
        </div>
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
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 shrink-0">
                <span className="text-[13px] font-semibold text-slate-700">
                  消息通知
                  {unreadCount > 0 && (
                    <span className="ml-1.5 text-[11px] text-blue-500 font-normal">{unreadCount} 条未读</span>
                  )}
                </span>
                {unreadCount > 0 && (
                  <button
                    onClick={handleMarkAllRead}
                    className="text-[12px] text-blue-500 hover:text-blue-700 transition-colors"
                  >
                    全部已读
                  </button>
                )}
              </div>

              <div className="max-h-[360px] overflow-y-auto divide-y divide-slate-50">
                {notifLoading ? (
                  <div className="py-10 text-center text-[13px] text-slate-400">加载中…</div>
                ) : notifications.length === 0 ? (
                  <div className="py-10 text-center">
                    <i className="ri-notification-off-line text-2xl text-slate-300 block mb-2" />
                    <span className="text-[13px] text-slate-400">暂无消息</span>
                  </div>
                ) : (
                  notifications.map(n => (
                    <button
                      key={n.id}
                      onClick={() => handleNotifClick(n)}
                      className={`w-full text-left px-4 py-3 border-l-2 ${LEVEL_BORDER[n.level] ?? 'border-l-slate-200'} ${n.is_read ? 'bg-white' : 'bg-blue-50/40'} hover:bg-slate-50 transition-colors`}
                    >
                      <div className="flex items-start gap-2">
                        <span className={`text-[12px] leading-snug flex-1 ${n.is_read ? 'text-slate-500' : 'text-slate-800 font-medium'}`}>
                          {n.title}
                        </span>
                        {!n.is_read && (
                          <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-blue-500 shrink-0" />
                        )}
                      </div>
                      <div className="text-[11px] text-slate-400 mt-1">{formatRelativeTime(n.created_at)}</div>
                    </button>
                  ))
                )}
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
            <div className="absolute right-0 top-full mt-1 w-44 bg-white border border-slate-200 rounded-xl shadow-lg z-50 py-1">
              <Link
                to="/account/security"
                onClick={() => setMenuOpen(false)}
                className="w-full flex items-center gap-2 px-4 py-2.5 text-[13px] text-slate-600 hover:bg-slate-50 transition-colors"
              >
                <i className="ri-shield-keyhole-line text-base" />
                账户安全
              </Link>
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-2 px-4 py-2.5 text-[13px] text-slate-600 hover:bg-slate-50 hover:text-red-600 transition-colors"
              >
                <i className="ri-logout-box-line text-base" />
                退出登录
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  );
}
