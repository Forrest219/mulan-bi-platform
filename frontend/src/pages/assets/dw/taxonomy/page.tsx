/**
 * 主题域层级配置 — /assets/dw/taxonomy
 *
 * 仅 admin / data_admin 可访问。
 * 管理 L1（业务板块）和 L2（业务过程）的两级架构。
 *
 * 后端 API：
 *   GET    /api/assets/dw/domain-taxonomy       → { items: TaxonomyItem[] }
 *   POST   /api/assets/dw/domain-taxonomy       → TaxonomyItem
 *   DELETE /api/assets/dw/domain-taxonomy/:id  → { message }
 */
import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../../../context/AuthContext';
import { ConfirmModal } from '../../../../components/ConfirmModal';
import {
  listDwDomainTaxonomy,
  createDwDomainTaxonomy,
  deleteDwDomainTaxonomy,
  DwDomainTaxonomyItem,
} from '../../../../api/dwAssets';

// ─── Types ────────────────────────────────────────────────────────────────────

interface TaxonomyGroup {
  l1: string;
  description?: string | null;
  children: DwDomainTaxonomyItem[]; // l2 items under this L1
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function buildGroups(items: DwDomainTaxonomyItem[]): TaxonomyGroup[] {
  const map = new Map<string, TaxonomyGroup>();
  for (const item of items) {
    if (!map.has(item.l1)) {
      map.set(item.l1, { l1: item.l1, children: [] });
    }
    if (item.l2) {
      map.get(item.l1)!.children.push(item);
    } else if (item.description) {
      map.get(item.l1)!.description = item.description;
    }
  }
  // Sort children by display_order
  for (const g of map.values()) {
    g.children.sort((a, b) => a.display_order - b.display_order);
  }
  return Array.from(map.values()).sort((a, b) => a.l1.localeCompare(b.l1));
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function DwTaxonomyPage() {
  const { user } = useAuth();
  const [groups, setGroups] = useState<TaxonomyGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Add form state
  const [newL1, setNewL1] = useState('');
  const [newL2, setNewL2] = useState('');
  const [addingL2For, setAddingL2For] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Delete modal
  const [deletingItem, setDeletingItem] = useState<DwDomainTaxonomyItem | null>(null);

  const isAdmin = user?.role === 'admin' || user?.role === 'data_admin';

  const fetch_ = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listDwDomainTaxonomy();
      setGroups(buildGroups(res.items));
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetch_(); }, []);

  const handleAddL1 = async () => {
    if (!newL1.trim()) return;
    setSaving(true);
    try {
      await createDwDomainTaxonomy({ l1: newL1.trim(), l2: null });
      setNewL1('');
      await fetch_();
    } catch (e) {
      alert(e instanceof Error ? e.message : '添加失败');
    } finally {
      setSaving(false);
    }
  };

