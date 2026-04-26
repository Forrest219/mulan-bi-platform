import { useState, useEffect, useCallback } from 'react';
import {
  listPublishLogs,
  getPublishLogDetail,
  PublishLogListItem,
  PublishLogDetail,
  PublishLogFilters,
} from '../../../api/semantic-maintenance';
import { PublishLogFilter } from './components/PublishLogFilter';
import { PublishLogTable } from './components/PublishLogTable';
import { PublishLogDetailDrawer } from './components/PublishLogDetail';

export default function SemanticPublishLogsPage() {
  const [items, setItems] = useState<PublishLogListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [pages, setPages] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detail drawer state
  const [selectedLog, setSelectedLog] = useState<PublishLogDetail | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Filter state
  const [filters, setFilters] = useState<PublishLogFilters>({});

  // Get user role from sessionStorage (simple approach)
  const userRole = (window as any).__USER_ROLE__ || 'analyst';
  const isAdmin = userRole === 'admin' || userRole === 'data_admin';

  const loadLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listPublishLogs({
        page,
        page_size: pageSize,
        ...filters,
      });
      setItems(data.items);
      setTotal(data.total);
      setPages(data.pages);
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, filters]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  const handleFilterChange = (newFilters: PublishLogFilters) => {
    setFilters(newFilters);
    setPage(1); // Reset to first page when filters change
  };

  const handleRowClick = async (item: PublishLogListItem) => {
    try {
      const detail = await getPublishLogDetail(item.id);
      setSelectedLog(detail);
      setDrawerOpen(true);
    } catch (e: any) {
      alert(e.message || '加载详情失败');
    }
  };

  const handleCloseDrawer = () => {
    setDrawerOpen(false);
    setSelectedLog(null);
  };

  const handleRetry = async (logId: number) => {
    alert(`重试功能待实现 (log_id=${logId})`);
    handleCloseDrawer();
    loadLogs();
  };

  const handleRollback = async (logId: number) => {
    if (!confirm('确定要回滚此发布吗？')) return;
    alert(`回滚功能待实现 (log_id=${logId})`);
    handleCloseDrawer();
    loadLogs();
  };

  return (
    <div className="p-6 min-h-screen bg-slate-50">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-slate-800">语义发布记录</h1>
        <p className="text-sm text-slate-400 mt-0.5">
          查看历史发布操作及字段变更详情
        </p>
      </div>

      {/* Filters */}
      <div className="mb-4">
        <PublishLogFilter onFilterChange={handleFilterChange} isAdmin={isAdmin} />
      </div>

      {/* Error State */}
      {error && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
          <i className="ri-error-warning-line mr-1" />
          {error}
        </div>
      )}

      {/* Table */}
      <PublishLogTable
        items={items}
        loading={loading}
        onRowClick={handleRowClick}
      />

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center justify-center gap-4 mt-4">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-4 py-2 text-sm border border-slate-200 rounded-lg hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <i className="ri-arrow-left-s-line mr-1" />
            上一页
          </button>
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-600">
              第 <span className="font-medium">{page}</span> / {pages} 页
            </span>
            <span className="text-sm text-slate-400">
              (共 {total} 条)
            </span>
          </div>
          <button
            onClick={() => setPage(p => Math.min(pages, p + 1))}
            disabled={page >= pages}
            className="px-4 py-2 text-sm border border-slate-200 rounded-lg hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            下一页
            <i className="ri-arrow-right-s-line ml-1" />
          </button>
        </div>
      )}

      {/* Detail Drawer */}
      <PublishLogDetailDrawer
        log={selectedLog}
        open={drawerOpen}
        onClose={handleCloseDrawer}
        onRetry={handleRetry}
        onRollback={handleRollback}
        isAdmin={isAdmin}
        userRole={userRole}
      />
    </div>
  );
}
