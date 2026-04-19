import React from 'react';
import type { McpTool, McpDebugCallResponse } from '../../../../api/mcpDebug';

export interface HistoryEntry {
  id: string;           // 前端本地 ID
  tool: McpTool;
  args: Record<string, unknown>;
  result: McpDebugCallResponse | null;
  error: string | null;
  calledAt: Date;
}

interface Props {
  history: HistoryEntry[];
  onRestore: (entry: HistoryEntry) => void;
}

export default function CallHistory({ history, onRestore }: Props) {
  if (history.length === 0) {
    return (
      <div className="text-center text-sm text-slate-400 py-4">
        本会话暂无调用记录
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200">
            <th className="text-left py-2 px-3 text-xs font-medium text-slate-500 w-36">时间</th>
            <th className="text-left py-2 px-3 text-xs font-medium text-slate-500">工具名</th>
            <th className="text-left py-2 px-3 text-xs font-medium text-slate-500 w-20">状态</th>
            <th className="text-left py-2 px-3 text-xs font-medium text-slate-500 w-20">耗时</th>
            <th className="py-2 px-3 w-16" />
          </tr>
        </thead>
        <tbody>
          {history.map((entry) => {
            const isError = !!entry.error || entry.result?.status === 'error';
            return (
              <tr
                key={entry.id}
                className="border-b border-slate-100 hover:bg-slate-50 transition-colors"
              >
                <td className="py-2 px-3 text-xs text-slate-400 whitespace-nowrap">
                  {entry.calledAt.toLocaleTimeString()}
                </td>
                <td className="py-2 px-3 font-mono text-xs text-slate-700 truncate max-w-[200px]">
                  {entry.tool.name}
                </td>
                <td className="py-2 px-3">
                  <span
                    className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${
                      isError
                        ? 'bg-red-100 text-red-600'
                        : 'bg-green-100 text-green-700'
                    }`}
                  >
                    {isError ? '失败' : '成功'}
                  </span>
                </td>
                <td className="py-2 px-3 text-xs text-slate-400">
                  {entry.result ? `${entry.result.duration_ms} ms` : '—'}
                </td>
                <td className="py-2 px-3">
                  <button
                    onClick={() => onRestore(entry)}
                    className="text-xs text-blue-500 hover:text-blue-700 hover:underline whitespace-nowrap"
                    title="恢复此次调用的参数"
                  >
                    恢复
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
