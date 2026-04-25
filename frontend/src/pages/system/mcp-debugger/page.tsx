import React, { useState, useCallback, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getMcpTools, callMcpTool, type McpTool, type McpDebugCallResponse } from '../../../api/mcpDebug';
import { API_BASE } from '../../../config';
import ToolSelector from './components/ToolSelector';
import ParamForm from './components/ParamForm';
import ResultViewer from './components/ResultViewer';
import CallHistory, { type HistoryEntry } from './components/CallHistory';
import AuditLogPage from './components/AuditLogPage';

interface McpServerOption {
  id: number;
  name: string;
  type: string;
  is_active: boolean;
}

let historyCounter = 0;

export default function McpDebuggerPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const view = (searchParams.get('view') || 'debugger') as 'debugger' | 'logs';

  const [servers, setServers] = useState<McpServerOption[]>([]);
  const [serverId, setServerId] = useState<number | undefined>(undefined);
  const [selectedTool, setSelectedTool] = useState<McpTool | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<McpDebugCallResponse | null>(null);
  const [callError, setCallError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [restoredArgs, setRestoredArgs] = useState<Record<string, unknown> | undefined>(undefined);
  const [toolsLoaded, setToolsLoaded] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/mcp-configs/`, { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then((list: McpServerOption[]) => {
        const active = list.filter(s => s.is_active);
        setServers(active);
        if (active.length > 0 && serverId === undefined) {
          setServerId(active[0].id);
        }
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const switchView = (v: 'debugger' | 'logs') => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      next.set('view', v);
      return next;
    });
  };

  useEffect(() => {
    const toolParam = searchParams.get('tool');
    if (!toolParam || toolsLoaded || serverId === undefined) return;

    getMcpTools(serverId).then(tools => {
      setToolsLoaded(true);
      const matched = tools.find(t => t.name === toolParam);
      if (!matched) return;

      const args: Record<string, unknown> = {};
      searchParams.forEach((value, key) => {
        if (key.startsWith('arg_')) {
          args[key.slice(4)] = value;
        }
      });

      setSelectedTool(matched);
      setRestoredArgs(Object.keys(args).length > 0 ? args : undefined);
    }).catch(() => {
      setToolsLoaded(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, serverId]);

  const handleToolSelect = useCallback((tool: McpTool) => {
    setSelectedTool(tool);
    setResult(null);
    setCallError(null);
    setRestoredArgs(undefined);
  }, []);

  const handleSubmit = useCallback(
    async (args: Record<string, unknown>) => {
      if (!selectedTool) return;
      setLoading(true);
      setResult(null);
      setCallError(null);

      let callResult: McpDebugCallResponse | null = null;
      let callErr: string | null = null;

      try {
        callResult = await callMcpTool(selectedTool.name, args, serverId);
        setResult(callResult);
      } catch (e) {
        callErr = e instanceof Error ? e.message : String(e);
        setCallError(callErr);
      } finally {
        setLoading(false);
      }

      historyCounter += 1;
      setHistory((prev) => [
        {
          id: String(historyCounter),
          tool: selectedTool,
          args,
          result: callResult,
          error: callErr,
          calledAt: new Date(),
        },
        ...prev,
      ]);
    },
    [selectedTool, serverId],
  );

  const handleRestore = useCallback((entry: HistoryEntry) => {
    setSelectedTool(entry.tool);
    setRestoredArgs(entry.args);
    setResult(entry.result);
    setCallError(entry.error);
  }, []);

  return (
    <div className="flex flex-col h-full p-4 gap-4">
      {/* 页头 */}
      <div className="shrink-0 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-800 flex items-center gap-2">
            <i className="ri-bug-line text-blue-600" />
            MCP 调试器
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            在线调用 MCP 工具并查看原始响应，仅限管理员使用
          </p>
        </div>
        {servers.length > 0 && (
          <select
            value={serverId ?? ''}
            onChange={(e) => {
              const id = e.target.value ? Number(e.target.value) : undefined;
              setServerId(id);
              setSelectedTool(null);
              setResult(null);
              setCallError(null);
              setToolsLoaded(false);
            }}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm text-slate-700 bg-white focus:outline-none focus:border-blue-500"
          >
            {servers.map(s => (
              <option key={s.id} value={s.id}>{s.name} ({s.type})</option>
            ))}
          </select>
        )}
      </div>

      {/* Tab 切换 */}
      <div className="shrink-0 flex items-center gap-1 px-1 py-1 bg-slate-100 rounded-lg w-fit">
        <button
          onClick={() => switchView('debugger')}
          className={`px-4 py-1.5 rounded-md text-[12px] font-medium transition-colors cursor-pointer ${
            view === 'debugger' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          调试器
        </button>
        <button
          onClick={() => switchView('logs')}
          className={`px-4 py-1.5 rounded-md text-[12px] font-medium transition-colors cursor-pointer ${
            view === 'logs' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          审计日志
        </button>
      </div>

      {view === 'logs' ? (
        <div className="flex-1 min-h-0 overflow-y-auto">
          <AuditLogPage />
        </div>
      ) : (
        <>
          {/* 三栏主体 */}
          <div className="flex flex-1 gap-4 min-h-0">
            {/* 左栏：工具选择器 */}
            <div className="w-64 shrink-0 bg-white border border-slate-200 rounded-xl p-3 flex flex-col overflow-hidden">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                工具列表
              </div>
              <div className="flex-1 min-h-0">
                <ToolSelector selectedTool={selectedTool} onSelect={handleToolSelect} serverId={serverId} />
              </div>
            </div>

            {/* 中栏：参数表单 */}
            <div className="w-72 shrink-0 bg-white border border-slate-200 rounded-xl p-4 overflow-y-auto">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
                参数配置
              </div>
              {selectedTool ? (
                <>
                  <div className="mb-3 p-2 bg-slate-50 rounded-lg">
                    <div className="text-sm font-medium text-slate-700">{selectedTool.name}</div>
                    {selectedTool.description && (
                      <div className="text-xs text-slate-400 mt-0.5">{selectedTool.description}</div>
                    )}
                  </div>
                  <ParamForm
                    tool={selectedTool}
                    initialValues={restoredArgs}
                    onSubmit={handleSubmit}
                    loading={loading}
                  />
                </>
              ) : (
                <div className="flex flex-col items-center justify-center h-32 text-slate-400 text-sm">
                  <i className="ri-arrow-left-line text-2xl mb-2" />
                  请先选择工具
                </div>
              )}
            </div>

            {/* 右栏：结果展示 */}
            <div className="flex-1 bg-white border border-slate-200 rounded-xl p-4 flex flex-col overflow-hidden min-w-0">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3 shrink-0">
                执行结果
              </div>
              <div className="flex-1 min-h-0">
                <ResultViewer result={result} error={callError} />
              </div>
            </div>
          </div>

          {/* 下方：调用历史 */}
          <div className="shrink-0 bg-white border border-slate-200 rounded-xl p-4">
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
              本会话调用历史
            </div>
            <CallHistory history={history} onRestore={handleRestore} />
          </div>
        </>
      )}
    </div>
  );
}
