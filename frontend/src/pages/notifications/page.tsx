import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  type AppNotification,
  listNotifications,
  markNotificationRead,
  markAllNotificationsRead,
} from '../../api/notifications';

// ── 工具函数（与 AppHeader 保持一致） ────────────────────────────

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
  if (title.includes('[P0]') || level === 'error')
    return { icon: 'ri-alarm-warning-fill', bg: 'bg-red-100', color: 'text-red-500' };
  if (title.includes('巡检') || title.includes('完成') || title.includes('成功'))
    return { icon: 'ri-checkbox-circle-fill', bg: 'bg-emerald-100', color: 'text-emerald-500' };
  if (title.includes('审核'))
    return { icon: 'ri-information-fill', bg: 'bg-blue-100', color: 'text-blue-500' };
  if (level === 'warning')
    return { icon: 'ri-error-warning-fill', bg: 'bg-amber-100', color: 'text-amber-500' };
  return { icon: 'ri-notification-3-line', bg: 'bg-slate-100', color: 'text-slate-400' };
}

// ── 过滤 Tab 定义 ────────────────────────────────────────────────

type FilterKey = 'all' | 'unread' | 'read' | 'alert';

const FILTER_TABS: { key: FilterKey; label: string }[] = [
  { key: 'all',    label: '全部' },
  { key: 'unread', label: '未读' },
  { key: 'read',   label: '已读' },
  { key: 'alert',  label: '告警' },
];

function filterToParams(key: FilterKey): { is_read?: boolean; level?: string } {
  if (key === 'unread') return { is_read: false };
  if (key === 'read')   return { is_read: true };
  if (key === 'alert')  return { level: 'error' };
  return {};
}

// ── 页面 ────────────────────────────────────────────────────────

const PAGE_SIZE = 20;

export default function NotificationsPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<FilterKey>('all');
  const [items, setItems] = useState<AppNotification[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);

  const load = useCallback(async (f: FilterKey, p: number) => {
    setLoading(true);
    try {
      const data = await listNotifications(p, PAGE_SIZE, filterToParams(f));
      setItems(data.items);
      setTotal(data.total);
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    load(filter, page);
  }, [filter, page, load]);

  const handleFilterChange = (f: FilterKey) => {
    setFilter(f);
    setPage(1);
  };

  const handleItemClick = async (n: AppNotification) => {
    if (!n.is_read) {
      await markNotificationRead(n.id);
      setItems(prev => prev.map(x => x.id === n.id ? { ...x, is_read: true } : x));
    }
    if (n.link) navigate(n.link);
  };

  const handleMarkAllRead = async () => {
    setMarkingAll(true);
    try {
      await markAllNotificationsRead();
      setItems(prev => prev.map(x => ({ ...x, is_read: true })));
    } finally { setMarkingAll(false); }
  };

  const unreadCount = items.filter(n => !n.is_read).length;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 页头 */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-notification-3-line text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">消息中心</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">
              {total > 0 ? `共 ${total} 条消息` : '暂无消息'}
            </p>
          </div>

          <button
            onClick={handleMarkAllRead}
            disabled={markingAll || unreadCount === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-blue-500 border border-blue-200 rounded-lg hover:bg-blue-50 transition-colors disabled:text-slate-300 disabled:border-slate-200 disabled:cursor-default"
          >
            {markingAll
              ? <><i className="ri-loader-4-line animate-spin" />处理中…</>
              : <><i className="ri-check-double-line" />全部标为已读</>
            }
          </button>
        </div>
      </div>

      {/* 过滤 Tab */}
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-6xl mx-auto">
          <div className="flex gap-1 py-2">
            {FILTER_TABS.map(t => (
              <button
                key={t.key}
                onClick={() => handleFilterChange(t.key)}
                className={`px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${
                  filter === t.key
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 列表 */}
      <div className="px-8 py-6">
        <div className="max-w-6xl mx-auto">
        {loading ? (
          <div className="flex items-center justify-center py-20 text-slate-400 text-[13px]">
            <i className="ri-loader-4-line animate-spin mr-2" />加载中…
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20">
            <i className="ri-notification-off-line text-4xl text-slate-200 mb-3" />
            <span className="text-[13px] text-slate-400">暂无消息</span>
          </div>
        ) : (
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden divide-y divide-slate-100">
            {items.map(n => {
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
                  onClick={() => handleItemClick(n)}
                  className={`w-full text-left px-5 py-4 flex items-start gap-4 transition-colors ${rowBg}`}
                >
                  <div className={`mt-0.5 w-8 h-8 rounded-full ${iconBg} flex items-center justify-center shrink-0`}>
                    <i className={`${icon} text-sm ${iconColor}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start gap-2">
                      <span className={`text-[13px] leading-snug flex-1 ${n.is_read ? 'text-slate-500' : 'text-slate-800 font-medium'}`}>
                        {n.title}
                      </span>
                      {!n.is_read && (
                        <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-blue-500 shrink-0" />
                      )}
                    </div>
                    {n.content && (
                      <p className="text-[12px] text-slate-400 mt-1 line-clamp-2 leading-relaxed">
                        {n.content}
                      </p>
                    )}
                    <div className="text-[11px] text-slate-400 mt-1.5">{formatRelativeTime(n.created_at)}</div>
                  </div>
                  {n.link && (
                    <i className="ri-arrow-right-s-line text-slate-300 text-lg mt-0.5 shrink-0" />
                  )}
                </button>
              );
            })}
          </div>
        )}

        {/* 分页 */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-6">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="w-8 h-8 flex items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-default transition-colors"
            >
              <i className="ri-arrow-left-s-line" />
            </button>
            <span className="text-[12px] text-slate-500">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="w-8 h-8 flex items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-default transition-colors"
            >
              <i className="ri-arrow-right-s-line" />
            </button>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}
