import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import DqcTabs from '../DqcTabs';
import {
  getTemplate, createTemplate, updateTemplate, aiParseTemplateConfig,
  type DqcRuleTemplate, type CreateTemplateInput, type UpdateTemplateInput,
  DIMENSION_LABELS, RULE_TYPE_LABELS, RULE_PACKAGE_LABELS,
  RULE_PACKAGE_DESCRIPTIONS, RULE_PACKAGE_RULE_TYPES, RULE_TYPE_DIMENSION_MAP,
  type Dimension, type RuleType,
} from '../../../../api/dqc';

// ── 专属参数字段定义 ────────────────────────────────────────────────
interface ConfigFieldDef {
  key: string; label: string; type: 'text' | 'number' | 'select';
  placeholder?: string; options?: { value: string; label: string }[];
  min?: number; max?: number; step?: number; help?: string;
}

const RULE_CONFIG_FIELDS: Record<string, ConfigFieldDef[]> = {
  null_rate: [
    { key: 'max_rate', label: '最多允许多少比例为空', type: 'number',
      placeholder: '如 0.05 = 最多 5% 为空', min: 0, max: 1, step: 0.01,
      help: '填 0.05 表示空值不得超过 5%，填 0 表示绝对不允许空值' },
  ],
  uniqueness: [
    { key: 'max_duplicate_rate', label: '最多允许多少比例重复', type: 'number',
      placeholder: '如 0 = 完全不允许重复', min: 0, max: 1, step: 0.01,
      help: '填 0 表示要求完全唯一，填 0.01 表示允许 1% 的重复' },
  ],
  range_check: [
    { key: 'check_mode', label: '检查方式', type: 'select', options: [
      { value: 'min_max_all', label: '扫描全部数据' },
      { value: 'sample', label: '抽样检查' },
    ], help: '数据量大时可选抽样，速度快但可能遗漏极端值' },
  ],
  freshness: [
    { key: 'max_age_hours', label: '最多允许过期多久（小时）', type: 'number', min: 1,
      help: '超过这个小时数没有新数据就报警。如填 24 = 超过 1 天没更新就报警' },
  ],
  regex: [
    { key: 'pattern', label: '正则表达式', type: 'text', placeholder: '^[0-9]{11}$',
      help: '字段值不匹配此正则则视为异常，如手机号 ^1[3-9]\\d{9}$' },
    { key: 'max_fail_rate', label: '最多允许多少比例不匹配', type: 'number',
      min: 0, max: 1, step: 0.01, help: '填 0 = 必须全部匹配，填 0.01 = 允许 1% 不匹配' },
  ],
  custom_sql: [
    { key: 'sql', label: '自定义查询', type: 'text', placeholder: '仅 SELECT 语句',
      help: '查询返回有结果 = 存在异常数据' },
  ],
  volume_anomaly: [
    { key: 'time_column', label: '时间字段', type: 'text',
      placeholder: '如 created_at、order_date',
      help: '按哪个字段统计每天的新增量？留空则对比全表总行数' },
    { key: 'threshold_pct', label: '波动超过多少报警', type: 'number',
      placeholder: '如 0.1 = 波动超 10% 报警', min: 0, max: 1, step: 0.01,
      help: '与上次相比，数据量变化超过这个比例就触发告警' },
    { key: 'direction', label: '关注什么变化', type: 'select', options: [
      { value: 'both', label: '涨跌都报' },
      { value: 'drop', label: '只关心变少（防丢数据）' },
      { value: 'rise', label: '只关心变多（防灌数据）' },
    ], help: '大多数场景选「涨跌都报」即可' },
    { key: 'min_row_count', label: '数据太少时跳过', type: 'number',
      placeholder: '默认 10', min: 0,
      help: '当天数据不足这个数就不检测，避免周末或冷启动时误报' },
  ],
  table_count_compare: [
    { key: 'tolerance_pct', label: '允许多大差异', type: 'number',
      min: 0, max: 1, step: 0.01,
      help: '填 0 = 必须完全一致；填 0.05 = 允许 5% 的偏差' },
  ],
  schema_drift: [
    { key: 'tolerance_cols', label: '允许变更的字段数', type: 'number', min: 0,
      help: '与上次快照相比，字段新增/删除数超过此值则报警。填 0 = 不允许任何 Schema 变更' },
  ],
  enum_check: [
    { key: 'field', label: '字段名', type: 'text', placeholder: '如 status、order_type',
      help: '检查哪个字段的值是否在允许的枚举范围内' },
    { key: 'allowed_values', label: '允许的值（逗号分隔）', type: 'text',
      placeholder: '如 active,inactive,pending', help: '这些值之外的数据视为异常' },
  ],
  sensitive_field: [
    { key: 'patterns', label: '敏感字段关键词（逗号分隔）', type: 'text',
      placeholder: '如 phone,id_card,email',
      help: '字段名包含这些关键词时，检查是否已标注脱敏处理方式' },
  ],
  ai_field_comment: [
    { key: 'min_coverage', label: '最低注释覆盖率', type: 'number',
      placeholder: '如 0.8 = 80% 字段需有注释', min: 0, max: 1, step: 0.01,
      help: 'DDL 中有注释的字段数 / 总字段数，低于此值则报警' },
  ],
  ai_table_description: [
    { key: 'require_description', label: '必须填写业务说明', type: 'select', options: [
      { value: 'true', label: '是（无说明视为不合规）' }, { value: 'false', label: '否（仅检查格式）' },
    ], help: '表是否必须有业务说明文字，留空则默认必须填写' },
    { key: 'min_length', label: '描述最低字符数', type: 'number', min: 0, step: 1,
      placeholder: '如 20 = 不足 20 字则不合规', help: '填 0 表示不限制长度，仅检查是否存在' },
    { key: 'require_zh', label: '要求包含中文', type: 'select', options: [
      { value: 'true', label: '是' }, { value: 'false', label: '否' },
    ], help: '说明中是否必须包含中文，便于 AI 理解表的业务含义' },
  ],
  ai_metric_definition: [
    { key: 'min_coverage', label: '最低指标定义覆盖率', type: 'number',
      placeholder: '如 0.8', min: 0, max: 1, step: 0.01,
      help: '已定义指标语义的字段数 / 全部可度量字段数，低于此值报警' },
  ],
};

