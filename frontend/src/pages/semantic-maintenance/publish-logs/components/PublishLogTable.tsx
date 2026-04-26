import { PublishLogListItem } from '../../../../api/semantic-maintenance';
import { StatusBadge } from './StatusBadge';

interface PublishLogTableProps {
  items: PublishLogListItem[];
  loading: boolean;
  onRowClick: (item: PublishLogListItem) => void;
}

function formatDate(dateStr: string): { relative: string; absolute: string } {
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  let relative = '';
  if (minutes < 1) relative = '刚刚';
  else if (minutes < 60) relative = `${minutes} 分钟前`;
  else if (hours < 24) relative = `${hours} 小时前`;
  else if (days < 7) relative = `${days} 天前`;
  else relative = date.toLocaleDateString('zh-CN');

  return {
    relative,
    absolute: date.toLocaleString('zh-CN'),
  };
}

function ObjectTypeBadge({ type }: { type: 'datasource' | 'field' }) {
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded font-medium ${
        type === 'datasource'
          ? 'bg-blue-50 text-blue-700'
          : 'bg-purple-50 text-purple-700'
      }`}
    >
      {type === 'datasource' ? '数据源' : '字段'}
    </span>
  );
}

export function PublishLogTable({ items, loading, onRowClick }: PublishLogTableProps) {
  if (loading) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="flex items-center justify-center py-16 text-slate-400">
          <i className="ri-loader-4-line animate-spin text-2xl mr-2" />
          加载中...
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="flex flex-col items-center justify-center py-16 text-slate-400">
          <i className="ri-file-list-3-line text-4xl mb-2" />
          <p>暂无发布日志</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wide w-[60px]">ID</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wide w-[140px]">连接</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wide w-[80px]">类型</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wide w-[180px]">对象名称</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wide w-[100px]">状态</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">变更摘要</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wide w-[100px]">操作人</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wide w-[140px]">发布时间</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wide w-[80px]">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map(item => {
              const dateInfo = formatDate(item.created_at);
              const diffSummary = item.diff_summary;

              return (
                <tr
                  key={item.id}
                  onClick={() => onRowClick(item)}
                  className="hover:bg-slate-50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3 text-slate-500 font-mono text-xs">{item.id}</td>
                  <td className="px-4 py-3 text-slate-700 text-sm truncate max-w-[140px]" title={item.connection_name || undefined}>
                    {item.connection_name || '-'}
                  </td>
                  <td className="px-4 py-3">
                    <ObjectTypeBadge type={item.object_type} />
                  </td>
                  <td className="px-4 py-3 text-slate-700 text-sm truncate max-w-[180px]" title={item.object_name || undefined}>
                    {item.object_name || '-'}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={item.status} />
                  </td>
                  <td className="px-4 py-3">
                    {diffSummary.total_changes > 0 ? (
                      <div className="text-slate-600 text-xs">
                        {diffSummary.is_rollback ? (
                          <span className="text-blue-600">回滚操作</span>
                        ) : (
                          <span>
                            修改了{' '}
                            <span className="font-medium text-slate-800">
                              {diffSummary.changed_fields.slice(0, 2).join('、')}
                            </span>
                            {diffSummary.changed_fields.length > 2 && (
                              <span className="text-slate-400"> 等</span>
                            )}
                            <span className="text-slate-400 ml-1">共 {diffSummary.total_changes} 个字段</span>
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="text-slate-400 text-xs">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600 text-sm">
                    {item.operator?.display_name || item.operator?.username || '-'}
                  </td>
                  <td className="px-4 py-3">
                    <div
                      className="text-slate-500 text-xs cursor-help"
                      title={dateInfo.absolute}
                    >
                      {dateInfo.relative}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={e => {
                        e.stopPropagation();
                        onRowClick(item);
                      }}
                      className="px-2 py-1 text-xs text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded transition-colors"
                    >
                      详情
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
