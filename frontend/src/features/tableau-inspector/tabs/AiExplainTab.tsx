import { Link } from 'react-router-dom';
import DOMPurify from 'dompurify';

// Simple markdown renderer (bold, headers, lists)
function renderMarkdown(text: string): string {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^### (.+)$/gm, '<h4 class="font-semibold text-slate-800 mt-4 mb-1">$1</h4>')
    .replace(/^## (.+)$/gm, '<h3 class="font-semibold text-slate-800 mt-5 mb-2 text-base">$1</h3>')
    .replace(/^# (.+)$/gm, '<h2 class="font-bold text-slate-800 mt-5 mb-2 text-lg">$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^\- (.+)$/gm, '<li class="ml-4 list-disc">$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li class="ml-4 list-decimal">$1</li>')
    .replace(/\n\n/g, '<br/><br/>');
}

interface AiExplainTabProps {
  aiContent: string | null;
  aiLoading: boolean;
  aiError: string | null;
  aiCached?: boolean;
  onRefresh: () => void;
  onLoadExplain?: () => void;
  llmConfigured: boolean;
}

export function AiExplainTab({
  aiContent,
  aiLoading,
  aiError,
  aiCached,
  onRefresh,
  onLoadExplain,
  llmConfigured,
}: AiExplainTabProps) {
  const handleLoad = onLoadExplain || onRefresh;

  return (
    <div className="space-y-4">
      <div className="bg-white border border-slate-200 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-700">AI 深度解读</h3>
            <p className="text-xs text-slate-400 mt-0.5">基于元数据、数据源字段和层级关系的深度分析</p>
          </div>
          <button
            onClick={onRefresh}
            disabled={aiLoading}
            className="px-3 py-1.5 text-xs border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50 transition-colors"
          >
            <i className="ri-refresh-line mr-1" />
            {aiContent ? '重新生成' : '生成解读'}
          </button>
        </div>

        {aiLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="flex flex-col items-center gap-3 text-slate-400">
              <i className="ri-loader-2-line animate-spin text-2xl" />
              <span className="text-sm">正在调用 LLM 深度分析...</span>
              <span className="text-xs text-slate-300">将分析元数据、数据源字段和关联关系</span>
            </div>
          </div>
        ) : !llmConfigured ? (
          <div className="text-center py-8">
            <div className="text-orange-500 text-sm mb-2">LLM 未配置</div>
            <p className="text-slate-500 text-xs mb-3">请联系管理员配置 LLM 后再试</p>
            <Link to="/system/llm-configs" className="text-sm text-blue-500 hover:underline">
              去配置 LLM
            </Link>
          </div>
        ) : aiError ? (
          <div className="text-center py-8">
            <div className="text-red-500 text-sm mb-2">{aiError}</div>
            <button onClick={handleLoad} className="text-sm text-blue-500 hover:underline">
              重试
            </button>
          </div>
        ) : aiContent ? (
          <div>
            <div
              className="prose prose-sm prose-slate max-w-none bg-slate-50 rounded-lg p-5 text-sm text-slate-700 leading-relaxed"
              dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(renderMarkdown(aiContent)) }}
            />
            {aiCached && (
              <div className="mt-2 text-xs text-slate-400">
                <i className="ri-checkbox-circle-line mr-1" />
                已缓存，1 小时内不重复生成
              </div>
            )}
          </div>
        ) : (
          <div className="text-center py-12">
            <i className="ri-sparkling-line text-3xl text-slate-300 mb-3 block" />
            <div className="text-slate-400 text-sm mb-4">点击生成 AI 深度解读</div>
            <button
              onClick={handleLoad}
              className="px-5 py-2.5 text-sm bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition-colors"
            >
              <i className="ri-sparkling-line mr-1" />
              生成深度解读
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
