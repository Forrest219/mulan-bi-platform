import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  getDwTableDetail,
  listDwColumns,
  listDwPartitions,
  getDwLineage,
  getDwPreview,
  createAgentContext,
  updateDwColumn,
  updateDwTable,
  fetchDomainValues,
  getDwTableSuggestions,
  DwAssetTableDetail,
  DwAssetColumn,
  DwAssetPartition,
  DwLineageData,
  DwPreviewData,
  DomainValueItem,
} from '../../../api/dwAssets';
import { useAuth } from '../../../context/AuthContext';

// ============================================================
// 治理编辑抽屉
// ============================================================

interface EditForm {
  business_name: string;
  description: string;
  domain_l1: string;
  domain_l2: string;
  tags: string; // 逗号分隔
}

function TableEditDrawer({
  detail,
  onClose,
  onSaved,
}: {
  detail: DwAssetTableDetail;
  onClose: () => void;
  onSaved: (updated: DwAssetTableDetail) => void;
}) {
  const [domainValues, setDomainValues] = useState<DomainValueItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parseDomain = (v: string | null) => {
    if (!v) return { l1: '', l2: '' };
    const parts = v.split('/', 2);
    return { l1: parts[0] || '', l2: parts[1] || '' };
  };

  const { l1: initL1, l2: initL2 } = parseDomain(detail.domain);
  const [form, setForm] = useState<EditForm>({
    business_name: detail.business_name || '',
    description: detail.description || '',
    domain_l1: initL1,
    domain_l2: initL2,
    tags: (detail.tags || []).join(', '),
  });

  useEffect(() => {
    fetchDomainValues().then((r) => setDomainValues(r.items)).catch(() => {});
  }, []);

  const currentL2List = domainValues.find((d) => d.l1 === form.domain_l1)?.l2_list || [];

  const handleAiSuggest = async () => {
    setSuggesting(true);
    setError(null);
    try {
      const s = await getDwTableSuggestions(detail.id);
      setForm((f) => ({
        ...f,
        business_name: s.business_name ?? f.business_name,
        description: s.description ?? f.description,
      }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'AI 建议获取失败');
    } finally {
      setSuggesting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      let domainVal: string | null = null;
      if (form.domain_l1.trim()) {
        const l2 = form.domain_l2.startsWith('__custom__') ? '' : form.domain_l2;
        domainVal = l2.trim()
          ? `${form.domain_l1.trim()}/${l2.trim()}`
          : form.domain_l1.trim();
      }
      const tags = form.tags.split(',').map((t) => t.trim()).filter(Boolean);
      const res = await updateDwTable(detail.id, {
        business_name: form.business_name || undefined,
        description: form.description || undefined,
        domain: domainVal ?? undefined,
        tags,
      });
      onSaved(res.table);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const fieldCls = 'w-full text-sm border border-slate-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500';

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-[420px] bg-white shadow-xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h2 className="text-sm font-semibold text-slate-900">编辑治理信息</h2>
          <div className="flex items-center gap-2">
            <button onClick={handleAiSuggest} disabled={suggesting}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs border border-purple-300 text-purple-700 rounded-md hover:bg-purple-50 disabled:opacity-50">
              <i className={`ri-sparkling-line ${suggesting ? 'animate-pulse' : ''}`} />
              {suggesting ? 'AI 分析中…' : 'AI 建议'}
            </button>
            <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
              <i className="ri-close-line text-xl" />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <div>
            <label className="text-xs font-medium text-slate-500 block mb-1">物理表名</label>
            <div className="text-sm text-slate-700 bg-slate-50 rounded-md px-3 py-2 border border-slate-200">
              {detail.table_name}
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-slate-500 block mb-1">业务名称</label>
            <input type="text" value={form.business_name}
              onChange={(e) => setForm({ ...form, business_name: e.target.value })}
              placeholder="如：订单事实表" className={fieldCls} />
          </div>

          <div>
            <label className="text-xs font-medium text-slate-500 block mb-1">业务描述</label>
            <textarea value={form.description} rows={3}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="简要说明该表的业务含义与使用场景"
              className={`${fieldCls} resize-none`} />
          </div>

          <div>
            <label className="text-xs font-medium text-slate-500 block mb-1">主题域 L1（业务板块）</label>
            <select value={form.domain_l1}
              onChange={(e) => setForm({ ...form, domain_l1: e.target.value, domain_l2: '' })}
              className={`${fieldCls} bg-white`}>
              <option value="">— 未分配 —</option>
              {domainValues.map((d) => <option key={d.l1} value={d.l1}>{d.l1}</option>)}
            </select>
          </div>

          {form.domain_l1 && (
            <div>
              <label className="text-xs font-medium text-slate-500 block mb-1">主题域 L2（业务过程）</label>
              <select value={form.domain_l2.startsWith('__custom__') ? '' : form.domain_l2}
                onChange={(e) => setForm({ ...form, domain_l2: e.target.value || '__custom__' })}
                className={`${fieldCls} bg-white`}>
                <option value="">— 仅 L1 —</option>
                {currentL2List.map((l2) => <option key={l2} value={l2}>{l2}</option>)}
                <option value="__custom__">其他（手动输入）</option>
              </select>
              {form.domain_l2 === '__custom__' && (
                <input type="text" value=""
                  onChange={(e) => setForm({ ...form, domain_l2: e.target.value })}
                  placeholder="直接输入新的 L2 名称"
                  className={`${fieldCls} mt-1.5`} />
              )}
            </div>
          )}

          <div>
            <label className="text-xs font-medium text-slate-500 block mb-1">数仓分层</label>
            <div className="text-sm text-slate-700 bg-slate-50 rounded-md px-3 py-2 border border-slate-200 font-mono uppercase">
              {detail.layer || '—'}
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-slate-500 block mb-1">标签（逗号分隔）</label>
            <input type="text" value={form.tags}
              onChange={(e) => setForm({ ...form, tags: e.target.value })}
              placeholder="如：核心, 订单, 高频" className={fieldCls} />
          </div>

          {error && (
            <div className="text-sm text-red-600 bg-red-50 rounded-md px-3 py-2">{error}</div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-slate-200 flex justify-end gap-2">
          <button onClick={onClose}
            className="px-4 py-2 text-sm text-slate-600 border border-slate-300 rounded-md hover:bg-slate-50">
            取消
          </button>
          <button onClick={handleSave} disabled={saving}
            className="px-4 py-2 text-sm bg-blue-700 text-white rounded-md hover:bg-blue-800 disabled:opacity-50">
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </>
  );
}

// ============================================================
// 工具函数
// ============================================================

function heatLabel(score: number): { label: string; cls: string } {
  if (score === 0) return { label: '冷资产', cls: 'bg-slate-100 text-slate-500' };
  if (score < 30) return { label: '低热度', cls: 'bg-blue-50 text-blue-500' };
  if (score < 70) return { label: '中热度', cls: 'bg-amber-50 text-amber-600' };
  return { label: '高热度', cls: 'bg-red-50 text-red-600' };
}

function inferBusinessName(tableName: string): string {
  const stripped = tableName.replace(/^(bidm|dwd|dws|ods|dim|ads|tmp|stg|fact|rpt|dwm|dwa)_/i, '');
  return stripped.split('_').filter(Boolean).join(' ');
}

function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatRowCount(count: number | null): string {
  if (count === null || count === undefined) return '-';
  if (count < 1000) return String(count);
  if (count < 10000) return `${(count / 1000).toFixed(1)}K`;
  if (count < 1000000) return `${Math.round(count / 1000)}K`;
  if (count < 1000000000) return `${(count / 1000000).toFixed(1)}M`;
  return `${(count / 1000000000).toFixed(2)}B`;
}

// ============================================================
// 详情页组件
// ============================================================

export default function DwAssetDetailPage() {
  const { tableId } = useParams<{ tableId: string }>();
  const numericId = Number(tableId);
  const { isAdmin, isDataAdmin } = useAuth();
  const canEdit = isAdmin || isDataAdmin;

  const [detail, setDetail] = useState<DwAssetTableDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'columns' | 'preview' | 'partitions' | 'lineage'>('columns');
  const [editOpen, setEditOpen] = useState(false);

  useEffect(() => {
    if (!numericId) return;
    setLoading(true);
    setError(null);
    getDwTableDetail(numericId)
      .then(setDetail)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : '加载失败'))
      .finally(() => setLoading(false));
  }, [numericId]);

  const handleSendToAgent = async () => {
    if (!numericId) return;
    try {
      await createAgentContext(numericId, { intent: 'ask_about_table' });
    } catch {
      // 静默
    }
  };

  // Loading
  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="flex items-center gap-3 text-slate-500">
          <i className="ri-loader-4-line animate-spin text-xl"></i>
          <span>加载中...</span>
        </div>
      </div>
    );
  }

  // Error
  if (error) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center">
        <i className="ri-error-warning-line text-4xl text-red-400 mb-3"></i>
        <p className="text-slate-600 mb-4">{error}</p>
        <Link to="/assets/dw" className="px-4 py-2 text-sm bg-blue-700 text-white rounded-md hover:bg-blue-800">
          返回列表
        </Link>
      </div>
    );
  }

  // Empty (should not happen normally)
  if (!detail) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center">
        <p className="text-slate-500">未找到该表信息</p>
        <Link to="/assets/dw" className="mt-4 text-sm text-blue-700 hover:underline">返回列表</Link>
      </div>
    );
  }

  const tabs = [
    { key: 'columns' as const, label: '字段定义', icon: 'ri-table-line' },
    { key: 'preview' as const, label: '数据预览', icon: 'ri-eye-line' },
    { key: 'partitions' as const, label: '分区信息', icon: 'ri-layout-grid-line' },
    { key: 'lineage' as const, label: '血缘拓扑', icon: 'ri-git-merge-line' },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-6 py-4">
        <div className="flex items-center gap-2 text-sm text-slate-500 mb-3">
          <Link to="/assets/dw" className="hover:text-blue-700">数仓资产</Link>
          <i className="ri-arrow-right-s-line"></i>
          <span className="text-slate-700">{detail.table_name}</span>
        </div>

        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            {/* H1: business_name 为主标题 */}
            <div className="flex items-center gap-2 flex-wrap">
              {detail.business_name ? (
                <h1 className="text-xl font-semibold text-slate-900 leading-tight">{detail.business_name}</h1>
              ) : (
                <h1 className="text-xl font-semibold text-slate-400 leading-tight">未命名资产</h1>
              )}
              {!detail.business_name && canEdit && (
                <button
                  onClick={() => setEditOpen(true)}
                  title="AI 自动填充业务名称"
                  className="flex items-center gap-0.5 px-1.5 py-0.5 text-xs text-purple-600 bg-purple-50 rounded hover:bg-purple-100"
                >
                  <i className="ri-sparkling-line" />
                  AI 建议
                </button>
              )}
              {/* 状态标签行 */}
              {detail.layer && (
                <span className="px-2 py-0.5 bg-slate-100 text-xs text-slate-500 rounded font-mono uppercase">
                  {detail.layer}
                </span>
              )}
              {detail.domain && (
                <span className="px-2 py-0.5 bg-blue-50 text-xs text-blue-600 rounded">
                  {detail.domain}
                </span>
              )}
              {(() => { const h = heatLabel(detail.heat_score); return (
                <span className={`px-2 py-0.5 text-xs rounded ${h.cls}`}>{h.label}</span>
              ); })()}
              {detail.lineage_summary.upstream_count === 0 && detail.lineage_summary.downstream_count === 0 && (
                <button
                  onClick={() => setActiveTab('lineage')}
                  className="px-2 py-0.5 text-xs rounded bg-amber-50 text-amber-600 hover:bg-amber-100"
                  title="点击前往血缘 Tab 补充"
                >
                  孤儿资产
                </button>
              )}
            </div>
            {/* 物理名 + 数据源信息（弱化） */}
            <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-400">
              <span className="font-mono">{detail.table_name}</span>
              <span>·</span>
              <span>{detail.datasource.name} / {detail.database_name}</span>
              <span>·</span>
              <span>同步于 {detail.synced_at}</span>
              {detail.heat_score > 0 && <span>· 热度 {Math.round(detail.heat_score)}</span>}
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {canEdit && (
              <button
                onClick={() => setEditOpen(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-slate-300 text-slate-700 rounded-md hover:bg-slate-50"
              >
                <i className="ri-edit-line"></i>
                编辑
              </button>
            )}
            <button
              onClick={handleSendToAgent}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-700 text-white rounded-md hover:bg-blue-800"
            >
              <i className="ri-robot-line"></i>
              发送到 Data Agent
            </button>
          </div>
        </div>
      </div>

      {/* Overview */}
      <div className="px-6 py-4">
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div>
              <div className="text-xs text-slate-500">行数估算</div>
              <div className="text-sm font-medium text-slate-900">{formatRowCount(detail.row_count_estimate)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">存储量</div>
              <div className="text-sm font-medium text-slate-900">{formatBytes(detail.storage_bytes)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">分区</div>
              <div className="text-sm font-medium text-slate-900">
                {detail.partition_count ? `${detail.partition_count} (${detail.partition_key || '-'})` : '无分区'}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">血缘</div>
              <div className="text-sm font-medium text-slate-900">
                {detail.lineage_summary.upstream_count} 上游 / {detail.lineage_summary.downstream_count} 下游
              </div>
            </div>
          </div>

          {/* 业务描述 — 始终显示 */}
          <div className="border-t border-slate-100 pt-3">
            <div className="text-xs text-slate-500 mb-1">业务描述</div>
            {detail.description ? (
              <div className="text-sm text-slate-700">{detail.description}</div>
            ) : (
              <div className="text-sm text-slate-400 flex items-center gap-2">
                暂无描述 — Agent 抓取此页时将无法理解该表的业务含义
                {canEdit && (
                  <button onClick={() => setEditOpen(true)}
                    className="text-xs text-blue-600 hover:text-blue-800 underline">
                    点击编辑补充
                  </button>
                )}
              </div>
            )}
          </div>

          {detail.tags && detail.tags.length > 0 && (
            <div className="border-t border-slate-100 pt-3 mt-3">
              <div className="text-xs text-slate-500 mb-1">标签</div>
              <div className="flex gap-1 flex-wrap">
                {detail.tags.map((tag) => (
                  <span key={tag} className="px-2 py-0.5 bg-blue-50 text-blue-700 text-xs rounded">{tag}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="px-6">
        <div className="border-b border-slate-200 flex gap-0">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-blue-700 text-blue-700 font-medium'
                  : 'border-transparent text-slate-500 hover:text-slate-700'
              }`}
            >
              <i className={tab.icon}></i>
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content */}
      <div className="px-6 py-4">
        {activeTab === 'columns' && <ColumnsTab tableId={numericId} />}
        {activeTab === 'preview' && <PreviewTab tableId={numericId} />}
        {activeTab === 'partitions' && <PartitionsTab tableId={numericId} />}
        {activeTab === 'lineage' && <LineageTab tableId={numericId} />}
      </div>

      {editOpen && detail && (
        <TableEditDrawer
          detail={detail}
          onClose={() => setEditOpen(false)}
          onSaved={(updated) => { setDetail(updated); setEditOpen(false); }}
        />
      )}
    </div>
  );
}

// ============================================================
// 字段定义 Tab
// ============================================================

function ColumnsTab({ tableId }: { tableId: number }) {
  const { isAdmin, isDataAdmin } = useAuth();
  const canEdit = isAdmin || isDataAdmin;

  const [columns, setColumns] = useState<DwAssetColumn[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(0);

  // 行内编辑状态
  type EditField = 'business_name' | 'description';
  interface EditCell {
    colId: number;
    field: EditField;
    bizName: string;
    desc: string;
    // user_has_modified: true = 不再使用 column_comment 兜底
    userHasModified: boolean;
    saving: boolean;
  }
  const [editCell, setEditCell] = useState<EditCell | null>(null);
  const bizNameRef = useRef<HTMLInputElement | null>(null);
  const descRef = useRef<HTMLTextAreaElement | null>(null);

  const fetchColumns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listDwColumns(tableId, { page, page_size: 100 });
      setColumns(res.items);
      setTotal(res.total);
      setPages(res.pages);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [tableId, page]);

  useEffect(() => { fetchColumns(); }, [fetchColumns]);

  // 启动编辑
  const startEdit = useCallback((col: DwAssetColumn, field: EditField) => {
    if (!canEdit) return;
    // 已有 business_name → 标记为已修改，不再用 column_comment 兜底
    const userHasModified = !!col.business_name;
    setEditCell({
      colId: col.id, field,
      bizName: col.business_name ?? col.column_comment ?? '',
      desc: col.description ?? '',
      userHasModified,
      saving: false,
    });
    setTimeout(() => {
      if (field === 'business_name') bizNameRef.current?.focus();
      else descRef.current?.focus();
    }, 0);
  }, [canEdit]);

  // Tab 导航：business_name → description → 下一行 business_name
  const handleBizNameKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>, colIndex: number) => {
    if (e.key === 'Tab' && !e.shiftKey) {
      const nextCol = columns[colIndex + 1];
      if (nextCol) {
        // 跳到下一行 business_name
        e.preventDefault();
        setEditCell((prev) => prev ? { ...prev, saving: true } : null);
        updateDwColumn(tableId, editCell!.colId, {
          business_name: editCell!.bizName || undefined,
          description: editCell!.desc || undefined,
        }).then(() => {
          setEditCell({
            colId: nextCol.id,
            field: 'business_name',
            bizName: nextCol.business_name ?? nextCol.column_comment ?? '',
            desc: nextCol.description ?? '',
            userHasModified: !!nextCol.business_name,
            saving: false,
          });
          setTimeout(() => bizNameRef.current?.focus(), 0);
        }).catch(() => {
          setEditCell((p) => p ? { ...p, saving: false } : null);
        });
      }
      // else: Tab 继续默认行为，跳到下一个可聚焦元素（description textarea）
    }
  }, [columns, editCell, tableId]);

  const handleDescKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>, colIndex: number) => {
    if (e.key === 'Tab' && !e.shiftKey) {
      const nextCol = columns[colIndex + 1];
      if (nextCol) {
        e.preventDefault();
        // 保存当前行后跳到下一行业务语义
        setEditCell((prev) => prev ? { ...prev, saving: true } : null);
        updateDwColumn(tableId, editCell!.colId, {
          business_name: editCell!.bizName || undefined,
          description: editCell!.desc || undefined,
        }).then(() => {
          setEditCell({
            colId: nextCol.id,
            field: 'business_name',
            bizName: nextCol.business_name ?? nextCol.column_comment ?? '',
            desc: nextCol.description ?? '',
            userHasModified: !!nextCol.business_name,
            saving: false,
          });
          setTimeout(() => bizNameRef.current?.focus(), 0);
        }).catch(() => {
          setEditCell((p) => p ? { ...p, saving: false } : null);
        });
      } else {
        // 最后一行，退出编辑
        setEditCell(null);
      }
    }
  }, [columns, editCell, tableId]);

  // 失焦保存（不保存则取消编辑）
  const handleContainerBlur = useCallback((e: React.FocusEvent) => {
    if (!editCell) return;
    const container = e.currentTarget as HTMLElement;
    if (container.contains(e.relatedTarget as Node)) return; // focus within, don't save yet
    // blur to outside → save
    setEditCell((prev) => prev ? { ...prev, saving: true } : null);
    updateDwColumn(tableId, editCell.colId, {
      business_name: editCell.bizName || undefined,
      description: editCell.desc || undefined,
    }).then(() => {
      setEditCell(null);
      fetchColumns();
    }).catch(() => {
      setEditCell((prev) => prev ? { ...prev, saving: false } : null);
    });
  }, [editCell, tableId, fetchColumns]);

  // 乐观切换业务主键
  const toggleBizKey = useCallback(async (col: DwAssetColumn) => {
    if (!canEdit) return;
    const newVal = !col.is_business_key;
    setColumns((prev) => prev.map((c) => c.id === col.id ? { ...c, is_business_key: newVal } : c));
    try {
      await updateDwColumn(tableId, col.id, { is_business_key: newVal });
      fetchColumns();
    } catch {
      setColumns((prev) => prev.map((c) => c.id === col.id ? { ...c, is_business_key: !newVal } : c));
    }
  }, [canEdit, tableId, fetchColumns]);

  if (loading) {
    return <div className="py-8 text-center text-slate-500"><i className="ri-loader-4-line animate-spin mr-2"></i>加载中...</div>;
  }
  if (error) {
    return <div className="py-8 text-center text-red-500">{error}</div>;
  }
  if (columns.length === 0) {
    return <div className="py-8 text-center text-slate-400">暂无字段数据</div>;
  }

  return (
    <div>
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <table className="w-full text-xs border-collapse table-fixed">
          <thead>
            <tr className="bg-slate-50">
              <th className="border border-slate-200 text-center px-3 py-2.5 font-medium text-slate-600 w-16">序号</th>
              <th className="border border-slate-200 text-left px-3 py-2.5 font-medium text-slate-600 w-30">字段名</th>
              <th className="border border-slate-200 text-left px-3 py-2.5 font-medium text-slate-600 w-30">注释</th>
              <th className="border border-slate-200 text-center px-3 py-2.5 font-medium text-slate-600 w-25">类型</th>
              <th className="border border-slate-200 text-center px-3 py-2.5 font-medium text-slate-600 w-20">主键</th>
              <th className="border border-slate-200 text-center px-3 py-2.5 font-medium text-slate-600 w-20">业务主键</th>
              <th className="border border-slate-200 text-left px-3 py-2.5 font-medium text-slate-600">业务语义</th>
              <th className="border border-slate-200 text-left px-3 py-2.5 font-medium text-slate-600 w-40">公式</th>
            </tr>
          </thead>
          <tbody>
            {columns.map((col, colIndex) => {
              const isEditingThis = editCell?.colId === col.id;

              return (
                <tr
                  key={col.id}
                  className={`hover:bg-slate-50 transition-colors ${isEditingThis ? 'bg-blue-50/40' : ''}`}
                >
                  {/* 序号 */}
                  <td className="border border-slate-200 px-3 py-2 text-center text-slate-400 w-16">
                    {col.ordinal_position}
                  </td>

                  {/* 字段名 — 只读 */}
                  <td className="border border-slate-200 px-3 py-2 w-30">
                    <span className="font-mono text-slate-900 block truncate">{col.column_name}</span>
                  </td>

                  {/* 注释 — 只读，灰色 */}
                  <td className="border border-slate-200 px-3 py-2 w-30">
                    <span className="text-slate-400 block truncate" title={col.column_comment ?? ''}>
                      {col.column_comment || '-'}
                    </span>
                  </td>

                  {/* 类型 — 只读，居中 */}
                  <td className="border border-slate-200 px-3 py-2 text-center w-20">
                    <span className="font-mono text-slate-500 block">{col.data_type}</span>
                    {col.is_nullable === true && <span className="block text-slate-400">null</span>}
                  </td>

                  {/* 主键 — 只读图标，居中 */}
                  <td className="border border-slate-200 px-3 py-2 text-center w-20">
                    {col.is_primary_key && (
                      <i className="ri-key-2-line text-amber-500" title="DDL 主键" />
                    )}
                  </td>

                  {/* 业务主键 — 可切换，居中 */}
                  <td className="border border-slate-200 px-3 py-2 text-center w-20">
                    {canEdit ? (
                      <button
                        onClick={() => toggleBizKey(col)}
                        title={col.is_business_key ? '取消业务主键标记' : '标记为业务唯一标识'}
                        className={`transition-colors ${col.is_business_key ? 'text-blue-600' : 'text-slate-300 hover:text-blue-400'}`}
                      >
                        <i className={col.is_business_key ? 'ri-bookmark-fill' : 'ri-bookmark-line'} />
                      </button>
                    ) : (
                      <i className={`${col.is_business_key ? 'ri-bookmark-fill text-blue-400' : 'ri-bookmark-line text-slate-300'}`} />
                    )}
                  </td>

                  {/* 业务语义 — 行内编辑 */}
                  <td
                    className="border border-slate-200 px-3 py-2"
                    onBlur={handleContainerBlur}
                  >
                    {isEditingThis && editCell.field === 'business_name' ? (
                      <input
                        ref={(el) => { bizNameRef.current = el; }}
                        value={editCell.bizName}
                        onChange={(e) => setEditCell((p) => p ? { ...p, bizName: e.target.value } : null)}
                        onKeyDown={(e) => handleBizNameKeyDown(e, colIndex)}
                        disabled={editCell.saving}
                        className="w-full text-xs border border-blue-400 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white"
                        placeholder="业务语义名称"
                      />
                    ) : (
                      <div
                        className={`min-h-[22px] whitespace-normal break-all ${col.business_name || (!editCell?.userHasModified && col.column_comment) ? 'text-slate-800' : 'text-slate-400 italic'} ${canEdit ? 'cursor-text hover:bg-blue-50 rounded px-1 -mx-1' : ''}`}
                        onClick={() => startEdit(col, 'business_name')}
                        title={canEdit ? '点击编辑' : ''}
                      >
                        {col.business_name
                          ? col.business_name
                          : (!editCell?.userHasModified && col.column_comment
                            ? <span className="italic text-slate-400">{col.column_comment}</span>
                            : canEdit ? <span className="text-blue-400">+ 填写</span> : '-')}
                      </div>
                    )}
                  </td>

                  {/* 公式 — 行内编辑 */}
                  <td
                    className="border border-slate-200 px-3 py-2 w-40"
                    onBlur={handleContainerBlur}
                  >
                    {isEditingThis && editCell.field === 'description' ? (
                      <textarea
                        ref={(el) => { descRef.current = el; }}
                        value={editCell.desc}
                        onChange={(e) => setEditCell((p) => p ? { ...p, desc: e.target.value } : null)}
                        onKeyDown={(e) => handleDescKeyDown(e, colIndex)}
                        disabled={editCell.saving}
                        rows={2}
                        className="w-full mt-1 text-xs border border-blue-400 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white resize-none"
                        placeholder="填写计算公式或业务描述"
                      />
                    ) : (
                      <div
                        className={`min-h-[22px] whitespace-normal break-all ${col.description ? 'text-slate-600' : 'text-slate-300'} ${canEdit ? 'cursor-text hover:bg-blue-50 rounded px-1 -mx-1' : ''}`}
                        onClick={() => startEdit(col, 'description')}
                        title={canEdit ? '点击编辑' : ''}
                      >
                        {col.description || (canEdit ? <span className="italic text-blue-400">+ 填写</span> : '-')}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* 分页 */}
      {pages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <span className="text-xs text-slate-500">共 {total} 个字段</span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-2.5 py-1 text-xs border border-slate-300 rounded disabled:opacity-40 hover:bg-slate-50"
            >
              上一页
            </button>
            <span className="text-xs text-slate-500">{page}/{pages}</span>
            <button
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page >= pages}
              className="px-2.5 py-1 text-xs border border-slate-300 rounded disabled:opacity-40 hover:bg-slate-50"
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================
// 数据预览 Tab
// ============================================================

function PreviewTab({ tableId }: { tableId: number }) {
  const [preview, setPreview] = useState<DwPreviewData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const handleLoadPreview = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getDwPreview(tableId, { limit: 20 });
      setPreview(data);
      setLoaded(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '预览加载失败');
    } finally {
      setLoading(false);
    }
  };

  if (!loaded && !loading) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <i className="ri-eye-line text-3xl text-slate-300 mb-3"></i>
        <p className="text-sm text-slate-500 mb-4">数据预览需手动加载，不会自动请求</p>
        <button
          onClick={handleLoadPreview}
          className="px-4 py-2 text-sm bg-blue-700 text-white rounded-md hover:bg-blue-800"
        >
          加载预览
        </button>
      </div>
    );
  }

  if (loading) {
    return <div className="py-8 text-center text-slate-500"><i className="ri-loader-4-line animate-spin mr-2"></i>加载中...</div>;
  }

  if (error) {
    return (
      <div className="flex flex-col items-center py-8">
        <p className="text-red-500 text-sm mb-3">{error}</p>
        <button onClick={handleLoadPreview} className="px-3 py-1.5 text-sm border border-slate-300 rounded-md hover:bg-slate-50">
          重试
        </button>
      </div>
    );
  }

  if (!preview) return null;

  return (
    <div>
      {/* 脱敏提示 */}
      {preview.masked_columns.length > 0 && (
        <div className="mb-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-md text-xs text-amber-700">
          <i className="ri-shield-line mr-1"></i>
          以下敏感字段已隐藏：{preview.masked_columns.join('、')}
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-lg overflow-x-auto">
        <table className="w-full text-xs border-collapse table-fixed">
          <thead>
            <tr className="bg-slate-50">
              {preview.columns.map((col) => (
                <th key={col.name} className="border border-slate-200 text-left px-3 py-2 font-medium text-slate-600 whitespace-nowrap">
                  {col.name}
                  <span className="ml-1 text-slate-400 font-normal">{col.data_type}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, idx) => (
              <tr key={idx} className="hover:bg-slate-50">
                {preview.columns.map((col) => (
                  <td key={col.name} className="border border-slate-200 px-3 py-2 text-slate-700 whitespace-nowrap max-w-[200px] truncate">
                    {row[col.name] === null ? <span className="text-slate-300">NULL</span> : String(row[col.name])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-2 text-xs text-slate-400">
        显示 {preview.rows.length} 行 {preview.truncated ? '（已截断）' : ''}
      </div>
    </div>
  );
}

// ============================================================
// 分区信息 Tab
// ============================================================

function PartitionsTab({ tableId }: { tableId: number }) {
  const [partitions, setPartitions] = useState<DwAssetPartition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(0);

  const fetchPartitions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listDwPartitions(tableId, { page, page_size: 50 });
      setPartitions(res.items);
      setTotal(res.total);
      setPages(res.pages);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [tableId, page]);

  useEffect(() => { fetchPartitions(); }, [fetchPartitions]);

  if (loading) {
    return <div className="py-8 text-center text-slate-500"><i className="ri-loader-4-line animate-spin mr-2"></i>加载中...</div>;
  }
  if (error) {
    return <div className="py-8 text-center text-red-500">{error}</div>;
  }
  if (partitions.length === 0) {
    return (
      <div className="py-8 text-center text-slate-400">
        <i className="ri-layout-grid-line text-3xl text-slate-300 mb-2 block"></i>
        该表暂无分区信息
      </div>
    );
  }

  return (
    <div>
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="text-left px-4 py-2.5 font-medium text-slate-600">分区名</th>
              <th className="text-left px-4 py-2.5 font-medium text-slate-600">分区值</th>
              <th className="text-right px-4 py-2.5 font-medium text-slate-600">行数</th>
              <th className="text-right px-4 py-2.5 font-medium text-slate-600">存储</th>
              <th className="text-left px-4 py-2.5 font-medium text-slate-600">版本</th>
              <th className="text-left px-4 py-2.5 font-medium text-slate-600">更新时间</th>
            </tr>
          </thead>
          <tbody>
            {partitions.map((p) => (
              <tr key={p.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                <td className="px-4 py-2.5 font-mono text-xs text-slate-900">{p.partition_name}</td>
                <td className="px-4 py-2.5 text-xs text-slate-600">{p.partition_value || '-'}</td>
                <td className="px-4 py-2.5 text-xs text-slate-600 text-right">{formatRowCount(p.row_count_estimate)}</td>
                <td className="px-4 py-2.5 text-xs text-slate-600 text-right">{formatBytes(p.storage_bytes)}</td>
                <td className="px-4 py-2.5 text-xs text-slate-500">{p.visible_version || '-'}</td>
                <td className="px-4 py-2.5 text-xs text-slate-400">{p.updated_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <span className="text-xs text-slate-500">共 {total} 个分区</span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-2.5 py-1 text-xs border border-slate-300 rounded disabled:opacity-40"
            >
              上一页
            </button>
            <span className="text-xs text-slate-500">{page}/{pages}</span>
            <button
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page >= pages}
              className="px-2.5 py-1 text-xs border border-slate-300 rounded disabled:opacity-40"
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================
// 血缘拓扑 Tab (Phase 1: 列表视图)
// ============================================================

function LineageTab({ tableId }: { tableId: number }) {
  const [lineage, setLineage] = useState<DwLineageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [depth, setDepth] = useState(1);
  const [direction, setDirection] = useState<'both' | 'upstream' | 'downstream'>('both');

  const fetchLineage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getDwLineage(tableId, { depth, direction });
      setLineage(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [tableId, depth, direction]);

  useEffect(() => { fetchLineage(); }, [fetchLineage]);

  if (loading) {
    return <div className="py-8 text-center text-slate-500"><i className="ri-loader-4-line animate-spin mr-2"></i>加载中...</div>;
  }
  if (error) {
    return <div className="py-8 text-center text-red-500">{error}</div>;
  }
  if (!lineage || (lineage.nodes.length <= 1 && lineage.edges.length === 0)) {
    return (
      <div className="py-12 flex flex-col items-center">
        <i className="ri-git-merge-line text-4xl text-slate-300 mb-3"></i>
        <p className="text-slate-500 text-sm mb-1">暂无血缘关系</p>
        <p className="text-xs text-slate-400 mb-4">SQL 解析器未检测到上下游依赖，可能是视图、手工表或新增表</p>
        <div className="flex items-center gap-3">
          <a
            href="mailto:?subject=手工添加血缘&body=请补充此表的上下游来源"
            className="px-4 py-2 text-sm bg-blue-700 text-white rounded-md hover:bg-blue-800 flex items-center gap-1.5"
          >
            <i className="ri-add-line"></i>
            手工添加血缘
          </a>
          <span className="text-xs text-slate-400">或让 AI 根据命名规范推断</span>
        </div>
      </div>
    );
  }

  const centerNode = lineage.nodes.find((n) => n.id === lineage.center);
  const upstreamEdges = lineage.edges.filter((e) => e.target === lineage.center);
  const downstreamEdges = lineage.edges.filter((e) => e.source === lineage.center);

  const getNodeById = (id: string) => lineage.nodes.find((n) => n.id === id);

  return (
    <div>
      {/* 控件 */}
      <div className="flex items-center gap-4 mb-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">层级：</span>
          {[1, 2, 3].map((d) => (
            <button
              key={d}
              onClick={() => setDepth(d)}
              className={`px-2 py-0.5 text-xs rounded ${depth === d ? 'bg-blue-700 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
            >
              {d}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">方向：</span>
          {([['both', '全部'], ['upstream', '上游'], ['downstream', '下游']] as const).map(([val, label]) => (
            <button
              key={val}
              onClick={() => setDirection(val)}
              className={`px-2 py-0.5 text-xs rounded ${direction === val ? 'bg-blue-700 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* 血缘列表视图 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* 上游 */}
        <div>
          <h3 className="text-xs font-medium text-slate-500 mb-2 uppercase">上游 ({upstreamEdges.length})</h3>
          <div className="space-y-2">
            {upstreamEdges.map((edge) => {
              const node = getNodeById(edge.source);
              if (!node) return null;
              return (
                <Link
                  key={edge.id}
                  to={`/assets/dw/${node.table_id}`}
                  className="block bg-white border border-slate-200 rounded-lg p-3 hover:border-blue-300 transition-colors"
                >
                  <div className="text-sm font-medium text-slate-900">{node.label}</div>
                  <div className="flex items-center gap-2 mt-1 text-xs text-slate-500">
                    {node.layer && <span className="uppercase">{node.layer}</span>}
                    <span>热度 {Math.round(node.heat_score)}</span>
                    <span className="text-slate-300">|</span>
                    <span>{edge.relation_type}</span>
                    {edge.confidence < 0.7 && (
                      <span className="text-amber-500">待确认</span>
                    )}
                  </div>
                </Link>
              );
            })}
            {upstreamEdges.length === 0 && (
              <p className="text-xs text-slate-400 py-2">无上游依赖</p>
            )}
          </div>
        </div>

        {/* 中心 */}
        <div className="flex items-center justify-center">
          {centerNode && (
            <div className="bg-blue-50 border-2 border-blue-700 rounded-lg p-4 text-center">
              <div className="text-sm font-semibold text-blue-700">{centerNode.label}</div>
              <div className="text-xs text-blue-500 mt-1">
                {centerNode.layer && <span className="uppercase">{centerNode.layer}</span>}
                {' '}热度 {Math.round(centerNode.heat_score)}
              </div>
            </div>
          )}
        </div>

        {/* 下游 */}
        <div>
          <h3 className="text-xs font-medium text-slate-500 mb-2 uppercase">下游 ({downstreamEdges.length})</h3>
          <div className="space-y-2">
            {downstreamEdges.map((edge) => {
              const node = getNodeById(edge.target);
              if (!node) return null;
              return (
                <Link
                  key={edge.id}
                  to={`/assets/dw/${node.table_id}`}
                  className="block bg-white border border-slate-200 rounded-lg p-3 hover:border-emerald-300 transition-colors"
                >
                  <div className="text-sm font-medium text-slate-900">{node.label}</div>
                  <div className="flex items-center gap-2 mt-1 text-xs text-slate-500">
                    {node.layer && <span className="uppercase">{node.layer}</span>}
                    <span>热度 {Math.round(node.heat_score)}</span>
                    <span className="text-slate-300">|</span>
                    <span>{edge.relation_type}</span>
                    {edge.confidence < 0.7 && (
                      <span className="text-amber-500">待确认</span>
                    )}
                  </div>
                </Link>
              );
            })}
            {downstreamEdges.length === 0 && (
              <p className="text-xs text-slate-400 py-2">无下游消费</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
