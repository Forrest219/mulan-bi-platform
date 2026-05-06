import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import DqcTabs from '../DqcTabs';

// ── 能力定义 ───────────────────────────────────────────────────

interface FieldDef {
  key: string;
  label: string;
  sublabel?: string;
  type: 'text' | 'number' | 'percent' | 'select';
  placeholder?: string;
  defaultValue?: string;
  required?: boolean;
  min?: number;
  options?: { value: string; label: string }[];
}

interface CapabilityDef {
  key: string;
  name: string;
  description: string;
  pkg: 'L1' | 'L2' | 'L3' | 'L4';
  pkgLabel: string;
  defaultSeverity: 'HIGH' | 'MEDIUM' | 'LOW';
  fields: FieldDef[];
}

const CAPABILITIES: CapabilityDef[] = [
  {
    key: 'null_rate', name: '空值率监控',
    description: '检查指定字段的空值比例，超过阈值则触发报警',
    pkg: 'L1', pkgLabel: 'L1 基础质量', defaultSeverity: 'HIGH',
    fields: [
      { key: 'table_name', label: '表名', type: 'text', placeholder: 'schema.table_name', required: true },
      { key: 'column', label: '字段名', type: 'text', placeholder: '如 order_id', required: true },
      { key: 'max_rate', label: '最大允许空值率', sublabel: '超过此比例触发报警', type: 'percent', placeholder: '5', defaultValue: '5', required: true },
    ],
  },
  {
    key: 'uniqueness', name: '唯一性监控',
    description: '检查字段（或字段组合）是否存在重复值',
    pkg: 'L1', pkgLabel: 'L1 基础质量', defaultSeverity: 'HIGH',
    fields: [
      { key: 'table_name', label: '表名', type: 'text', placeholder: 'schema.table_name', required: true },
      { key: 'columns', label: '检查字段', sublabel: '多个字段用逗号分隔', type: 'text', placeholder: '如 order_id 或 user_id,date', required: true },
    ],
  },
  {
    key: 'enum_check', name: '值域合法监控',
    description: '检查枚举类字段是否只包含预期的合法值',
    pkg: 'L1', pkgLabel: 'L1 基础质量', defaultSeverity: 'MEDIUM',
    fields: [
      { key: 'table_name', label: '表名', type: 'text', placeholder: 'schema.table_name', required: true },
      { key: 'column', label: '字段名', type: 'text', placeholder: '如 status', required: true },
      { key: 'allowed_values', label: '合法值列表', sublabel: '用英文逗号分隔', type: 'text', placeholder: '如 active,inactive,pending', required: true },
    ],
  },
  {
    key: 'freshness', name: '新鲜度监控',
    description: '检查时间字段距今是否超出允许的最大延迟',
    pkg: 'L2', pkgLabel: 'L2 时效稳定', defaultSeverity: 'HIGH',
    fields: [
      { key: 'table_name', label: '表名', type: 'text', placeholder: 'schema.table_name', required: true },
      { key: 'column', label: '时间字段', type: 'text', placeholder: '如 updated_at、created_at', required: true },
      { key: 'max_age_hours', label: '最大允许延迟', sublabel: '单位：小时', type: 'number', placeholder: '24', defaultValue: '24', required: true, min: 1 },
    ],
  },
  {
    key: 'volume_anomaly', name: '表行数异常监控',
    description: '检测表行数与历史基线的波动幅度，超出阈值则触发报警',
    pkg: 'L2', pkgLabel: 'L2 时效稳定', defaultSeverity: 'MEDIUM',
    fields: [
      { key: 'table_name', label: '表名', type: 'text', placeholder: 'schema.table_name', required: true },
      { key: 'threshold_pct', label: '波动阈值', sublabel: '超过此百分比触发报警', type: 'percent', placeholder: '20', defaultValue: '20', required: true },
      { key: 'direction', label: '关注方向', type: 'select', defaultValue: 'both', required: true, options: [
        { value: 'both', label: '涨跌都报' },
        { value: 'drop', label: '只关心下降' },
        { value: 'rise', label: '只关心上涨' },
      ]},
    ],
  },
  {
    key: 'table_count_compare', name: '跨表行数比对',
    description: '比较主表与对比表的行数，差异超出容差则触发报警',
    pkg: 'L3', pkgLabel: 'L3 业务一致性', defaultSeverity: 'HIGH',
    fields: [
      { key: 'table_name', label: '主表', type: 'text', placeholder: 'schema.table_name', required: true },
      { key: 'compare_table', label: '对比表', type: 'text', placeholder: 'schema.table_name', required: true },
      { key: 'tolerance_pct', label: '允许容差', sublabel: '行数差异百分比', type: 'percent', placeholder: '5', defaultValue: '5', required: true },
    ],
  },
  {
    key: 'ai_table_description', name: '表业务说明完整性',
    description: '检查表是否有充分的业务说明，确保 AI 选表准确',
    pkg: 'L4', pkgLabel: 'L4 AI Ready', defaultSeverity: 'HIGH',
    fields: [
      { key: 'table_name', label: '表名', type: 'text', placeholder: 'schema.table_name', required: true },
      { key: 'min_length', label: '最低字符数', sublabel: '业务说明文本最少长度', type: 'number', placeholder: '20', defaultValue: '20', required: true, min: 1 },
      { key: 'require_zh', label: '要求包含中文', type: 'select', defaultValue: 'true', required: true, options: [
        { value: 'true', label: '是' },
        { value: 'false', label: '否' },
      ]},
    ],
  },
  {
    key: 'ai_field_comment', name: '字段注释完整性',
    description: '检查表字段注释覆盖率，确保 AI 能准确理解字段语义',
    pkg: 'L4', pkgLabel: 'L4 AI Ready', defaultSeverity: 'MEDIUM',
    fields: [
      { key: 'table_name', label: '表名', type: 'text', placeholder: 'schema.table_name', required: true },
      { key: 'min_coverage', label: '最低注释覆盖率', sublabel: '字段需有注释的最低比例', type: 'percent', placeholder: '80', defaultValue: '80', required: true },
    ],
  },
];

