/**
 * PendingActionsList — 待处理操作提示
 *
 * 基于当前健康数据展示需要人工介入的操作建议。
 * 当前策略：健康分 < 50 的资产超过 3 个时提示"存在多个低健康资产，建议全面检查"
 */
import type { HealthOverview } from '../../../api/tableau';

interface PendingActionsListProps {
  overview: HealthOverview | null;
}

export function PendingActionsList({ overview }: PendingActionsListProps) {
  if (!overview) return null;

  const lowHealthCount = overview.assets.filter(a => a.score < 50).length;

  if (lowHealthCount === 0) return null;

  const actions: string[] = [];

  if (lowHealthCount >= 3) {
    actions.push(`存在 ${lowHealthCount} 个低健康资产，建议进行系统性检查`);
  }

  const poorCount = overview.assets.filter(a => a.level === 'poor').length;
  if (poorCount > 0) {
    actions.push(`${poorCount} 个资产处于"差"状态，优先处理`);
  }

  if (actions.length === 0) return null;

  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-slate-500 mb-1">待处理建议</p>
      {actions.map((action, i) => (
        <div key={i} className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 rounded px-3 py-2">
          <i className="ri-error-warning-line mt-0.5 shrink-0" />
          <span>{action}</span>
        </div>
      ))}
    </div>
  );
}
