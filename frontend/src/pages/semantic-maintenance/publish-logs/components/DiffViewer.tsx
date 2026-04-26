import React, { useState } from 'react';

export interface DiffField {
  tableau: string | null;
  mulan: string | null;
}

export interface DiffViewerProps {
  /** diff 数据，key=字段名，value={tableau, mulan} */
  diff: Record<string, DiffField> | null;
  /** rollback diff: key=字段名，value=恢复的原始值 */
  rollbackDiff?: Record<string, string> | null;
  /** 显示模式：并排 | 内联 */
  mode?: 'side-by-side' | 'inline';
  /** 是否为回滚类型 diff */
  isRollback?: boolean;
}

const FIELD_LABELS: Record<string, string> = {
  description: '描述',
  caption: '标题',
  semantic_name: '语义名称',
  semantic_name_zh: '中文名称',
};

function getFieldLabel(field: string): string {
  return FIELD_LABELS[field] || field;
}

function formatValue(val: string | null): string {
  if (val === null || val === undefined) return '（空）';
  return val;
}

export function DiffViewer({ diff, rollbackDiff, mode = 'side-by-side', isRollback = false }: DiffViewerProps) {
  const [expandedFields, setExpandedFields] = useState<Set<string>>(new Set());

  const toggleExpanded = (field: string) => {
    const newSet = new Set(expandedFields);
    if (newSet.has(field)) newSet.delete(field);
    else newSet.add(field);
    setExpandedFields(newSet);
  };

  // Render rollback diff
  if (isRollback && rollbackDiff) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 mb-3">
          <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded font-medium">
            回滚操作
          </span>
          <span className="text-xs text-slate-400">恢复到发布前的原始值</span>
        </div>
        {Object.entries(rollbackDiff).map(([field, originalValue]) => (
          <div key={field} className="border border-blue-200 rounded-lg overflow-hidden">
            <div className="bg-blue-50 px-3 py-2 flex items-center justify-between">
              <span className="font-medium text-blue-800 text-sm">{getFieldLabel(field)}</span>
              <span className="text-xs text-blue-500">原始值</span>
            </div>
            <div className="px-3 py-2 bg-white">
              <span className="text-slate-700 text-sm">{formatValue(originalValue)}</span>
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (!diff || Object.keys(diff).length === 0) {
    return (
      <div className="text-center py-8 text-slate-400 text-sm">
        无差异记录
      </div>
    );
  }

  const entries = Object.entries(diff);

  // Group by change type
  const added: Array<[string, DiffField]> = [];
  const modified: Array<[string, DiffField]> = [];
  const unchanged: Array<[string, DiffField]> = [];

  for (const [field, values] of entries) {
    const oldVal = values.tableau;
    const newVal = values.mulan;
    if (oldVal === null && newVal !== null) {
      added.push([field, values]);
    } else if (oldVal !== null && newVal !== null && oldVal !== newVal) {
      modified.push([field, values]);
    } else {
      unchanged.push([field, values]);
    }
  }

  const isLongText = (val: string | null) => val && val.length > 100;

  if (mode === 'inline') {
    return (
      <div className="space-y-3">
        {entries.map(([field, values]) => {
          const oldVal = values.tableau;
          const newVal = values.mulan;
          const isLong = isLongText(oldVal || newVal);
          const expanded = expandedFields.has(field);

          return (
            <div key={field} className="border border-slate-200 rounded-lg overflow-hidden">
              <button
                onClick={() => toggleExpanded(field)}
                className="w-full px-3 py-2 flex items-center justify-between bg-slate-50 hover:bg-slate-100 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-700 text-sm">{getFieldLabel(field)}</span>
                  {oldVal === null && newVal !== null && (
                    <span className="px-1.5 py-0.5 bg-emerald-100 text-emerald-700 text-xs rounded">新增</span>
                  )}
                  {oldVal !== null && newVal !== null && oldVal !== newVal && (
                    <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 text-xs rounded">修改</span>
                  )}
                </div>
                {isLong && (
                  <span className="text-xs text-slate-400">{expanded ? '收起' : '展开'}</span>
                )}
              </button>
              {!isLong || expanded ? (
                <div className="px-3 py-2 bg-white space-y-1">
                  {oldVal !== null && (
                    <div>
                      <div className="text-xs text-slate-400 mb-0.5">Tableau 当前值</div>
                      <div className="text-sm text-slate-600 line-through bg-red-50 px-2 py-1 rounded">
                        {formatValue(oldVal)}
                      </div>
                    </div>
                  )}
                  {newVal !== null && (
                    <div>
                      <div className="text-xs text-slate-400 mb-0.5">Mulan 发布值</div>
                      <div className="text-sm text-slate-800 bg-emerald-50 px-2 py-1 rounded">
                        {formatValue(newVal)}
                      </div>
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    );
  }

  // Side-by-side mode
  return (
    <div className="space-y-3">
      {added.length > 0 && (
        <div>
          <div className="text-xs font-medium text-emerald-600 mb-2 uppercase tracking-wide">
            + 新增字段
          </div>
          <div className="space-y-2">
            {added.map(([field, values]) => (
              <div key={field} className="grid grid-cols-2 gap-2">
                <div className="border border-slate-200 rounded-lg p-2 bg-slate-50">
                  <div className="text-xs text-slate-400 mb-1">{getFieldLabel(field)} · Tableau</div>
                  <div className="text-sm text-slate-400 italic">{formatValue(null)}</div>
                </div>
                <div className="border border-emerald-300 rounded-lg p-2 bg-emerald-50">
                  <div className="text-xs text-emerald-600 mb-1">{getFieldLabel(field)} · Mulan</div>
                  <div className="text-sm text-emerald-800">{formatValue(values.mulan)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {modified.length > 0 && (
        <div>
          <div className="text-xs font-medium text-amber-600 mb-2 uppercase tracking-wide">
            ~ 修改字段
          </div>
          <div className="space-y-2">
            {modified.map(([field, values]) => {
              const oldVal = values.tableau;
              const newVal = values.mulan;
              const isLong = isLongText(oldVal || newVal);
              const expanded = expandedFields.has(field);

              if (isLong) {
                return (
                  <div key={field} className="border border-amber-200 rounded-lg overflow-hidden">
                    <button
                      onClick={() => toggleExpanded(field)}
                      className="w-full px-3 py-2 flex items-center justify-between bg-amber-50 hover:bg-amber-100 transition-colors"
                    >
                      <span className="font-medium text-amber-800 text-sm">{getFieldLabel(field)}</span>
                      <span className="text-xs text-amber-600">{expanded ? '收起' : '展开'}</span>
                    </button>
                    {expanded && (
                      <div className="grid grid-cols-2 gap-2 p-2 bg-white">
                        <div className="p-2 bg-red-50 rounded">
                          <div className="text-xs text-red-500 mb-1">Tableau 当前值</div>
                          <div className="text-sm text-red-700 line-through whitespace-pre-wrap">
                            {formatValue(oldVal)}
                          </div>
                        </div>
                        <div className="p-2 bg-emerald-50 rounded">
                          <div className="text-xs text-emerald-500 mb-1">Mulan 发布值</div>
                          <div className="text-sm text-emerald-700 whitespace-pre-wrap">
                            {formatValue(newVal)}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              }

              return (
                <div key={field} className="grid grid-cols-2 gap-2">
                  <div className="border border-red-200 rounded-lg p-2 bg-red-50">
                    <div className="text-xs text-red-400 mb-1">{getFieldLabel(field)} · Tableau</div>
                    <div className="text-sm text-red-700 line-through">{formatValue(oldVal)}</div>
                  </div>
                  <div className="border border-emerald-200 rounded-lg p-2 bg-emerald-50">
                    <div className="text-xs text-emerald-400 mb-1">{getFieldLabel(field)} · Mulan</div>
                    <div className="text-sm text-emerald-700">{formatValue(newVal)}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {unchanged.length > 0 && (
        <div>
          <div className="text-xs font-medium text-slate-400 mb-2 uppercase tracking-wide">
            = 未变化
          </div>
          <div className="space-y-1">
            {unchanged.map(([field, values]) => (
              <div key={field} className="flex items-center gap-2 text-sm text-slate-400">
                <span className="font-medium">{getFieldLabel(field)}:</span>
                <span>{formatValue(values.tableau)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
