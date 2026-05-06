/**
 * SuggestionGrid — open-webui 风格 2×3 建议卡片
 *
 * 挂载时尝试从 GET /api/chat/suggestions 获取动态建议；
 * 请求失败时回退到本地 SUGGESTIONS 数组。
 * 本地卡片按类型带色标图标：资产发现（紫）/ 趋势分析（琥珀）/ 对比排名（蓝）。
 */
import { useState, useEffect } from 'react';

type SuggestionCategory = 'asset' | 'trend' | 'rank';

interface Suggestion {
  title: string;
  hint?: string;
  category?: SuggestionCategory;
}

const CATEGORY_STYLES: Record<SuggestionCategory, { icon: string; iconColor: string; borderL: string; hoverBg: string }> = {
  asset: { icon: 'ri-database-2-line',      iconColor: 'text-violet-400', borderL: 'border-l-violet-300', hoverBg: 'hover:bg-violet-50/60' },
  trend: { icon: 'ri-line-chart-line',       iconColor: 'text-amber-400',  borderL: 'border-l-amber-300',  hoverBg: 'hover:bg-amber-50/60'  },
  rank:  { icon: 'ri-bar-chart-grouped-line',iconColor: 'text-blue-400',   borderL: 'border-l-blue-300',   hoverBg: 'hover:bg-blue-50/60'   },
};

const DEFAULT_STYLE = {
  icon: 'ri-questionnaire-line',
  iconColor: 'text-slate-300 group-hover:text-blue-400',
  borderL: 'border-l-slate-200',
  hoverBg: 'hover:bg-blue-50/50',
};

const SUGGESTIONS: Suggestion[] = [
  { title: '你有哪些看板？',                               category: 'asset' },
  { title: '你有哪些数据源？',                             category: 'asset' },
  { title: '哪些子类别近6个月利润率持续下滑？',           category: 'trend' },
  { title: '对比各区域本季度销售额与利润率排名',           category: 'rank'  },
  { title: '分析各类别近12个月销售额的月度变化趋势',       category: 'trend' },
  { title: '利润贡献前10的客户是谁？集中度如何？',         category: 'rank'  },
];

interface SuggestionGridProps {
  onPick: (question: string) => void;
}

export function SuggestionGrid({ onPick }: SuggestionGridProps) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);

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
          setSuggestions(Array.isArray(parsed) && parsed.length > 0 ? parsed : SUGGESTIONS);
        }
      } catch {
        if (!cancelled) setSuggestions(SUGGESTIONS);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void fetchSuggestions();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl mx-auto">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-16 rounded-xl bg-slate-100 animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="w-full max-w-2xl mx-auto mb-8">
      <p className="text-xs text-slate-400 mb-3">快速开始</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {suggestions.map((s) => {
          const style = (s.category && CATEGORY_STYLES[s.category]) ?? DEFAULT_STYLE;
          return (
            <button
              key={s.title}
              onClick={() => onPick(s.title)}
              className={`group flex items-start gap-2.5 text-left
                         border border-l-2 border-slate-200 ${style.borderL} bg-white rounded-xl p-4
                         text-[13px] text-slate-600
                         ${style.hoverBg} hover:border-slate-300 hover:text-slate-800
                         transition-all duration-150 cursor-pointer
                         focus:outline-none focus:ring-2 focus:ring-blue-500/20`}
            >
              <i className={`${style.icon} ${style.iconColor} text-base mt-0.5 flex-shrink-0`} />
              <span>{s.title}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
