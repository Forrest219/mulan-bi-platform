import { useState, useEffect, useCallback } from 'react';
import DqcTabs from '../DqcTabs';
import {
  listTemplates, createTemplate, updateTemplate, deleteTemplate, applyTemplate,
  aiParseTemplateConfig,
  type DqcRuleTemplate, type CreateTemplateInput, type UpdateTemplateInput,
  DIMENSION_LABELS, RULE_TYPE_LABELS, DIMENSION_RULE_COMPATIBILITY,
  type Dimension, type RuleType,
} from '../../../../api/dqc';
import { ConfirmModal } from '../../../../components/ConfirmModal';
import { useAuth } from '../../../../context/AuthContext';

const ALL_DIMENSIONS = Object.keys(DIMENSION_LABELS) as Dimension[];
const SEVERITY_OPTIONS = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const;
const SEVERITY_COLORS: Record<string, string> = {
  LOW: 'bg-slate-100 text-slate-600',
  MEDIUM: 'bg-blue-100 text-blue-700',
  HIGH: 'bg-amber-100 text-amber-700',
  CRITICAL: 'bg-red-100 text-red-700',
};

// ── 规则参数表单字段定义（与 monitor 页同构）──
interface ConfigFieldDef {
  key: string; label: string; type: 'text' | 'number' | 'select';
  placeholder?: string; options?: { value: string; label: string }[];
  min?: number; max?: number; step?: number;
  help?: string;
}

const RULE_CONFIG_FIELDS: Record<string, ConfigFieldDef[]> = {
  null_rate: [
    { key: 'max_rate', label: '最多允许多少比例为空', type: 'number', placeholder: '如 0.05 = 最多 5% 为空', min: 0, max: 1, step: 0.01,
      help: '填 0.05 表示空值不得超过 5%，填 0 表示绝对不允许空值' },
  ],
  uniqueness: [
    { key: 'max_duplicate_rate', label: '最多允许多少比例重复', type: 'number', placeholder: '如 0 = 完全不允许重复', min: 0, max: 1, step: 0.01,
      help: '填 0 表示要求完全唯一，填 0.01 表示允许 1% 的重复' },
  ],
  range_check: [
    { key: 'check_mode', label: '检查方式', type: 'select', options: [
      { value: 'min_max_all', label: '扫描全部数据' }, { value: 'sample', label: '抽样检查' },
    ], help: '数据量大时可选抽样，速度快但可能遗漏极端值' },
  ],
  freshness: [
    { key: 'max_age_hours', label: '最多允许过期多久（小时）', type: 'number', min: 1,
      help: '超过这个小时数没有新数据就报警。如填 24 = 超过 1 天没更新就报警' },
  ],
  regex: [
    { key: 'pattern', label: '格式要求（正则）', type: 'text', placeholder: '如 ^[\\w.]+@[\\w.]+$',
      help: '不符合此格式的数据视为异常' },
  ],
  custom_sql: [
    { key: 'sql', label: '自定义查询', type: 'text', placeholder: '仅 SELECT 语句',
      help: '查询返回有结果 = 存在异常数据' },
  ],
  volume_anomaly: [
    { key: 'time_column', label: '时间字段', type: 'text', placeholder: '如 created_at、order_date',
      help: '按哪个字段统计每天的新增量？留空则对比全表总行数' },
    { key: 'threshold_pct', label: '波动超过多少报警', type: 'number', placeholder: '如 0.1 = 波动超 10% 报警', min: 0, max: 1, step: 0.01,
      help: '与上次相比，数据量变化超过这个比例就触发告警' },
    { key: 'direction', label: '关注什么变化', type: 'select', options: [
      { value: 'both', label: '涨跌都报' }, { value: 'drop', label: '只关心变少（防丢数据）' }, { value: 'rise', label: '只关心变多（防灌数据）' },
    ], help: '大多数场景选「涨跌都报」即可' },
    { key: 'min_row_count', label: '数据太少时跳过', type: 'number', placeholder: '默认 10', min: 0,
      help: '当天数据不足这个数就不检测，避免周末或冷启动时误报' },
    { key: 'observation_date', label: '统计哪天', type: 'text', placeholder: '默认 today（当天）',
      help: '一般不需要改。如需回测历史可填 today-2 等' },
  ],
  table_count_compare: [
    { key: 'tolerance_pct', label: '允许多大差异', type: 'number', min: 0, max: 1, step: 0.01,
      help: '填 0 = 必须完全一致；填 0.05 = 允许 5% 的偏差' },
  ],
};

