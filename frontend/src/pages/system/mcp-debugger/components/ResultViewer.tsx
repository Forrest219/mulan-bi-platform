import React, { useState, useCallback } from 'react';
import type { McpDebugCallResponse } from '../../../../api/mcpDebug';
import DatasourceListRenderer from './renderers/DatasourceListRenderer';
import DatasourceMetaRenderer from './renderers/DatasourceMetaRenderer';
import FieldSchemaRenderer from './renderers/FieldSchemaRenderer';
import ArrayTableRenderer from './renderers/ArrayTableRenderer';

interface Props {
  result: McpDebugCallResponse | null;
  error: string | null;
}

// ── Result Normalizer ──────────────────────────────────────────────────────────

interface NormalizedBlock {
  type: 'text' | 'image' | 'unknown';
  raw: string;
  parsed?: unknown;
}

interface NormalizedResult {
  toolName: string;
  durationMs: number;
  logId: number;
  status: 'success' | 'error';
  blocks: NormalizedBlock[];
  /** 尝试把 text 内容 JSON.parse 后的结构化对象 */
  payload: unknown;
  /** 原始 result.result */
  raw: Record<string, unknown>;
}

/** 尝试把 MCP content[].text JSON.parse，返回结构化对象或 null */
function tryParseJson(text: string): unknown | null {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function normalizeResult(result: McpDebugCallResponse): NormalizedResult {
  const content = result.result as Record<string, unknown>;
  const resultContent = content?.result as Record<string, unknown> | undefined;
  const mcpContent = (resultContent?.content as Array<{ type: string; text?: string; source?: { media: string; data: string } }>) ?? [];

  const blocks: NormalizedBlock[] = mcpContent.map((item) => {
    if (item.type === 'text' && item.text) {
      const parsed = tryParseJson(item.text);
      return { type: 'text' as const, raw: item.text, parsed: parsed ?? undefined };
    }
    if (item.type === 'image') {
      return { type: 'image' as const, raw: (item as { source?: { data: string } }).source?.data ?? '' };
    }
    return { type: 'unknown' as const, raw: JSON.stringify(item) };
  });

  // payload：优先取第一个 text block 的 parse 结果
  const firstText = blocks.find((b) => b.type === 'text');
  const payload = firstText?.parsed ?? firstText?.raw ?? null;

  return {
    toolName: result.tool_name,
    durationMs: result.duration_ms,
    logId: result.log_id,
    status: result.status,
    blocks,
    payload,
    raw: result.result,
  };
}

// ── Tool-Specific Renderer Dispatcher ────────────────────────────────────────

function renderByTool(
  toolName: string,
  payload: unknown,
  nr: NormalizedResult,
): React.ReactNode {
  switch (toolName) {
    case 'list-datasources':
      return <DatasourceListRenderer payload={payload} raw={nr.raw} />;
    case 'get-datasource-metadata':
      return <DatasourceMetaRenderer payload={payload} raw={nr.raw} />;
    case 'get-field-schema':
      return <FieldSchemaRenderer payload={payload} raw={nr.raw} />;
    default: {
      // 通用列表兜底：如果 payload 是数组
      if (Array.isArray(payload)) {
        return <ArrayTableRenderer rows={payload} toolName={toolName} />;
      }
      // 如果是对象且有数组字段，尝试取第一个数组
      if (payload && typeof payload === 'object') {
        const obj = payload as Record<string, unknown>;
        const arrKey = Object.keys(obj).find((k) => Array.isArray(obj[k]));
        if (arrKey) {
          return <ArrayTableRenderer rows={obj[arrKey] as unknown[]} toolName={toolName} hint={arrKey} />;
        }
      }
      return null; // 走 fallback
    }
  }
}

// ── Raw JSON Viewer ────────────────────────────────────────────────────────────

function RawViewer({ nr }: { nr: NormalizedResult }) {
  const [copied, setCopied] = useState(false);
  const json = JSON.stringify(nr.raw, null, 2);

  const copy = useCallback(() => {
    navigator.clipboard.writeText(json).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [json]);

  return (
    <div className="flex flex-col gap-2 h-full">
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-xs text-slate-400">完整响应</span>
        <button
          onClick={copy}
          className="text-xs px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors"
        >
          {copied ? '✓ 已复制' : '复制'}
        </button>
      </div>
      <pre className="flex-1 text-xs bg-slate-50 border border-slate-200 rounded-lg p-3 overflow-auto whitespace-pre-wrap break-all">
        {json}
      </pre>
    </div>
  );
}

// ── Image Block Renderer ───────────────────────────────────────────────────────

function ImageBlock({ block }: { block: NormalizedBlock }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <div className="space-y-1">
      <div className="text-xs text-slate-400">🖼 图片</div>
      {!loaded && <div className="text-xs text-slate-400">图片加载中...</div>}
      <img
        src={`data:image/png;base64,${block.raw}`}
        alt="MCP result"
        className="max-w-full rounded border border-slate-200"
        onLoad={() => setLoaded(true)}
      />
    </div>
  );
}

// ── Status Bar ─────────────────────────────────────────────────────────────────

function StatusBar({ nr }: { nr: NormalizedResult }) {
  const isError = nr.status === 'error';
  const isStructured = nr.blocks.some((b) => b.type === 'text' && b.parsed);

  return (
    <div className="flex items-center gap-3 shrink-0 flex-wrap">
      <span
        className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
          isError ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'
        }`}
      >
        <i className={`${isError ? 'ri-close-circle-line' : 'ri-checkbox-circle-line'} mr-1`} />
        {isError ? '失败' : '成功'}
      </span>
      <span className="text-xs text-slate-400">
        <i className="ri-timer-line mr-1" />
        {nr.durationMs} ms
      </span>
      <span className="text-xs text-slate-400">
        <i className="ri-hashtag mr-1" />
        log #{nr.logId}
      </span>
      <span className="text-xs text-slate-400">
        <i className="ri-tool-line mr-1" />
        {nr.toolName}
      </span>
      <span className="text-xs text-slate-400">
        <i className={`${isStructured ? 'ri-list-check' : 'ri-file-text-line'} mr-1`} />
        {isStructured ? '结构化' : '原始文本'}
      </span>
      {nr.blocks.length > 1 && (
        <span className="text-xs text-slate-400">
          <i className="ri-stack-line mr-1" />
          {nr.blocks.length} blocks
        </span>
      )}
    </div>
  );
}

// ── Fallback for non-structured results ───────────────────────────────────────

function FallbackViewer({ nr }: { nr: NormalizedResult }) {
  return (
    <div className="flex flex-col gap-3 h-full">
      {nr.blocks.map((block, idx) =>
        block.type === 'image' ? (
          <ImageBlock key={idx} block={block} />
        ) : (
          <pre
            key={idx}
            className="text-xs bg-slate-50 border border-slate-200 rounded-lg p-3 overflow-auto whitespace-pre-wrap break-all"
          >
            {block.raw}
          </pre>
        ),
      )}
    </div>
  );
}

// ── Main ResultViewer ──────────────────────────────────────────────────────────

export default function ResultViewer({ result, error }: Props) {
  const [activeTab, setActiveTab] = useState<'overview' | 'raw'>('overview');

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

  const nr = normalizeResult(result);
  const structuredView = renderByTool(nr.toolName, nr.payload, nr);

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* 状态栏 */}
      <StatusBar nr={nr} />

      {/* Tab 切换 */}
      <div className="shrink-0 flex items-center gap-1 px-1 py-1 bg-slate-100 rounded-lg w-fit">
        <button
          onClick={() => setActiveTab('overview')}
          className={`px-3 py-1 rounded-md text-[12px] font-medium transition-colors ${
            activeTab === 'overview'
              ? 'bg-white text-slate-800 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          概览
        </button>
        <button
          onClick={() => setActiveTab('raw')}
          className={`px-3 py-1 rounded-md text-[12px] font-medium transition-colors ${
            activeTab === 'raw'
              ? 'bg-white text-slate-800 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          原始
        </button>
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-auto min-h-0">
        {activeTab === 'raw' ? (
          <RawViewer nr={nr} />
        ) : structuredView ? (
          <div className="h-full">{structuredView}</div>
        ) : (
          <FallbackViewer nr={nr} />
        )}
      </div>
    </div>
  );
}
