import { TableauAsset } from '../../../api/tableau';
import { ASSET_TYPE_LABELS } from '../../../config';

interface InfoTabProps {
  asset: TableauAsset;
  parent: TableauAsset | null;
}

export function InfoTab({ asset }: InfoTabProps) {
  return (
    <div className="space-y-6">
      <div className="bg-white border border-slate-200 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-slate-700 mb-4">基本信息</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-slate-400">资产名称</span>
            <p className="font-medium text-slate-800">{asset.name}</p>
          </div>
          <div>
            <span className="text-slate-400">资产类型</span>
            <p className="font-medium text-slate-800">{ASSET_TYPE_LABELS[asset.asset_type] || asset.asset_type}</p>
          </div>
          <div>
            <span className="text-slate-400">项目</span>
            <p className="font-medium text-slate-800">{asset.project_name || '-'}</p>
          </div>
          <div>
            <span className="text-slate-400">所有者</span>
            <p className="font-medium text-slate-800">{asset.owner_name || '-'}</p>
          </div>
          <div>
            <span className="text-slate-400">Tableau ID</span>
            <p className="font-mono text-xs text-slate-600">{asset.tableau_id}</p>
          </div>
          <div>
            <span className="text-slate-400">同步时间</span>
            <p className="text-slate-600">{asset.synced_at}</p>
          </div>
          {asset.created_on_server && (
            <div>
              <span className="text-slate-400">创建时间 (Server)</span>
              <p className="text-slate-600">{asset.created_on_server}</p>
            </div>
          )}
          {asset.updated_on_server && (
            <div>
              <span className="text-slate-400">更新时间 (Server)</span>
              <p className="text-slate-600">{asset.updated_on_server}</p>
            </div>
          )}
          {asset.view_count != null && (
            <div>
              <span className="text-slate-400">浏览次数</span>
              <p className="font-medium text-slate-800">{asset.view_count.toLocaleString()}</p>
            </div>
          )}
          {asset.sheet_type && (
            <div>
              <span className="text-slate-400">视图类型</span>
              <p className="text-slate-600">{asset.sheet_type}</p>
            </div>
          )}
          {asset.field_count != null && (
            <div>
              <span className="text-slate-400">字段数</span>
              <p className="text-slate-600">{asset.field_count}</p>
            </div>
          )}
          {asset.is_certified != null && (
            <div>
              <span className="text-slate-400">认证状态</span>
              <p className={`font-medium ${asset.is_certified ? 'text-emerald-600' : 'text-slate-500'}`}>
                {asset.is_certified ? '已认证' : '未认证'}
              </p>
            </div>
          )}
        </div>
        {asset.description && (
          <div className="mt-4 pt-4 border-t border-slate-100">
            <span className="text-slate-400 text-sm">描述</span>
            <p className="text-sm text-slate-700 mt-1">{asset.description}</p>
          </div>
        )}
      </div>
    </div>
  );
}
