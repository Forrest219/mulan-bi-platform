import { useNavigate } from 'react-router-dom';
import { TableauAsset } from '../../../api/tableau';
import { ASSET_TYPE_LABELS } from '../../../config';

const ASSET_TYPE_ICONS: Record<string, string> = {
  workbook: 'ri-file-chart-line',
  dashboard: 'ri-dashboard-line',
  view: 'ri-bar-chart-box-line',
  datasource: 'ri-database-2-line',
};

interface ChildrenTabProps {
  children: TableauAsset[];
  childrenLoading: boolean;
}

export function ChildrenTab({ children, childrenLoading }: ChildrenTabProps) {
  const navigate = useNavigate();

  return (
    <div className="space-y-4">
      {childrenLoading ? (
        <div className="text-center py-8 text-slate-400">
          <i className="ri-loader-2-line animate-spin" /> 加载子视图...
        </div>
      ) : children.length > 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left text-xs font-semibold text-slate-500 px-4 py-3">类型</th>
                <th className="text-left text-xs font-semibold text-slate-500 px-4 py-3">名称</th>
                <th className="text-left text-xs font-semibold text-slate-500 px-4 py-3">所有者</th>
                <th className="text-right text-xs font-semibold text-slate-500 px-4 py-3">浏览次数</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {children.map(child => (
                <tr
                  key={child.id}
                  onClick={() => navigate(`/tableau/assets/${child.id}`)}
                  className="hover:bg-slate-50 cursor-pointer"
                >
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs ${
                      child.asset_type === 'dashboard' ? 'bg-purple-50 text-purple-600' :
                      'bg-emerald-50 text-emerald-600'
                    }`}>
                      <i className={ASSET_TYPE_ICONS[child.asset_type]} />
                      {ASSET_TYPE_LABELS[child.asset_type]}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-800">{child.name}</td>
                  <td className="px-4 py-3 text-sm text-slate-500">{child.owner_name || '-'}</td>
                  <td className="px-4 py-3 text-sm text-slate-500 text-right">
                    {child.view_count != null ? child.view_count.toLocaleString() : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl p-5 text-center text-slate-400">
          暂无子视图
        </div>
      )}
    </div>
  );
}