  const handleAddL2 = async (l1: string) => {
    const val = addingL2For === l1 ? newL2.trim() : '';
    if (!val) return;
    setSaving(true);
    try {
      await createDwDomainTaxonomy({ l1, l2: val });
      setNewL2('');
      setAddingL2For(null);
      await fetch_();
    } catch (e) {
      alert(e instanceof Error ? e.message : '添加失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deletingItem) return;
    try {
      await deleteDwDomainTaxonomy(deletingItem.id);
      setDeletingItem(null);
      await fetch_();
    } catch (e) {
      alert(e instanceof Error ? e.message : '删除失败');
    }
  };

  if (!isAdmin) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400">
        <i className="ri-shield-forbid-line text-2xl mr-2" />
        仅管理员可访问
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Page header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-4xl mx-auto">
          <Link to="/assets/dw" className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 mb-1.5 transition-colors">
            <i className="ri-arrow-left-s-line text-sm" />
            返回数仓资产
          </Link>
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-mind-map text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">主题域配置</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">
            定义业务板块（L1）与业务过程（L2）的两级架构，普通用户仅可选择不可修改
          </p>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-8 py-6">
        {/* 新增 L1 */}
        <div className="bg-white border border-slate-200 rounded-lg p-4 mb-6">
          <h3 className="text-sm font-medium text-slate-700 mb-3">新增业务板块（L1）</h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={newL1}
              onChange={(e) => setNewL1(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAddL1()}
              placeholder="例如：营销域"
              className="flex-1 text-sm border border-slate-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={handleAddL1}
              disabled={saving || !newL1.trim()}
              className="px-4 py-2 text-sm bg-blue-700 text-white rounded-md hover:bg-blue-800 disabled:opacity-50"
            >
              添加 L1
            </button>
          </div>
        </div>

        {/* Loading / Error */}
        {loading && (
          <div className="text-center py-12 text-slate-400">
            <i className="ri-loader-4-line animate-spin text-xl mr-1" />
            加载中…
          </div>
        )}

        {error && (
          <div className="text-center py-8 text-red-500 text-sm">{error}</div>
        )}

        {!loading && !error && groups.length === 0 && (
          <div className="text-center py-16 text-slate-400">
            <i className="ri-folder-chart-line text-3xl mb-2 block" />
            暂无配置，请先添加业务板块
          </div>
        )}

        {/* L1 groups */}
        {!loading && !error && groups.map((group) => (
          <div key={group.l1} className="bg-white border border-slate-200 rounded-lg mb-4 overflow-hidden">
            {/* L1 row */}
            <div className="flex items-center justify-between px-4 py-3 bg-slate-50 border-b border-slate-100">
              <div className="flex items-center gap-2 min-w-0">
                <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs font-medium rounded shrink-0">
                  L1
                </span>
                <span className="text-sm font-medium text-slate-800">{group.l1}</span>
                <span className="text-xs text-slate-400 shrink-0">({group.children.length} 个 L2)</span>
                {group.description && (
                  <span className="text-xs text-slate-400 truncate" title={group.description}>
                    — {group.description}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {/* Add L2 */}
                {addingL2For === group.l1 ? (
                  <div className="flex gap-1">
                    <input
                      autoFocus
                      type="text"
                      value={newL2}
                      onChange={(e) => setNewL2(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleAddL2(group.l1);
                        if (e.key === 'Escape') { setAddingL2For(null); setNewL2(''); }
                      }}
                      placeholder="L2 名称"
                      className="w-32 text-sm border border-slate-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                    <button
                      onClick={() => handleAddL2(group.l1)}
                      disabled={saving || !newL2.trim()}
                      className="px-2 py-1 text-xs bg-blue-700 text-white rounded hover:bg-blue-800 disabled:opacity-50"
                    >
                      确认
                    </button>
                    <button
                      onClick={() => { setAddingL2For(null); setNewL2(''); }}
                      className="px-2 py-1 text-xs border border-slate-300 rounded hover:bg-slate-50"
                    >
                      取消
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setAddingL2For(group.l1)}
                    className="px-2.5 py-1 text-xs border border-slate-300 text-slate-600 rounded hover:bg-slate-50 flex items-center gap-1"
                  >
                    <i className="ri-add-line" />
                    添加 L2
                  </button>
                )}
                {/* Delete L1 */}
                <button
                  onClick={() => setDeletingItem({ id: 0, l1: group.l1, l2: null, display_order: 0 })}
                  className="p-1 text-slate-300 hover:text-red-500"
                  title="删除 L1 及所有 L2"
                >
                  <i className="ri-delete-bin-line text-base" />
                </button>
              </div>
            </div>

            {/* L2 children */}
            {group.children.length > 0 ? (
              <div className="divide-y divide-slate-50">
                {group.children.map((child) => (
                  <div key={child.id} className="flex items-center justify-between px-6 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="px-1.5 py-0.5 bg-slate-100 text-slate-500 text-xs rounded">
                        L2
                      </span>
                      <span className="text-sm text-slate-700">{child.l2}</span>
                    </div>
                    <button
                      onClick={() => setDeletingItem(child)}
                      className="p-1 text-slate-300 hover:text-red-500"
                      title="删除"
                    >
                      <i className="ri-close-line text-base" />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="px-6 py-2.5 text-xs text-slate-300 italic">无 L2</div>
            )}
          </div>
        ))}
      </div>

      {/* Delete confirm */}
      <ConfirmModal
        open={!!deletingItem}
        title="确认删除"
        message={
          deletingItem?.l2
            ? `确定要删除「${deletingItem.l1} / ${deletingItem.l2}」吗？`
            : `确定要删除业务板块「${deletingItem?.l1}」及其所有 L2 吗？`
        }
        confirmLabel="删除"
        onConfirm={handleDelete}
        onCancel={() => setDeletingItem(null)}
        variant="danger"
      />
    </div>
  );
}
