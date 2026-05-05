/**
 * SuggestionGrid — open-webui 风格 2×2 建议卡片
 *
 * 固定 4 条快速开始建议问题。
 * 挂载时尝试从 GET /api/chat/suggestions 获取动态建议；
 * 请求失败（网络、404、非 OK）时回退到本地 SUGGESTIONS 数组。
 */
import { useState, useEffect } from 'react';

interface Suggestion {
  title: string;
  hint?: string;
}

const SUGGESTIONS: Suggestion[] = [
  { title: '你有哪些看板？' },
  { title: '你有哪些数据源？' },
  { title: '哪些子类别近6个月利润率持续下滑？' },
  { title: '对比各区域本季度销售额与利润率排名' },
  { title: '分析各类别近12个月销售额的月度变化趋势' },
  { title: '利润贡献前10的客户是谁？集中度如何？' },
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
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl mx-auto">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className="h-16 rounded-xl bg-slate-100 animate-pulse"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="w-full max-w-2xl mx-auto mb-8">
      <p className="text-xs text-slate-400 mb-3">快速开始</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {suggestions.map((s) => (
          <button
            key={s.title}
            onClick={() => onPick(s.title)}
            className="group flex items-center gap-2 text-left
                       border border-slate-200 bg-white rounded-xl p-4
                       text-[13px] text-slate-600
                       hover:border-blue-300 hover:bg-blue-50/50 hover:text-slate-800
                       transition-all duration-150 cursor-pointer
                       focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
          >
            <i className="ri-questionnaire-line text-slate-300 group-hover:text-blue-400 text-base" />
            <span>{s.title}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
