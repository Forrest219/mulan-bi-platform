interface SourceCardProps {
  sourcesCount: number;
  topSources: string[];
}

export default function SourceCard({ sourcesCount, topSources }: SourceCardProps) {
  return (
    <div className="mt-3 p-3 bg-slate-50 border border-slate-200 rounded-lg">
      <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-2">
        <i className="ri-database-2-line" />
        <span>基于 <strong className="text-slate-700">{sourcesCount}</strong> 个数据源生成</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {topSources.map((name) => (
          <span key={name} className="px-2 py-0.5 bg-white border border-slate-200 rounded text-xs text-slate-600">
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
