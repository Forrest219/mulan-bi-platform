import { useState, useEffect, useCallback, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Placeholder from '@tiptap/extension-placeholder';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useAuth } from '../../context/AuthContext';
import { ConfirmModal } from '../../components/ConfirmModal';
import {
  listDocuments, createDocument, deleteDocument, parseFile,
  searchKnowledge, listGlossary, createGlossary, deleteGlossary, importGlossaryCSV,
  type DocumentItem, type GlossaryItem,
} from '../../api/knowledge';
import { listMetrics, type MetricItem } from '../../api/metrics';
import { listDataSources } from '../../api/datasources';
import { searchAssets } from '../../api/tableau';

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

// ── 格式 / 类型 配置 ────────────────────────────────────────────────────────────

type DocFormat = 'markdown' | 'text' | 'json' | 'sql' | 'richtext';
type DocType   = 'general' | 'business_term' | 'calculation' | 'guide' | 'faq';

const FORMAT_OPTIONS: { value: DocFormat; label: string; icon: string }[] = [
  { value: 'markdown', label: 'Markdown',  icon: 'ri-markdown-line' },
  { value: 'text',     label: '纯文本',    icon: 'ri-article-line' },
  { value: 'json',     label: 'JSON',      icon: 'ri-braces-line' },
  { value: 'sql',      label: 'SQL',       icon: 'ri-database-2-line' },
  { value: 'richtext', label: '富文本',    icon: 'ri-text' },
];

const DOC_TYPE_OPTIONS: { value: DocType; label: string; icon: string }[] = [
  { value: 'general',       label: '通用',     icon: 'ri-file-2-line' },
  { value: 'business_term', label: '业务术语', icon: 'ri-bookmark-line' },
  { value: 'calculation',   label: '计算口径', icon: 'ri-calculator-line' },
  { value: 'guide',         label: '操作指南', icon: 'ri-book-open-line' },
  { value: 'faq',           label: 'FAQ',      icon: 'ri-question-answer-line' },
];

function detectFormat(content: string): DocFormat | null {
  const t = content.trimStart();
  if (/^(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s/i.test(t)) return 'sql';
  if (t.startsWith('[{') || (t.startsWith('{') && t.includes('"') && t.includes(':'))) return 'json';
  return null;
}

// ── 富文本编辑器 ───────────────────────────────────────────────────────────────

function RichTextEditor({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Placeholder.configure({ placeholder: '在此输入富文本内容…' }),
    ],
    content: value || '',
    onUpdate: ({ editor: e }) => onChange(e.getHTML()),
  });

  useEffect(() => {
    if (editor && editor.getHTML() !== value) {
      editor.commands.setContent(value || '');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      {/* toolbar */}
      <div className="flex items-center gap-0.5 px-2 py-1 bg-slate-50 border-b border-slate-200">
        {[
          { action: () => editor?.chain().focus().toggleBold().run(),        icon: 'ri-bold',            title: '加粗' },
          { action: () => editor?.chain().focus().toggleItalic().run(),      icon: 'ri-italic',          title: '斜体' },
          { action: () => editor?.chain().focus().toggleStrike().run(),      icon: 'ri-strikethrough',   title: '删除线' },
          { action: () => editor?.chain().focus().toggleBulletList().run(),  icon: 'ri-list-unordered',  title: '无序列表' },
          { action: () => editor?.chain().focus().toggleOrderedList().run(), icon: 'ri-list-ordered',    title: '有序列表' },
          { action: () => editor?.chain().focus().toggleBlockquote().run(),  icon: 'ri-double-quotes-l', title: '引用' },
          { action: () => editor?.chain().focus().toggleCodeBlock().run(),   icon: 'ri-code-box-line',   title: '代码块' },
        ].map(({ action, icon, title }, i) => (
          <button key={i} type="button" onClick={action}
            className="w-7 h-7 flex items-center justify-center rounded hover:bg-slate-200 text-slate-600">
            <i className={`${icon} text-[13px]`} title={title} />
          </button>
        ))}
      </div>
      <EditorContent
        editor={editor}
        className="min-h-[216px] max-h-[360px] overflow-y-auto px-3 py-2 text-[13px] prose prose-sm prose-slate max-w-none focus:outline-none"
      />
    </div>
  );
}

// ── 代码编辑器（JSON / SQL）────────────────────────────────────────────────────

function CodeEditor({
  format, value, onChange,
}: { format: 'json' | 'sql'; value: string; onChange: (v: string) => void }) {
  const [preview, setPreview] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Tab') {
      e.preventDefault();
      const ta = taRef.current!;
      const start = ta.selectionStart; const end = ta.selectionEnd;
      const next = value.slice(0, start) + '  ' + value.slice(end);
      onChange(next);
      setTimeout(() => ta.setSelectionRange(start + 2, start + 2), 0);
    }
  }

  function handleFormat() {
    if (format !== 'json') return;
    try { onChange(JSON.stringify(JSON.parse(value), null, 2)); } catch { /* ignore */ }
  }

  return (
    <div className="border border-slate-700 rounded-lg overflow-hidden bg-[#1e1e1e]">
      <div className="flex items-center gap-1.5 px-3 py-1.5 bg-[#2d2d2d] border-b border-slate-700">
        <span className="text-[11px] text-slate-400 uppercase tracking-wide font-mono">{format}</span>
        <div className="ml-auto flex items-center gap-1">
          {format === 'json' && (
            <button type="button" onClick={handleFormat}
              className="px-2 py-0.5 text-[11px] text-slate-400 hover:text-white rounded hover:bg-slate-700">
              格式化
            </button>
          )}
          <div className="flex rounded overflow-hidden border border-slate-600">
            {(['编辑', '预览'] as const).map((m, i) => (
              <button key={m} type="button" onClick={() => setPreview(i === 1)}
                className={`px-2.5 py-0.5 text-[11px] font-medium border-r last:border-r-0 border-slate-600 transition-colors ${preview === (i === 1) ? 'bg-slate-200 text-slate-900' : 'text-slate-400 hover:text-white'}`}>
                {m}
              </button>
            ))}
          </div>
        </div>
      </div>
      {preview ? (
        <div className="max-h-[300px] overflow-y-auto">
          <SyntaxHighlighter language={format} style={vscDarkPlus}
            customStyle={{ margin: 0, borderRadius: 0, fontSize: 12, background: '#1e1e1e' }}>
            {value || ' '}
          </SyntaxHighlighter>
        </div>
      ) : (
        <textarea
          ref={taRef}
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={10}
          spellCheck={false}
          placeholder={format === 'json' ? '{ "key": "value" }' : 'SELECT * FROM table WHERE ...'}
          className="w-full bg-[#1e1e1e] text-[#d4d4d4] px-4 py-3 text-[12px] font-mono resize-none focus:outline-none placeholder:text-slate-600"
        />
      )}
    </div>
  );
}