// ── 规则类型预填默认值（isNew 时自动填入）────────────────────────
const RULE_TYPE_DEFAULTS: Partial<Record<string, {
  name: string; description: string; severity: string; block_strategy: string;
  default_config: Record<string, unknown>; match_scope: 'table' | 'column' | 'ddl';
}>> = {
  ai_table_description: {
    name: '表业务说明完整性',
    description: '检查每张监控表是否有充分的业务说明，确保 AI 能正确理解表用途',
    severity: 'HIGH',
    block_strategy: 'alert',
    default_config: { require_description: 'true', min_length: 20, require_zh: 'true' },
    match_scope: 'ddl',
  },
};

// ── L4 检查对象名称 ───────────────────────────────────────────────
const L4_META_OBJECT_LABELS: Partial<Record<string, string>> = {
  ai_table_description: '表元数据',
  ai_field_comment: '字段元数据',
  ai_metric_definition: '指标元数据',
  default_time_field: '表元数据',
  default_amount_field: '表元数据',
  default_filter_condition: '表元数据',
  sensitive_field: '字段元数据',
  deprecated_field: '字段元数据',
  sample_questions: '表元数据',
};

// ── 失败提示 & 修复建议 ───────────────────────────────────────────
const RULE_TYPE_FAILURE_INFO: Partial<Record<string, { hint: string; fix: string }>> = {
  ai_table_description: {
    hint: 'AI 选表准确性下降，问数时可能引用错误的数据源或无法理解表的业务含义',
    fix: '在数据库 DDL 中为该表添加 COMMENT，说明表的业务用途、数据来源和主要字段含义（建议 20 字以上，包含中文）',
  },
};

// ── 字段画像标签（match_condition.column_tags）────────────────────
const COLUMN_TAGS = [
  { value: 'candidate_primary_key', label: '候选主键' },
  { value: 'business_primary_key',  label: '业务主键' },
  { value: 'default_time_column',   label: '默认时间字段' },
  { value: 'default_amount_column', label: '默认金额字段' },
  { value: 'ai_recommended',        label: 'AI 推荐字段' },
] as const;

// ── 匹配范围 ──────────────────────────────────────────────────────
type MatchScope = 'table' | 'column' | 'ddl';

interface MatchFormState {
  scope: MatchScope;
  column_tags: string[];
  data_type_contains: string;
}

function matchConditionToForm(mc: Record<string, unknown>): MatchFormState {
  const rawScope = mc.scope as string;
  const scope: MatchScope = rawScope === 'column' ? 'column' : rawScope === 'ddl' ? 'ddl' : 'table';
  const tags = (mc.column_tags as string[]) || [];
  const filter = (mc.column_filter as Record<string, unknown>) || {};
  const dtc = ((filter.data_type_contains as string[]) || []).join(', ');
  return { scope, column_tags: tags, data_type_contains: dtc };
}

