import { TableauAsset } from '../../../api/tableau';

interface DatasourcesTabProps {
  datasources: TableauAsset['datasources'];
}

export function DatasourcesTab({ datasources }: DatasourcesTabProps) {
  return (
    <div className="space-y-4">
      {datasources && datasources.length > 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">关联数据源</h3>
          <div className="space-y-2">
            {datasources.map(ds => (
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
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl p-5 text-center text-slate-400">
          暂无关联数据源
        </div>
      )}
    </div>
  );
}
