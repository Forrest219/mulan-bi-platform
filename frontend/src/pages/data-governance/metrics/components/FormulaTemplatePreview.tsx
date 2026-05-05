import React, { useState } from 'react';
import { renderTemplate } from '../../../../api/metrics';

interface FormulaTemplatePreviewProps {
  formulaTemplate: string | null;
  filters: Record<string, unknown> | null;
}

export default function FormulaTemplatePreview({
  formulaTemplate,
  filters,
}: FormulaTemplatePreviewProps) {
  const [contextInput, setContextInput] = useState<string>(() => {
    // 预填当前 filters 值
    if (filters && Object.keys(filters).length > 0) {
      return JSON.stringify(filters, null, 2);
    }
    return '{}';
  });
  const [rendered, setRendered] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!formulaTemplate) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl p-6">
        <h3 className="text-[14px] font-semibold text-slate-700 mb-3">公式模板预览</h3>
        <p className="text-[13px] text-slate-400">无公式模板</p>
      </div>
    );
  }

  const handlePreview = async () => {
    setLoading(true);
    setError(null);
    setRendered(null);
    try {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(contextInput);
      } catch {
        setError('变量值 JSON 格式错误，请检查输入');
        setLoading(false);
        return;
      }
      const resp = await renderTemplate(formulaTemplate, parsed);
      if (resp.success && resp.result !== undefined) {
        setRendered(resp.result);
        setError(null);
      } else {
        setError(resp.error || '渲染失败');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '渲染请求失败');
    } finally {
      setLoading(false);
    }
  };

  const filterEntries = filters && Object.keys(filters).length > 0
    ? Object.entries(filters)
    : null;

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6">
      <h3 className="text-[14px] font-semibold text-slate-700 mb-3">公式模板预览</h3>

      {/* 原始模板 */}
      <div className="mb-4">
        <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide mb-1.5">
          模板内容
        </div>
        <pre className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-[12px] text-slate-600 font-mono overflow-x-auto">
          {formulaTemplate}
        </pre>
      </div>

      {/* 模板变量参考表 */}
      {filterEntries && (
        <div className="mb-4">
          <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide mb-1.5">
            模板变量（当前值）
          </div>
          <table className="min-w-[240px] text-[12px] border border-slate-200 rounded-lg overflow-hidden">
            <thead>
              <tr className="bg-slate-50">
                <th className="text-left px-3 py-2 font-semibold text-slate-500">变量名</th>
                <th className="text-left px-3 py-2 font-semibold text-slate-500">当前值</th>
              </tr>
            </thead>
            <tbody>
              {filterEntries.map(([key, val]) => (
                <tr key={key} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-mono text-slate-600">{`{{${key}}}`}</td>
                  <td className="px-3 py-2 font-mono text-slate-700">{String(val)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 变量输入区 */}
      <div className="mb-4">
        <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide mb-1.5">
          变量值（JSON）
        </div>
        <textarea
          className="w-full h-24 bg-slate-50 border border-slate-200 rounded-lg p-3 text-[12px] font-mono text-slate-700 resize-y"
          value={contextInput}
          onChange={(e) => setContextInput(e.target.value)}
          placeholder='例: {"column": "amount", "id": "orders"}'
          spellCheck={false}
        />
      </div>

      {/* 预览按钮 */}
      <button
        onClick={handlePreview}
        disabled={loading}
        className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-50 cursor-pointer"
      >
        {loading ? (
          <>
            <i className="ri-loader-4-line animate-spin" />
            渲染中...
          </>
        ) : (
          <>
            <i className="ri-play-line" />
            预览渲染结果
          </>
        )}
      </button>

      {/* 渲染结果 */}
      {rendered && (
        <div className="mt-4">
          <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide mb-1.5">
            渲染结果
          </div>
          <pre className="bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-[12px] text-emerald-700 font-mono overflow-x-auto">
            {rendered}
          </pre>
        </div>
      )}

      {/* 错误提示 */}
      {error && (
        <div className="mt-4 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-[12px] text-red-600 flex items-center gap-1.5">
          <i className="ri-error-warning-line" />
          {error}
        </div>
      )}
    </div>
  );
}