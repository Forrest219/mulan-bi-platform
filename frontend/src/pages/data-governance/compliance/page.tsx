import { useState, useEffect, useCallback, Fragment } from 'react';
import {
  listComplianceRules,
  toggleComplianceRule,
  createComplianceRule,
  updateComplianceRule,
  deleteComplianceRule,
  DISPLAY_GROUP_LABELS,
  DISPLAY_GROUP_ICONS,
} from '@/api/compliance';
import type { ComplianceRule, CreateComplianceRuleInput, UpdateComplianceRuleInput } from '@/api/compliance';

const levelConfig: Record<string, { label: string; bg: string; text: string }> = {
  HIGH: { label: '高', bg: 'bg-red-50', text: 'text-red-600' },
  MEDIUM: { label: '中', bg: 'bg-amber-50', text: 'text-amber-600' },
  LOW: { label: '低', bg: 'bg-blue-50', text: 'text-blue-600' },
};

function normalizeLevel(level: string): 'HIGH' | 'MEDIUM' | 'LOW' {
  const l = level.toLowerCase();
  if (l === 'critical' || l === 'high') return 'HIGH';
  if (l === 'medium') return 'MEDIUM';
  return 'LOW';
}

interface RuleFormData {
  id: string;
  name: string;
  description: string;
  level: 'HIGH' | 'MEDIUM' | 'LOW';
  display_group: string;
  suggestion: string;
  scene_type: string;
  db_type: string;
}

const EMPTY_FORM: RuleFormData = {
  id: '',
  name: '',
  description: '',
  level: 'MEDIUM',
  display_group: 'naming',
  suggestion: '',
  scene_type: 'ALL',
  db_type: 'StarRocks',
};

