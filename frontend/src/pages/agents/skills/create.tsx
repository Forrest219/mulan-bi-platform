import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  createSkill,
  listRegisteredTools,
  type CreateSkillPayload,
  type RegisteredTool,
} from '../../../api/skills';

const DRAFT_PREFIX = 'skill_draft_create:';
const EMPTY_SCHEMA = { type: 'object', properties: {}, required: [] };

const CATEGORIES = [
  { key: 'query', label: '查询' },
  { key: 'analysis', label: '分析' },
  { key: 'visualization', label: '可视化' },
  { key: 'reporting', label: '报告' },
  { key: 'general', label: '通用' },
];

const TEMPLATES = [
  {
    key: 'empty',
    label: '无参数模板',
    description: '适合无需入参的静态工具',
    schema: EMPTY_SCHEMA,
  },
  {
    key: 'single_string',
    label: '单字符串参数模板',
    description: '适合 query、question、sql 等单文本参数',
    schema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '用户输入的查询文本' },
      },
      required: ['query'],
    },
  },
  {
    key: 'enum',
    label: '枚举参数模板',
    description: '适合固定模式、范围或类型选择',
    schema: {
      type: 'object',
      properties: {
        mode: {
          type: 'string',
          enum: ['summary', 'detail'],
          description: '执行模式',
        },
      },
      required: ['mode'],
    },
  },
];

interface DraftState {
  selectedKey: string;
  name: string;
  category: string;
  description: string;
  versionDescription: string;
  schemaText: string;
  codeRef: string;
  changeNotes: string;
}

function draftKey(skillKey: string) {
  return `${DRAFT_PREFIX}${skillKey || 'unselected'}`;
}

function stringifyJson(value: Record<string, unknown>) {
  return JSON.stringify(value, null, 2);
}

function parseJsonObject(text: string): Record<string, unknown> {
  const parsed = JSON.parse(text) as unknown;
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('JSON 顶层必须是对象');
  }
  return parsed as Record<string, unknown>;
}

function buildDraftFromTool(tool: RegisteredTool): DraftState {
  return {
    selectedKey: tool.skill_key,
    name: tool.name,
    category: tool.category || 'general',
    description: '',
    versionDescription: tool.default_description ?? tool.description,
    schemaText: stringifyJson(tool.default_parameters_schema ?? tool.input_schema ?? EMPTY_SCHEMA),
    codeRef: tool.code_ref || '',
    changeNotes: '从已注册静态工具创建初始版本',
  };
}

function readDraft(key: string): DraftState | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as DraftState) : null;
  } catch {
    return null;
  }
}

function findFirstDraft(): DraftState | null {
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key?.startsWith(DRAFT_PREFIX)) {
        const draft = readDraft(key);
        if (draft) return draft;
      }
    }
  } catch {
    return null;
  }
  return null;
}

