interface ExamplePromptsProps {
  onPick: (question: string) => void;
}

const EXAMPLES = [
  'Q1 销售额是多少',
  '3 月各区域订单数量',
  '销售额最高的前 5 个产品',
];

export function ExamplePrompts({ onPick }: ExamplePromptsProps) {
  return (
    <div className="flex flex-wrap justify-center gap-2">
      {EXAMPLES.map((prompt) => (
        <button
          key={prompt}
          onClick={() => onPick(prompt)}
          className="text-xs px-3 py-1 hover:bg-slate-200/60 text-slate-500 rounded-full
                     hover:text-slate-700 transition-colors border border-slate-200"
        >
          {prompt}
        </button>
      ))}
    </div>
  );
}
