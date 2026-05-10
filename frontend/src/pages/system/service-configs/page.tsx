import { useSearchParams } from 'react-router-dom';
import LLMConfigsPage from '../../admin/llm-configs/page';
import McpConfigsPage from '../../admin/mcp-configs/page';

const TABS = [
  { key: 'llm', label: 'LLM 配置' },
  { key: 'mcp', label: 'MCP 配置' },
] as const;

type TabKey = typeof TABS[number]['key'];

export default function ServiceConfigsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get('tab') as TabKey) ?? 'llm';

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-settings-3-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">服务配置</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">配置 LLM 模型与 MCP 服务</p>
        </div>
      </div>
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-6xl mx-auto flex gap-1 py-2">
          {TABS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setSearchParams({ tab: tab.key })}
              className={`px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${
                activeTab === tab.key
                  ? 'bg-slate-800 text-white'
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      {activeTab === 'llm' && <LLMConfigsPage headerless />}
      {activeTab === 'mcp' && <McpConfigsPage headerless />}
    </div>
  );
}
