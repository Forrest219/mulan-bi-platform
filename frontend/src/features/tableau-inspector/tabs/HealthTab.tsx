import { AssetHealth } from '../../../api/tableau';
import { FactorBreakdown } from './FactorBreakdown';
import { AskAboutThis } from './AskAboutThis';

interface HealthTabProps {
  healthData: AssetHealth | null;
  healthLoading: boolean;
  healthError: string | null;
  onLoad: () => void;
  assetName?: string;
  assetId?: string;
}

export function HealthTab({
  healthData,
  healthLoading,
  healthError,
  onLoad,
  assetName,
  assetId,
}: HealthTabProps) {
  return (
    <div className="space-y-4">
      <div className="bg-white border border-slate-200 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-700">健康度评估</h3>
          <button
            onClick={onLoad}
            disabled={healthLoading}
            className="px-3 py-1.5 text-xs border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50"
          >
            <i className={healthLoading ? 'ri-loader-2-line animate-spin mr-1' : 'ri-refresh-line mr-1'} />
            {healthData ? '重新评估' : '开始评估'}
          </button>
        </div>

        {healthError && (
          <div className="text-center py-4 text-red-500 text-sm">{healthError}</div>
        )}

        {healthLoading ? (
          <div className="text-center py-10 text-slate-400 text-sm">
            <i className="ri-loader-2-line animate-spin text-xl block mb-2" />
            评估中...
          </div>
        ) : !healthData ? (
          <div className="text-center py-10">
            <i className="ri-heart-pulse-line text-3xl text-slate-300 block mb-3" />
            <div className="text-slate-400 text-sm mb-4">点击&quot;开始评估&quot;检查资产健康度</div>
            <button
              onClick={onLoad}
              className="px-5 py-2.5 text-sm bg-slate-900 text-white rounded-lg hover:bg-slate-800"
            >
              <i className="ri-heart-pulse-line mr-1" /> 开始评估
            </button>
          </div>
        ) : (
          <>
            {/* Score header */}
            <div className="flex items-center gap-6 mb-6 p-4 bg-slate-50 rounded-xl">
              <div
                className={`text-4xl font-bold ${
                  healthData.score >= 80
                    ? 'text-emerald-600'
                    : healthData.score >= 60
                      ? 'text-amber-600'
                      : healthData.score >= 40
                        ? 'text-orange-600'
                        : 'text-red-600'
                }`}
              >
                {healthData.score}
              </div>
              <div>
                <div className="text-sm font-medium text-slate-700">
                  {healthData.level === 'excellent'
                    ? '优秀'
                    : healthData.level === 'good'
                      ? '良好'
                      : healthData.level === 'warning'
                        ? '需改进'
                        : '较差'}
                </div>
                <div className="text-xs text-slate-400">
                  满分 100 · 基于 {healthData.checks.length} 项检查
                </div>
              </div>
            </div>

            {/* 7 Factor Breakdown */}
            <FactorBreakdown checks={healthData.checks} />

            {/* Ask About This */}
            {assetName && assetId && (
              <AskAboutThis
                assetName={assetName}
                assetId={assetId}
                healthScore={healthData.score}
              />
            )}

            {/* Check items */}
            <div className="space-y-2 mt-4">
              {healthData.checks.map((check) => (
                <div
                  key={check.key}
                  className={`flex items-center justify-between p-3 rounded-lg border ${
                    check.passed ? 'bg-emerald-50 border-emerald-200' : 'bg-red-50 border-red-200'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <i
                      className={
                        check.passed
                          ? 'ri-checkbox-circle-fill text-emerald-500'
                          : 'ri-close-circle-fill text-red-500'
                      }
                    />
                    <div>
                      <div className="text-xs font-medium text-slate-700">{check.label}</div>
                      <div className="text-[11px] text-slate-500">{check.detail}</div>
                    </div>
                  </div>
                  <span className="text-[10px] text-slate-400 font-medium">{check.weight}%</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
