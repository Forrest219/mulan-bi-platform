import React from 'react';
import type { McpDebugCallResponse } from '../../../../api/mcpDebug';

interface Props {
  result: McpDebugCallResponse | null;
  error: string | null;
}

export default function ResultViewer({ result, error }: Props) {
  if (!result && !error) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-3">
        <i className="ri-terminal-box-line text-5xl opacity-30" />
        <p className="text-sm">选择工具并执行后，结果将在此显示</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
            <i className="ri-close-circle-line mr-1" />
            错误
          </span>
        </div>
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-700 break-all">{error}</p>
        </div>
      </div>
    );
  }

  if (!result) return null;

  const isError = result.status === 'error';

  // 尝试提取 MCP content 文本（tools/call 返回的 result.result.content[].text）
  const content = (result.result as Record<string, unknown>);
  const resultContent = content?.result as Record<string, unknown> | undefined;
  const mcpContent = resultContent?.content as Array<{ type: string; text?: string }> | undefined;

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* 状态栏 */}
      <div className="flex items-center gap-3 shrink-0">
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
            isError
              ? 'bg-red-100 text-red-700'
              : 'bg-green-100 text-green-700'
          }`}
        >
          <i className={`${isError ? 'ri-close-circle-line' : 'ri-checkbox-circle-line'} mr-1`} />
          {isError ? '失败' : '成功'}
        </span>
        <span className="text-xs text-slate-400">
          <i className="ri-timer-line mr-1" />
          {result.duration_ms} ms
        </span>
        <span className="text-xs text-slate-400">
          <i className="ri-hashtag mr-1" />
          log #{result.log_id}
        </span>
      </div>

      {/* 结果内容 */}
      <div className="flex-1 overflow-auto min-h-0">
        {/* 优先展示 MCP content 文本（更易读） */}
        {mcpContent && mcpContent.length > 0 ? (
          <div className="space-y-2">
            {mcpContent.map((item, idx) =>
              item.type === 'text' && item.text ? (
                <pre
                  key={idx}
                  className="text-xs bg-slate-50 border border-slate-200 rounded-lg p-3 overflow-auto whitespace-pre-wrap break-all"
                >
                  {item.text}
                </pre>
              ) : null,
            )}
          </div>
        ) : (
          <pre className="text-xs bg-slate-50 border border-slate-200 rounded-lg p-3 overflow-auto h-full whitespace-pre-wrap break-all">
            {JSON.stringify(result.result, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
