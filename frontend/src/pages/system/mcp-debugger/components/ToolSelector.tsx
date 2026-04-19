import React, { useEffect, useState } from 'react';
import { getMcpTools, type McpTool } from '../../../../api/mcpDebug';

// 工具分类规则
const TOOL_CATEGORIES: { label: string; pattern: RegExp }[] = [
  { label: '查询类', pattern: /^(list|get|search|query|describe)/i },
  { label: '字段类', pattern: /field|column|schema/i },
  { label: '视图控制类', pattern: /view|workbook|dashboard/i },
  { label: '写操作类', pattern: /create|update|delete|publish|move|add/i },
];

function categorizeTool(name: string): string {
  for (const cat of TOOL_CATEGORIES) {
    if (cat.pattern.test(name)) return cat.label;
  }
  return '其他';
}

interface Props {
  selectedTool: McpTool | null;
  onSelect: (tool: McpTool) => void;
}

export default function ToolSelector({ selectedTool, onSelect }: Props) {
  const [tools, setTools] = useState<McpTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    getMcpTools()
      .then(setTools)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = tools.filter(
    (t) =>
      t.name.toLowerCase().includes(search.toLowerCase()) ||
      (t.description || '').toLowerCase().includes(search.toLowerCase()),
  );

  // 按分类分组
  const grouped: Record<string, McpTool[]> = {};
  for (const tool of filtered) {
    const cat = categorizeTool(tool.name);
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(tool);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-32 text-slate-400">
        <i className="ri-loader-4-line animate-spin mr-2" />
        加载工具列表...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 bg-red-50 border border-red-200 rounded text-red-600 text-sm">
        <i className="ri-error-warning-line mr-1" />
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full gap-2">
      <input
        type="text"
        placeholder="搜索工具..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
      />

      <div className="flex-1 overflow-y-auto space-y-3">
        {Object.entries(grouped).map(([category, items]) => (
          <div key={category}>
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider px-1 mb-1">
              {category}
            </div>
            <div className="space-y-1">
              {items.map((tool) => {
                const isSelected = selectedTool?.name === tool.name;
                return (
                  <button
                    key={tool.name}
                    onClick={() => onSelect(tool)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                      isSelected
                        ? 'bg-blue-600 text-white'
                        : 'text-slate-700 hover:bg-slate-100'
                    }`}
                  >
                    <div className="font-medium truncate">{tool.name}</div>
                    {tool.description && (
                      <div
                        className={`text-xs mt-0.5 truncate ${
                          isSelected ? 'text-blue-100' : 'text-slate-400'
                        }`}
                      >
                        {tool.description}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}

        {filtered.length === 0 && (
          <div className="text-center text-slate-400 text-sm py-8">
            没有匹配的工具
          </div>
        )}
      </div>
    </div>
  );
}
