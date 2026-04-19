/**
 * MCP Debugger Page — /system/mcp-debugger
 *
 * admin / data_admin 专用 MCP 工具调试页面。
 *
 * 布局：
 *   左栏（固定宽度）：ToolSelector
 *   中栏（弹性）：ParamForm
 *   右栏（弹性）：ResultViewer
 *   下方：CallHistory
 */
import React, { useState, useCallback } from 'react';
import { callMcpTool, type McpTool, type McpDebugCallResponse } from '../../../api/mcpDebug';
import ToolSelector from './components/ToolSelector';
import ParamForm from './components/ParamForm';
import ResultViewer from './components/ResultViewer';
import CallHistory, { type HistoryEntry } from './components/CallHistory';

let historyCounter = 0;

export default function McpDebuggerPage() {
  const [selectedTool, setSelectedTool] = useState<McpTool | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<McpDebugCallResponse | null>(null);
  const [callError, setCallError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [restoredArgs, setRestoredArgs] = useState<Record<string, unknown> | undefined>(undefined);

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
        callResult = await callMcpTool(selectedTool.name, args);
        setResult(callResult);
      } catch (e) {
        callErr = e instanceof Error ? e.message : String(e);
        setCallError(callErr);
      } finally {
        setLoading(false);
      }

      // 追加历史记录
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
    [selectedTool],
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
      <div className="shrink-0">
        <h1 className="text-xl font-semibold text-slate-800 flex items-center gap-2">
          <i className="ri-bug-line text-blue-600" />
          MCP 调试器
        </h1>
        <p className="text-sm text-slate-400 mt-0.5">
          在线调用 MCP 工具并查看原始响应，仅限管理员使用
        </p>
      </div>

      {/* 三栏主体 */}
      <div className="flex flex-1 gap-4 min-h-0">
        {/* 左栏：工具选择器 */}
        <div className="w-64 shrink-0 bg-white border border-slate-200 rounded-xl p-3 flex flex-col overflow-hidden">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
            工具列表
          </div>
          <div className="flex-1 min-h-0">
            <ToolSelector selectedTool={selectedTool} onSelect={handleToolSelect} />
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
    </div>
  );
}
