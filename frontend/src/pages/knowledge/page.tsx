import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import { ConfirmModal } from '../../components/ConfirmModal';
import {
  listDocuments, createDocument, deleteDocument,
  type DocumentItem,
} from '../../api/knowledge';

// ── 常量 ──────────────────────────────────────────────────────────────────────

const DOC_CATEGORIES = [
  { value: 'general',   label: '通用' },
  { value: 'handbook',  label: '品控手册' },
  { value: 'process',   label: '流程规范' },
  { value: 'reference', label: '参考资料' },
];

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  DOC_CATEGORIES.map(c => [c.value, c.label])
);

// ── 工具 ──────────────────────────────────────────────────────────────────────

function fmtDate(s: string | null) {
  if (!s) return '—';
  return s.slice(0, 10);
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active:     'bg-emerald-50 text-emerald-700 border-emerald-200',
    deprecated: 'bg-amber-50 text-amber-700 border-amber-200',
    archived:   'bg-slate-100 text-slate-500 border-slate-200',
  };
  const labels: Record<string, string> = {
    active: '有效', deprecated: '已弃用', archived: '已归档',
  };
  return (
    <span className={`inline-block px-2 py-0.5 text-xs rounded border ${map[status] ?? map.active}`}>
      {labels[status] ?? status}
    </span>
  );
}

// ── 文档新建 Modal ─────────────────────────────────────────────────────────────

interface DocFormState {
  title: string;
  content: string;
  format: string;
  category: string;
  tags: string;
}

function DocumentModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<DocFormState>({
    title: '', content: '', format: 'markdown', category: 'general', tags: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const set = (k: keyof DocFormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim() || !form.content.trim()) { setError('标题和内容不能为空'); return; }
    setSaving(true);
    setError('');
    try {
      await createDocument({
        title: form.title.trim(),
        content: form.content.trim(),
        format: form.format,
        category: form.category,
        tags: form.tags ? form.tags.split(',').map(s => s.trim()).filter(Boolean) : [],
      });
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <h2 className="text-base font-semibold text-slate-800">新建文档</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><i className="ri-close-line text-xl" /></button>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-slate-600 mb-1">标题 *</label>
              <input value={form.title} onChange={set('title')} placeholder="文档标题"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">分类</label>
              <select value={form.category} onChange={set('category')}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white">
                {DOC_CATEGORIES.map(c => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">格式</label>
              <select value={form.format} onChange={set('format')}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white">
                <option value="markdown">Markdown</option>
                <option value="text">纯文本</option>
              </select>
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-medium text-slate-600 mb-1">标签（逗号分隔）</label>
              <input value={form.tags} onChange={set('tags')}
                placeholder="如：BI, 规范" className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">内容 *</label>
            <textarea value={form.content} onChange={set('content')} rows={10}
              placeholder="在此输入文档内容..." className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none font-mono" />
          </div>
          {error && <p className="text-sm text-red-500">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose}
              className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800">取消</button>
            <button type="submit" disabled={saving}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── 主页面 ─────────────────────────────────────────────────────────────────────

export default function KnowledgePage() {
  const { user } = useAuth();
  const [items, setItems] = useState<DocumentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState('');
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null);

  const PAGE_SIZE = 20;

  const roleRank: Record<string, number> = { user: 0, analyst: 1, data_admin: 2, admin: 3 };
  const canWrite = (roleRank[user?.role ?? 'user'] ?? 0) >= 2;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listDocuments({ page, page_size: PAGE_SIZE, category: category || undefined });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
    }
  }, [page, category]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete() {
    if (!deleteTarget) return;
    await deleteDocument(deleteTarget.id);
    setDeleteTarget(null);
    load();
  }

  return (
    <div className="p-6">
      {/* 筛选栏 */}
      <div className="flex items-center gap-3 mb-4">
        <select value={category} onChange={e => { setCategory(e.target.value); setPage(1); }}
          className="border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">全部分类</option>
          {DOC_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
        {canWrite && (
          <button onClick={() => setShowCreate(true)}
            className="ml-auto flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
            <i className="ri-add-line" />新建文档
          </button>
        )}
      </div>

      {/* 表格 */}
      <div className="border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-slate-600">标题</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">分类</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">格式</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">向量块数</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">状态</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">更新时间</th>
              {canWrite && <th className="px-4 py-3" />}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td colSpan={canWrite ? 7 : 6} className="px-4 py-8 text-center text-slate-400">加载中…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={canWrite ? 7 : 6} className="px-4 py-8 text-center text-slate-400">暂无文档</td></tr>
            ) : items.map(item => (
              <tr key={item.id} className="hover:bg-slate-50">
                <td className="px-4 py-3 font-medium text-slate-800">{item.title}</td>
                <td className="px-4 py-3 text-slate-500">{CATEGORY_LABEL[item.category] ?? item.category}</td>
                <td className="px-4 py-3 text-slate-500 uppercase text-xs">{item.format}</td>
                <td className="px-4 py-3 text-slate-500">{item.chunk_count > 0 ? item.chunk_count : '—'}</td>
                <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
                <td className="px-4 py-3 text-slate-400">{fmtDate(item.updated_at)}</td>
                {canWrite && (
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => setDeleteTarget(item)}
                      className="text-slate-400 hover:text-red-500 transition-colors">
                      <i className="ri-delete-bin-line" />
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 分页 */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between mt-4 text-sm text-slate-500">
          <span>共 {total} 条</span>
          <div className="flex gap-2">
            <button disabled={page === 1} onClick={() => setPage(p => p - 1)}
              className="px-3 py-1 border border-slate-200 rounded-lg disabled:opacity-40 hover:bg-slate-50">上一页</button>
            <span className="px-3 py-1">第 {page} / {Math.ceil(total / PAGE_SIZE)} 页</span>
            <button disabled={page >= Math.ceil(total / PAGE_SIZE)} onClick={() => setPage(p => p + 1)}
              className="px-3 py-1 border border-slate-200 rounded-lg disabled:opacity-40 hover:bg-slate-50">下一页</button>
          </div>
        </div>
      )}

      {showCreate && (
        <DocumentModal onClose={() => setShowCreate(false)} onSaved={() => { setShowCreate(false); load(); }} />
      )}
      {deleteTarget && (
        <ConfirmModal
          open
          title="删除文档"
          message={`确定要归档文档「${deleteTarget.title}」吗？`}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
