import { TableauAsset } from '../../../api/tableau';

interface DatasourcesTabProps {
  asset: TableauAsset;
  datasources: TableauAsset['datasources'];
}

export function DatasourcesTab({ asset, datasources }: DatasourcesTabProps) {
  const shouldShowSelf = asset.asset_type === 'datasource';
  const datasourceSelf = asset.datasource_self;
  const selfName = typeof datasourceSelf === 'object' && datasourceSelf
    ? datasourceSelf.name || datasourceSelf.datasource_name || asset.name
    : asset.name;
  const selfType = typeof datasourceSelf === 'object' && datasourceSelf
    ? datasourceSelf.datasource_type
    : null;

  return (
    <div className="space-y-4">
      {shouldShowSelf ? (
        <div className="bg-white border border-slate-200 rounded-xl p-5">
          <h3 className="text-xs font-semibold text-slate-700 mb-4">关联数据源</h3>
          <div className="flex items-center gap-3 p-3 bg-orange-50 rounded-lg border border-orange-100">
            <i className="ri-database-2-line text-orange-500" />
            <div>
              <div className="flex items-center gap-2">
                <p className="text-xs font-medium text-slate-700">{selfName}</p>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-white text-orange-600 border border-orange-100">
                  当前数据源
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                {selfType || '它本身就是 Tableau 数据源'}
              </p>
            </div>
          </div>
        </div>
      ) : datasources && datasources.length > 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-5">
          <h3 className="text-xs font-semibold text-slate-700 mb-4">关联数据源</h3>
          <div className="space-y-2">
            {datasources.map(ds => (
              <div key={ds.id} className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg">
                <i className="ri-database-2-line text-slate-400" />
                <div>
                  <p className="text-xs font-medium text-slate-700">{ds.datasource_name}</p>
                  {ds.datasource_type && (
                    <p className="text-xs text-slate-400">{ds.datasource_type}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl p-5 text-center text-slate-400">
          暂无关联数据源
        </div>
      )}
    </div>
  );
}
