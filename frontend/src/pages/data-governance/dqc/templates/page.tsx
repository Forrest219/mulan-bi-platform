import { useState, useEffect, useCallback, Fragment, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import DqcTabs from '../DqcTabs';
import {
  listTemplates, updateTemplate, deleteTemplate,
  getTemplateCoverage, toggleTemplateCoverage, batchToggleTemplateCoverage,
  type DqcRuleTemplate, type TemplateCoverageItem,
  RULE_PACKAGE_LABELS,
} from '../../../../api/dqc';
import { ConfirmModal } from '../../../../components/ConfirmModal';
import { useAuth } from '../../../../context/AuthContext';

const severityConfig: Record<string, { label: string; bg: string; text: string }> = {
  HIGH:   { label: '高', bg: 'bg-red-50',   text: 'text-red-600' },
  MEDIUM: { label: '中', bg: 'bg-amber-50', text: 'text-amber-600' },
  LOW:    { label: '低', bg: 'bg-blue-50',  text: 'text-blue-600' },
};

function normalizeSeverity(s: string): 'HIGH' | 'MEDIUM' | 'LOW' {
  if (s === 'CRITICAL' || s === 'HIGH') return 'HIGH';
  if (s === 'MEDIUM') return 'MEDIUM';
  return 'LOW';
}

const getErrorMessage = (e: unknown, fallback = '操作失败') =>
  e instanceof Error ? e.message : fallback;

const PACKAGE_ORDER = ['L1', 'L2', 'L3', 'L4', ''];
const PACKAGE_ICONS: Record<string, string> = {
  L1: 'ri-shield-check-line',
  L2: 'ri-time-line',
  L3: 'ri-git-merge-line',
  L4: 'ri-robot-line',
  '': 'ri-file-list-line',
};

const COLUMN_HEADERS: { label: string; tip: string }[] = [
  { label: '能力名称',   tip: '用户知道系统会检查什么' },
  { label: '适用对象',   tip: '表 / 字段 / 字段组合 / 跨表 / 元数据' },
  { label: '默认级别',   tip: '这类能力默认风险等级' },
  { label: '已生成规则', tip: '这个能力落地了多少条具体规则' },
  { label: '更新时间',   tip: '能力最近是否调整过' },
  { label: '启用',       tip: '是否允许用于生成规则' },
  { label: '操作',       tip: '' },
];

function getMatchTarget(t: DqcRuleTemplate): string {
  if (t.rule_package === 'L4') return '元数据';
  if (t.rule_package === 'L3') return '跨表';
  const scope = (t.match_condition as { scope?: string })?.scope;
  if (scope === 'column') return '字段';
  if (scope === 'ddl') return '元数据';
  return '表';
}

function formatDate(s: string | null | undefined): string {
  if (!s) return '—';
  const d = new Date(s);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

export default function DqcTemplatesPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin' || user?.role === 'data_admin';

  const [templates, setTemplates] = useState<DqcRuleTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [filterPackage, setFilterPackage] = useState('');
  const [filterSeverity, setFilterSeverity] = useState('');
  const [confirm, setConfirm] = useState<{
    open: boolean; title: string; message: string; onConfirm: () => void;
  }>({ open: false, title: '', message: '', onConfirm: () => {} });
  const [coverageModal, setCoverageModal] = useState<{ open: boolean; template: DqcRuleTemplate | null }>({
    open: false, template: null,
  });

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

  const handleToggleEnabled = async (t: DqcRuleTemplate) => {
    try {
      await updateTemplate(t.id, { enabled: !t.enabled });
      load();
    } catch (e) {
      setError(getErrorMessage(e));
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

  const filteredTemplates = templates.filter(t => {
    if (filterPackage && t.rule_package !== filterPackage) return false;
    if (filterSeverity && normalizeSeverity(t.severity) !== filterSeverity) return false;
    return true;
  });

  const groupedTemplates: Record<string, DqcRuleTemplate[]> = {};
  for (const t of filteredTemplates) {
    const pkg = t.rule_package || '';
    if (!groupedTemplates[pkg]) groupedTemplates[pkg] = [];
    groupedTemplates[pkg].push(t);
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
          <p className="text-[13px] text-slate-400 ml-7 mb-4">数据质量规则与检查管理</p>
          <DqcTabs />
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-8 py-7">
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-600 text-xs rounded-lg px-4 py-2 mb-4 flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError('')} className="text-red-400 hover:text-red-600">
              <i className="ri-close-line" />
            </button>
          </div>
        )}
        {successMsg && (
          <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs rounded-lg px-4 py-2 mb-4">
            {successMsg}
          </div>
        )}

        {/* 页面说明 */}
        <p className="text-[12px] text-slate-400 mb-4">
          系统内置检查能力，支持基于能力创建检查规则。
        </p>

        {/* 过滤栏 */}
        <div className="flex items-center gap-3 mb-4">
          <select
            value={filterPackage}
            onChange={e => setFilterPackage(e.target.value)}
            className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white focus:outline-none focus:ring-1 focus:ring-slate-300"
          >
            <option value="">全部规则包</option>
            {Object.entries(RULE_PACKAGE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <select
            value={filterSeverity}
            onChange={e => setFilterSeverity(e.target.value)}
            className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white focus:outline-none focus:ring-1 focus:ring-slate-300"
          >
            <option value="">全部级别</option>
            <option value="HIGH">高</option>
            <option value="MEDIUM">中</option>
            <option value="LOW">低</option>
          </select>
          <span className="text-[11px] text-slate-400 ml-auto">
            共 {filteredTemplates.length} 条模板
          </span>
          {isAdmin && (
            <button
              onClick={() => navigate('/governance/dqc/templates/ai-create')}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 text-white text-xs font-medium rounded-lg hover:bg-slate-700 transition-colors"
            >
              <i className="ri-add-line" />AI 创建检查规则
            </button>
          )}
        </div>

        {/* 表格 */}
        {loading ? (
          <div className="text-center py-20 text-slate-400 text-sm">
            <i className="ri-loader-4-line animate-spin mr-2" />加载中...
          </div>
        ) : filteredTemplates.length === 0 ? (
          <div className="text-center py-16 text-slate-400 text-xs">
            <i className="ri-file-list-3-line text-3xl mb-2 block" />
            暂无规则模板，请先 Seed 内置模板或新建
          </div>
        ) : (
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full table-fixed">
              <colgroup>
                <col className="w-[25%]" />
                <col className="w-[13%]" />
                <col className="w-[8%]" />
                <col className="w-[12%]" />
                <col className="w-[13%]" />
                <col className="w-[9%]" />
                <col className="w-[16%]" />
              </colgroup>
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  {COLUMN_HEADERS.map(h => (
                    <th
                      key={h.label}
                      title={h.tip || undefined}
                      className={`text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 whitespace-nowrap${h.tip ? ' cursor-help' : ''}`}
                    >
                      {h.label}
                      {h.tip && <i className="ri-information-line text-[10px] text-slate-300 ml-1 align-middle normal-case" />}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {PACKAGE_ORDER.filter(pkg => groupedTemplates[pkg]?.length > 0).map(pkg => (
                  <Fragment key={pkg}>
                    <tr className="bg-slate-50/70 border-t border-slate-200">
                      <td colSpan={7} className="px-5 py-2">
                        <div className="flex items-center gap-2">
                          <i className={`${PACKAGE_ICONS[pkg] ?? 'ri-file-list-line'} text-slate-400 text-[13px]`} />
                          <span className="text-[12px] font-semibold text-slate-600">
                            {pkg ? RULE_PACKAGE_LABELS[pkg] : '未分类'}
                          </span>
                          <span className="text-[11px] text-slate-400">({groupedTemplates[pkg].length})</span>
                        </div>
                      </td>
                    </tr>
                    {groupedTemplates[pkg].map(t => (
                      <tr
                        key={t.id}
                        className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer transition-colors"
                        onClick={() => navigate(`/governance/dqc/templates/${t.id}`)}
                      >
                        <td className="px-4 py-3">
                          <span className="font-medium text-[12px] text-slate-700 truncate block">
                            {t.name}
                            {t.is_builtin && (
                              <span className="ml-1.5 text-[10px] font-normal px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-500">内置</span>
                            )}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-[11px] text-slate-600">{getMatchTarget(t)}</span>
                        </td>
                        <td className="px-4 py-3">
                          {(() => {
                            const sc = severityConfig[normalizeSeverity(t.severity)];
                            return (
                              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${sc.bg} ${sc.text}`}>
                                {sc.label}
                              </span>
                            );
                          })()}
                        </td>
                        <td className="px-4 py-3 text-[12px]">
                          {t.derived_rules_count != null
                            ? <span className="text-slate-700">{t.derived_rules_count}</span>
                            : <span className="text-slate-300">—</span>}
                        </td>
                        <td className="px-4 py-3 text-[11px] text-slate-400">
                          {formatDate(t.updated_at)}
                        </td>
                        <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                          <button
                            onClick={() => handleToggleEnabled(t)}
                            disabled={!isAdmin}
                            title={t.enabled ? '禁用后停止生成新派生规则' : '启用'}
                            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                              t.enabled ? 'bg-emerald-500' : 'bg-slate-300'
                            } ${!isAdmin ? 'opacity-60 cursor-not-allowed' : ''}`}
                          >
                            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                              t.enabled ? 'translate-x-4' : 'translate-x-1'
                            }`} />
                          </button>
                        </td>
                        <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                          <div className="flex items-center gap-1.5">
                            <button
                              onClick={() => navigate(`/governance/dqc/templates/${t.id}`)}
                              title="查看能力说明、参数、执行逻辑"
                              className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-800 px-2 py-1 rounded hover:bg-slate-100 transition-colors"
                            >
                              <i className="ri-eye-line text-[12px]" />
                              查看
                            </button>
                            {isAdmin && (
                              <button
                                onClick={() => setCoverageModal({ open: true, template: t })}
                                disabled={!t.enabled}
                                title="管理该能力应用到哪些表"
                                className="flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-700 px-2 py-1 rounded hover:bg-blue-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                              >
                                <i className="ri-flashlight-line text-[12px]" />
                                应用
                              </button>
                            )}
                            {isAdmin && !t.is_builtin && (
                              <button
                                onClick={() => handleDelete(t)}
                                title="删除模板（仅自定义模板可删除）"
                                className="text-slate-300 hover:text-red-500 transition-colors px-1 py-1 rounded hover:bg-red-50"
                              >
                                <i className="ri-delete-bin-line text-[12px]" />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ConfirmModal
        open={confirm.open}
        title={confirm.title}
        message={confirm.message}
        onConfirm={confirm.onConfirm}
        onCancel={() => setConfirm(c => ({ ...c, open: false }))}
        variant="danger"
      />

      {coverageModal.open && coverageModal.template && (
        <CoverageModal
          template={coverageModal.template}
          onClose={() => { setCoverageModal({ open: false, template: null }); load(); }}
        />
      )}
    </div>
  );
}

// ── 覆盖范围弹窗 ──────────────────────────────────────────────

function CoverageModal({ template, onClose }: { template: DqcRuleTemplate; onClose: () => void }) {
  const [items, setItems] = useState<TemplateCoverageItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  // selected = 当前勾选状态（asset_id set），初始从 items.enabled 同步
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  useEffect(() => {
    getTemplateCoverage(template.id)
      .then(d => {
        setItems(d.items);
        setSelected(new Set(d.items.filter(i => i.enabled).map(i => i.asset_id)));
      })
      .catch(e => setError(e instanceof Error ? e.message : '加载失败'))
      .finally(() => setLoading(false));
  }, [template.id]);

  // 过滤后的 items
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(i =>
      i.table_name.toLowerCase().includes(q) || i.schema_name.toLowerCase().includes(q)
    );
  }, [items, search]);

  // 按 schema 分组
  const groups = useMemo(() => {
    const map = new Map<string, TemplateCoverageItem[]>();
    for (const item of filtered) {
      const list = map.get(item.schema_name) ?? [];
      list.push(item);
      map.set(item.schema_name, list);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  const toggleItem = (id: number) =>
    setSelected(prev => { const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s; });

  const toggleSchema = (schema: string, schemaItems: TemplateCoverageItem[]) => {
    const ids = schemaItems.map(i => i.asset_id);
    const allOn = ids.every(id => selected.has(id));
    setSelected(prev => {
      const s = new Set(prev);
      if (allOn) ids.forEach(id => s.delete(id));
      else ids.forEach(id => s.add(id));
      return s;
    });
  };

  const toggleAll = () => {
    const allIds = filtered.map(i => i.asset_id);
    const allOn = allIds.every(id => selected.has(id));
    setSelected(prev => {
      const s = new Set(prev);
      if (allOn) allIds.forEach(id => s.delete(id));
      else allIds.forEach(id => s.add(id));
      return s;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    const originalEnabled = new Set(items.filter(i => i.enabled).map(i => i.asset_id));
    const add = [...selected].filter(id => !originalEnabled.has(id));
    const remove = [...originalEnabled].filter(id => !selected.has(id));
    try {
      await batchToggleTemplateCoverage(template.id, add, remove);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败');
      setSaving(false);
    }
  };

  const selectedCount = filtered.filter(i => selected.has(i.asset_id)).length;
  const allFilteredOn = filtered.length > 0 && filtered.every(i => selected.has(i.asset_id));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-xl max-h-[85vh] flex flex-col">

        {/* 头部 */}
        <div className="px-5 py-4 border-b border-slate-100 flex items-start justify-between">
          <div>
            <div className="text-[14px] font-semibold text-slate-800">{template.name} — 应用范围</div>
            <div className="text-[12px] text-slate-400 mt-0.5">
              已选 {selectedCount} / {filtered.length} 个资产
              {search && <span className="ml-1">（搜索结果）</span>}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 mt-0.5">
            <i className="ri-close-line text-lg" />
          </button>
        </div>

        {/* 工具栏 */}
        <div className="px-4 py-2.5 border-b border-slate-100 flex items-center gap-3">
          <div className="relative flex-1">
            <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-300 text-[13px]" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="搜索表名或 schema…"
              className="w-full pl-7 pr-3 py-1.5 text-[12px] border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </div>
          <button
            onClick={toggleAll}
            className="text-[11px] text-slate-500 hover:text-slate-800 whitespace-nowrap px-2 py-1.5 rounded hover:bg-slate-100"
          >
            {allFilteredOn ? '清空' : '全选'}
          </button>
        </div>

        {/* 列表 */}
        <div className="overflow-y-auto flex-1">
          {error && <div className="text-[12px] text-red-500 px-4 py-2">{error}</div>}
          {loading ? (
            <div className="text-center py-12 text-slate-400 text-sm">
              <i className="ri-loader-4-line animate-spin mr-1" />加载中…
            </div>
          ) : groups.length === 0 ? (
            <div className="text-center py-12 text-slate-400 text-[13px]">
              {search ? '无匹配结果' : '暂无已监控资产，请先在「健康看板」中添加监控表'}
            </div>
          ) : (
            groups.map(([schema, schemaItems]) => {
              const isCollapsed = collapsed.has(schema);
              const schemaIds = schemaItems.map(i => i.asset_id);
              const onCount = schemaIds.filter(id => selected.has(id)).length;
              const allOn = onCount === schemaIds.length;
              const someOn = onCount > 0 && !allOn;

              return (
                <div key={schema}>
                  {/* Schema 行 */}
                  <div className="flex items-center gap-2 px-4 py-2 bg-slate-50 border-b border-slate-100 sticky top-0">
                    <input
                      type="checkbox"
                      checked={allOn}
                      ref={el => { if (el) el.indeterminate = someOn; }}
                      onChange={() => toggleSchema(schema, schemaItems)}
                      className="w-3.5 h-3.5 rounded accent-slate-700 cursor-pointer"
                    />
                    <button
                      className="flex items-center gap-1.5 flex-1 text-left"
                      onClick={() => setCollapsed(prev => {
                        const s = new Set(prev);
                        s.has(schema) ? s.delete(schema) : s.add(schema);
                        return s;
                      })}
                    >
                      <i className={`ri-database-2-line text-slate-400 text-[12px]`} />
                      <span className="text-[12px] font-semibold text-slate-600">{schema}</span>
                      <span className="text-[11px] text-slate-400">({schemaItems.length})</span>
                      {onCount > 0 && (
                        <span className="text-[10px] text-emerald-600 font-medium ml-1">已启用 {onCount}</span>
                      )}
                      <i className={`ri-arrow-${isCollapsed ? 'right' : 'down'}-s-line text-slate-300 text-[12px] ml-auto`} />
                    </button>
                  </div>

                  {/* 表行 */}
                  {!isCollapsed && schemaItems.map(item => (
                    <label
                      key={item.asset_id}
                      className="flex items-center gap-3 px-4 py-2 hover:bg-slate-50 cursor-pointer border-b border-slate-50"
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(item.asset_id)}
                        onChange={() => toggleItem(item.asset_id)}
                        className="w-3.5 h-3.5 rounded accent-slate-700 cursor-pointer shrink-0"
                      />
                      <span className="text-[12px] text-slate-700 truncate">{item.table_name}</span>
                    </label>
                  ))}
                </div>
              );
            })
          )}
        </div>

        {/* 底部 */}
        <div className="px-5 py-3 border-t border-slate-100 flex items-center justify-between">
          <span className="text-[11px] text-slate-400">
            共 {items.length} 个资产，已选 {[...selected].filter(id => items.some(i => i.asset_id === id)).length} 个
          </span>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-[13px] text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 text-[13px] font-medium bg-slate-800 text-white rounded-lg hover:bg-slate-700 disabled:opacity-50"
            >
              {saving ? <><i className="ri-loader-4-line animate-spin mr-1" />保存中…</> : '保存'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
