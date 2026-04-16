/**
 * SuggestionGrid — 2×2 BI 场景建议问题卡片
 */

const SUGGESTIONS = [
  '帮我分析近30天订单金额的变化趋势',
  '对比本月和上月各区域销售额表现',
  '找出退款率最高的产品类别',
  '统计最近7天新增客户数及环比变化',
  '分析订单量下降的可能原因',
];

interface SuggestionGridProps {
  onPick: (question: string) => void;
}

export function SuggestionGrid({ onPick }: SuggestionGridProps) {
  return (
    <div className="grid grid-cols-2 gap-3 w-full max-w-2xl mx-auto px-4">
      {SUGGESTIONS.map((q) => (
        <button
          key={q}
          onClick={() => onPick(q)}
          className="border border-slate-200 rounded-xl p-4 hover:border-blue-400 hover:bg-blue-50
                     cursor-pointer transition-all text-sm text-slate-600 text-left"
        >
          {q}
        </button>
      ))}
    </div>
  );
}