function matchFormToCondition(mf: MatchFormState): Record<string, unknown> {
  if (mf.scope === 'table') return { scope: 'table' };
  if (mf.scope === 'ddl')   return { scope: 'ddl' };
  const cond: Record<string, unknown> = { scope: 'column' };
  if (mf.column_tags.length) cond.column_tags = mf.column_tags;
  const dtc = mf.data_type_contains.split(',').map(s => s.trim()).filter(Boolean);
  if (dtc.length) cond.column_filter = { data_type_contains: dtc };
  return cond;
}

const getErrorMessage = (e: unknown, fallback = '操作失败') =>
  e instanceof Error ? e.message : fallback;

const DEFAULT_FORM: CreateTemplateInput = {
  name: '', dimension: '', rule_type: '', default_config: {}, match_condition: {},
  severity: 'MEDIUM', enabled: true, rule_package: '', block_strategy: 'alert',
};
const DEFAULT_MATCH: MatchFormState = { scope: 'table', column_tags: [], data_type_contains: '' };

// ── 分节标题组件 ──────────────────────────────────────────────────
function SectionHeader({ icon, label, violet }: { icon: string; label: string; violet?: boolean }) {
  return (
    <div className="flex items-center gap-2 mb-4">
      <i className={`${icon} text-sm ${violet ? 'text-violet-400' : 'text-slate-400'}`} />
      <span className={`text-[11px] font-semibold uppercase tracking-wide ${violet ? 'text-violet-500' : 'text-slate-500'}`}>
        {label}
      </span>
      <div className={`flex-1 h-px ${violet ? 'bg-violet-100' : 'bg-slate-100'}`} />
    </div>
  );
}