// ── 匹配条件表单化 ──
type MatchScope = 'table' | 'column';
interface MatchFormState {
  scope: MatchScope;
  has_nulls: boolean;
  is_candidate_id: boolean;
  has_numeric_range: boolean;
  data_type_contains: string;
}

function matchConditionToForm(mc: Record<string, unknown>): MatchFormState {
  const scope = (mc.scope as string) === 'column' ? 'column' : 'table';
  const filter = (mc.column_filter as Record<string, unknown>) || {};
  return {
    scope: scope as MatchScope,
    has_nulls: !!filter.has_nulls,
    is_candidate_id: !!filter.is_candidate_id,
    has_numeric_range: !!filter.has_numeric_range,
    data_type_contains: ((filter.data_type_contains as string[]) || []).join(', '),
  };
}

function matchFormToCondition(mf: MatchFormState): Record<string, unknown> {
  if (mf.scope === 'table') return { scope: 'table' };
  const filter: Record<string, unknown> = {};
  if (mf.has_nulls) filter.has_nulls = true;
  if (mf.is_candidate_id) filter.is_candidate_id = true;
  if (mf.has_numeric_range) filter.has_numeric_range = true;
  const dtc = mf.data_type_contains.split(',').map(s => s.trim()).filter(Boolean);
  if (dtc.length) filter.data_type_contains = dtc;
  return { scope: 'column', column_filter: filter };
}

const getErrorMessage = (error: unknown, fallback = '操作失败'): string =>
  error instanceof Error ? error.message : fallback;

function matchConditionSummary(mc: Record<string, unknown>): string {
  const scope = (mc.scope as string) || 'table';
  if (scope === 'table') return '表级';
  const filter = mc.column_filter as Record<string, unknown> | undefined;
  if (!filter) return '列级';
  const parts: string[] = [];
  if (filter.has_nulls) parts.push('有空值');
  if (filter.is_candidate_id) parts.push('候选主键');
  if (filter.has_numeric_range) parts.push('数值列');
  const dtc = filter.data_type_contains as string[] | undefined;
  if (dtc?.length) parts.push(`类型含 ${dtc.join('/')}`);
  return parts.length ? `列级: ${parts.join(', ')}` : '列级';
}

const DEFAULT_FORM: CreateTemplateInput = {
  name: '', dimension: '', rule_type: '', default_config: {}, match_condition: {},
  severity: 'MEDIUM', enabled: true,
};

const DEFAULT_MATCH_FORM: MatchFormState = {
  scope: 'table', has_nulls: false, is_candidate_id: false, has_numeric_range: false, data_type_contains: '',
};

