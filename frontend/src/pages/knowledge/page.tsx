import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import { ConfirmModal } from '../../components/ConfirmModal';
import {
  listDocuments, createDocument, deleteDocument,
  searchKnowledge, listGlossary, createGlossary, deleteGlossary,
  type DocumentItem, type GlossaryItem,
} from '../../api/knowledge';

// ── 常量 ──────────────────────────────────────────────────────────────────────

const DOC_CATEGORIES = [
  { value: 'general',         label: '通用' },
  { value: 'business_rule',   label: '业务规则' },
  { value: 'data_dictionary', label: '数据字典' },
  { value: 'methodology',     label: '方法论' },
  { value: 'faq',             label: '常见问题' },
];

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  DOC_CATEGORIES.map(c => [c.value, c.label])
);

const GLOSSARY_CATEGORIES = [
  { value: 'concept',  label: '概念' },
  { value: 'metric',   label: '指标' },
  { value: 'entity',   label: '实体' },
  { value: 'formula',  label: '公式' },
];

// ── 工具组件 ───────────────────────────────────────────────────────────────────

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
  const labels: Record<string, string> = { active: '有效', deprecated: '已弃用', archived: '已归档' };
  return (
    <span className={`inline-block px-2 py-0.5 text-[11px] rounded border ${map[status] ?? map.active}`}>
      {labels[status] ?? status}
    </span>
  );
}

// ── 文档新建 Modal ─────────────────────────────────────────────────────────────

interface DocFormState { title: string; content: string; format: string; category: string; tags: string; }

function DocumentModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<DocFormState>({ title: '', content: '', format: 'markdown', category: 'general', tags: '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const set = (k: keyof DocFormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim() || !form.content.trim()) { setError('标题和内容不能为空'); return; }
    setSaving(true); setError('');
    try {
      await createDocument({ title: form.title.trim(), content: form.content.trim(), format: form.format, category: form.category, tags: form.tags ? form.tags.split(',').map(s => s.trim()).filter(Boolean) : [] });
      onSaved();
    } catch (err: unknown) { setError(err instanceof Error ? err.message : '保存失败'); }
    finally { setSaving(false); }
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
              <label className="block text-[12px] font-medium text-slate-600 mb-1">标题 *</label>
              <input value={form.title} onChange={set('title')} placeholder="文档标题"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">分类</label>
              <select value={form.category} onChange={set('category')}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                {DOC_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">格式</label>
              <select value={form.format} onChange={set('format')}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="markdown">Markdown</option>
                <option value="text">纯文本</option>
              </select>
            </div>
            <div className="col-span-2">
              <label className="block text-[12px] font-medium text-slate-600 mb-1">标签（逗号分隔）</label>
              <input value={form.tags} onChange={set('tags')} placeholder="如：BI, 规范"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">内容 *</label>
            <textarea value={form.content} onChange={set('content')} rows={10} placeholder="在此输入文档内容…"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none font-mono" />
          </div>
          {error && <p className="text-[12px] text-red-500">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-[12px] text-slate-600 hover:text-slate-800">取消</button>
            <button type="submit" disabled={saving}
              className="px-4 py-2 text-[12px] bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── 术语新建 Modal ─────────────────────────────────────────────────────────────

interface GlossaryForm { term: string; canonical_term: string; definition: string; category: string; synonyms: string; formula: string; }

function GlossaryModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<GlossaryForm>({ term: '', canonical_term: '', definition: '', category: 'concept', synonyms: '', formula: '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const set = (k: keyof GlossaryForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.term.trim() || !form.canonical_term.trim() || !form.definition.trim()) {
      setError('术语名称、标准名称、定义不能为空'); return;
    }
    setSaving(true); setError('');
    try {
      await createGlossary({
        term: form.term.trim(),
        canonical_term: form.canonical_term.trim(),
        definition: form.definition.trim(),
        category: form.category,
        synonyms: form.synonyms ? form.synonyms.split(',').map(s => s.trim()).filter(Boolean) : [],
        formula: form.formula.trim() || undefined,
      });
      onSaved();
    } catch (err: unknown) { setError(err instanceof Error ? err.message : '创建失败'); }
    finally { setSaving(false); }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <h2 className="text-base font-semibold text-slate-800">新建术语</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><i className="ri-close-line text-xl" /></button>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">术语名称 *</label>
              <input value={form.term} onChange={set('term')} placeholder="原始术语"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">标准名称 *</label>
              <input value={form.canonical_term} onChange={set('canonical_term')} placeholder="规范化名称"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">分类</label>
              <select value={form.category} onChange={set('category')}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                {GLOSSARY_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">同义词（逗号分隔）</label>
              <input value={form.synonyms} onChange={set('synonyms')} placeholder="如：成交额, GMV"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">定义 *</label>
            <textarea value={form.definition} onChange={set('definition')} rows={3} placeholder="清晰描述该术语的业务含义"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
          </div>
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">计算公式（可选）</label>
            <input value={form.formula} onChange={set('formula')} placeholder="如：GMV = 成交笔数 × 客单价"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          {error && <p className="text-[12px] text-red-500">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-[12px] text-slate-600 hover:text-slate-800">取消</button>
            <button type="submit" disabled={saving}
              className="px-4 py-2 text-[12px] bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
              {saving ? '创建中…' : '创建术语'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── 文档列表 Tab ───────────────────────────────────────────────────────────────

const PAGE_SIZE = 20;

function DocumentsTab({ canWrite }: { canWrite: boolean }) {
  const [items, setItems] = useState<DocumentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState('');
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listDocuments({ page, page_size: PAGE_SIZE, category: category || undefined });
      setItems(res.items); setTotal(res.total);
    } catch { /* keep stale */ }
    finally { setLoading(false); }
  }, [page, category]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete() {
    if (!deleteTarget) return;
    await deleteDocument(deleteTarget.id);
    setDeleteTarget(null); load();
  }

  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <select value={category} onChange={e => { setCategory(e.target.value); setPage(1); }}
          className="border border-slate-200 rounded-lg px-3 py-1.5 text-[13px] bg-white focus:outline-none focus:border-slate-400">
          <option value="">全部分类</option>
          {DOC_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
        {canWrite && (
          <button onClick={() => setShowCreate(true)}
            className="ml-auto flex items-center gap-1.5 px-3.5 py-1.5 bg-blue-600 text-white text-[12px] font-medium rounded-lg hover:bg-blue-700">
            <i className="ri-add-line" />新建文档
          </button>
        )}
      </div>

      {loading ? (
        <div className="text-center py-20 text-slate-400 text-[13px]">加载中…</div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20">
          <i className="ri-book-open-line text-4xl text-slate-300 mb-3" />
          <p className="text-slate-400 text-[13px] mb-4">暂无文档</p>
          {canWrite && <button onClick={() => setShowCreate(true)} className="px-4 py-2 bg-blue-600 text-white text-[12px] rounded-lg hover:bg-blue-700">新建文档</button>}
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                {['标题', '分类', '格式', '向量块数', '状态', '更新时间'].map(h => (
                  <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">{h}</th>
                ))}
                {canWrite && <th className="px-4 py-3" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map(item => (
                <tr key={item.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-[12px] font-medium text-slate-800">{item.title}</td>
                  <td className="px-4 py-3 text-[12px] text-slate-500">{CATEGORY_LABEL[item.category] ?? item.category}</td>
                  <td className="px-4 py-3 text-[11px] text-slate-500 uppercase">{item.format}</td>
                  <td className="px-4 py-3 text-[12px] text-slate-500">{item.chunk_count > 0 ? item.chunk_count : '—'}</td>
                  <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
                  <td className="px-4 py-3 text-[12px] text-slate-400">{fmtDate(item.updated_at)}</td>
                  {canWrite && (
                    <td className="px-4 py-3 text-right">
                      <button onClick={() => setDeleteTarget(item)} className="text-slate-400 hover:text-red-500">
                        <i className="ri-delete-bin-line" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-center gap-2 mt-4">
          <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
            className="w-8 h-8 flex items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40">
            <i className="ri-arrow-left-s-line" />
          </button>
          <span className="text-[12px] text-slate-500">{page} / {totalPages}</span>
          <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
            className="w-8 h-8 flex items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40">
            <i className="ri-arrow-right-s-line" />
          </button>
        </div>
      )}

      {showCreate && <DocumentModal onClose={() => setShowCreate(false)} onSaved={() => { setShowCreate(false); load(); }} />}
      {deleteTarget && (
        <ConfirmModal open title="删除文档" message={`确定要归档文档「${deleteTarget.title}」吗？`}
          onConfirm={handleDelete} onCancel={() => setDeleteTarget(null)} />
      )}
    </div>
  );
}

// ── 语义检索 Tab ───────────────────────────────────────────────────────────────

function RagSearchTab() {
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<{ items: { source_type: string; title: string; content_snippet: string; score: number }[]; terms: { term: string; canonical_term: string; definition: string }[] } | null>(null);
  const [error, setError] = useState('');

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true); setError(''); setResults(null);
    try {
      const res = await searchKnowledge(query.trim());
      setResults({ items: res.results, terms: res.terms });
    } catch (err: unknown) { setError(err instanceof Error ? err.message : '检索失败'); }
    finally { setSearching(false); }
  }

  const SOURCE_LABELS: Record<string, string> = { document: '文档', glossary: '术语', schema: '表结构', field_semantic: '字段语义' };

  return (
    <div className="space-y-5">
      <form onSubmit={handleSearch} className="flex gap-3">
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder={'输入业务问题或关键词，如"订单转化率如何定义"'}
          className="flex-1 border border-slate-200 rounded-lg px-4 py-2.5 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button type="submit" disabled={searching || !query.trim()}
          className="px-5 py-2.5 bg-blue-600 text-white text-[13px] font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2">
          <i className="ri-search-line" />{searching ? '检索中…' : '语义检索'}
        </button>
      </form>

      {error && <div className="text-[12px] text-red-500 bg-red-50 border border-red-200 rounded-lg px-4 py-3">{error}</div>}

      {results && (
        <div className="space-y-4">
          {results.terms.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-2">精确匹配术语</p>
              <div className="flex flex-wrap gap-2">
                {results.terms.map((t, i) => (
                  <div key={i} className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2">
                    <span className="text-[12px] font-medium text-blue-800">{t.term}</span>
                    <span className="text-[11px] text-blue-500 ml-1.5">→ {t.canonical_term}</span>
                    {t.definition && <p className="text-[11px] text-blue-700 mt-0.5">{t.definition}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}
          {results.items.length > 0 ? (
            <div>
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-2">向量相似结果（{results.items.length} 条）</p>
              <div className="space-y-2">
                {results.items.map((item, i) => (
                  <div key={i} className="bg-white border border-slate-200 rounded-xl px-4 py-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[12px] font-medium text-slate-800">{item.title}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-slate-400">{SOURCE_LABELS[item.source_type] ?? item.source_type}</span>
                        <span className="text-[11px] font-mono text-blue-600">{(item.score * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                    {item.content_snippet && <p className="text-[12px] text-slate-500 line-clamp-2">{item.content_snippet}</p>}
                  </div>
                ))}
              </div>
            </div>
          ) : results.terms.length === 0 ? (
            <div className="text-center py-12 text-slate-400 text-[13px]">
              <i className="ri-search-line text-3xl mb-2 block" />未找到相关结果，尝试调整关键词
            </div>
          ) : null}
        </div>
      )}

      {!results && !searching && (
        <div className="text-center py-16 text-slate-300">
          <i className="ri-search-eye-line text-5xl mb-3 block" />
          <p className="text-[13px] text-slate-400">输入问题，搜索知识库中的相关内容</p>
        </div>
      )}
    </div>
  );
}

// ── 术语表 Tab ─────────────────────────────────────────────────────────────────

function GlossaryTab({ canWrite }: { canWrite: boolean }) {
  const [items, setItems] = useState<GlossaryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<GlossaryItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listGlossary({ keyword: keyword || undefined, page_size: 50 });
      setItems(res.items ?? []); setTotal(res.total ?? 0);
    } catch { /* keep stale */ }
    finally { setLoading(false); }
  }, [keyword]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete() {
    if (!deleteTarget) return;
    await deleteGlossary(deleteTarget.id);
    setDeleteTarget(null); load();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <input value={keyword} onChange={e => setKeyword(e.target.value)} placeholder="搜索术语…"
          className="border border-slate-200 rounded-lg px-3 py-1.5 text-[13px] focus:outline-none focus:border-slate-400 w-56" />
        <span className="text-[12px] text-slate-400">共 {total} 条</span>
        {canWrite && (
          <button onClick={() => setShowCreate(true)}
            className="ml-auto flex items-center gap-1.5 px-3.5 py-1.5 bg-blue-600 text-white text-[12px] font-medium rounded-lg hover:bg-blue-700">
            <i className="ri-add-line" />新建术语
          </button>
        )}
      </div>

      {loading ? (
        <div className="text-center py-16 text-slate-400 text-[13px]">加载中…</div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <i className="ri-book-2-line text-4xl text-slate-300 mb-3" />
          <p className="text-slate-400 text-[13px] mb-4">暂无术语</p>
          {canWrite && <button onClick={() => setShowCreate(true)} className="px-4 py-2 bg-blue-600 text-white text-[12px] rounded-lg hover:bg-blue-700">新建术语</button>}
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                {['术语', '标准名称', '分类', '定义', '同义词', '创建时间'].map(h => (
                  <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">{h}</th>
                ))}
                {canWrite && <th className="px-4 py-3" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map(item => (
                <tr key={item.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-[12px] font-medium text-slate-800">{item.term}</td>
                  <td className="px-4 py-3 text-[12px] text-blue-700 font-medium">{item.canonical_term}</td>
                  <td className="px-4 py-3 text-[11px] text-slate-500">{GLOSSARY_CATEGORIES.find(c => c.value === item.category)?.label ?? item.category}</td>
                  <td className="px-4 py-3 text-[12px] text-slate-600 max-w-xs truncate" title={item.definition}>{item.definition}</td>
                  <td className="px-4 py-3 text-[11px] text-slate-400">{item.synonyms?.length > 0 ? item.synonyms.join('、') : '—'}</td>
                  <td className="px-4 py-3 text-[12px] text-slate-400">{fmtDate(item.created_at)}</td>
                  {canWrite && (
                    <td className="px-4 py-3 text-right">
                      <button onClick={() => setDeleteTarget(item)} className="text-slate-400 hover:text-red-500">
                        <i className="ri-delete-bin-line" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && <GlossaryModal onClose={() => setShowCreate(false)} onSaved={() => { setShowCreate(false); load(); }} />}
      {deleteTarget && (
        <ConfirmModal open title="删除术语" message={`确定删除术语「${deleteTarget.term}」吗？`}
          onConfirm={handleDelete} onCancel={() => setDeleteTarget(null)} />
      )}
    </div>
  );
}

// ── 主页面 ─────────────────────────────────────────────────────────────────────

type TabId = 'docs' | 'rag' | 'glossary';

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: 'docs',     label: '文档库',   icon: 'ri-file-list-3-line' },
  { id: 'rag',      label: '语义检索', icon: 'ri-search-eye-line' },
  { id: 'glossary', label: '术语表',   icon: 'ri-book-2-line' },
];

export default function KnowledgePage() {
  const { user } = useAuth();
  const roleRank: Record<string, number> = { user: 0, analyst: 1, data_admin: 2, admin: 3 };
  const canWrite = (roleRank[user?.role ?? 'user'] ?? 0) >= 2;
  const [activeTab, setActiveTab] = useState<TabId>('docs');

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 页头 */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-book-open-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">知识库</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">管理业务知识文档与术语，为 NL→SQL 提供语义上下文</p>
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto">
          {/* Tabs */}
          <div className="flex border-b border-slate-200 mb-6">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-5 py-2.5 text-[13px] font-medium border-b-2 -mb-px transition-colors ${
                  activeTab === tab.id
                    ? 'border-blue-600 text-blue-700'
                    : 'border-transparent text-slate-500 hover:text-slate-700'
                }`}
              >
                <i className={tab.icon} />{tab.label}
              </button>
            ))}
          </div>

          {activeTab === 'docs'     && <DocumentsTab canWrite={canWrite} />}
          {activeTab === 'rag'      && <RagSearchTab />}
          {activeTab === 'glossary' && <GlossaryTab canWrite={canWrite} />}
        </div>
      </div>
    </div>
  );
}