// ── 资产 + 文档新建 Modal ──────────────────────────────────────────────────────

type AssetKind = 'tableau' | 'metric' | 'datasource';
interface AssetOption { uid: string; kind: AssetKind; label: string; sublabel: string; icon: string; }
const ASSET_KIND_LABEL: Record<AssetKind, string> = { tableau: 'Tableau', metric: '指标', datasource: '数据表' };

interface DocFormState {
  title: string; content: string;
  format: DocFormat; doc_type: DocType;
  category: string; tags: string;
}

function DocumentModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<DocFormState>({
    title: '', content: '', format: 'markdown', doc_type: 'general', category: 'general', tags: '',
  });
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [error, setError] = useState('');
  const [formatHint, setFormatHint] = useState<DocFormat | null>(null);

  const [linkedAssets, setLinkedAssets] = useState<AssetOption[]>([]);
  const [assetQuery, setAssetQuery] = useState('');
  const [assetOptions, setAssetOptions] = useState<AssetOption[]>([]);
  const [assetLoading, setAssetLoading] = useState(false);
  const [assetOpen, setAssetOpen] = useState(false);
  const assetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [allowRag, setAllowRag] = useState(true);
  const [ragWeight, setRagWeight] = useState<'low' | 'medium' | 'high'>('medium');

  const [fileLoading, setFileLoading] = useState(false);
  const [uploadedFileName, setUploadedFileName] = useState('');
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [editorMode, setEditorMode] = useState<'edit' | 'preview'>('edit');
  const contentRef = useRef<HTMLTextAreaElement>(null);

  const set = (k: keyof DocFormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }));

  const isCodeFormat  = form.format === 'json' || form.format === 'sql';
  const isRichFormat  = form.format === 'richtext';
  const isMdTextFormat = !isCodeFormat && !isRichFormat;

  useEffect(() => {
    if (!assetOpen) return;
    if (assetTimerRef.current) clearTimeout(assetTimerRef.current);
    assetTimerRef.current = setTimeout(async () => {
      setAssetLoading(true);
      const q = assetQuery.toLowerCase();
      try {
        const results: AssetOption[] = [];
        const selectedUids = new Set(linkedAssets.map(a => a.uid));
        const [metricsRes, dsRes, taRes] = await Promise.allSettled([
          listMetrics({ search: assetQuery, page_size: 5 }),
          listDataSources(),
          searchAssets({ q: assetQuery || '*', asset_type: 'dashboard', page_size: 5 }),
        ]);
        if (metricsRes.status === 'fulfilled') {
          metricsRes.value.items.forEach((m: MetricItem) => {
            const uid = `metric:${m.id}`;
            if (!selectedUids.has(uid)) results.push({ uid, kind: 'metric', label: m.name, sublabel: m.metric_type, icon: 'ri-hammer-line' });
          });
        }
        if (dsRes.status === 'fulfilled') {
          dsRes.value.datasources.filter(s => !q || s.name.toLowerCase().includes(q)).slice(0, 5).forEach(s => {
            const uid = `datasource:${s.id}`;
            if (!selectedUids.has(uid)) results.push({ uid, kind: 'datasource', label: s.name, sublabel: s.db_type, icon: 'ri-database-2-line' });
          });
        }
        if (taRes.status === 'fulfilled') {
          taRes.value.assets.forEach(a => {
            const uid = `tableau:${a.id}`;
            if (!selectedUids.has(uid)) results.push({ uid, kind: 'tableau', label: a.name, sublabel: a.project_name ?? 'Tableau', icon: 'ri-bar-chart-box-line' });
          });
        }
        setAssetOptions(results);
      } catch { setAssetOptions([]); }
      finally { setAssetLoading(false); }
    }, 300);
    return () => { if (assetTimerRef.current) clearTimeout(assetTimerRef.current); };
  }, [assetQuery, assetOpen, linkedAssets]);

  async function handleFileSelect(file: File) {
    const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
    if (!['md', 'txt', 'docx'].includes(ext)) { setError('仅支持 .md、.txt、.docx 格式'); return; }
    setFileLoading(true); setError('');
    try {
      let text = ''; let fmt: DocFormat = 'text';
      if (ext === 'docx') {
        const fd = new FormData(); fd.append('file', file);
        const res = await parseFile(fd); text = res.content; fmt = res.format as DocFormat;
      } else {
        text = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = e => resolve(e.target!.result as string);
          reader.onerror = () => reject(new Error('文件读取失败'));
          reader.readAsText(file, 'utf-8');
        });
        fmt = ext === 'md' ? 'markdown' : 'text';
      }
      setForm(f => ({ ...f, content: text, format: fmt }));
      setUploadedFileName(file.name);
    } catch (err: unknown) { setError(err instanceof Error ? err.message : '文件解析失败'); }
    finally { setFileLoading(false); }
  }

  function handleContentChange(val: string) {
    setForm(f => ({ ...f, content: val }));
    if (isMdTextFormat) {
      const hint = detectFormat(val);
      setFormatHint(hint !== form.format ? hint : null);
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const pasted = e.clipboardData.getData('text');
    const hint = detectFormat(pasted);
    if (hint && hint !== form.format) setFormatHint(hint);
  }

  function insertMd(prefix: string, suffix = '') {
    const ta = contentRef.current; if (!ta) return;
    const start = ta.selectionStart; const end = ta.selectionEnd;
    const selected = form.content.slice(start, end) || '文本';
    setForm(f => ({ ...f, content: f.content.slice(0, start) + prefix + selected + suffix + f.content.slice(end) }));
    setTimeout(() => { ta.focus(); ta.setSelectionRange(start + prefix.length, start + prefix.length + selected.length); }, 0);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim() || !form.content.trim()) { setError('标题和内容不能为空'); return; }
    setSaving(true); setError('');
    try {
      await createDocument({
        title: form.title.trim(), content: form.content.trim(), format: form.format,
        doc_type: form.doc_type, category: form.category,
        tags: form.tags ? form.tags.split(',').map(s => s.trim()).filter(Boolean) : [],
        linked_assets: linkedAssets.map(a => ({ uid: a.uid, kind: a.kind, label: a.label })),
        allow_rag: allowRag, rag_weight: ragWeight,
      });
      setSaveSuccess(true);
      setTimeout(onSaved, 800);
    } catch (err: unknown) { setError(err instanceof Error ? err.message : '保存失败'); }
    finally { setSaving(false); }
  }

  const currentFormat = FORMAT_OPTIONS.find(f => f.value === form.format);
  const currentType   = DOC_TYPE_OPTIONS.find(t => t.value === form.doc_type);

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[92vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <h2 className="text-base font-semibold text-slate-800">新建文档</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><i className="ri-close-line text-xl" /></button>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">

          {/* 标题 */}
          <div>
            <label className="flex items-center gap-1 text-[12px] font-medium text-slate-600 mb-1">
              <i className="ri-edit-line text-slate-400" />标题 *
            </label>
            <input value={form.title} onChange={set('title')} placeholder="文档标题"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          {/* 分类 + 格式 + 类型 (三列) */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="flex items-center gap-1 text-[12px] font-medium text-slate-600 mb-1">
                <i className="ri-folder-3-line text-slate-400" />分类
              </label>
              <select value={form.category} onChange={set('category')}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                {DOC_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
            <div>
              <label className="flex items-center gap-1 text-[12px] font-medium text-slate-600 mb-1">
                {currentFormat && <i className={`${currentFormat.icon} text-slate-400`} />}格式
              </label>
              <select value={form.format} onChange={e => { setForm(f => ({ ...f, format: e.target.value as DocFormat })); setFormatHint(null); }}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                {FORMAT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div>
              <label className="flex items-center gap-1 text-[12px] font-medium text-slate-600 mb-1">
                {currentType && <i className={`${currentType.icon} text-slate-400`} />}类型
              </label>
              <select value={form.doc_type} onChange={e => setForm(f => ({ ...f, doc_type: e.target.value as DocType }))}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                {DOC_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
          </div>

          {/* 标签 */}
          <div>
            <label className="flex items-center gap-1 text-[12px] font-medium text-slate-600 mb-1">
              <i className="ri-price-tag-3-line text-slate-400" />标签（逗号分隔）
            </label>
            <input value={form.tags} onChange={set('tags')} placeholder="如：BI, 规范"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          {/* 关联资产 */}
          <div>
            <label className="flex items-center gap-1 text-[12px] font-medium text-slate-600 mb-1">
              <i className="ri-links-line text-slate-400" />关联资产
            </label>
            {linkedAssets.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {linkedAssets.map(asset => (
                  <span key={asset.uid} className="inline-flex items-center gap-1 pl-2 pr-1 py-0.5 bg-slate-100 text-slate-700 text-[11px] rounded-full border border-slate-200">
                    <i className={`${asset.icon} text-slate-500`} />
                    <span>{asset.label}</span>
                    <span className="text-[10px] text-slate-400 bg-slate-200 rounded-full px-1">{ASSET_KIND_LABEL[asset.kind]}</span>
                    <button type="button" onClick={() => setLinkedAssets(prev => prev.filter(a => a.uid !== asset.uid))}
                      className="ml-0.5 text-slate-400 hover:text-red-500"><i className="ri-close-line text-[10px]" /></button>
                  </span>
                ))}
              </div>
            )}
            <div className="relative">
              <input value={assetQuery} onChange={e => setAssetQuery(e.target.value)}
                onFocus={() => setAssetOpen(true)} onBlur={() => setTimeout(() => setAssetOpen(false), 150)}
                placeholder="搜索 Tableau 看板、指标或数据表…"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
              {assetOpen && (
                <div className="mt-1 border border-slate-200 rounded-lg bg-white shadow-md overflow-hidden">
                  {assetLoading ? <div className="px-3 py-3 text-[12px] text-slate-400 text-center">加载中…</div>
                    : assetOptions.length === 0 ? <div className="px-3 py-3 text-[12px] text-slate-400 text-center">无匹配资产</div>
                    : <ul>{assetOptions.map(opt => (
                        <li key={opt.uid}>
                          <button type="button" onMouseDown={() => { setLinkedAssets(prev => [...prev, opt]); setAssetQuery(''); }}
                            className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-slate-50 text-left">
                            <i className={`${opt.icon} text-slate-500 text-[13px]`} />
                            <div className="min-w-0">
                              <div className="text-[12px] text-slate-800 truncate">{opt.label}</div>
                              <div className="text-[11px] text-slate-400 truncate">{opt.sublabel}</div>
                            </div>
                            <span className="ml-auto text-[10px] text-slate-400 bg-slate-100 rounded-full px-1.5 py-0.5 shrink-0">{ASSET_KIND_LABEL[opt.kind]}</span>
                          </button>
                        </li>
                      ))}</ul>}
                </div>
              )}
            </div>
          </div>

          {/* 内容 */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="flex items-center gap-1 text-[12px] font-medium text-slate-600">
                <i className="ri-file-text-line text-slate-400" />内容 *
              </label>
              {isMdTextFormat && (
                <div className="flex rounded-lg overflow-hidden border border-slate-200">
                  {(['edit', 'preview'] as const).map(mode => (
                    <button key={mode} type="button" onClick={() => setEditorMode(mode)}
                      className={`px-2.5 py-0.5 text-[11px] font-medium border-r last:border-r-0 border-slate-200 transition-colors ${editorMode === mode ? 'bg-slate-800 text-white' : 'text-slate-500 hover:bg-slate-50'}`}>
                      {mode === 'edit' ? '编辑' : '预览'}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* 格式自动识别提示 */}
            {formatHint && (
              <div className="mb-2 flex items-center gap-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-[12px] text-amber-700">
                <i className="ri-magic-line" />
                检测到 <strong>{FORMAT_OPTIONS.find(f => f.value === formatHint)?.label}</strong> 格式内容，是否切换？
                <button type="button" onClick={() => { setForm(f => ({ ...f, format: formatHint! })); setFormatHint(null); }}
                  className="ml-auto px-2 py-0.5 bg-amber-600 text-white rounded-md hover:bg-amber-700 text-[11px]">切换</button>
                <button type="button" onClick={() => setFormatHint(null)} className="text-amber-500 hover:text-amber-700"><i className="ri-close-line" /></button>
              </div>
            )}

            {/* 文件上传区（非富文本才显示） */}
            {!isRichFormat && (
              <div onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) handleFileSelect(f); }}
                onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
                onClick={() => !fileLoading && fileInputRef.current?.click()}
                className={`mb-2 cursor-pointer border-2 border-dashed rounded-lg px-4 py-2 flex items-center gap-3 transition-colors select-none ${dragging ? 'border-blue-400 bg-blue-50' : 'border-slate-200 hover:border-slate-300 bg-slate-50/60'}`}>
                {fileLoading
                  ? <><i className="ri-loader-4-line animate-spin text-slate-400" /><span className="text-[12px] text-slate-400">解析中…</span></>
                  : uploadedFileName
                    ? <><i className="ri-file-check-line text-emerald-500" /><span className="text-[12px] text-slate-600 truncate">{uploadedFileName}</span>
                        <button type="button" onClick={e => { e.stopPropagation(); setUploadedFileName(''); setForm(f => ({ ...f, content: '' })); }}
                          className="ml-auto text-[11px] text-slate-400 hover:text-red-400 shrink-0">清除</button></>
                    : <><i className="ri-upload-cloud-2-line text-slate-400 text-lg" />
                        <div><div className="text-[12px] text-slate-500">拖拽文件到此，或<span className="text-blue-500 ml-1">点击选择</span></div>
                        <div className="text-[11px] text-slate-400">.md · .txt · .docx</div></div></>}
                <input ref={fileInputRef} type="file" accept=".md,.txt,.docx" className="hidden"
                  onChange={e => { const f = e.target.files?.[0]; if (f) handleFileSelect(f); e.target.value = ''; }} />
              </div>
            )}

            {/* 代码编辑器 */}
            {isCodeFormat && (
              <CodeEditor format={form.format as 'json' | 'sql'} value={form.content} onChange={handleContentChange} />
            )}

            {/* 富文本编辑器 */}
            {isRichFormat && (
              <RichTextEditor value={form.content} onChange={handleContentChange} />
            )}

            {/* Markdown / 纯文本编辑器 */}
            {isMdTextFormat && editorMode === 'edit' && (
              <>
                <div className="flex items-center gap-0.5 px-2 py-1 bg-slate-50 border border-slate-200 border-b-0 rounded-t-lg">
                  <button type="button" onClick={() => insertMd('**', '**')}
                    className="w-7 h-7 flex items-center justify-center rounded hover:bg-slate-200 text-[12px] font-bold text-slate-600" title="加粗">B</button>
                  <button type="button" onClick={() => insertMd('*', '*')}
                    className="w-7 h-7 flex items-center justify-center rounded hover:bg-slate-200 text-[12px] italic text-slate-600" title="斜体">I</button>
                  <div className="w-px h-4 bg-slate-200 mx-0.5" />
                  <button type="button" onClick={() => insertMd('\n- ', '')}
                    className="w-7 h-7 flex items-center justify-center rounded hover:bg-slate-200 text-slate-600" title="无序列表">
                    <i className="ri-list-unordered text-[13px]" /></button>
                  <button type="button" onClick={() => insertMd('\n1. ', '')}
                    className="w-7 h-7 flex items-center justify-center rounded hover:bg-slate-200 text-slate-600" title="有序列表">
                    <i className="ri-list-ordered text-[13px]" /></button>
                  <div className="w-px h-4 bg-slate-200 mx-0.5" />
                  <button type="button" onClick={() => insertMd('[', '](url)')}
                    className="w-7 h-7 flex items-center justify-center rounded hover:bg-slate-200 text-slate-600" title="链接">
                    <i className="ri-link text-[13px]" /></button>
                  <button type="button" onClick={() => insertMd('`', '`')}
                    className="w-7 h-7 flex items-center justify-center rounded hover:bg-slate-200 text-[11px] font-mono text-slate-600" title="行内代码">{`</>`}</button>
                </div>
                <textarea ref={contentRef} value={form.content} onChange={e => handleContentChange(e.target.value)}
                  onPaste={handlePaste} rows={9}
                  placeholder="在此输入 Markdown 内容，或通过上方拖拽文件自动填充…"
                  className="w-full border border-slate-200 rounded-b-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none font-mono" />
              </>
            )}
            {isMdTextFormat && editorMode === 'preview' && (
              <div className="w-full border border-slate-200 rounded-lg px-4 py-3 min-h-[216px] max-h-[400px] overflow-y-auto prose prose-sm prose-slate max-w-none text-[13px]">
                {form.content
                  ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{form.content}</ReactMarkdown>
                  : <p className="text-slate-300 italic text-[13px]">暂无内容</p>}
              </div>
            )}
          </div>

          {/* AI 索引配置 */}
          <div className="border border-slate-200 rounded-lg px-4 py-3 space-y-3 bg-slate-50">
            <div className="flex items-center justify-between">
              <div className="flex items-start gap-1.5">
                <i className="ri-robot-2-line text-slate-400 mt-0.5 text-[13px]" />
                <div>
                  <div className="text-[12px] font-medium text-slate-700">允许 Agent 检索此文档</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">开启后，Data Agent 将学习此内容以辅助 SQL 生成和业务问答</div>
                </div>
              </div>
              <button type="button" onClick={() => setAllowRag(v => !v)}
                className={`relative inline-flex w-9 h-5 rounded-full transition-colors focus:outline-none ml-4 shrink-0 ${allowRag ? 'bg-blue-600' : 'bg-slate-300'}`}>
                <span className={`inline-block w-3.5 h-3.5 rounded-full bg-white shadow transform transition-transform mt-[3px] ${allowRag ? 'translate-x-[18px]' : 'translate-x-[3px]'}`} />
              </button>
            </div>
            {allowRag && (
              <div className="flex items-center gap-2 pl-5">
                <span className="text-[11px] text-slate-500">检索权重</span>
                <div className="flex rounded-lg overflow-hidden border border-slate-200 bg-white">
                  {(['low', 'medium', 'high'] as const).map((w, i) => (
                    <button key={w} type="button" onClick={() => setRagWeight(w)}
                      className={`px-3 py-1 text-[11px] font-medium border-r last:border-r-0 border-slate-200 transition-colors ${ragWeight === w ? 'bg-slate-800 text-white' : 'text-slate-600 hover:bg-slate-50'}`}>
                      {['低', '中', '高'][i]}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {error && <p className="text-[12px] text-red-500">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-[12px] text-slate-600 hover:text-slate-800">取消</button>
            <button type="submit" disabled={saving || saveSuccess}
              className={`px-4 py-2 text-[12px] rounded-lg flex items-center gap-1.5 transition-all ${saveSuccess ? 'bg-emerald-600 text-white' : 'bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50'}`}>
              {saving ? <><i className="ri-loader-4-line animate-spin" />保存中…</>
                : saveSuccess ? <><i className="ri-check-line" />新建成功</>
                : '保存'}
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

// ── 标签 chip 输入 ─────────────────────────────────────────────────────────────

function TagInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  function addTag(raw: string) {
    const tags = raw.split(',').map(s => s.trim()).filter(Boolean);
    if (tags.length === 0) return;
    onChange([...value, ...tags.filter(t => !value.includes(t))]);
    setInput('');
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag(input);
    } else if (e.key === 'Backspace' && !input) {
      onChange(value.slice(0, -1));
    }
  }

  return (
    <div
      onClick={() => inputRef.current?.focus()}
      className="min-h-[38px] flex flex-wrap gap-1.5 items-center border border-slate-200 rounded-lg px-2 py-1.5 cursor-text focus-within:ring-2 focus-within:ring-blue-500"
    >
      {value.map(tag => (
        <span key={tag} className="inline-flex items-center gap-1 bg-slate-100 text-slate-700 text-[11px] rounded px-2 py-0.5">
          {tag}
          <button type="button" onClick={() => onChange(value.filter(t => t !== tag))} className="text-slate-400 hover:text-slate-600 leading-none">×</button>
        </span>
      ))}
      <input
        ref={inputRef}
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => input && addTag(input)}
        placeholder={value.length === 0 ? placeholder : ''}
        className="flex-1 min-w-[80px] outline-none text-[13px] bg-transparent"
      />
    </div>
  );
}

// ── 术语新建 Modal ─────────────────────────────────────────────────────────────

interface GlossaryForm { term: string; canonical_term: string; definition: string; category: string; synonyms: string[]; formula: string; related_metric_ids: string[]; }

function GlossaryModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<GlossaryForm>({ term: '', canonical_term: '', definition: '', category: 'concept', synonyms: [], formula: '', related_metric_ids: [] });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [metrics, setMetrics] = useState<MetricItem[]>([]);
  const [metricSearch, setMetricSearch] = useState('');
  const [metricOpen, setMetricOpen] = useState(false);
  const metricRef = useRef<HTMLDivElement>(null);
  const set = (k: keyof GlossaryForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    listMetrics({ page_size: 200 }).then(r => setMetrics(r.items ?? [])).catch(() => {});
  }, []);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (metricRef.current && !metricRef.current.contains(e.target as Node)) setMetricOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const filteredMetrics = metrics.filter(m => !metricSearch || m.name.toLowerCase().includes(metricSearch.toLowerCase()));

  function toggleMetric(id: string) {
    setForm(f => ({
      ...f,
      related_metric_ids: f.related_metric_ids.includes(id)
        ? f.related_metric_ids.filter(x => x !== id)
        : [...f.related_metric_ids, id],
    }));
  }

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
        synonyms: form.synonyms,
        formula: form.formula.trim() || undefined,
        related_metric_ids: form.related_metric_ids,
      });
      onSaved();
    } catch (err: unknown) { setError(err instanceof Error ? err.message : '创建失败'); }
    finally { setSaving(false); }
  }

  const selectedMetricNames = form.related_metric_ids
    .map(id => metrics.find(m => String(m.id) === id)?.name ?? id)
    .join('、');

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
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
              <label className="block text-[12px] font-medium text-slate-600 mb-1">计算公式（可选）</label>
              <input value={form.formula} onChange={set('formula')} placeholder="如：GMV = 成交笔数 × 客单价"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">定义 *</label>
            <textarea value={form.definition} onChange={set('definition')} rows={3} placeholder="清晰描述该术语的业务含义"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
          </div>
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">同义词（回车或逗号分隔）</label>
            <TagInput value={form.synonyms} onChange={v => setForm(f => ({ ...f, synonyms: v }))} placeholder="如：成交额、GMV" />
          </div>
          <div ref={metricRef} className="relative">
            <label className="block text-[12px] font-medium text-slate-600 mb-1">关联指标</label>
            <button type="button" onClick={() => setMetricOpen(o => !o)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] text-left flex items-center justify-between focus:outline-none focus:ring-2 focus:ring-blue-500">
              <span className={form.related_metric_ids.length === 0 ? 'text-slate-400' : 'text-slate-700 truncate'}>
                {form.related_metric_ids.length === 0 ? '选择关联指标…' : selectedMetricNames}
              </span>
              <i className={`ri-arrow-${metricOpen ? 'up' : 'down'}-s-line text-slate-400 flex-shrink-0`} />
            </button>
            {metricOpen && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-slate-200 rounded-xl shadow-lg z-10 overflow-hidden">
                <div className="p-2 border-b border-slate-100">
                  <input value={metricSearch} onChange={e => setMetricSearch(e.target.value)} placeholder="搜索指标…"
                    className="w-full px-3 py-1.5 text-[12px] border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-500" />
                </div>
                <div className="max-h-40 overflow-y-auto">
                  {filteredMetrics.length === 0 ? (
                    <p className="text-[12px] text-slate-400 text-center py-4">无匹配指标</p>
                  ) : filteredMetrics.map(m => (
                    <button key={m.id} type="button" onClick={() => toggleMetric(String(m.id))}
                      className="w-full flex items-center gap-2.5 px-3 py-2 text-[12px] text-slate-700 hover:bg-slate-50 text-left">
                      <span className={`w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0 ${
                        form.related_metric_ids.includes(String(m.id)) ? 'bg-blue-600 border-blue-600 text-white' : 'border-slate-300'
                      }`}>
                        {form.related_metric_ids.includes(String(m.id)) && <i className="ri-check-line text-[9px]" />}
                      </span>
                      {m.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
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

// ── 批量导入术语 Modal ─────────────────────────────────────────────────────────

function ImportGlossaryModal({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ created: number; skipped: number; errors: { row: number; term?: string; reason: string }[] } | null>(null);
  const [error, setError] = useState('');

  async function handleUpload() {
    if (!file) return;
    setUploading(true); setError(''); setResult(null);
    try {
      const res = await importGlossaryCSV(file);
      setResult(res);
      if (res.created > 0) onImported();
    } catch (err: unknown) { setError(err instanceof Error ? err.message : '导入失败'); }
    finally { setUploading(false); }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <h2 className="text-base font-semibold text-slate-800">批量导入术语</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><i className="ri-close-line text-xl" /></button>
        </div>
        <div className="px-6 py-4 space-y-4">
          <div className="bg-slate-50 rounded-lg px-4 py-3 text-[12px] text-slate-600 space-y-1">
            <p className="font-medium text-slate-700">CSV 格式说明</p>
            <p>必填列：<code className="bg-white px-1 rounded">term</code>、<code className="bg-white px-1 rounded">canonical_term</code>、<code className="bg-white px-1 rounded">definition</code></p>
            <p>可选列：<code className="bg-white px-1 rounded">category</code>、<code className="bg-white px-1 rounded">synonyms</code>（逗号分隔）、<code className="bg-white px-1 rounded">formula</code></p>
            <p>支持中文列名：术语 / 标准名称 / 定义 / 分类 / 同义词 / 公式</p>
          </div>
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1.5">选择 CSV 文件</label>
            <input type="file" accept=".csv" onChange={e => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(''); }}
              className="w-full text-[12px] text-slate-600 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-blue-50 file:text-blue-700 file:text-[12px] file:cursor-pointer hover:file:bg-blue-100" />
          </div>
          {result && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3 space-y-1">
              <p className="text-[12px] font-medium text-emerald-700">导入完成</p>
              <p className="text-[12px] text-emerald-600">成功创建 {result.created} 条，跳过 {result.skipped} 条（已存在）</p>
              {result.errors.length > 0 && (
                <div className="mt-2 space-y-1">
                  <p className="text-[12px] text-amber-700 font-medium">以下行存在错误：</p>
                  {result.errors.slice(0, 5).map((e, i) => (
                    <p key={i} className="text-[11px] text-amber-600">第 {e.row} 行{e.term ? `（${e.term}）` : ''}：{e.reason}</p>
                  ))}
                  {result.errors.length > 5 && <p className="text-[11px] text-amber-500">…及另外 {result.errors.length - 5} 个错误</p>}
                </div>
              )}
            </div>
          )}
          {error && <p className="text-[12px] text-red-500">{error}</p>}
          <div className="flex justify-end gap-3 pt-1">
            <button type="button" onClick={onClose} className="px-4 py-2 text-[12px] text-slate-600 hover:text-slate-800">关闭</button>
            {!result && (
              <button onClick={handleUpload} disabled={!file || uploading}
                className="px-4 py-2 text-[12px] bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5">
                <i className="ri-upload-2-line" />{uploading ? '导入中…' : '开始导入'}
              </button>
            )}
          </div>
        </div>
      </div>
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
  const [showImport, setShowImport] = useState(false);
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
          <>
            <button onClick={() => setShowImport(true)}
              className="ml-auto flex items-center gap-1.5 px-3.5 py-1.5 border border-slate-200 text-slate-600 text-[12px] font-medium rounded-lg hover:bg-slate-50">
              <i className="ri-upload-2-line" />导入术语
            </button>
            <button onClick={() => setShowCreate(true)}
              className="flex items-center gap-1.5 px-3.5 py-1.5 bg-blue-600 text-white text-[12px] font-medium rounded-lg hover:bg-blue-700">
              <i className="ri-add-line" />新建术语
            </button>
          </>
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
                {['术语', '标准名称', '分类', '定义', '同义词', '指标', '创建时间'].map(h => (
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
                  <td className="px-4 py-3">
                    {item.related_metric_ids?.length > 0 ? (
                      <span className="inline-block px-2 py-0.5 text-[11px] rounded-full bg-violet-50 text-violet-700 border border-violet-200 whitespace-nowrap">
                        {item.related_metric_ids.length} 个指标
                      </span>
                    ) : <span className="text-[11px] text-slate-300">—</span>}
                  </td>
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
      {showImport && <ImportGlossaryModal onClose={() => setShowImport(false)} onImported={() => { load(); }} />}
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

      {/* Filter strip */}
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 py-2">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${
                  activeTab === tab.id
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
                }`}
              >
                <i className={tab.icon} />{tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="px-8 py-6">
        <div className="max-w-6xl mx-auto">
          {activeTab === 'docs'     && <DocumentsTab canWrite={canWrite} />}
          {activeTab === 'rag'      && <RagSearchTab />}
          {activeTab === 'glossary' && <GlossaryTab canWrite={canWrite} />}
        </div>
      </div>
    </div>
  );
}
