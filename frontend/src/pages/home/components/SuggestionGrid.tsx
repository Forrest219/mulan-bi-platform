/**
 * SuggestionGrid — 2×2 BI 场景建议问题卡片
 */

const SUGGESTIONS = [
  'Q1 各区域销售额对比是怎样的？',
  '帮我检查 orders 表的 DDL 规范',
  '最近一周数据质量扫描有异常吗？',
  'Tableau 仪表盘中哪些字段缺少语义定义？',
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
