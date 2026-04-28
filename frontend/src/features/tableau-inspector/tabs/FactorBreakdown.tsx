import type { AssetHealth } from '../../../api/tableau';

interface FactorBreakdownProps {
  checks: AssetHealth['checks'];
}

export function FactorBreakdown({ checks }: FactorBreakdownProps) {
  const displayChecks = checks.slice(0, 7);

  return (
    <div className="mt-4 p-4 bg-slate-50 rounded-xl">
      <h4 className="text-xs font-semibold text-slate-500 mb-3">7 因子评估</h4>
      <div className="grid grid-cols-2 gap-2">
        {displayChecks.map((check) => (
          <div
            key={check.key}
            className={`flex items-center gap-2 p-2 rounded-lg ${
              check.passed ? 'bg-emerald-50' : 'bg-red-50'
            }`}
          >
            <i
              className={
                check.passed
                  ? 'ri-checkbox-circle-fill text-emerald-500 text-sm'
                  : 'ri-close-circle-fill text-red-500 text-sm'
              }
            />
            <span className="text-xs text-slate-700">{check.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