// 本组件由 dw-audit/page.tsx 作为 tab 子页面渲染，外层已提供 header + min-h-screen 容器
export default function CompliancePage() {
  const [rules, setRules] = useState<ComplianceRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(true);
  const [error, setError] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterLevel, setFilterLevel] = useState('');
  const [filterSource, setFilterSource] = useState('');
  const [toggling, setToggling] = useState<string | null>(null);

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [editingRule, setEditingRule] = useState<ComplianceRule | null>(null);
  const [formData, setFormData] = useState<RuleFormData>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  // Delete confirm
  const [deletingRule, setDeletingRule] = useState<ComplianceRule | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    loadRules();
  }, []);

  async function loadRules() {
    setRulesLoading(true);
    try {
      const data = await listComplianceRules();
      setRules(data.rules);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载规则失败';
      setError(msg);
    } finally {
      setRulesLoading(false);
    }
  }

  const handleToggle = useCallback(async (ruleId: string) => {
    setToggling(ruleId);
    try {
      await toggleComplianceRule(ruleId);
      await loadRules();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '操作失败';
      setError(msg);
    } finally {
      setToggling(null);
    }
  }, []);

  function generateRuleId() {
    return `RULE_CUSTOM_${Math.random().toString(16).slice(2, 7).toUpperCase()}`;
  }

  function openCreateModal() {
    setEditingRule(null);
    setFormData({ ...EMPTY_FORM, id: generateRuleId() });
    setShowModal(true);
  }

  function openEditModal(rule: ComplianceRule) {
    setEditingRule(rule);
    setFormData({
      id: rule.id,
      name: rule.name,
      description: rule.description,
      level: rule.level as 'HIGH' | 'MEDIUM' | 'LOW',
      display_group: rule.display_group || 'other',
      suggestion: rule.suggestion,
      scene_type: 'ALL',
      db_type: rule.db_type,
    });
    setShowModal(true);
  }

  async function handleSave() {
    setSaving(true);
    setError('');
    try {
      if (editingRule) {
        const updates: UpdateComplianceRuleInput = {};
        if (formData.name !== editingRule.name) updates.name = formData.name;
        if (formData.description !== editingRule.description) updates.description = formData.description;
        if (formData.level !== editingRule.level) updates.level = formData.level;
        if (formData.display_group !== (editingRule.display_group || 'other')) updates.display_group = formData.display_group;
        if (formData.suggestion !== editingRule.suggestion) updates.suggestion = formData.suggestion;
        if (formData.scene_type) updates.scene_type = formData.scene_type;
        await updateComplianceRule(editingRule.id, updates);
      } else {
        const input: CreateComplianceRuleInput = {
          id: formData.id,
          name: formData.name,
          description: formData.description,
          level: formData.level,
          category: formData.display_group,
          display_group: formData.display_group,
          db_type: formData.db_type,
          suggestion: formData.suggestion || undefined,
          scene_type: formData.scene_type || undefined,
        };
        await createComplianceRule(input);
      }
      setShowModal(false);
      await loadRules();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '保存失败';
      setError(msg);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deletingRule) return;
    setDeleting(true);
    try {
      await deleteComplianceRule(deletingRule.id);
      setDeletingRule(null);
      await loadRules();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '删除失败';
      setError(msg);
    } finally {
      setDeleting(false);
    }
  }

  const filteredRules = rules.filter((r) => {
    if (filterCategory && (r.display_group || 'other') !== filterCategory) return false;
    if (filterLevel && normalizeLevel(r.level) !== filterLevel) return false;
    if (filterSource === 'builtin' && !r.built_in) return false;
    if (filterSource === 'custom' && r.built_in) return false;
    return true;
  });

  const groupedRules: Record<string, ComplianceRule[]> = {};
  for (const r of filteredRules) {
    const grp = r.display_group || 'other';
    if (!groupedRules[grp]) groupedRules[grp] = [];
    groupedRules[grp].push(r);
  }

  const enabledCount = rules.filter((r) => r.status === 'enabled').length;
  const highCount = rules.filter((r) => normalizeLevel(r.level) === 'HIGH').length;
  const mediumCount = rules.filter((r) => normalizeLevel(r.level) === 'MEDIUM').length;
  const lowCount = rules.filter((r) => normalizeLevel(r.level) === 'LOW').length;

  return (
    <div className="px-8 py-7">
      <div className="max-w-6xl mx-auto">
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-600 text-xs rounded-lg px-4 py-2 mb-4">
          {error}
          <button onClick={() => setError('')} className="ml-2 text-red-400 hover:text-red-600">
            <i className="ri-close-line" />
          </button>
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-slate-500">合规规则</span>
            <i className="ri-shield-check-line text-slate-400" />
          </div>
          <div className="text-2xl font-bold text-slate-800">{rules.length}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">已启用 {enabledCount} 条</div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-slate-500">高优先级</span>
            <i className="ri-error-warning-line text-red-400" />
          </div>
          <div className="text-2xl font-bold text-red-600">{highCount}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">
            占 {rules.length > 0 ? Math.round(highCount / rules.length * 100) : 0}%
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-slate-500">中优先级</span>
            <i className="ri-alert-line text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-amber-600">{mediumCount}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">
            占 {rules.length > 0 ? Math.round(mediumCount / rules.length * 100) : 0}%
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-slate-500">低优先级</span>
            <i className="ri-information-line text-blue-400" />
          </div>
          <div className="text-2xl font-bold text-blue-600">{lowCount}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">
            占 {rules.length > 0 ? Math.round(lowCount / rules.length * 100) : 0}%
          </div>
        </div>
      </div>

      {/* Filter bar + Create button */}
      <div className="flex items-center gap-3 mb-4">
        <select
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
          className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
        >
          <option value="">全部分类</option>
          {Object.entries(DISPLAY_GROUP_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
        <select
          value={filterLevel}
          onChange={(e) => setFilterLevel(e.target.value)}
          className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
        >
          <option value="">全部级别</option>
          <option value="HIGH">高</option>
          <option value="MEDIUM">中</option>
          <option value="LOW">低</option>
        </select>
        <select
          value={filterSource}
          onChange={(e) => setFilterSource(e.target.value)}
          className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
        >
          <option value="">全部来源</option>
          <option value="builtin">系统内置</option>
          <option value="custom">用户自定义</option>
        </select>
        <span className="text-[11px] text-slate-400 ml-auto">
          共 {filteredRules.length} 条规则
        </span>
        <button
          onClick={openCreateModal}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 text-white text-xs font-medium rounded-lg hover:bg-slate-700 transition-colors"
        >
          <i className="ri-add-line" />
          新增规则
        </button>
      </div>

      {rulesLoading ? (
        <div className="text-center py-20 text-slate-400 text-sm">加载中...</div>
      ) : Object.keys(groupedRules).length === 0 ? (
        <div className="text-center py-10 text-slate-400 text-xs">暂无匹配规则</div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full table-fixed">
            <colgroup>
              <col className="w-[14%]" />
              <col className="w-[20%]" />
              <col className="w-[7%]" />
              <col className="w-[40%]" />
              <col className="w-[9%]" />
              <col className="w-[10%]" />
            </colgroup>
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                {['规则 ID', '名称', '级别', '描述', '状态', '操作'].map((h) => (
                  <th
                    key={h}
                    className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(groupedRules).map(([group, catRules]) => (
                <Fragment key={group}>
                  <tr className="bg-slate-50/70 border-t border-slate-200">
                    <td colSpan={6} className="px-5 py-2">
                      <div className="flex items-center gap-2">
                        <i className={`${DISPLAY_GROUP_ICONS[group] || 'ri-file-list-line'} text-slate-400 text-[13px]`} />
                        <span className="text-[12px] font-semibold text-slate-600">
                          {DISPLAY_GROUP_LABELS[group] || group}
                        </span>
                        <span className="text-[11px] text-slate-400">({catRules.length})</span>
                      </div>
                    </td>
                  </tr>
                  {catRules.map((rule: ComplianceRule) => {
                    const lc = levelConfig[normalizeLevel(rule.level)];
                    return (
                      <tr key={rule.id} className="border-t border-slate-100 hover:bg-slate-50">
                        <td className="px-4 py-3 text-[11px] font-mono text-slate-400 truncate">{rule.id}</td>
                        <td className="px-4 py-3 text-[12px] font-medium text-slate-700">
                          <span className="truncate block">
                            {rule.name}
                            {!rule.built_in && (
                              <span className="ml-1.5 text-[10px] font-normal px-1.5 py-0.5 rounded bg-violet-50 text-violet-500">
                                自定义
                              </span>
                            )}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${lc.bg} ${lc.text}`}>
                            {lc.label}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-[12px] text-slate-600 truncate">{rule.description}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => handleToggle(rule.id)}
                            disabled={toggling === rule.id}
                            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                              rule.status === 'enabled' ? 'bg-emerald-500' : 'bg-slate-300'
                            } ${toggling === rule.id ? 'opacity-50' : ''}`}
                          >
                            <span
                              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                                rule.status === 'enabled' ? 'translate-x-4' : 'translate-x-1'
                              }`}
                            />
                          </button>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => openEditModal(rule)}
                              className="text-slate-400 hover:text-slate-700 transition-colors"
                              title="编辑"
                            >
                              <i className="ri-edit-line text-sm" />
                            </button>
                            {!rule.built_in && (
                              <button
                                onClick={() => setDeletingRule(rule)}
                                className="text-slate-400 hover:text-red-500 transition-colors"
                                title="删除"
                              >
                                <i className="ri-delete-bin-line text-sm" />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setShowModal(false)} />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 p-6">
            <h2 className="text-sm font-semibold text-slate-800 mb-4">
              {editingRule ? '编辑规则' : '新增规则'}
            </h2>
            <div className="space-y-3">
              {!editingRule && (
                <div>
                  <label className="text-[11px] text-slate-500 mb-1 block">规则 ID（自动生成）</label>
                  <input
                    value={formData.id}
                    readOnly
                    className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg bg-slate-50 text-slate-400 font-mono cursor-default"
                  />
                </div>
              )}
              <div>
                <label className="text-[11px] text-slate-500 mb-1 block">名称</label>
                <input
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg"
                />
              </div>
              <div>
                <label className="text-[11px] text-slate-500 mb-1 block">描述</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  rows={2}
                  className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg resize-none"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] text-slate-500 mb-1 block">级别</label>
                  <select
                    value={formData.level}
                    onChange={(e) => setFormData({ ...formData, level: e.target.value as 'HIGH' | 'MEDIUM' | 'LOW' })}
                    className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg"
                  >
                    <option value="HIGH">HIGH</option>
                    <option value="MEDIUM">MEDIUM</option>
                    <option value="LOW">LOW</option>
                  </select>
                </div>
                <div>
                  <label className="text-[11px] text-slate-500 mb-1 block">分类</label>
                  <select
                    value={formData.display_group}
                    onChange={(e) => setFormData({ ...formData, display_group: e.target.value })}
                    className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg"
                  >
                    {Object.entries(DISPLAY_GROUP_LABELS).map(([key, label]) => (
                      <option key={key} value={key}>{label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="text-[11px] text-slate-500 mb-1 block">修复建议</label>
                <textarea
                  value={formData.suggestion}
                  onChange={(e) => setFormData({ ...formData, suggestion: e.target.value })}
                  rows={2}
                  className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg resize-none"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] text-slate-500 mb-1 block">适用场景</label>
                  <select
                    value={formData.scene_type}
                    onChange={(e) => setFormData({ ...formData, scene_type: e.target.value })}
                    className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg"
                  >
                    <option value="ALL">全部</option>
                    <option value="ODS">ODS</option>
                    <option value="DWD">DWD</option>
                    <option value="DWS">DWS</option>
                    <option value="ADS">ADS</option>
                  </select>
                </div>
                <div>
                  <label className="text-[11px] text-slate-500 mb-1 block">数据库类型</label>
                  <select
                    value={formData.db_type}
                    onChange={(e) => setFormData({ ...formData, db_type: e.target.value })}
                    className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg"
                    disabled={!!editingRule}
                  >
                    <option value="MySQL">MySQL</option>
                    <option value="SQL Server">SQL Server</option>
                    <option value="StarRocks">StarRocks</option>
                  </select>
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-1.5 text-xs text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !formData.name}
                className="px-4 py-1.5 text-xs text-white bg-slate-800 rounded-lg hover:bg-slate-700 disabled:opacity-50"
              >
                {saving ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirm Modal */}
      {deletingRule && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDeletingRule(null)} />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-sm mx-4 p-6">
            <h2 className="text-sm font-semibold text-slate-800 mb-2">确认删除</h2>
            <p className="text-xs text-slate-500 mb-4">
              确定要删除规则「{deletingRule.name}」（{deletingRule.id}）吗？此操作不可撤销。
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeletingRule(null)}
                className="px-4 py-1.5 text-xs text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50"
              >
                取消
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="px-4 py-1.5 text-xs text-white bg-red-600 rounded-lg hover:bg-red-500 disabled:opacity-50"
              >
                {deleting ? '删除中...' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}
