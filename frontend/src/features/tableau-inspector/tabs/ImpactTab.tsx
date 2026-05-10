import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { getAssetImpact, AssetImpactResult } from '../../../api/tableau';

interface ImpactTabProps {
  assetId: string;
}

export function ImpactTab({ assetId }: ImpactTabProps) {
  const [data, setData] = useState<AssetImpactResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedWorkbooks, setExpandedWorkbooks] = useState<Set<number>>(new Set());

  useEffect(() => {
    setLoading(true);
    setError(null);
    getAssetImpact(assetId)
      .then(result => {
        setData(result);
        // 默认展开所有工作簿
        const ids = new Set(result.affected_workbooks.map(wb => wb.id));
        setExpandedWorkbooks(ids);
      })
      .catch(e => {
        setError(e instanceof Error ? e.message : '加载影响分析失败');
      })
      .finally(() => setLoading(false));
  }, [assetId]);

  const toggleWorkbook = (id: number) => {
    setExpandedWorkbooks(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <div className="space-y-4">
      <div className="bg-white border border-slate-200 rounded-xl p-5">
        <div className="mb-4">
          <h3 className="text-xs font-semibold text-slate-700">影响分析</h3>
          <p className="text-xs text-slate-400 mt-0.5">展示依赖此数据源的下游工作簿和视图</p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="flex flex-col items-center gap-3 text-slate-400">
              <i className="ri-loader-2-line animate-spin text-2xl" />
              <span className="text-xs">正在加载影响树...</span>
            </div>
          </div>
        ) : error ? (
          <div className="text-center py-8">
            <div className="text-red-500 text-xs mb-2">{error}</div>
            <button
              onClick={() => {
                setLoading(true);
                setError(null);
                getAssetImpact(assetId)
                  .then(result => {
                    setData(result);
                    const ids = new Set(result.affected_workbooks.map(wb => wb.id));
                    setExpandedWorkbooks(ids);
                  })
                  .catch(e => setError(e instanceof Error ? e.message : '加载影响分析失败'))
                  .finally(() => setLoading(false));
              }}
              className="text-xs text-blue-500 hover:underline"
            >
              重试
            </button>
          </div>
        ) : data ? (
          <>
            {/* 摘要卡片 */}
            <div className="flex items-center gap-4 mb-5 p-3 bg-slate-50 rounded-lg">
              <div className="text-center">
                <div className="text-lg font-bold text-slate-800">{data.summary.workbook_count}</div>
                <div className="text-[11px] text-slate-500">受影响工作簿</div>
              </div>
              <div className="w-px h-8 bg-slate-200" />
              <div className="text-center">
                <div className="text-lg font-bold text-slate-800">{data.summary.view_dashboard_count}</div>
                <div className="text-[11px] text-slate-500">受影响视图/仪表板</div>
              </div>
            </div>

            {/* 影响树 */}
            {data.affected_workbooks.length === 0 ? (
              <div className="text-center py-8">
                <i className="ri-git-merge-line text-3xl text-slate-200 block mb-2" />
                <p className="text-xs text-slate-400">该数据源暂无下游工作簿</p>
              </div>
            ) : (
              <div className="space-y-2">
                {data.affected_workbooks.map(wb => (
                  <div key={wb.id} className="border border-slate-200 rounded-lg overflow-hidden">
                    {/* 工作簿行 */}
                    <button
                      onClick={() => toggleWorkbook(wb.id)}
                      className="w-full flex items-center gap-2 px-3 py-2.5 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
                    >
                      <i className={`text-slate-400 text-sm flex-shrink-0 ${
                        expandedWorkbooks.has(wb.id) ? 'ri-arrow-down-s-line' : 'ri-arrow-right-s-line'
                      }`} />
                      <i className="ri-file-chart-line text-blue-500 flex-shrink-0" />
                      <span className="text-xs font-medium text-slate-700 flex-1 truncate">{wb.name}</span>
                      <span className="text-[11px] text-slate-400 flex-shrink-0 ml-2">
                        {wb.affected_views.length} 个视图/仪表板
                      </span>
                    </button>

                    {/* 展开的 view/dashboard 列表 */}
                    {expandedWorkbooks.has(wb.id) && (
                      <div className="divide-y divide-slate-100">
                        {wb.affected_views.length === 0 ? (
                          <p className="px-8 py-2 text-[11px] text-slate-400">无关联视图</p>
                        ) : (
                          wb.affected_views.map(view => (
                            <div key={view.id} className="flex items-center gap-2 px-8 py-2 hover:bg-slate-50">
                              <i className={`flex-shrink-0 text-xs ${
                                view.asset_type === 'dashboard'
                                  ? 'ri-dashboard-line text-purple-500'
                                  : 'ri-bar-chart-box-line text-emerald-500'
                              }`} />
                              <span className="text-xs text-slate-700 flex-1 truncate">{view.name}</span>
                              <span className={`text-[10px] px-1.5 py-0.5 rounded flex-shrink-0 ${
                                view.asset_type === 'dashboard'
                                  ? 'bg-purple-50 text-purple-600'
                                  : 'bg-emerald-50 text-emerald-600'
                              }`}>
                                {view.asset_type === 'dashboard' ? '仪表板' : '视图'}
                              </span>
                              <Link
                                to={`/assets/tableau/${view.id}`}
                                className="text-[11px] text-blue-500 hover:underline flex-shrink-0"
                                onClick={e => e.stopPropagation()}
                              >
                                查看 →
                              </Link>
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