export default function SkillCreatePage() {
  const navigate = useNavigate();
  const historyGuardActiveRef = useRef(false);

  const [tools, setTools] = useState<RegisteredTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [dirty, setDirty] = useState(false);

  const [draft, setDraft] = useState<DraftState>({
    selectedKey: '',
    name: '',
    category: 'query',
    description: '',
    versionDescription: '',
    schemaText: stringifyJson(EMPTY_SCHEMA),
    codeRef: '',
    changeNotes: '初始版本',
  });

  const selectedTool = useMemo(
    () => tools.find(tool => tool.skill_key === draft.selectedKey) || null,
    [tools, draft.selectedKey],
  );

  const updateDraft = (patch: Partial<DraftState>) => {
    setDraft(prev => ({ ...prev, ...patch }));
    setDirty(true);
  };

  const applyDraft = (nextDraft: DraftState, markDirty = false) => {
    setDraft(nextDraft);
    setDirty(markDirty);
  };

  useEffect(() => {
    let alive = true;
    async function loadTools() {
      setLoading(true);
      setError('');
      try {
        const res = await listRegisteredTools();
        if (!alive) return;
        setTools(res.tools);
        const saved = findFirstDraft();
        if (saved && window.confirm('发现未保存草稿，是否恢复？')) {
          applyDraft(saved, true);
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : '加载已注册工具失败');
      } finally {
        if (alive) setLoading(false);
      }
    }
    loadTools();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!dirty) return;
    const timer = window.setTimeout(() => {
      try {
        localStorage.setItem(draftKey(draft.selectedKey), JSON.stringify(draft));
      } catch {
        // localStorage unavailable or full; keep editing state in memory.
      }
    }, 500);
    return () => window.clearTimeout(timer);
  }, [dirty, draft]);

  useEffect(() => {
    if (!dirty) return undefined;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  useEffect(() => {
    if (!dirty || historyGuardActiveRef.current) return undefined;
    historyGuardActiveRef.current = true;
    window.history.pushState({ skillCreateDirtyGuard: true }, '', window.location.href);

    const handler = () => {
      if (!dirty) return;
      if (window.confirm('当前页面有未保存草稿，确认离开？')) {
        historyGuardActiveRef.current = false;
        setDirty(false);
        window.setTimeout(() => window.history.back(), 0);
      } else {
        window.history.pushState({ skillCreateDirtyGuard: true }, '', window.location.href);
      }
    };

    window.addEventListener('popstate', handler);
    return () => {
      window.removeEventListener('popstate', handler);
      historyGuardActiveRef.current = false;
    };
  }, [dirty]);

  useEffect(() => {
    if (!dirty) return undefined;
    const handler = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      const anchor = target?.closest('a[href]') as HTMLAnchorElement | null;
      if (!anchor) return;
      const href = anchor.getAttribute('href');
      if (!href || href.startsWith('#') || anchor.target === '_blank') return;
      const nextUrl = new URL(anchor.href, window.location.origin);
      if (nextUrl.origin !== window.location.origin || nextUrl.pathname === window.location.pathname) return;
      if (!window.confirm('当前页面有未保存草稿，确认离开？')) {
        event.preventDefault();
        event.stopPropagation();
      } else {
        setDirty(false);
      }
    };
    document.addEventListener('click', handler, true);
    return () => document.removeEventListener('click', handler, true);
  }, [dirty]);

  const handleSelectTool = (skillKey: string) => {
    const tool = tools.find(item => item.skill_key === skillKey);
    if (!tool) {
      updateDraft({ selectedKey: skillKey });
      return;
    }

    if (dirty && draft.selectedKey !== skillKey) {
      const shouldOverwrite = window.confirm(
        '右侧编辑区已有未保存草稿。切换工具会用新工具的默认描述和参数 Schema 覆盖当前草稿，是否继续？',
      );
      if (!shouldOverwrite) return;
    }

    const saved = readDraft(draftKey(skillKey));
    if (saved && window.confirm('发现该工具的未保存草稿，是否恢复？')) {
      applyDraft(saved, true);
      return;
    }
    applyDraft(buildDraftFromTool(tool), false);
  };

  const handleRestoreStatic = () => {
    if (!selectedTool) return;
    applyDraft(buildDraftFromTool(selectedTool), true);
  };

  const handleApplyTemplate = (schema: Record<string, unknown>) => {
    updateDraft({ schemaText: stringifyJson(schema) });
  };

  const handleFormatSchema = () => {
    try {
      updateDraft({ schemaText: stringifyJson(parseJsonObject(draft.schemaText)) });
      setError('');
    } catch (e) {
      setError(`Input Schema 格式不正确：${e instanceof Error ? e.message : '未知错误'}`);
    }
  };

  const leaveWithConfirm = useCallback(() => {
    if (!dirty || window.confirm('当前页面有未保存草稿，确认离开？')) {
      setDirty(false);
      navigate('/agents/skills');
    }
  }, [dirty, navigate]);

  const handleCreate = async () => {
    if (!selectedTool) {
      setError('请选择已注册工具');
      return;
    }
    if (selectedTool.configured) {
      setError('该工具已配置，不能重复创建');
      return;
    }
    if (!draft.name.trim() || !draft.versionDescription.trim()) {
      setError('请填写技能名称和 LLM 工具描述');
      return;
    }

    let parsedSchema: Record<string, unknown>;
    try {
      parsedSchema = parseJsonObject(draft.schemaText);
    } catch (e) {
      setError(`JSON 格式有误，请检查标点或括号${e instanceof Error ? `：${e.message}` : ''}`);
      return;
    }

    const payload: CreateSkillPayload = {
      skill_key: selectedTool.skill_key,
      name: draft.name.trim(),
      description: draft.description.trim() || undefined,
      category: draft.category,
      initial_version: {
        description: draft.versionDescription.trim(),
        input_schema: parsedSchema,
        endpoint_type: 'static',
        code_ref: draft.codeRef.trim() || undefined,
        change_notes: draft.changeNotes.trim() || undefined,
      },
    };

    setSubmitting(true);
    setError('');
    setSuccessMsg('');
    try {
      const created = await createSkill(payload);
      localStorage.removeItem(draftKey(selectedTool.skill_key));
      setDirty(false);
      setSuccessMsg('技能 v1 创建成功');
      window.setTimeout(() => {
        navigate(`/agents/skills/${created.id}`);
      }, 800);
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败');
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {successMsg && (
        <div className="fixed top-5 left-1/2 z-[70] -translate-x-1/2 rounded-lg border border-emerald-200 bg-white px-4 py-2.5 text-[13px] text-emerald-700 shadow-lg flex items-center gap-2">
          <i className="ri-checkbox-circle-line text-base" />
          {successMsg}
        </div>
      )}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-puzzle-2-line text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">从已注册工具添加</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">选择后端 ToolRegistry 中的静态工具，编辑 LLM 可见元数据后创建 v1</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={leaveWithConfirm}
              className="px-3 py-2 text-[13px] border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleCreate}
              disabled={submitting || !selectedTool || selectedTool.configured}
              className="px-3 py-2 text-[13px] bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
            >
              {submitting && <i className="ri-loader-4-line animate-spin" />}
              创建 v1
            </button>
          </div>
        </div>
      </div>

      <div className="px-8 py-6">
        <div className="max-w-6xl mx-auto">
          {error && (
            <div className="mb-4 px-4 py-3 bg-red-50 text-red-700 border border-red-200 rounded-lg text-[13px] flex items-center justify-between">
              <span>{error}</span>
              <button onClick={() => setError('')} className="text-red-400 hover:text-red-600">
                <i className="ri-close-line" />
              </button>
            </div>
          )}

          <div className="grid grid-cols-[320px_minmax(0,1fr)] gap-5 items-start">
            <aside className="bg-white border border-slate-200 rounded-xl p-5 space-y-4">
              <div>
                <label className="block text-[12px] font-medium text-slate-600 mb-1">
                  已注册工具 <span className="text-red-500">*</span>
                </label>
                <select
                  value={draft.selectedKey}
                  onChange={e => handleSelectTool(e.target.value)}
                  disabled={loading}
                  className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg bg-white focus:outline-none focus:border-blue-400"
                >
                  <option value="">{loading ? '加载中...' : '请选择工具'}</option>
                  {tools.map(tool => (
                    <option key={tool.skill_key} value={tool.skill_key}>
                      {tool.name} ({tool.skill_key})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-[12px] font-medium text-slate-600 mb-1">skill_key</label>
                <div className="px-3 py-2 text-[12px] border border-slate-200 rounded-lg bg-slate-50 text-slate-500 font-mono min-h-9">
                  {draft.selectedKey || '-'}
                </div>
              </div>

              <div>
                <label className="block text-[12px] font-medium text-slate-600 mb-1">
                  技能名称 <span className="text-red-500">*</span>
                </label>
                <input
                  value={draft.name}
                  onChange={e => updateDraft({ name: e.target.value })}
                  className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-slate-600 mb-1">分类</label>
                <select
                  value={draft.category}
                  onChange={e => updateDraft({ category: e.target.value })}
                  className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg bg-white focus:outline-none focus:border-blue-400"
                >
                  {CATEGORIES.map(category => (
                    <option key={category.key} value={category.key}>{category.label}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-[12px] font-medium text-slate-600 mb-1">管理简介</label>
                <textarea
                  value={draft.description}
                  onChange={e => updateDraft({ description: e.target.value })}
                  rows={3}
                  placeholder="用于管理界面展示，不进入 LLM Prompt"
                  className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 resize-none"
                />
              </div>

              <div className="border-t border-slate-100 pt-4">
                <div className="text-[12px] font-medium text-slate-600 mb-2">当前配置状态</div>
                {selectedTool?.configured ? (
                  <div className="space-y-3">
                    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-200 text-[12px] font-medium">
                      <i className="ri-lock-line" />
                      已配置 {selectedTool.active_version_number || ''}
                    </div>
                    <p className="text-[12px] text-slate-500 leading-5">已配置工具默认禁止重复创建，避免覆盖现有 schema skill 或活跃版本。</p>
                    {selectedTool.skill_id && (
                      <button
                        type="button"
                        onClick={() => navigate(`/agents/skills/${selectedTool.skill_id}`)}
                        className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg text-slate-700 hover:bg-slate-50"
                      >
                        查看详情
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 text-[12px] font-medium">
                    <i className="ri-checkbox-circle-line" />
                    未配置
                  </div>
                )}
              </div>
            </aside>

            <main className="bg-white border border-slate-200 rounded-xl p-5 space-y-5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-[15px] font-semibold text-slate-800">版本内容编辑</h2>
                  <p className="text-[12px] text-slate-400 mt-0.5">以下内容只保存在前端草稿，确认创建前不会写入数据库</p>
                </div>
                <button
                  type="button"
                  onClick={handleRestoreStatic}
                  disabled={!selectedTool}
                  className="px-3 py-2 text-[12px] border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  从静态工具恢复
                </button>
              </div>

              <div>
                <label className="block text-[12px] font-medium text-slate-600 mb-1">
                  LLM 工具描述 <span className="text-red-500">*</span>
                </label>
                <textarea
                  value={draft.versionDescription}
                  onChange={e => updateDraft({ versionDescription: e.target.value })}
                  rows={8}
                  placeholder="注入 LLM System Prompt 的工具描述"
                  className="w-full px-3 py-2 text-[13px] leading-6 border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 resize-y"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="block text-[12px] font-medium text-slate-600">
                    Input Schema（JSON）
                  </label>
                  <button
                    type="button"
                    onClick={handleFormatSchema}
                    className="text-[12px] text-blue-600 hover:text-blue-500 px-2 py-1 rounded hover:bg-blue-50"
                  >
                    格式化 JSON
                  </button>
                </div>
                <textarea
                  value={draft.schemaText}
                  onChange={e => updateDraft({ schemaText: e.target.value })}
                  rows={14}
                  spellCheck={false}
                  className="w-full px-3 py-2 text-[12px] leading-5 border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 font-mono resize-y bg-slate-50"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[12px] font-medium text-slate-600 mb-1">代码引用</label>
                  <input
                    value={draft.codeRef}
                    onChange={e => updateDraft({ codeRef: e.target.value })}
                    className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 font-mono"
                  />
                </div>
                <div>
                  <label className="block text-[12px] font-medium text-slate-600 mb-1">变更说明</label>
                  <input
                    value={draft.changeNotes}
                    onChange={e => updateDraft({ changeNotes: e.target.value })}
                    className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
                  />
                </div>
              </div>

              <div className="border-t border-slate-100 pt-4">
                <div className="text-[12px] font-medium text-slate-600 mb-3">模板库</div>
                <div className="grid grid-cols-3 gap-3">
                  {TEMPLATES.map(template => (
                    <button
                      key={template.key}
                      type="button"
                      onClick={() => handleApplyTemplate(template.schema)}
                      className="text-left px-3 py-3 border border-slate-200 rounded-lg hover:border-blue-200 hover:bg-blue-50/40"
                    >
                      <div className="text-[13px] font-medium text-slate-700">{template.label}</div>
                      <div className="text-[11px] text-slate-400 mt-1 leading-4">{template.description}</div>
                    </button>
                  ))}
                </div>
              </div>
            </main>
          </div>
        </div>
      </div>

    </div>
  );
}
