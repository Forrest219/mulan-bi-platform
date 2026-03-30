import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getAsset, TableauAsset } from '../../../api/tableau';

const ASSET_TYPE_LABELS: Record<string, string> = {
  workbook: '工作簿',
  view: '视图',
  datasource: '数据源'
};

export default function TableauAssetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [asset, setAsset] = useState<TableauAsset | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    getAsset(Number(id))
      .then(setAsset)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;
  if (!asset) return <div className="p-8 text-center text-slate-400">资产不存在</div>;

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-5xl mx-auto">
          <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700 mb-4">
            <i className="ri-arrow-left-line" /> 返回
          </button>
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-xl font-semibold text-slate-800">{asset.name}</h1>
              <div className="flex items-center gap-3 mt-2">
                <span className={`px-2 py-0.5 rounded text-xs ${
                  asset.asset_type === 'workbook' ? 'bg-blue-50 text-blue-600' :
                  asset.asset_type === 'view' ? 'bg-emerald-50 text-emerald-600' :
                  'bg-orange-50 text-orange-600'
                }`}>
                  {ASSET_TYPE_LABELS[asset.asset_type] || asset.asset_type}
                </span>
                <span className="text-sm text-slate-400">{asset.project_name || '未分类'}</span>
              </div>
            </div>
            {asset.content_url && (
              <span className="text-xs text-slate-400 bg-slate-100 px-2 py-1 rounded">
                ID: {asset.tableau_id}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-8 py-6">
        <div className="grid grid-cols-3 gap-6">
          {/* Main Info */}
          <div className="col-span-2 space-y-6">
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
              </div>
              {asset.description && (
                <div className="mt-4 pt-4 border-t border-slate-100">
                  <span className="text-slate-400 text-sm">描述</span>
                  <p className="text-sm text-slate-700 mt-1">{asset.description}</p>
                </div>
              )}
            </div>

            {/* Datasources */}
            {asset.datasources && asset.datasources.length > 0 && (
              <div className="bg-white border border-slate-200 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-slate-700 mb-4">关联数据源</h3>
                <div className="space-y-2">
                  {asset.datasources.map(ds => (
                    <div key={ds.id} className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg">
                      <i className="ri-database-2-line text-slate-400" />
                      <div>
                        <p className="text-sm font-medium text-slate-700">{ds.datasource_name}</p>
                        {ds.datasource_type && (
                          <p className="text-xs text-slate-400">{ds.datasource_type}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Sidebar */}
          <aside className="space-y-6">
            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-4">链接信息</h3>
              {asset.content_url ? (
                <p className="text-xs text-slate-400 break-all">{asset.content_url}</p>
              ) : (
                <p className="text-xs text-slate-400">-</p>
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