export default function DqcTemplatesPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin' || user?.role === 'data_admin';

  const [templates, setTemplates] = useState<DqcRuleTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingSnapshot, setEditingSnapshot] = useState<DqcRuleTemplate | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const [applyingId, setApplyingId] = useState<number | null>(null);
  const [successMsg, setSuccessMsg] = useState('');
  const [confirm, setConfirm] = useState<{
    open: boolean; title: string; message: string; onConfirm: () => void;
  }>({ open: false, title: '', message: '', onConfirm: () => {} });

  const [form, setForm] = useState<CreateTemplateInput>({ ...DEFAULT_FORM });
  const [matchForm, setMatchForm] = useState<MatchFormState>({ ...DEFAULT_MATCH_FORM });
  const [aiInput, setAiInput] = useState('');
  const [aiParsing, setAiParsing] = useState(false);
  const [aiReasoning, setAiReasoning] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listTemplates();
      setTemplates(data.items);
    } catch (e) {
      setError(getErrorMessage(e, '获取规则模板列表失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (successMsg) {
      const t = setTimeout(() => setSuccessMsg(''), 3000);
      return () => clearTimeout(t);
    }
  }, [successMsg]);

  const handleClose = () => {
    setShowForm(false);
    setFormError('');
    setEditingId(null);
    setEditingSnapshot(null);
    setAiInput('');
    setAiReasoning('');
  };

  const handleAiParse = async () => {
    if (!aiInput.trim()) return;
    setAiParsing(true);
    setAiReasoning('');
    setFormError('');
    try {
      const result = await aiParseTemplateConfig(aiInput, form.rule_type || undefined);
      setForm(f => ({
        ...f,
        name: result.name || f.name,
        default_config: result.default_config,
        severity: result.severity || f.severity,
      }));
      setMatchForm(matchConditionToForm(result.match_condition));
      setAiReasoning(result.reasoning);
    } catch (e) {
      setFormError(getErrorMessage(e, 'AI 解析失败，请重试或手动配置'));
    } finally {
      setAiParsing(false);
    }
  };

  const handleOpenNew = () => {
    setEditingId(null);
    setEditingSnapshot(null);
    setForm({ ...DEFAULT_FORM });
    setMatchForm({ ...DEFAULT_MATCH_FORM });
    setFormError('');
    setShowForm(true);
  };

  const handleOpenEdit = (t: DqcRuleTemplate) => {
    setEditingId(t.id);
    setEditingSnapshot(t);
    setForm({
      name: t.name,
      description: t.description ?? '',
      dimension: t.dimension,
      rule_type: t.rule_type,
      default_config: { ...t.default_config },
      match_condition: { ...t.match_condition },
      severity: t.severity,
      enabled: t.enabled,
    });
    setMatchForm(matchConditionToForm(t.match_condition));
    setFormError('');
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) { setFormError('请填写模板名称'); return; }
    if (editingId === null && !form.dimension) { setFormError('请选择维度'); return; }
    if (editingId === null && !form.rule_type) { setFormError('请选择规则类型'); return; }

    const matchCondition = matchFormToCondition(matchForm);

    setSaving(true);
    setFormError('');
    try {
      if (editingId !== null && editingSnapshot) {
        const payload: UpdateTemplateInput = {};
        if (form.name !== editingSnapshot.name) payload.name = form.name;
        if ((form.description ?? '') !== (editingSnapshot.description ?? '')) payload.description = form.description;
        if (JSON.stringify(form.default_config) !== JSON.stringify(editingSnapshot.default_config)) payload.default_config = form.default_config;
        if (JSON.stringify(matchCondition) !== JSON.stringify(editingSnapshot.match_condition)) payload.match_condition = matchCondition;
        if (form.severity !== editingSnapshot.severity) payload.severity = form.severity;
        if (form.enabled !== editingSnapshot.enabled) payload.enabled = form.enabled;

        const result = await updateTemplate(editingId, payload);
        if (result.propagated_count > 0) {
          setSuccessMsg(`已更新模板，并同步了 ${result.propagated_count} 条派生规则`);
        } else {
          setSuccessMsg('模板已更新');
        }
      } else {
        await createTemplate({ ...form, match_condition: matchCondition });
        setSuccessMsg('模板已创建');
      }
      handleClose();
      load();
    } catch (e) {
      setFormError(getErrorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = (t: DqcRuleTemplate) => {
    setConfirm({
      open: true,
      title: '删除模板',
      message: `确认删除模板「${t.name}」？已生成的派生规则不会被删除。`,
      onConfirm: async () => {
        try {
          await deleteTemplate(t.id);
          setSuccessMsg('模板已删除');
          load();
        } catch (e) {
          setError(getErrorMessage(e));
        }
        setConfirm(c => ({ ...c, open: false }));
      },
    });
  };

  const handleApply = async (t: DqcRuleTemplate) => {
    setApplyingId(t.id);
    try {
      const result = await applyTemplate(t.id);
      setSuccessMsg(`已对 ${result.applied_assets} 个资产应用模板，共创建 ${result.rules_created} 条规则`);
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setApplyingId(null);
    }
  };

  const handleToggleEnabled = async (t: DqcRuleTemplate) => {
    try {
      await updateTemplate(t.id, { enabled: !t.enabled });
      load();
    } catch (e) {
      setError(getErrorMessage(e));
    }
  };

  const compatibleTypes = form.dimension
    ? DIMENSION_RULE_COMPATIBILITY[form.dimension as Dimension] ?? []
    : (Object.keys(RULE_TYPE_LABELS) as RuleType[]);

  const configFields = RULE_CONFIG_FIELDS[form.rule_type] ?? [];

  return (
    <div className="max-w-6xl mx-auto px-8 py-7">
      {/* ── 页头 ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {showForm && (
            <button
              onClick={handleClose}
              className="p-1 -ml-1 text-slate-400 hover:text-slate-700 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
          )}
          <div>
            <h1 className="text-lg font-semibold text-slate-900">
              {showForm
                ? (editingId !== null ? '编辑规则模板' : '新建规则模板')
                : '数据质量核心'}
            </h1>
            {!showForm && (
              <p className="text-xs text-slate-500 mt-0.5">DQC — 规则模板管理</p>
            )}
          </div>
        </div>
        {!showForm && isAdmin && (
          <button
            onClick={handleOpenNew}
            className="px-3 py-1.5 text-xs font-medium bg-slate-800 text-white rounded-md hover:bg-slate-700 transition-colors"
          >
            新建模板
          </button>
        )}
      </div>

      {!showForm && <DqcTabs />}

      {/* ── 全局提示 ── */}
      {successMsg && (
        <div className="mt-4 px-3 py-2 bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs rounded-lg">
          {successMsg}
        </div>
      )}
      {error && (
        <div className="mt-4 px-3 py-2 bg-red-50 border border-red-200 text-red-600 text-xs rounded-lg">
          {error}
        </div>
      )}

      {/* ── 列表视图 ── */}
      {!showForm && (
        <>
          {loading ? (
            <div className="text-center py-12 text-slate-400 text-sm">加载中...</div>
          ) : templates.length === 0 ? (
            <div className="text-center py-12 text-slate-400 text-sm">暂无规则模板，请先 Seed 内置模板或新建</div>
          ) : (
            <div className="mt-5 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="pb-2 font-medium">模板名称</th>
                    <th className="pb-2 font-medium">维度</th>
                    <th className="pb-2 font-medium">规则类型</th>
                    <th className="pb-2 font-medium">匹配条件</th>
                    <th className="pb-2 font-medium">严重级别</th>
                    <th className="pb-2 font-medium text-center">启用</th>
                    <th className="pb-2 font-medium text-right">派生规则</th>
                    {isAdmin && <th className="pb-2 font-medium text-right">操作</th>}
                  </tr>
                </thead>
                <tbody>
                  {templates.map(t => (
                    <tr key={t.id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center gap-1.5">
                          <span className="font-medium text-slate-800">{t.name}</span>
                          {t.is_builtin && (
                            <span className="px-1.5 py-0.5 bg-indigo-50 text-indigo-600 text-[10px] rounded">内置</span>
                          )}
                        </div>
                        {t.description && (
                          <div className="text-[11px] text-slate-400 mt-0.5 truncate max-w-[200px]">{t.description}</div>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 text-slate-600">
                        {DIMENSION_LABELS[t.dimension] ?? t.dimension}
                      </td>
                      <td className="py-2.5 pr-3 text-slate-600">
                        {RULE_TYPE_LABELS[t.rule_type] ?? t.rule_type}
                      </td>
                      <td className="py-2.5 pr-3 text-slate-500">
                        {matchConditionSummary(t.match_condition)}
                      </td>
                      <td className="py-2.5 pr-3">
                        <span className={`px-1.5 py-0.5 text-[10px] font-medium rounded ${SEVERITY_COLORS[t.severity] ?? 'bg-slate-100 text-slate-600'}`}>
                          {t.severity}
                        </span>
                      </td>
                      <td className="py-2.5 text-center">
                        <button
                          onClick={() => handleToggleEnabled(t)}
                          disabled={!isAdmin}
                          className={`w-8 h-4 rounded-full transition-colors relative ${t.enabled ? 'bg-emerald-500' : 'bg-slate-300'} ${!isAdmin ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}
                        >
                          <span className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform ${t.enabled ? 'left-4' : 'left-0.5'}`} />
                        </button>
                      </td>
                      <td className="py-2.5 text-right pr-3">
                        <span className="text-slate-700">{t.derived_rules_count ?? 0}</span>
                        {(t.unmodified_rules_count ?? 0) > 0 && (
                          <span className="text-slate-400 ml-1">({t.unmodified_rules_count} 可同步)</span>
                        )}
                      </td>
                      {isAdmin && (
                        <td className="py-2.5 text-right">
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={() => handleOpenEdit(t)}
                              className="px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-100 rounded transition-colors"
                            >
                              编辑
                            </button>
                            <button
                              onClick={() => handleApply(t)}
                              disabled={applyingId === t.id || !t.enabled}
                              className="px-2 py-1 text-[11px] text-blue-600 hover:bg-blue-50 rounded transition-colors disabled:opacity-50"
                            >
                              {applyingId === t.id ? '应用中...' : '补刷'}
                            </button>
                            {!t.is_builtin && (
                              <button
                                onClick={() => handleDelete(t)}
                                className="px-2 py-1 text-[11px] text-red-500 hover:bg-red-50 rounded transition-colors"
                              >
                                删除
                              </button>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ── 内嵌表单视图 ── */}
      {showForm && (
        <div className="mt-6 bg-white border border-slate-200 rounded-xl shadow-sm">
          <div className="px-6 py-4 space-y-4">
            {formError && (
              <div className="px-3 py-2 bg-red-50 border border-red-200 text-red-600 text-xs rounded-lg">{formError}</div>
            )}

            {editingSnapshot?.is_modified_by_user && (
              <div className="px-3 py-2 bg-amber-50 border border-amber-200 text-amber-700 text-xs rounded-lg">
                此内置模板已被手动修改，更新不会覆盖
              </div>
            )}

            {/* ── AI 智能填充 ── */}
            <div className="p-4 bg-gradient-to-r from-indigo-50 to-blue-50 border border-indigo-100 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <svg className="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                <span className="text-xs font-medium text-indigo-700">AI 智能配置</span>
                <span className="text-[11px] text-indigo-400">用自然语言描述你的监控需求，AI 自动生成配置</span>
              </div>
              <div className="flex gap-2">
                <input
                  value={aiInput}
                  onChange={e => setAiInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !aiParsing) handleAiParse(); }}
                  placeholder="例如：监控订单表每天新增数据量，如果比昨天下降超过 20% 就告警"
                  className="flex-1 border border-indigo-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400 bg-white placeholder:text-slate-400"
                />
                <button
                  onClick={handleAiParse}
                  disabled={aiParsing || !aiInput.trim()}
                  className="px-4 py-2 text-xs font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-50 transition-colors whitespace-nowrap"
                >
                  {aiParsing ? '解析中...' : '智能填充'}
                </button>
              </div>
              {aiReasoning && (
                <div className="mt-2 text-[11px] text-indigo-600 flex items-start gap-1.5">
                  <svg className="w-3.5 h-3.5 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>AI 理解：{aiReasoning}。请检查下方配置是否符合预期，可手动微调。</span>
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">模板名称</label>
                <input
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-slate-400"
                  placeholder="如：空值率监控"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">描述</label>
                <input
                  value={form.description ?? ''}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-slate-400"
                  placeholder="可选"
                />
              </div>
            </div>

            {editingId === null && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">维度</label>
                  <select
                    value={form.dimension}
                    onChange={e => setForm(f => ({ ...f, dimension: e.target.value, rule_type: '' }))}
                    className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-slate-400"
                  >
                    <option value="">请选择</option>
                    {ALL_DIMENSIONS.map(d => (
                      <option key={d} value={d}>{DIMENSION_LABELS[d]}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">规则类型</label>
                  <select
                    value={form.rule_type}
                    onChange={e => setForm(f => ({ ...f, rule_type: e.target.value }))}
                    className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-slate-400"
                  >
                    <option value="">请选择</option>
                    {compatibleTypes.map(rt => (
                      <option key={rt} value={rt}>{RULE_TYPE_LABELS[rt]}</option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            {editingId !== null && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">维度</label>
                  <div className="px-3 py-1.5 text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg">
                    {DIMENSION_LABELS[form.dimension as Dimension] ?? form.dimension}
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">规则类型</label>
                  <div className="px-3 py-1.5 text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg">
                    {RULE_TYPE_LABELS[form.rule_type as RuleType] ?? form.rule_type}
                  </div>
                </div>
                <p className="col-span-2 text-[11px] text-slate-400">维度和规则类型创建后不可修改，因为已有派生规则依赖此设定</p>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">严重级别</label>
                <select
                  value={form.severity}
                  onChange={e => setForm(f => ({ ...f, severity: e.target.value }))}
                  className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-slate-400"
                >
                  {SEVERITY_OPTIONS.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-end pb-0.5">
                <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.enabled ?? true}
                    onChange={e => setForm(f => ({ ...f, enabled: e.target.checked }))}
                    className="rounded border-slate-300"
                  />
                  启用
                </label>
              </div>
            </div>

            {/* ── 默认配置（结构化） ── */}
            {configFields.length > 0 && (
              <div>
                <div className="mb-2">
                  <label className="block text-xs font-medium text-slate-600">默认配置</label>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    应用此模板时，派生规则将继承以下默认参数。用户可在单条规则中覆盖。
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-3 p-3 bg-slate-50 rounded-lg border border-slate-200">
                  {configFields.map(fd => (
                    <div key={fd.key}>
                      <label className="block text-[11px] text-slate-500 mb-0.5">{fd.label}</label>
                      {fd.type === 'select' ? (
                        <select
                          value={(form.default_config as Record<string, string>)[fd.key] ?? ''}
                          onChange={e => setForm(f => ({
                            ...f, default_config: { ...f.default_config, [fd.key]: e.target.value || undefined },
                          }))}
                          className="w-full border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-slate-400"
                        >
                          <option value="">不设置</option>
                          {fd.options?.map(o => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type={fd.type}
                          value={(form.default_config as Record<string, string | number>)[fd.key] ?? ''}
                          onChange={e => {
                            const val = fd.type === 'number' && e.target.value !== '' ? Number(e.target.value) : e.target.value || undefined;
                            setForm(f => ({
                              ...f, default_config: { ...f.default_config, [fd.key]: val },
                            }));
                          }}
                          placeholder={fd.placeholder}
                          min={fd.min}
                          max={fd.max}
                          step={fd.step}
                          className="w-full border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-slate-400"
                        />
                      )}
                      {fd.help && <p className="text-[10px] text-slate-400 mt-0.5">{fd.help}</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {configFields.length === 0 && form.rule_type && (
              <div className="text-xs text-slate-400 italic">该规则类型无可配置参数</div>
            )}

            {/* ── 匹配条件（结构化） ── */}
            <div>
              <div className="mb-2">
                <label className="block text-xs font-medium text-slate-600">匹配范围</label>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  决定此模板自动应用到哪些对象：表级对整张表生效；列级会根据字段画像（如是否有空值、是否为主键）自动匹配符合条件的列。
                </p>
              </div>
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-3">
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer">
                    <input
                      type="radio" name="matchScope" value="table"
                      checked={matchForm.scope === 'table'}
                      onChange={() => setMatchForm(m => ({ ...m, scope: 'table' }))}
                    />
                    表级
                  </label>
                  <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer">
                    <input
                      type="radio" name="matchScope" value="column"
                      checked={matchForm.scope === 'column'}
                      onChange={() => setMatchForm(m => ({ ...m, scope: 'column' }))}
                    />
                    列级
                  </label>
                </div>
                {matchForm.scope === 'table' && (
                  <p className="text-[11px] text-slate-400 pl-1">
                    对纳入监控的每张表自动生成一条规则，适合行数监控、新鲜度监控等全表级检测。
                  </p>
                )}
                {matchForm.scope === 'column' && (
                  <div className="pl-4 space-y-2.5 border-l-2 border-slate-200">
                    <p className="text-[11px] text-slate-400">
                      勾选以下条件，系统会在字段画像中自动筛选符合特征的列，为每列生成一条规则。
                    </p>
                    <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
                      <input type="checkbox" checked={matchForm.has_nulls}
                        onChange={e => setMatchForm(m => ({ ...m, has_nulls: e.target.checked }))}
                        className="rounded border-slate-300"
                      />
                      <span>有空值的列<span className="text-slate-400 ml-1">— 画像显示该列存在 NULL</span></span>
                    </label>
                    <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
                      <input type="checkbox" checked={matchForm.is_candidate_id}
                        onChange={e => setMatchForm(m => ({ ...m, is_candidate_id: e.target.checked }))}
                        className="rounded border-slate-300"
                      />
                      <span>候选主键列<span className="text-slate-400 ml-1">— 画像判定该列为唯一标识</span></span>
                    </label>
                    <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
                      <input type="checkbox" checked={matchForm.has_numeric_range}
                        onChange={e => setMatchForm(m => ({ ...m, has_numeric_range: e.target.checked }))}
                        className="rounded border-slate-300"
                      />
                      <span>数值列<span className="text-slate-400 ml-1">— 画像中有最大/最小值的数字字段</span></span>
                    </label>
                    <div>
                      <label className="block text-[11px] text-slate-500 mb-0.5">字段类型包含</label>
                      <input
                        value={matchForm.data_type_contains}
                        onChange={e => setMatchForm(m => ({ ...m, data_type_contains: e.target.value }))}
                        placeholder="如 varchar, text（逗号分隔）"
                        className="w-64 border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-slate-400"
                      />
                      <p className="text-[10px] text-slate-400 mt-0.5">只匹配字段数据类型名中包含这些关键词的列</p>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {editingSnapshot && (editingSnapshot.unmodified_rules_count ?? 0) > 0 && (
              <div className="px-3 py-2 bg-blue-50 border border-blue-200 text-blue-700 text-xs rounded-lg">
                修改默认配置将同步更新 {editingSnapshot.unmodified_rules_count} 条未被用户修改的派生规则
              </div>
            )}
          </div>

          {/* 表单底栏 */}
          <div className="flex justify-end gap-2 px-6 py-3 border-t border-slate-100">
            <button
              onClick={handleClose}
              className="px-4 py-1.5 text-xs text-slate-500 hover:bg-slate-100 rounded-md transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-1.5 text-xs font-medium bg-slate-800 text-white rounded-md hover:bg-slate-700 disabled:opacity-50 transition-colors"
            >
              {saving ? '保存中...' : editingId !== null ? '保存修改' : '创建模板'}
            </button>
          </div>
        </div>
      )}

      <ConfirmModal
        open={confirm.open}
        title={confirm.title}
        message={confirm.message}
        onConfirm={confirm.onConfirm}
        onCancel={() => setConfirm(c => ({ ...c, open: false }))}
        variant="danger"
      />
    </div>
  );
}
