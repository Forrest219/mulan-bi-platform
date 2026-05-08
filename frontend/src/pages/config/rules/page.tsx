import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../../context/AuthContext';
import {
  listRules, toggleRule, createRule, deleteRule, dryRunRule,
  type RuleItem, type CreateRulePayload,
} from '../../../api/rules';
import { ConfirmModal } from '../../../components/ConfirmModal';

// ── 常量 ──────────────────────────────────────────────────────────────────────

const DB_TYPES   = ['ALL', 'MySQL', 'StarRocks', 'SQL Server'];
const LEVELS     = ['ALL', 'HIGH', 'MEDIUM', 'LOW', 'critical', 'high', 'medium', 'low'];
const STATUSES   = [
  { value: '', label: '全部状态' },
  { value: 'enabled', label: '已启用' },
  { value: 'disabled', label: '已禁用' },
];

const LEVEL_STYLE: Record<string, string> = {
  HIGH:     'bg-red-50 text-red-700 border-red-200',
  critical: 'bg-red-50 text-red-700 border-red-200',
  high:     'bg-orange-50 text-orange-700 border-orange-200',
  MEDIUM:   'bg-amber-50 text-amber-700 border-amber-200',
  medium:   'bg-amber-50 text-amber-700 border-amber-200',
  LOW:      'bg-slate-50 text-slate-600 border-slate-200',
  low:      'bg-slate-50 text-slate-600 border-slate-200',
};

function LevelBadge({ level }: { level: string }) {
  const cls = LEVEL_STYLE[level] ?? LEVEL_STYLE.LOW;
  return (
    <span className={`inline-block px-2 py-0.5 text-[11px] rounded border ${cls}`}>{level}</span>
  );
}

// ── 新建规则 Modal ─────────────────────────────────────────────────────────────

const EMPTY_FORM: CreateRulePayload = {
  id: '', name: '', level: 'HIGH', category: '', description: '', suggestion: '', db_type: 'MySQL', scene_type: 'ALL', display_group: '',
};

function CreateRuleModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<CreateRulePayload>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const set = (k: keyof CreateRulePayload) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setForm(f => ({ ...f, [k]: e.target.value }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.id.trim() || !form.name.trim() || !form.description.trim()) {
      setError('规则 ID、名称、描述不能为空');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await createRule(form);
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '创建失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <h2 className="text-base font-semibold text-slate-800">新建自定义规则</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><i className="ri-close-line text-xl" /></button>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">规则 ID *</label>
              <input value={form.id} onChange={set('id')} placeholder="如 RULE_CUSTOM_001"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">规则名称 *</label>
              <input value={form.name} onChange={set('name')} placeholder="简短描述"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">数据库类型</label>
              <select value={form.db_type} onChange={set('db_type')}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                {['MySQL', 'StarRocks', 'SQL Server'].map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">级别</label>
              <select value={form.level} onChange={set('level')}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                {['HIGH', 'MEDIUM', 'LOW'].map(l => <option key={l} value={l}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">分类</label>
              <input value={form.category} onChange={set('category')} placeholder="如 Naming"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">场景类型</label>
              <input value={form.scene_type} onChange={set('scene_type')} placeholder="ALL / ODS / DWD …"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">规则描述 *</label>
            <textarea value={form.description} onChange={set('description')} rows={3}
              placeholder="此规则检查什么，违反条件是什么"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
          </div>
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">修复建议</label>
            <textarea value={form.suggestion} onChange={set('suggestion')} rows={2}
              placeholder="如何修复此违规"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
          </div>
          {error && <p className="text-[12px] text-red-500">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-[12px] text-slate-600 hover:text-slate-800">取消</button>
            <button type="submit" disabled={saving}
              className="px-4 py-2 text-[12px] bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
              {saving ? '创建中…' : '创建规则'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── 干运行面板 ─────────────────────────────────────────────────────────────────

function DryRunPanel({ rule, onClose }: { rule: RuleItem; onClose: () => void }) {
  const [ddl, setDdl] = useState('');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ hit: boolean; violations: { level: string; message: string; suggestion: string }[] } | null>(null);
  const [err, setErr] = useState('');

  async function run() {
    if (!ddl.trim()) { setErr('请输入 DDL 语句'); return; }
    setRunning(true);
    setErr('');
    setResult(null);
    try {
      const res = await dryRunRule({ rule: rule as unknown as Record<string, unknown>, ddl_text: ddl, db_type: rule.db_type.toLowerCase() });
      setResult(res.data);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '干运行失败');
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div>
            <h2 className="text-base font-semibold text-slate-800">干运行测试</h2>
            <p className="text-[12px] text-slate-400 mt-0.5">{rule.rule_id} · {rule.name}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><i className="ri-close-line text-xl" /></button>
        </div>
        <div className="px-6 py-4 space-y-4">
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">DDL 语句</label>
            <textarea
              value={ddl}
              onChange={e => setDdl(e.target.value)}
              rows={8}
              placeholder="粘贴 CREATE TABLE 语句…"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[12px] font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
          </div>
          {err && <p className="text-[12px] text-red-500">{err}</p>}
          <div className="flex justify-end">
            <button onClick={run} disabled={running}
              className="px-4 py-2 text-[12px] bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
              {running ? '运行中…' : '开始测试'}
            </button>
          </div>
          {result && (
            <div className={`rounded-lg border p-4 ${result.hit ? 'bg-red-50 border-red-200' : 'bg-emerald-50 border-emerald-200'}`}>
              <div className="flex items-center gap-2 mb-2">
                <i className={`text-base ${result.hit ? 'ri-error-warning-line text-red-500' : 'ri-checkbox-circle-line text-emerald-500'}`} />
                <span className={`text-[13px] font-medium ${result.hit ? 'text-red-700' : 'text-emerald-700'}`}>
                  {result.hit ? `命中 ${result.violations.length} 个违规` : '通过，未命中违规'}
                </span>
              </div>
              {result.violations.map((v, i) => (
                <div key={i} className="mt-2 text-[12px] bg-white rounded border border-red-100 px-3 py-2">
                  <p className="font-medium text-slate-700">{v.message}</p>
                  {v.suggestion && <p className="text-slate-400 mt-0.5">建议：{v.suggestion}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 主页面 ─────────────────────────────────────────────────────────────────────

export default function RulesConfigPage() {
  const { user } = useAuth();
  const roleRank: Record<string, number> = { user: 0, analyst: 1, data_admin: 2, admin: 3 };
  const canWrite = (roleRank[user?.role ?? 'user'] ?? 0) >= 2;

  const [rules, setRules] = useState<RuleItem[]>([]);
  const [stats, setStats] = useState({ total: 0, enabled_count: 0, disabled_count: 0 });
  const [loading, setLoading] = useState(false);
  const [dbType, setDbType] = useState('ALL');
  const [level, setLevel] = useState('ALL');
  const [status, setStatus] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [dryRunTarget, setDryRunTarget] = useState<RuleItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<RuleItem | null>(null);
  const [toastMsg, setToastMsg] = useState('');

  const flash = (msg: string) => { setToastMsg(msg); setTimeout(() => setToastMsg(''), 3000); };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listRules({
        db_type: dbType !== 'ALL' ? dbType : undefined,
        level: level !== 'ALL' ? level : undefined,
        status: status || undefined,
      });
      setRules(res.rules);
      setStats({ total: res.total, enabled_count: res.enabled_count, disabled_count: res.disabled_count });
    } catch {
      // keep stale
    } finally {
      setLoading(false);
    }
  }, [dbType, level, status]);

  useEffect(() => { load(); }, [load]);

  async function handleToggle(rule: RuleItem) {
    try {
      await toggleRule(rule.rule_id);
      flash(`规则 ${rule.rule_id} 已${rule.status === 'enabled' ? '禁用' : '启用'}`);
      load();
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : '操作失败');
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteRule(deleteTarget.rule_id);
      flash('规则已删除');
      setDeleteTarget(null);
      load();
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : '删除失败');
      setDeleteTarget(null);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 页头 */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-shield-check-line text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">规则配置</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">管理 DDL 合规规则，支持启停与自定义规则扩展</p>
          </div>
          {canWrite && (
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-1.5 px-3.5 py-1.5 bg-blue-600 text-white text-[12px] font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              <i className="ri-add-line" />新建规则
            </button>
          )}
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-7xl mx-auto space-y-5">

          {/* 统计卡片 */}
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: '规则总数', value: stats.total, icon: 'ri-list-check-2', color: 'text-blue-600' },
              { label: '已启用',   value: stats.enabled_count, icon: 'ri-checkbox-circle-line', color: 'text-emerald-600' },
              { label: '已禁用',   value: stats.disabled_count, icon: 'ri-close-circle-line', color: 'text-slate-400' },
            ].map(c => (
              <div key={c.label} className="bg-white rounded-xl border border-slate-200 px-5 py-4 flex items-center gap-3">
                <i className={`text-2xl ${c.icon} ${c.color}`} />
                <div>
                  <p className="text-2xl font-bold text-slate-800">{c.value}</p>
                  <p className="text-[12px] text-slate-400">{c.label}</p>
                </div>
              </div>
            ))}
          </div>

          {/* 筛选栏 */}
          <div className="flex items-center gap-3 flex-wrap">
            <select value={dbType} onChange={e => setDbType(e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-[13px] bg-white focus:outline-none focus:border-slate-400">
              {DB_TYPES.map(t => <option key={t} value={t}>{t === 'ALL' ? '全部类型' : t}</option>)}
            </select>
            <select value={level} onChange={e => setLevel(e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-[13px] bg-white focus:outline-none focus:border-slate-400">
              {LEVELS.map(l => <option key={l} value={l}>{l === 'ALL' ? '全部级别' : l}</option>)}
            </select>
            <select value={status} onChange={e => setStatus(e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-[13px] bg-white focus:outline-none focus:border-slate-400">
              {STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
            <span className="text-[12px] text-slate-400 ml-auto">共 {rules.length} 条</span>
          </div>

          {/* 规则表格 */}
          {loading ? (
            <div className="text-center py-20 text-slate-400 text-[13px]">加载中…</div>
          ) : rules.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20">
              <i className="ri-shield-check-line text-4xl text-slate-300 mb-3" />
              <p className="text-slate-400 text-[13px]">暂无规则</p>
            </div>
          ) : (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 border-b border-slate-200">
                  <tr>
                    {['规则 ID', '名称', '数据库', '级别', '分类', '描述', '状态', '操作'].map(h => (
                      <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-3 py-3 whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {rules.map(rule => (
                    <tr key={rule.rule_id} className={`hover:bg-slate-50 ${rule.status === 'disabled' ? 'opacity-50' : ''}`}>
                      <td className="px-3 py-3 text-[11px] font-mono text-slate-600 whitespace-nowrap">{rule.rule_id}</td>
                      <td className="px-3 py-3 text-[12px] font-medium text-slate-800 whitespace-nowrap">{rule.name}</td>
                      <td className="px-3 py-3 text-[11px] text-slate-500">{rule.db_type}</td>
                      <td className="px-3 py-3"><LevelBadge level={rule.level} /></td>
                      <td className="px-3 py-3 text-[11px] text-slate-400">{rule.category}</td>
                      <td className="px-3 py-3 text-[12px] text-slate-600 max-w-xs truncate" title={rule.description}>{rule.description}</td>
                      <td className="px-3 py-3">
                        <span className={`inline-block px-2 py-0.5 text-[11px] rounded border ${rule.status === 'enabled' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-50 text-slate-500 border-slate-200'}`}>
                          {rule.status === 'enabled' ? '启用' : '禁用'}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-2">
                          {canWrite && (
                            <button onClick={() => handleToggle(rule)}
                              className="text-[11px] px-2 py-1 rounded border border-slate-200 text-slate-500 hover:border-blue-300 hover:text-blue-600 transition-colors">
                              {rule.status === 'enabled' ? '禁用' : '启用'}
                            </button>
                          )}
                          <button onClick={() => setDryRunTarget(rule)}
                            className="text-[11px] px-2 py-1 rounded border border-slate-200 text-slate-500 hover:border-amber-300 hover:text-amber-600 transition-colors">
                            测试
                          </button>
                          {canWrite && rule.is_custom && (
                            <button onClick={() => setDeleteTarget(rule)}
                              className="text-slate-400 hover:text-red-500 transition-colors ml-1">
                              <i className="ri-delete-bin-line text-[13px]" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Toast */}
      {toastMsg && (
        <div className="fixed bottom-6 right-6 bg-slate-800 text-white text-[12px] px-4 py-2.5 rounded-lg shadow-lg z-50">
          {toastMsg}
        </div>
      )}

      {showCreate && (
        <CreateRuleModal onClose={() => setShowCreate(false)} onSaved={() => { setShowCreate(false); load(); }} />
      )}
      {dryRunTarget && <DryRunPanel rule={dryRunTarget} onClose={() => setDryRunTarget(null)} />}
      {deleteTarget && (
        <ConfirmModal
          open
          title="删除规则"
          message={`确定删除自定义规则「${deleteTarget.name}」（${deleteTarget.rule_id}）吗？内置规则不可删除。`}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
