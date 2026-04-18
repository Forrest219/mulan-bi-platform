/**
 * SuggestionGrid — open-webui 风格 2×2 建议卡片
 *
 * 固定 4 条，每张卡 = 主问题 + 补充说明。
 */

interface Suggestion {
  title: string;
  hint?: string;
}

const SUGGESTIONS: Suggestion[] = [
  { title: '分析近 30 天订单金额趋势', hint: '按日聚合并识别拐点' },
  { title: '对比本月与上月各区域销售', hint: '找出同比增长最快的区域' },
  { title: '找出退款率最高的产品类别', hint: '定位需要优化的品类' },
  { title: '统计最近 7 天新增客户与环比', hint: '观察获客节奏' },
];

interface SuggestionGridProps {
  onPick: (question: string) => void;
}

export function SuggestionGrid({ onPick }: SuggestionGridProps) {
  return (
    <div className="grid grid-cols-2 gap-2.5 w-full max-w-2xl mx-auto">
      {SUGGESTIONS.map((s) => (
        <button
          key={s.title}
          onClick={() => onPick(s.title)}
          className="group flex flex-col items-start text-left
                     rounded-xl border border-slate-200 bg-white
                     px-4 py-3
                     hover:bg-slate-50 hover:border-slate-300
                     transition-colors duration-150
                     focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
        >
          <span className="text-sm font-medium text-slate-800">
            {s.title}
          </span>
          {s.hint && (
            <span className="mt-1 text-xs text-slate-500">
              {s.hint}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