const PKG_GROUPS = ['L1', 'L2', 'L3', 'L4'] as const;
const PKG_LABELS: Record<string, string> = {
  L1: 'L1 基础质量', L2: 'L2 时效稳定', L3: 'L3 业务一致性', L4: 'L4 AI Ready',
};
const PKG_ICONS: Record<string, string> = {
  L1: 'ri-shield-check-line', L2: 'ri-time-line',
  L3: 'ri-git-merge-line', L4: 'ri-robot-line',
};
const SEVERITY_LABELS = { HIGH: '高', MEDIUM: '中', LOW: '低' };

// ── 组件 ───────────────────────────────────────────────────────

export default function CreateRulePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [capability, setCapability] = useState<CapabilityDef | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [severity, setSeverity] = useState<'HIGH' | 'MEDIUM' | 'LOW'>('HIGH');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    const key = searchParams.get('capability');
    if (key) {
      const cap = CAPABILITIES.find(c => c.key === key);
      if (cap) selectCapability(cap);
    }
  }, []);

  const selectCapability = (cap: CapabilityDef) => {
    setCapability(cap);
    setSeverity(cap.defaultSeverity);
    const defaults: Record<string, string> = {};
    cap.fields.forEach(f => { if (f.defaultValue) defaults[f.key] = f.defaultValue; });
    setForm(defaults);
    setError('');
  };

  const handleSubmit = async () => {
    if (!capability) return;

    // 前端必填校验
    for (const f of capability.fields) {
      if (f.required && !form[f.key]?.trim()) {
        setError(`「${f.label}」不能为空`);
        return;
      }
    }

    setSaving(true);
    setError('');
    try {
      // 构建 rule_config
      const config: Record<string, unknown> = {};
      for (const f of capability.fields) {
        if (f.key === 'table_name') continue;
        const val = form[f.key];
        if (!val) continue;
        if (f.type === 'number') config[f.key] = Number(val);
        else if (f.type === 'percent') config[f.key] = Number(val) / 100;
        else if (f.key === 'columns') config[f.key] = val.split(',').map(s => s.trim());
        else if (f.key === 'allowed_values') config[f.key] = val.split(',').map(s => s.trim());
        else config[f.key] = val;
      }

      const tableName = form['table_name'] || '';
      const [schema, table] = tableName.includes('.')
        ? tableName.split('.') : ['public', tableName];

      const res = await fetch('/api/dqc/rules/quick-create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          table_name: table,
          schema_name: schema,
          rule_type: capability.key,
          rule_config: config,
          severity,
          name: buildRuleName(capability, form),
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `创建失败 (${res.status})`);
      }

      setSuccess('规则创建成功');
      setTimeout(() => navigate('/governance/dqc/derived-rules'), 1200);
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 页头 */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-list-check text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">数据质量监控</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7 mb-4">数据质量规则与检查管理</p>
          <DqcTabs />
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-8 py-8">
        {/* 返回 */}
        <button
          onClick={() => capability ? setCapability(null) : navigate('/governance/dqc/templates')}
          className="flex items-center gap-1.5 text-[12px] text-slate-400 hover:text-slate-700 mb-6 transition-colors"
        >
          <i className="ri-arrow-left-line" />
          {capability ? '重新选择能力' : '返回检查能力库'}
        </button>

        {/* ── Step 1: 选择能力 ── */}
        {!capability && (
          <>
            <div className="mb-6">
              <h2 className="text-[17px] font-semibold text-slate-800 mb-1">创建检查规则</h2>
              <p className="text-[13px] text-slate-400">选择一种检查能力，填写参数后生成规则</p>
            </div>

            <div className="space-y-5">
              {PKG_GROUPS.map(pkg => {
                const caps = CAPABILITIES.filter(c => c.pkg === pkg);
                return (
                  <div key={pkg}>
                    <div className="flex items-center gap-2 mb-2.5">
                      <i className={`${PKG_ICONS[pkg]} text-slate-400 text-[13px]`} />
                      <span className="text-[12px] font-semibold text-slate-500 uppercase tracking-wide">
                        {PKG_LABELS[pkg]}
                      </span>
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                      {caps.map(cap => (
                        <button
                          key={cap.key}
                          onClick={() => selectCapability(cap)}
                          className="text-left p-4 bg-white border border-slate-200 rounded-xl hover:border-slate-400 hover:shadow-sm transition-all group"
                        >
                          <div className="font-medium text-[13px] text-slate-800 mb-1 group-hover:text-slate-900">
                            {cap.name}
                          </div>
                          <p className="text-[11px] text-slate-400 leading-relaxed line-clamp-2">
                            {cap.description}
                          </p>
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}

        {/* ── Step 2: 填写参数 ── */}
        {capability && (
          <>
            <div className="mb-6">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-500 font-medium">
                  {capability.pkgLabel}
                </span>
                <h2 className="text-[17px] font-semibold text-slate-800">{capability.name}</h2>
              </div>
              <p className="text-[13px] text-slate-400">{capability.description}</p>
            </div>

            {error && (
              <div className="flex items-center gap-2 p-3 mb-4 bg-red-50 border border-red-100 rounded-lg text-[12px] text-red-600">
                <i className="ri-error-warning-line shrink-0" />{error}
              </div>
            )}
            {success && (
              <div className="flex items-center gap-2 p-3 mb-4 bg-emerald-50 border border-emerald-100 rounded-lg text-[12px] text-emerald-600">
                <i className="ri-checkbox-circle-line shrink-0" />{success}
              </div>
            )}

            <div className="bg-white border border-slate-200 rounded-xl divide-y divide-slate-100">
              {/* 能力参数字段 */}
              {capability.fields.map(f => (
                <div key={f.key} className="px-5 py-4 flex items-start gap-6">
                  <div className="w-36 shrink-0 pt-0.5">
                    <div className="text-[12px] font-medium text-slate-700">{f.label}</div>
                    {f.sublabel && <div className="text-[11px] text-slate-400 mt-0.5">{f.sublabel}</div>}
                  </div>
                  <div className="flex-1">
                    {f.type === 'select' ? (
                      <select
                        value={form[f.key] ?? f.defaultValue ?? ''}
                        onChange={e => setForm(p => ({ ...p, [f.key]: e.target.value }))}
                        className="w-full max-w-xs border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-700 focus:outline-none focus:ring-1 focus:ring-slate-400"
                      >
                        {f.options?.map(o => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                    ) : f.type === 'percent' ? (
                      <div className="flex items-center gap-2 max-w-xs">
                        <input
                          type="number"
                          value={form[f.key] ?? ''}
                          onChange={e => setForm(p => ({ ...p, [f.key]: e.target.value }))}
                          placeholder={f.placeholder}
                          min={0} max={100} step={1}
                          className="w-24 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-700 focus:outline-none focus:ring-1 focus:ring-slate-400"
                        />
                        <span className="text-[12px] text-slate-400">%</span>
                      </div>
                    ) : (
                      <input
                        type={f.type === 'number' ? 'number' : 'text'}
                        value={form[f.key] ?? ''}
                        onChange={e => setForm(p => ({ ...p, [f.key]: e.target.value }))}
                        placeholder={f.placeholder}
                        min={f.min}
                        className="w-full max-w-sm border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-700 focus:outline-none focus:ring-1 focus:ring-slate-400"
                      />
                    )}
                  </div>
                </div>
              ))}

              {/* 严重级别 */}
              <div className="px-5 py-4 flex items-start gap-6">
                <div className="w-36 shrink-0 pt-0.5">
                  <div className="text-[12px] font-medium text-slate-700">严重级别</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">触发报警的优先级</div>
                </div>
                <div className="flex gap-2">
                  {(['HIGH', 'MEDIUM', 'LOW'] as const).map(s => (
                    <button
                      key={s}
                      onClick={() => setSeverity(s)}
                      className={`px-3 py-1.5 text-[11px] font-medium rounded-lg border transition-colors ${
                        severity === s
                          ? s === 'HIGH' ? 'bg-red-50 border-red-200 text-red-600'
                            : s === 'MEDIUM' ? 'bg-amber-50 border-amber-200 text-amber-600'
                            : 'bg-blue-50 border-blue-200 text-blue-600'
                          : 'bg-white border-slate-200 text-slate-400 hover:border-slate-300'
                      }`}
                    >
                      {SEVERITY_LABELS[s]}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* 操作按钮 */}
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setCapability(null)}
                className="px-4 py-2.5 text-[13px] text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleSubmit}
                disabled={saving}
                className="flex-1 flex items-center justify-center gap-2 py-2.5 text-[13px] font-medium bg-slate-800 text-white rounded-lg hover:bg-slate-700 disabled:opacity-50 transition-colors"
              >
                {saving ? <><i className="ri-loader-4-line animate-spin" />创建中…</> : '创建规则'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── 规则名称自动生成 ──────────────────────────────────────────

function buildRuleName(cap: CapabilityDef, form: Record<string, string>): string {
  const table = form['table_name'] || '?';
  const col = form['column'] || form['columns'] || '';
  switch (cap.key) {
    case 'null_rate':        return `${table}.${col} 空值率监控`;
    case 'uniqueness':       return `${table}.${col} 唯一性监控`;
    case 'enum_check':       return `${table}.${col} 值域合法监控`;
    case 'freshness':        return `${table} 新鲜度监控 (${col})`;
    case 'volume_anomaly':   return `${table} 行数异常监控`;
    case 'table_count_compare': return `${table} 跨表行数比对`;
    case 'ai_table_description': return `${table} 表业务说明完整性`;
    case 'ai_field_comment': return `${table} 字段注释完整性`;
    default: return `${table} ${cap.name}`;
  }
}
