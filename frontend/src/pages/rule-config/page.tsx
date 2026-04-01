import { useState, useEffect } from 'react';
import SeverityBadge from '../ddl-validator/components/SeverityBadge';
import { API_BASE } from '../../config';

interface ValidationRule {
  id: string;
  name: string;
  level: string;
  category: string;
  description: string;
  suggestion: string;
  db_type: string;
  built_in: boolean;
  status: string;
}

const categoryColors: Record<string, string> = {
  Naming: 'bg-violet-50 text-violet-600 border-violet-200',
  Structure: 'bg-slate-100 text-slate-600 border-slate-200',
  Type: 'bg-teal-50 text-teal-600 border-teal-200',
  Index: 'bg-orange-50 text-orange-600 border-orange-200',
  Audit: 'bg-rose-50 text-rose-600 border-rose-200',
};

const categories = ['ALL', 'Naming', 'Structure', 'Type', 'Index', 'Audit'];
const levels = ['ALL', 'HIGH', 'MEDIUM', 'LOW'];

export default function RuleConfigPage() {
  const [rules, setRules] = useState<ValidationRule[]>([]);
  const [categoryFilter, setCategoryFilter] = useState<string>('ALL');
  const [levelFilter, setLevelFilter] = useState<string>('ALL');
  const [searchText, setSearchText] = useState('');
  const [toastMsg, setToastMsg] = useState('');
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);

  // 新规则表单状态
  const [newRule, setNewRule] = useState({
    id: '',
    name: '',
    level: 'HIGH',
    category: 'Naming',
    description: '',
    suggestion: '',
    db_type: 'MySQL',
  });

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(''), 2000);
  };

  const fetchRules = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/api/rules/`, { credentials: 'include' });
      if (!resp.ok) throw new Error('获取规则列表失败');
      const data = await resp.json();
      setRules(data.rules);
    } catch (error) {
      showToast('获取规则列表失败');
    }
    setLoading(false);
  };

  /* eslint-disable react-hooks/exhaustive-deps -- fetchRules 在组件挂载时运行，故意不放入 deps */
  useEffect(() => {
    fetchRules();
  }, []);
  /* eslint-enable react-hooks/exhaustive-deps */

  const toggleRule = async (id: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/rules/${id}/toggle`, {
        method: 'PUT',
        credentials: 'include',
      });
      if (!resp.ok) throw new Error('切换规则状态失败');
      const data = await resp.json();
      setRules((prev) =>
        prev.map((r) => (r.id === id ? { ...r, status: data.status } : r))
      );
      showToast(data.message);
    } catch (error) {
      showToast('切换规则状态失败');
    }
  };

  const handleCreateRule = async () => {
    if (!newRule.id || !newRule.name) {
      showToast('请填写规则ID和名称');
      return;
    }

    try {
      const resp = await fetch(`${API_BASE}/api/rules/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newRule),
      });
      if (!resp.ok) throw new Error('创建规则失败');
      const data = await resp.json();
      if (data.error) {
        showToast(data.error);
        return;
      }
      showToast(data.message);
      setShowModal(false);
      setNewRule({
        id: '',
        name: '',
        level: 'HIGH',
        category: 'Naming',
        description: '',
        suggestion: '',
        db_type: 'MySQL',
      });
      fetchRules();
    } catch (error) {
      showToast('创建规则失败');
    }
  };

  const filtered = rules.filter((r) => {
    const matchCat = categoryFilter === 'ALL' || r.category === categoryFilter;
    const matchLvl = levelFilter === 'ALL' || r.level === levelFilter;
    const matchSearch =
      !searchText ||
      r.name.includes(searchText) ||
      r.id.includes(searchText) ||
      r.description.includes(searchText);
    return matchCat && matchLvl && matchSearch;
  });

  const enabledCount = rules.filter((r) => r.status === 'enabled').length;
  const disabledCount = rules.filter((r) => r.status === 'disabled').length;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Page header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="w-5 h-5 flex items-center justify-center">
                <i className="ri-settings-3-line text-slate-500 text-base" />
              </span>
              <h1 className="text-lg font-semibold text-slate-800">规则配置</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">管理 DDL Validator 校验规则集，启用 / 禁用规则</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-[12px] text-slate-500 flex items-center gap-4">
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
                {enabledCount} 已启用
              </span>
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-slate-300 inline-block" />
                {disabledCount} 已禁用
              </span>
            </div>
            <button
              onClick={() => setShowModal(true)}
              className="flex items-center gap-1.5 px-3.5 py-1.5 border border-slate-200 text-slate-600 text-[12px] font-medium rounded-lg hover:bg-slate-50 transition-colors cursor-pointer whitespace-nowrap"
            >
              <i className="ri-add-line" />
              自定义规则
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-8 py-7">
        {/* Filters row */}
        <div className="flex items-center gap-3 mb-5 flex-wrap">
          {/* Search */}
          <div className="relative">
            <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
            <input
              type="text"
              placeholder="搜索规则..."
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              className="pl-8 pr-3 py-1.5 text-sm border border-slate-200 rounded-lg bg-white text-slate-700 focus:outline-none focus:border-slate-400 w-48"
            />
          </div>

          {/* Category filter */}
          <div className="flex items-center gap-1 px-1 py-1 bg-white border border-slate-200 rounded-lg">
            {categories.map((c) => (
              <button
                key={c}
                onClick={() => setCategoryFilter(c)}
                className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors cursor-pointer whitespace-nowrap ${
                  categoryFilter === c ? 'bg-slate-900 text-white' : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                {c}
              </button>
            ))}
          </div>

          {/* Level filter */}
          <div className="flex items-center gap-1 px-1 py-1 bg-white border border-slate-200 rounded-lg">
            {levels.map((l) => (
              <button
                key={l}
                onClick={() => setLevelFilter(l)}
                className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors cursor-pointer whitespace-nowrap ${
                  levelFilter === l ? 'bg-slate-900 text-white' : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                {l}
              </button>
            ))}
          </div>

          <span className="text-[12px] text-slate-400 ml-auto">
            显示 {filtered.length} / {rules.length} 条规则
          </span>
        </div>

        {/* Rules table */}
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          {loading ? (
            <div className="p-8 text-center text-slate-400">加载中...</div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50">
                  {['Rule ID', 'Severity', '规则名称', '类别', '适用 DB', '来源', '描述', '状态'].map((h) => (
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
                {filtered.map((rule) => (
                  <tr key={rule.id} className="border-t border-slate-100 hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="font-mono text-[11px] text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">
                        {rule.id}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <SeverityBadge level={rule.level as 'HIGH' | 'MEDIUM' | 'LOW'} size="sm" />
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={`text-[13px] font-medium ${rule.status === 'disabled' ? 'text-slate-400 line-through' : 'text-slate-700'}`}>
                        {rule.name}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${categoryColors[rule.category] || 'bg-slate-100 text-slate-600 border-slate-200'}`}>
                        {rule.category}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="text-[11px] text-slate-500">{rule.db_type}</span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {rule.built_in ? (
                        <span className="text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">内置</span>
                      ) : (
                        <span className="text-[10px] text-teal-600 bg-teal-50 border border-teal-200 px-1.5 py-0.5 rounded">自定义</span>
                      )}
                    </td>
                    <td className="px-4 py-3 max-w-xs">
                      <span className="text-[12px] text-slate-500">{rule.description}</span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <button
                        onClick={() => toggleRule(rule.id)}
                        className={`relative w-8 h-4 rounded-full transition-colors cursor-pointer ${
                          rule.status === 'enabled' ? 'bg-emerald-500' : 'bg-slate-200'
                        }`}
                      >
                        <span
                          className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform ${
                            rule.status === 'enabled' ? 'translate-x-4' : 'translate-x-0.5'
                          }`}
                        />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Toast */}
      {toastMsg && (
        <div className="fixed bottom-6 right-6 bg-slate-800 text-white text-[12px] px-4 py-2.5 rounded-lg z-50">
          {toastMsg}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-[500px] max-h-[80vh] overflow-y-auto">
            <h3 className="text-lg font-semibold text-slate-800 mb-4">创建自定义规则</h3>
            <div className="space-y-4">
              <div>
                <label className="text-[11px] font-medium text-slate-500 uppercase tracking-wide block mb-1">Rule ID</label>
                <input
                  type="text"
                  value={newRule.id}
                  onChange={(e) => setNewRule({ ...newRule, id: e.target.value.toUpperCase() })}
                  placeholder="如: RULE_101"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-slate-400"
                />
              </div>
              <div>
                <label className="text-[11px] font-medium text-slate-500 uppercase tracking-wide block mb-1">规则名称</label>
                <input
                  type="text"
                  value={newRule.name}
                  onChange={(e) => setNewRule({ ...newRule, name: e.target.value })}
                  placeholder="如: 字段长度规范"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-slate-400"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[11px] font-medium text-slate-500 uppercase tracking-wide block mb-1">严重级别</label>
                  <select
                    value={newRule.level}
                    onChange={(e) => setNewRule({ ...newRule, level: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-slate-400"
                  >
                    <option value="HIGH">HIGH</option>
                    <option value="MEDIUM">MEDIUM</option>
                    <option value="LOW">LOW</option>
                  </select>
                </div>
                <div>
                  <label className="text-[11px] font-medium text-slate-500 uppercase tracking-wide block mb-1">类别</label>
                  <select
                    value={newRule.category}
                    onChange={(e) => setNewRule({ ...newRule, category: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-slate-400"
                  >
                    {categories.filter(c => c !== 'ALL').map(c => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="text-[11px] font-medium text-slate-500 uppercase tracking-wide block mb-1">描述</label>
                <textarea
                  value={newRule.description}
                  onChange={(e) => setNewRule({ ...newRule, description: e.target.value })}
                  placeholder="描述规则检查的内容..."
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-slate-400 h-20"
                />
              </div>
              <div>
                <label className="text-[11px] font-medium text-slate-500 uppercase tracking-wide block mb-1">建议</label>
                <textarea
                  value={newRule.suggestion}
                  onChange={(e) => setNewRule({ ...newRule, suggestion: e.target.value })}
                  placeholder="修复建议..."
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-slate-400 h-20"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-2 border border-slate-200 text-slate-600 text-[12px] font-medium rounded-lg hover:bg-slate-50"
              >
                取消
              </button>
              <button
                onClick={handleCreateRule}
                className="px-4 py-2 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700"
              >
                创建规则
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
