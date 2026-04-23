/**
 * SuggestionGrid — open-webui 风格 2×2 建议卡片
 *
 * 固定 4 条，每张卡 = 主问题 + 补充说明。
 * 挂载时尝试从 GET /api/chat/suggestions 获取动态建议；
 * 请求失败（网络、404、非 OK）时回退到本地 SUGGESTIONS 数组。
 */
import { useState, useEffect } from 'react';

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
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [fromApi, setFromApi] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const fetchSuggestions = async () => {
      try {
        const response = await fetch('/api/chat/suggestions', { credentials: 'include' });
        if (!response.ok) throw new Error('non-ok response');
        const data: unknown = await response.json();

        let parsed: Suggestion[] | null = null;
        if (Array.isArray(data)) {
          parsed = data as Suggestion[];
        } else if (
          data !== null &&
          typeof data === 'object' &&
          'suggestions' in data &&
          Array.isArray((data as { suggestions: unknown }).suggestions)
        ) {
          parsed = (data as { suggestions: Suggestion[] }).suggestions;
        }

        if (!cancelled) {
          const loaded = Array.isArray(parsed) && parsed.length > 0;
          setSuggestions(loaded ? parsed : SUGGESTIONS);
          setFromApi(loaded);
        }
      } catch {
        if (!cancelled) {
          setSuggestions(SUGGESTIONS);
          setFromApi(false);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void fetchSuggestions();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-2.5 w-full max-w-2xl mx-auto">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-16 rounded-xl bg-slate-100 animate-pulse"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2.5 w-full max-w-2xl mx-auto">
      {!fromApi && (
        <p className="col-span-2 text-center text-xs text-slate-400 mb-1">
          使用默认推荐问题
        </p>
      )}
      {suggestions.map((s) => (
        <button
          key={s.title}
          onClick={() => onPick(s.title)}
          className="group flex flex-col justify-between text-left
                     rounded-xl border border-slate-200 bg-white
                     px-4 py-3 min-h-[72px]
                     hover:bg-slate-50 hover:border-slate-300
                     transition-colors duration-150
                     focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
        >
          <span className="text-sm font-medium text-slate-800">
            {s.title}
          </span>
          {s.hint && (
            <span className="text-xs text-slate-500">
              {s.hint}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