export default function DqcTemplateDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isNew = id === 'new';

  const [template, setTemplate] = useState<DqcRuleTemplate | null>(null);
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [formError, setFormError] = useState('');

  const [form, setForm] = useState<CreateTemplateInput>({ ...DEFAULT_FORM });
  const [matchForm, setMatchForm] = useState<MatchFormState>({ ...DEFAULT_MATCH });
  const [aiInput, setAiInput] = useState('');
  const [aiParsing, setAiParsing] = useState(false);
  const [aiReasoning, setAiReasoning] = useState('');

  const load = useCallback(async () => {
    if (isNew || !id) return;
    setLoading(true);
    try {
      const t = await getTemplate(Number(id));
      setTemplate(t);
      setForm({
        name: t.name,
        description: t.description ?? '',
        dimension: t.dimension,
        rule_type: t.rule_type,
        default_config: { ...t.default_config },
        match_condition: { ...t.match_condition },
        severity: t.severity,
        enabled: t.enabled,
        rule_package: t.rule_package ?? '',
        block_strategy: t.block_strategy ?? 'alert',
      });
      setMatchForm(matchConditionToForm(t.match_condition));
    } catch (e) {
      setError(getErrorMessage(e, '加载模板失败'));
    } finally {
      setLoading(false);
    }
  }, [id, isNew]);

  useEffect(() => { load(); }, [load]);

  // isNew 时选完 rule_type 自动预填
  useEffect(() => {
    if (!isNew || !form.rule_type) return;
    const defaults = RULE_TYPE_DEFAULTS[form.rule_type];
    if (!defaults) return;
    setForm(f => ({
      ...f,
      name: f.name || defaults.name,
      description: f.description || defaults.description,
      severity: defaults.severity,
      block_strategy: defaults.block_strategy,
      default_config: { ...defaults.default_config, ...f.default_config },
    }));
    if (defaults.match_scope) {
      setMatchForm(m => ({ ...m, scope: defaults.match_scope! }));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.rule_type, isNew]);

  const handleAiParse = async () => {
    if (!aiInput.trim()) return;
    setAiParsing(true);
    setAiReasoning('');
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

  const handleSave = async () => {
    if (!form.name.trim()) { setFormError('请填写模板名称'); return; }
    if (isNew && !form.rule_package) { setFormError('请选择规则包'); return; }
    if (isNew && !form.dimension)    { setFormError('请选择维度'); return; }
    if (isNew && !form.rule_type)    { setFormError('请选择规则类型'); return; }

    const matchCondition = matchFormToCondition(matchForm);
    setSaving(true);
    setFormError('');
    try {
      if (!isNew && template) {
        const payload: UpdateTemplateInput = {};
        if (form.name !== template.name) payload.name = form.name;
        if ((form.description ?? '') !== (template.description ?? '')) payload.description = form.description;
        if (JSON.stringify(form.default_config) !== JSON.stringify(template.default_config)) payload.default_config = form.default_config;
        if (JSON.stringify(matchCondition) !== JSON.stringify(template.match_condition)) payload.match_condition = matchCondition;
        if (form.severity !== template.severity) payload.severity = form.severity;
        if (form.enabled !== template.enabled) payload.enabled = form.enabled;
        if ((form.rule_package ?? '') !== (template.rule_package ?? '')) payload.rule_package = form.rule_package;
        if ((form.block_strategy ?? '') !== (template.block_strategy ?? '')) payload.block_strategy = form.block_strategy;
        await updateTemplate(template.id, payload);
      } else {
        await createTemplate({ ...form, match_condition: matchCondition });
      }
      navigate('/governance/dqc/templates');
    } catch (e) {
      setFormError(getErrorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const configFields = RULE_CONFIG_FIELDS[form.rule_type] ?? [];

  // 阻断 AI 文案（随匹配范围变化）
  const blockAiDesc = matchForm.scope === 'column'
    ? 'AI Agent 不得引用此字段'
    : matchForm.scope === 'ddl'
      ? 'AI Agent 不得将该对象纳入问数上下文'
      : 'AI Agent 不得引用此表';

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50">
        <div className="bg-white border-b border-slate-200 px-8 py-5">
          <div className="max-w-6xl mx-auto">
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-list-check text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">数据质量监控</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7 mb-4">规则模板</p>
            <DqcTabs />
          </div>
        </div>
        <div className="flex items-center justify-center py-32 text-slate-400">
          <i className="ri-loader-4-line animate-spin mr-2" />加载中...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-slate-50">
        <div className="bg-white border-b border-slate-200 px-8 py-5">
          <div className="max-w-6xl mx-auto">
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-list-check text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">数据质量监控</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7 mb-4">规则模板</p>
            <DqcTabs />
          </div>
        </div>
        <div className="flex flex-col items-center justify-center py-32 gap-3 text-slate-400">
          <i className="ri-error-warning-line text-2xl text-red-400" />
          <p className="text-sm">{error}</p>
          <button onClick={() => navigate('/governance/dqc/templates')} className="text-xs text-slate-500 hover:text-slate-700 underline">
            返回列表
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 页头 */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-list-check text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">数据质量监控</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7 mb-4">规则模板</p>
          <DqcTabs />
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-8 py-8">
        {/* 面包屑 + 操作按钮 */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <button
              onClick={() => navigate('/governance/dqc/templates')}
              className="hover:text-slate-700 transition-colors"
            >
              规则模板
            </button>
            <i className="ri-arrow-right-s-line" />
            <span className="text-slate-700 font-medium">
              {isNew
                ? (form.rule_package && form.rule_type ? '配置模板' : '新建模板')
                : (template?.name ?? '编辑模板')}
            </span>
            {!isNew && form.dimension && (
              <>
                <span className="text-slate-200">·</span>
                <span className="text-xs">{DIMENSION_LABELS[form.dimension as Dimension] ?? form.dimension}</span>
                <span className="text-slate-200">·</span>
                <span className="text-xs">
                  {matchForm.scope === 'column' ? '列级' : matchForm.scope === 'ddl' ? 'DDL 级' : '表级'}
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate('/governance/dqc/templates')}
              className="px-4 py-1.5 text-xs text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
            >
              取消
            </button>
            {(!isNew || (form.rule_package && form.rule_type)) && (
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-1.5 text-xs font-medium bg-slate-800 text-white rounded-lg hover:bg-slate-700 disabled:opacity-50 transition-colors"
              >
                {saving ? '保存中...' : isNew ? '创建模板' : '保存修改'}
              </button>
            )}
          </div>
        </div>

        {/* 错误提示 */}
        {formError && (
          <div className="flex items-center gap-2 mb-4 px-3 py-2 bg-red-50 border border-red-100 rounded-lg">
            <i className="ri-error-warning-line text-red-400 text-sm" />
            <span className="text-xs text-red-600">{formError}</span>
          </div>
        )}

        {/* ── Step 1: 选择规则包 (isNew only) ── */}
        {isNew && !form.rule_package && (
          <div className="bg-white rounded-xl border border-slate-200 px-8 py-8">
            <SectionHeader icon="ri-folder-line" label="选择规则包" />
            <div className="grid grid-cols-2 gap-3">
              {(['L1', 'L2', 'L3', 'L4'] as const).map(pkg => (
                <button
                  key={pkg}
                  type="button"
                  onClick={() => setForm(f => ({ ...f, rule_package: pkg }))}
                  className="flex flex-col gap-1.5 p-4 rounded-xl border border-slate-200 text-left hover:border-slate-400 hover:bg-slate-50 transition-colors group"
                >
                  <span className="text-sm font-semibold text-slate-800 group-hover:text-slate-900">
                    {RULE_PACKAGE_LABELS[pkg]}
                  </span>
                  <span className="text-[12px] text-slate-400 leading-snug">
                    {RULE_PACKAGE_DESCRIPTIONS[pkg]}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── Step 2: 选择规则类型 (isNew only) ── */}
        {isNew && form.rule_package && !form.rule_type && (
          <div className="bg-white rounded-xl border border-slate-200 px-8 py-8">
            <div className="flex items-center justify-between mb-4">
              <SectionHeader icon="ri-list-check" label={`选择规则类型 · ${RULE_PACKAGE_LABELS[form.rule_package]}`} />
              <button
                type="button"
                onClick={() => setForm(f => ({ ...f, rule_package: '' }))}
                className="text-xs text-slate-400 hover:text-slate-600 flex items-center gap-1 shrink-0 mb-4"
              >
                <i className="ri-arrow-left-s-line" />重选规则包
              </button>
            </div>
            <div className="space-y-1.5">
              {RULE_PACKAGE_RULE_TYPES[form.rule_package].map(rt => (
                <button
                  key={rt}
                  type="button"
                  onClick={() => {
                    const dim = RULE_TYPE_DIMENSION_MAP[rt] ?? '';
                    setForm(f => ({ ...f, rule_type: rt, dimension: dim }));
                  }}
                  className="w-full flex items-center justify-between px-4 py-3 rounded-lg border border-slate-200 text-left hover:border-slate-400 hover:bg-slate-50 transition-colors group"
                >
                  <span className="text-sm text-slate-700 group-hover:text-slate-900">
                    {RULE_TYPE_LABELS[rt] ?? rt}
                  </span>
                  <i className="ri-arrow-right-s-line text-slate-300 group-hover:text-slate-500" />
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── 主表单：编辑 or 新建已选包+类型 ── */}
        {(!isNew || (form.rule_package && form.rule_type)) && (
        <div className="bg-white rounded-xl border border-slate-200 px-8 py-8 space-y-8">

          {/* ── Section 1: 基础信息 ── */}
          <div>
            <SectionHeader icon="ri-file-info-line" label="基础信息" />
            <div className="space-y-4">
              {/* isNew: 规则包 + 类型已选，显示 badge + 重选入口 */}
              {isNew && form.rule_package && form.rule_type && (
                <div className="flex items-center gap-2 py-1 flex-wrap">
                  <span className="px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded-full font-medium">
                    {RULE_PACKAGE_LABELS[form.rule_package]}
                  </span>
                  <span className="text-slate-300">/</span>
                  <span className="px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded-full font-medium">
                    {RULE_TYPE_LABELS[form.rule_type as RuleType] ?? form.rule_type}
                  </span>
                  <button
                    type="button"
                    onClick={() => setForm(f => ({ ...f, rule_type: '', dimension: '' }))}
                    className="text-xs text-slate-400 hover:text-slate-600 ml-1"
                  >
                    重选
                  </button>
                </div>
              )}
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  模板名称 <span className="text-red-400">*</span>
                </label>
                <input
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
                  placeholder="如：字段空值率监控"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">描述</label>
                <input
                  value={form.description ?? ''}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
                  placeholder="说明此模板的用途，会展示在规则列表中"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                {!isNew && (
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">规则包</label>
                    <select
                      value={form.rule_package ?? ''}
                      onChange={e => setForm(f => ({ ...f, rule_package: e.target.value }))}
                      className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
                    >
                      <option value="">不归属</option>
                      {Object.entries(RULE_PACKAGE_LABELS).map(([k, v]) => (
                        <option key={k} value={k}>{v}</option>
                      ))}
                    </select>
                  </div>
                )}
                <div className={isNew ? 'col-span-2' : ''}>
                  <label className="block text-xs font-medium text-slate-600 mb-1">严重级别</label>
                  <select
                    value={form.severity}
                    onChange={e => setForm(f => ({ ...f, severity: e.target.value }))}
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
                  >
                    <option value="LOW">低</option>
                    <option value="MEDIUM">中</option>
                    <option value="HIGH">高</option>
                    <option value="CRITICAL">严重</option>
                  </select>
                </div>
              </div>
            </div>
          </div>

          {/* ── Section 2: 执行策略 ── */}
          <div>
            <SectionHeader icon="ri-settings-3-line" label="执行策略" />
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-2">检查失败时的处理方式</label>
                <div className="grid grid-cols-2 gap-2">
                  {([
                    { value: 'record_only', icon: 'ri-file-list-line',      label: '仅记录',  desc: '记录结果，不触发告警' },
                    { value: 'alert',       icon: 'ri-alarm-warning-line',  label: '告警',    desc: '推送告警，流程继续运行' },
                    { value: 'blocking',    icon: 'ri-spam-2-line',         label: '阻断',    desc: '阻断下游数据流水线' },
                    { value: 'block_ai',    icon: 'ri-robot-2-line',        label: '阻断 AI', desc: blockAiDesc },
                  ] as const).map(opt => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setForm(f => ({ ...f, block_strategy: opt.value }))}
                      className={`flex items-start gap-2.5 p-3 rounded-lg border text-left transition-colors ${
                        form.block_strategy === opt.value
                          ? 'border-slate-700 bg-slate-50'
                          : 'border-slate-200 hover:border-slate-300 bg-white'
                      }`}
                    >
                      <i className={`${opt.icon} text-sm mt-0.5 shrink-0 ${form.block_strategy === opt.value ? 'text-slate-700' : 'text-slate-400'}`} />
                      <div>
                        <div className={`text-xs font-medium ${form.block_strategy === opt.value ? 'text-slate-800' : 'text-slate-600'}`}>
                          {opt.label}
                        </div>
                        <div className="text-[11px] text-slate-400 mt-0.5 leading-tight">{opt.desc}</div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex items-start justify-between py-1">
                <div>
                  <div className="text-xs font-medium text-slate-600">启用此模板</div>
                  <div className="text-[11px] text-slate-400 mt-0.5 max-w-sm">
                    关闭后，不再为新资产自动生成检查规则；已生成的派生规则仍保留并按自身状态执行。
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setForm(f => ({ ...f, enabled: !f.enabled }))}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 mt-0.5 ${
                    form.enabled ? 'bg-emerald-500' : 'bg-slate-300'
                  }`}
                >
                  <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                    form.enabled ? 'translate-x-4' : 'translate-x-1'
                  }`} />
                </button>
              </div>
            </div>
          </div>

          {/* ── Section 3: 专属参数 ── */}
          {form.rule_type && (
            <div>
              <SectionHeader icon="ri-sliders-2-line" label={`专属参数 · ${RULE_TYPE_LABELS[form.rule_type as RuleType] ?? form.rule_type}`} />
              <div className="space-y-4">
                {/* AI 自动填参 */}
                <div className="p-4 bg-gradient-to-r from-indigo-50 to-blue-50 border border-indigo-100 rounded-lg">
                  <div className="flex items-center gap-1.5 mb-2">
                    <i className="ri-sparkling-line text-indigo-500 text-sm" />
                    <span className="text-[11px] font-medium text-indigo-700">AI 自动填参</span>
                    <span className="text-[11px] text-indigo-400 ml-1">用自然语言描述阈值要求</span>
                  </div>
                  <div className="flex gap-2 items-start">
                    <textarea
                      rows={3}
                      value={aiInput}
                      onChange={e => setAiInput(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter' && e.metaKey && !aiParsing) handleAiParse(); }}
                      placeholder="如：空值率不超过 5%、最多允许 1% 重复..."
                      className="flex-1 border border-indigo-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-300 bg-white placeholder:text-slate-400 resize-none leading-relaxed"
                    />
                    <button
                      onClick={handleAiParse}
                      disabled={aiParsing || !aiInput.trim()}
                      className="px-3 py-1.5 text-xs font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-50 transition-colors whitespace-nowrap"
                    >
                      {aiParsing ? '解析中...' : '填参'}
                    </button>
                  </div>
                  {aiReasoning && (
                    <div className="mt-2 text-[11px] text-indigo-600 flex items-start gap-1.5">
                      <i className="ri-check-line mt-0.5 shrink-0" />
                      <span>AI 理解：{aiReasoning}</span>
                    </div>
                  )}
                </div>

                {/* 具体参数字段 */}
                {configFields.length > 0 ? (
                  <div className="space-y-4">
                    {configFields.map(fd => (
                      <div key={fd.key}>
                        <label className="block text-xs font-medium text-slate-600 mb-1">{fd.label}</label>
                        {fd.type === 'select' ? (
                          <select
                            value={(form.default_config as Record<string, string>)[fd.key] ?? ''}
                            onChange={e => setForm(f => ({
                              ...f,
                              default_config: { ...f.default_config, [fd.key]: e.target.value || undefined },
                            }))}
                            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
                          >
                            <option value="">不设置</option>
                            {fd.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                          </select>
                        ) : (
                          <input
                            type={fd.type}
                            value={(form.default_config as Record<string, string | number>)[fd.key] ?? ''}
                            onChange={e => {
                              const val = fd.type === 'number' && e.target.value !== ''
                                ? Number(e.target.value) : e.target.value || undefined;
                              setForm(f => ({ ...f, default_config: { ...f.default_config, [fd.key]: val } }));
                            }}
                            placeholder={fd.placeholder}
                            min={fd.min} max={fd.max} step={fd.step}
                            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
                          />
                        )}
                        {fd.help && <p className="text-[11px] text-slate-400 mt-1">{fd.help}</p>}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-[11px] text-slate-400 italic">该规则类型无需额外参数</p>
                )}

                {!isNew && template && (template.unmodified_rules_count ?? 0) > 0 && (
                  <div className="px-3 py-2 bg-blue-50 border border-blue-200 text-blue-700 text-xs rounded-lg">
                    修改以上参数将同步更新 {template.unmodified_rules_count} 条未被手动调整的派生规则
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Section 4: 匹配范围 ── */}
          <div>
            <SectionHeader icon="ri-focus-3-line" label="匹配范围" />
            <div className="space-y-4">
              {/* L4 规则：固定显示元数据对象 */}
              {form.rule_package === 'L4' && L4_META_OBJECT_LABELS[form.rule_type] ? (
                <div className="flex items-center gap-2">
                  <label className="text-xs font-medium text-slate-600">检查对象</label>
                  <span className="px-2.5 py-1 bg-violet-50 border border-violet-200 text-violet-700 text-xs rounded-full font-medium">
                    {L4_META_OBJECT_LABELS[form.rule_type]}
                  </span>
                  <span className="text-[11px] text-slate-400">— 此规则仅针对元数据，无需配置匹配范围</span>
                </div>
              ) : (
              <>
              {/* 对象类型 Tab */}
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-2">检查对象类型</label>
                <div className="flex items-center gap-1 p-1 bg-slate-100 rounded-lg w-fit">
                  {(['table', 'column', 'ddl'] as MatchScope[]).map(s => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setMatchForm(m => ({ ...m, scope: s, column_tags: [] }))}
                      className={`px-3 py-1 text-xs rounded-md transition-colors ${
                        matchForm.scope === s
                          ? 'bg-white text-slate-800 shadow-sm font-medium'
                          : 'text-slate-500 hover:text-slate-700'
                      }`}
                    >
                      {s === 'table' ? '表级' : s === 'column' ? '列级' : 'DDL 级'}
                    </button>
                  ))}
                </div>
                {matchForm.scope === 'table' && (
                  <p className="text-[11px] text-slate-400 mt-2">
                    对每张纳入监控的表自动生成一条规则，适合行数监控、新鲜度等全表检测。
                  </p>
                )}
                {matchForm.scope === 'ddl' && (
                  <p className="text-[11px] text-slate-400 mt-2">
                    检查 DDL 元数据（字段注释覆盖率、表描述、敏感字段标注等），适合 AI Ready 类规则。
                  </p>
                )}
              </div>

              {/* 列级：字段画像标签 */}
              {matchForm.scope === 'column' && (
                <div className="pl-4 border-l-2 border-slate-100 space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-2">
                      字段画像标签
                      <span className="text-slate-400 font-normal ml-1.5">— 命中任一标签的字段将自动生成一条派生规则</span>
                    </label>
                    <div className="flex flex-wrap gap-2">
                      {COLUMN_TAGS.map(tag => {
                        const active = matchForm.column_tags.includes(tag.value);
                        return (
                          <button
                            key={tag.value}
                            type="button"
                            onClick={() => setMatchForm(m => ({
                              ...m,
                              column_tags: active
                                ? m.column_tags.filter(t => t !== tag.value)
                                : [...m.column_tags, tag.value],
                            }))}
                            className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                              active
                                ? 'bg-slate-800 text-white border-slate-800'
                                : 'bg-white text-slate-600 border-slate-200 hover:border-slate-400'
                            }`}
                          >
                            {tag.label}
                          </button>
                        );
                      })}
                    </div>
                    {matchForm.column_tags.length === 0 && (
                      <p className="text-[11px] text-amber-600 mt-1.5 flex items-center gap-1">
                        <i className="ri-alert-line text-xs" />
                        未选择任何标签，模板将不会自动匹配字段
                      </p>
                    )}
                  </div>
                  <div>
                    <label className="block text-[11px] text-slate-500 mb-1">字段类型包含（可选，逗号分隔）</label>
                    <input
                      value={matchForm.data_type_contains}
                      onChange={e => setMatchForm(m => ({ ...m, data_type_contains: e.target.value }))}
                      placeholder="如 varchar, text"
                      className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-slate-400"
                    />
                  </div>
                </div>
              )}
            </>
          )}
            </div>
          </div>

          {/* ── Section 5: AI Ready 影响 ── */}
          {(form.dimension === 'ai_ready' || form.rule_package === 'L4' || form.block_strategy === 'block_ai') && (
            <div>
              <SectionHeader icon="ri-robot-line" label="AI Ready 影响" violet />
              <div className="p-4 bg-violet-50 border border-violet-100 rounded-lg space-y-2">
                {form.rule_type === 'ai_field_comment' && (
                  <p className="text-[11px] text-violet-700">字段注释覆盖率不足，会降低 AI 理解字段语义的准确性，导致 NL→SQL 翻译偏差。</p>
                )}
                {form.rule_type === 'ai_table_description' && (
                  <p className="text-[11px] text-violet-700">表描述缺失影响 AI 选表准确性，问数时可能引用错误的数据源。</p>
                )}
                {form.rule_type === 'ai_metric_definition' && (
                  <p className="text-[11px] text-violet-700">指标语义未定义，AI 无法正确计算或解释派生指标，指标问答结果不可信。</p>
                )}
                {form.rule_type === 'sensitive_field' && (
                  <p className="text-[11px] text-violet-700">敏感字段未标注时，AI 回答可能无意暴露手机号、身份证等隐私数据。</p>
                )}
                {!['ai_field_comment', 'ai_table_description', 'ai_metric_definition', 'sensitive_field'].includes(form.rule_type) && (
                  <p className="text-[11px] text-violet-700">
                    此规则纳入 L4 AI Ready 包，检查失败时会拉低该资产的 AI 就绪度评分。
                  </p>
                )}
                {form.block_strategy === 'block_ai' && (
                  <div className="flex items-center gap-1.5 pt-2 border-t border-violet-200 mt-1">
                    <i className="ri-error-warning-line text-violet-500 text-xs shrink-0" />
                    <p className="text-[11px] text-violet-700 font-medium">
                      当前策略：阻断 AI — 检查失败时 {blockAiDesc}。
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Section 6: 失败提示 & 修复建议 ── */}
          {RULE_TYPE_FAILURE_INFO[form.rule_type] && (
            <div>
              <SectionHeader icon="ri-tools-line" label="检查失败时" />
              <div className="space-y-3">
                <div className="flex items-start gap-3 p-3 bg-red-50 border border-red-100 rounded-lg">
                  <i className="ri-error-warning-line text-red-400 text-sm mt-0.5 shrink-0" />
                  <div>
                    <div className="text-[11px] font-medium text-red-700 mb-0.5">影响</div>
                    <p className="text-[11px] text-red-600">{RULE_TYPE_FAILURE_INFO[form.rule_type]!.hint}</p>
                  </div>
                </div>
                <div className="flex items-start gap-3 p-3 bg-emerald-50 border border-emerald-100 rounded-lg">
                  <i className="ri-tools-line text-emerald-500 text-sm mt-0.5 shrink-0" />
                  <div>
                    <div className="text-[11px] font-medium text-emerald-700 mb-0.5">修复建议</div>
                    <p className="text-[11px] text-emerald-600">{RULE_TYPE_FAILURE_INFO[form.rule_type]!.fix}</p>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
        )} {/* end 主表单 */}

        {/* 底部操作栏 */}
        {(!isNew || (form.rule_package && form.rule_type)) && (
        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={() => navigate('/governance/dqc/templates')}
            className="px-4 py-2 text-xs text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 text-xs font-medium bg-slate-800 text-white rounded-lg hover:bg-slate-700 disabled:opacity-50 transition-colors"
          >
            {saving ? '保存中...' : isNew ? '创建模板' : '保存修改'}
          </button>
        </div>
        )}
      </div>
    </div>
  );
}
