import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import DqcTabs from '../DqcTabs';
import {
  listAssets, listRules, createAsset, deleteAsset, batchDeleteAssets,
  listAssetSchemas,
  createRule, updateRule, deleteRule,
  listDatasourceTables, batchImportAssets,
  DqcAsset, DqcRule,
  DIMENSION_LABELS, RULE_TYPE_LABELS, SIGNAL_CONFIG, DIMENSION_RULE_COMPATIBILITY,
  type Dimension, type RuleType,
  type CreateAssetInput, type CreateRuleInput, type UpdateRuleInput,
} from '../../../../api/dqc';
import { listDataSources, DataSource } from '../../../../api/datasources';
import { ConfirmModal } from '../../../../components/ConfirmModal';
import { useAuth } from '../../../../context/AuthContext';

const getErrorMessage = (error: unknown, fallback = '操作失败'): string =>
  error instanceof Error ? error.message : fallback;

const ALL_DIMENSIONS = Object.keys(DIMENSION_LABELS) as Dimension[];

// ── 规则参数表单配置 ──────────────────────────────────────────

interface RuleFieldDef { key: string; label: string; type: 'text' | 'number' | 'select'; placeholder?: string; help?: string; options?: { value: string; label: string }[]; min?: number; max?: number; step?: number; advanced?: boolean }

const RULE_CONFIG_FIELDS: Partial<Record<RuleType, RuleFieldDef[]>> = {
  null_rate: [
    { key: 'column', label: '检查哪个字段', type: 'text', placeholder: '如 user_id', help: '哪个字段不允许为空' },
    { key: 'max_rate', label: '最多允许多少比例为空', type: 'number', placeholder: '如 0.05 = 最多 5% 为空', min: 0, max: 1, step: 0.01 },
  ],
  uniqueness: [
    { key: 'columns', label: '检查哪些字段', type: 'text', placeholder: '如 id,email（逗号分隔）', help: '这些字段的组合应该不重复' },
  ],
  range_check: [
    { key: 'column', label: '检查哪个字段', type: 'text', placeholder: '如 age' },
    { key: 'min', label: '允许的最小值', type: 'number' },
    { key: 'max', label: '允许的最大值', type: 'number' },
  ],
  freshness: [
    { key: 'column', label: '时间字段', type: 'text', placeholder: '如 updated_at', help: '表里记录最后更新时间的字段' },
    { key: 'max_age_hours', label: '最多允许过期多久（小时）', type: 'number', min: 1, help: '超过这个小时数没有新数据就报警。如填 24 = 超过 1 天没更新就报警' },
  ],
  regex: [
    { key: 'column', label: '检查哪个字段', type: 'text', placeholder: '如 email' },
    { key: 'pattern', label: '格式要求（正则）', type: 'text', placeholder: '如 ^[\\w.]+@[\\w.]+$', help: '不符合此格式的数据视为异常' },
  ],
  custom_sql: [
    { key: 'sql', label: '自定义查询', type: 'text', placeholder: '仅 SELECT 语句', help: '查询返回有结果 = 存在异常数据' },
  ],
  volume_anomaly: [
    { key: 'time_column', label: '按哪个时间字段统计', type: 'text', placeholder: 'created_at', help: '留空 = 对比全表总行数' },
    { key: 'baseline_offset', label: '对比哪天的数据', type: 'select', options: [{ value: '1', label: '昨天' }, { value: '7', label: '上周同天' }, { value: '30', label: '上月同天' }], help: '今天的数据量 vs N 天前的数据量，超出波动率即报警' },
    { key: 'threshold_pct', label: '波动率超过多少报警', type: 'number', placeholder: '5', min: 0, max: 100, step: 1, help: '填 5 = 波动超 5% 就报警' },
    { key: 'direction', label: '关注方向', type: 'select', options: [{ value: 'both', label: '涨跌都报' }, { value: 'drop', label: '只关心变少' }, { value: 'rise', label: '只关心变多' }] },
  ],
  table_count_compare: [
    { key: 'target_schema', label: '对比哪个库', type: 'text', help: '要对比的目标表所在的 Schema' },
    { key: 'target_table', label: '对比哪张表', type: 'text', help: '两张表的行数应该一致或接近' },
    { key: 'tolerance_pct', label: '允许多大差异', type: 'number', min: 0, max: 1, step: 0.01, help: '填 0 = 必须完全一致；填 0.05 = 允许 5% 的偏差' },
  ],
  schema_drift: [
    { key: 'tolerance_cols', label: '允许变更的字段数', type: 'number', min: 0, help: '与上次快照相比，字段新增/删除数超过此值则报警。填 0 = 不允许任何 Schema 变更' },
  ],
  enum_check: [
    { key: 'field', label: '字段名', type: 'text', placeholder: '如 status', help: '检查哪个字段的值是否在允许的枚举范围内' },
    { key: 'allowed_values', label: '允许的值（逗号分隔）', type: 'text', placeholder: '如 active,inactive,pending', help: '这些值之外的数据视为异常' },
  ],
  sensitive_field: [
    { key: 'patterns', label: '敏感字段关键词（逗号分隔）', type: 'text', placeholder: '如 phone,id_card,email', help: '字段名包含这些关键词时，检查是否已标注脱敏处理方式' },
  ],
  ai_field_comment: [
    { key: 'min_coverage', label: '最低注释覆盖率', type: 'number', placeholder: '如 0.8', min: 0, max: 1, step: 0.01, help: 'DDL 中有注释的字段数 / 总字段数，低于此值则报警' },
  ],
  ai_table_description: [],
  ai_metric_definition: [
    { key: 'min_coverage', label: '最低指标定义覆盖率', type: 'number', placeholder: '如 0.8', min: 0, max: 1, step: 0.01, help: '已定义指标语义的字段数 / 全部可度量字段数，低于此值报警' },
  ],
};

// ── 组件 ──────────────────────────────────────────────────────

export default function DqcMonitorPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isDataAdmin = user?.role === 'admin' || user?.role === 'data_admin';

  // 资产列表状态
  const [assets, setAssets] = useState<DqcAsset[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 筛选
  const [filterSignal, setFilterSignal] = useState('');
  const [filterStatus, setFilterStatus] = useState('enabled');
  const [search, setSearch] = useState('');
  const [filterDsIds, setFilterDsIds] = useState<Set<number>>(new Set());
  const [filterSchemas, setFilterSchemas] = useState<Set<string>>(new Set());
  const [schemaOptions, setSchemaOptions] = useState<string[]>([]);

  // 行展开
  const [expandedAssetId, setExpandedAssetId] = useState<number | null>(null);
  const [assetRules, setAssetRules] = useState<DqcRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(false);

  // 添加监控 Modal
  const [showAddAsset, setShowAddAsset] = useState(false);
  const [datasources, setDatasources] = useState<DataSource[]>([]);
  const [assetForm, setAssetForm] = useState<CreateAssetInput>({ datasource_id: 0, schema_name: '', table_name: '', auto_suggest_rules: true });
  const [assetFormError, setAssetFormError] = useState('');
  const [assetFormLoading, setAssetFormLoading] = useState(false);

  // 规则 Modal
  const [showRuleModal, setShowRuleModal] = useState(false);
  const [editingRule, setEditingRule] = useState<DqcRule | null>(null);
  const [ruleFormAssetId, setRuleFormAssetId] = useState<number>(0);
  const [ruleForm, setRuleForm] = useState({ name: '', dimension: '' as string, rule_type: '' as string, rule_config: {} as Record<string, unknown>, is_active: true });
  const [ruleFormError, setRuleFormError] = useState('');
  const [ruleFormLoading, setRuleFormLoading] = useState(false);

  // 确认删除
  const [confirm, setConfirm] = useState<{ open: boolean; title: string; message: string; onConfirm: () => void }>({ open: false, title: '', message: '', onConfirm: () => {} });

  // 批量选择
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  // 批量导入
  const [showBatchImport, setShowBatchImport] = useState(false);

  // ── 加载资产列表 ────────────────────────────────────────────

  const fetchAssets = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await listAssets({
        datasource_ids: filterDsIds.size ? [...filterDsIds] : undefined,
        schema_names: filterSchemas.size ? [...filterSchemas] : undefined,
        signal: filterSignal || undefined,
        status: filterStatus || undefined,
        page,
        page_size: 20,
      });
      let items = res.items;
      if (search) {
        const q = search.toLowerCase();
        items = items.filter(a => a.table_name.toLowerCase().includes(q) || a.schema_name.toLowerCase().includes(q) || (a.display_name ?? '').toLowerCase().includes(q));
      }
      setAssets(items);
      setTotal(res.total);
      setPages(res.pages);
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [page, filterDsIds, filterSchemas, filterSignal, filterStatus, search]);

  useEffect(() => { fetchAssets(); }, [fetchAssets]);

  useEffect(() => { setSelectedIds(new Set()); }, [page, filterSignal, filterStatus, search, filterDsIds, filterSchemas]);

  // 数据源列表 & schema 选项
  useEffect(() => {
    listDataSources().then(res => setDatasources(res.datasources ?? [])).catch(() => {});
    listAssetSchemas().then(setSchemaOptions).catch(() => {});
  }, []);

  // 数据源筛选变化时重新加载 schema 选项，并清空已选 schema
  useEffect(() => {
    const ids = [...filterDsIds];
    listAssetSchemas(ids).then(schemas => {
      setSchemaOptions(schemas);
      setFilterSchemas(prev => {
        const next = new Set([...prev].filter(s => schemas.includes(s)));
        return next.size === prev.size ? prev : next;
      });
    }).catch(() => {});
  }, [filterDsIds]);

  // ── 展开行加载规则 ──────────────────────────────────────────

  const toggleExpand = async (assetId: number) => {
    if (expandedAssetId === assetId) {
      setExpandedAssetId(null);
      return;
    }
    setExpandedAssetId(assetId);
    setRulesLoading(true);
    try {
      const res = await listRules(assetId);
      setAssetRules(res.items);
    } catch { setAssetRules([]); }
    finally { setRulesLoading(false); }
  };

  // ── 添加监控 ────────────────────────────────────────────────

  const openAddAsset = () => {
    setAssetForm({ datasource_id: 0, schema_name: '', table_name: '', auto_suggest_rules: true });
    setAssetFormError('');
    setShowAddAsset(true);
  };

  const handleCreateAsset = async () => {
    if (!assetForm.datasource_id) { setAssetFormError('请选择数据源'); return; }
    if (!assetForm.schema_name.trim()) { setAssetFormError('请输入 Schema'); return; }
    if (!assetForm.table_name.trim()) { setAssetFormError('请输入表名'); return; }
    setAssetFormLoading(true);
    setAssetFormError('');
    try {
      await createAsset(assetForm);
      setShowAddAsset(false);
      fetchAssets();
    } catch (e) {
      setAssetFormError(getErrorMessage(e));
    } finally {
      setAssetFormLoading(false);
    }
  };

  // ── 删除资产 ────────────────────────────────────────────────

  const handleDeleteAsset = (asset: DqcAsset) => {
    setConfirm({
      open: true,
      title: '停用监控',
      message: `确定停用 ${asset.schema_name}.${asset.table_name} 的监控？`,
      onConfirm: async () => {
        try {
          await deleteAsset(asset.id);
          setConfirm(prev => ({ ...prev, open: false }));
          fetchAssets();
        } catch (e) {
          setError(getErrorMessage(e));
          setConfirm(prev => ({ ...prev, open: false }));
        }
      },
    });
  };

  const handleBatchDelete = () => {
    const count = selectedIds.size;
    setConfirm({
      open: true,
      title: '批量停用监控',
      message: `确定停用已选的 ${count} 张表的监控？`,
      onConfirm: async () => {
        try {
          const result = await batchDeleteAssets([...selectedIds]);
          setSelectedIds(new Set());
          setConfirm(prev => ({ ...prev, open: false }));
          if (result.unauthorized > 0) {
            setError(`已停用 ${result.deleted} 张，跳过 ${result.unauthorized} 张（非本人创建，无权操作）`);
          }
          fetchAssets();
        } catch (e) {
          setError(getErrorMessage(e));
          setConfirm(prev => ({ ...prev, open: false }));
        }
      },
    });
  };

  // ── 规则 CRUD ───────────────────────────────────────────────

  const openCreateRule = (assetId: number) => {
    setRuleFormAssetId(assetId);
    setEditingRule(null);
    setRuleForm({ name: '', dimension: '', rule_type: '', rule_config: {}, is_active: true });
    setRuleFormError('');
    setShowRuleModal(true);
  };

  const openEditRule = (assetId: number, rule: DqcRule) => {
    setRuleFormAssetId(assetId);
    setEditingRule(rule);
    const config = { ...rule.rule_config };
    if (rule.rule_type === 'volume_anomaly' && typeof config.threshold_pct === 'number') {
      config.threshold_pct = Math.round(config.threshold_pct * 100);
    }
    setRuleForm({
      name: rule.name,
      dimension: rule.dimension,
      rule_type: rule.rule_type,
      rule_config: config,
      is_active: rule.is_active,
    });
    setRuleFormError('');
    setShowRuleModal(true);
  };

  const handleSaveRule = async () => {
    if (!ruleForm.name.trim()) { setRuleFormError('请输入规则名称'); return; }
    if (!editingRule && !ruleForm.dimension) { setRuleFormError('请选择质量维度'); return; }
    if (!editingRule && !ruleForm.rule_type) { setRuleFormError('请选择规则类型'); return; }
    setRuleFormLoading(true);
    setRuleFormError('');
    try {
      const ruleType = editingRule ? editingRule.rule_type : ruleForm.rule_type;
      let configToSend = { ...ruleForm.rule_config };
      if (ruleType === 'volume_anomaly' && typeof configToSend.threshold_pct === 'number') {
        configToSend = { ...configToSend, threshold_pct: configToSend.threshold_pct / 100 };
      }
      if (editingRule) {
        const updateData: UpdateRuleInput = { name: ruleForm.name, rule_config: configToSend, is_active: ruleForm.is_active };
        await updateRule(ruleFormAssetId, editingRule.id, updateData);
      } else {
        const createData: CreateRuleInput = { name: ruleForm.name, dimension: ruleForm.dimension, rule_type: ruleForm.rule_type, rule_config: configToSend, is_active: ruleForm.is_active };
        await createRule(ruleFormAssetId, createData);
      }
      setShowRuleModal(false);
      // 刷新展开行的规则
      if (expandedAssetId === ruleFormAssetId) {
        const res = await listRules(ruleFormAssetId);
        setAssetRules(res.items);
      }
      fetchAssets();
    } catch (e) {
      setRuleFormError(getErrorMessage(e));
    } finally {
      setRuleFormLoading(false);
    }
  };

  const handleDeleteRule = (assetId: number, rule: DqcRule) => {
    setConfirm({
      open: true,
      title: '删除规则',
      message: `确定删除规则「${rule.name}」？`,
      onConfirm: async () => {
        try {
          await deleteRule(assetId, rule.id);
          setConfirm(prev => ({ ...prev, open: false }));
          if (expandedAssetId === assetId) {
            const res = await listRules(assetId);
            setAssetRules(res.items);
          }
          fetchAssets();
        } catch (e) {
          setError(getErrorMessage(e));
          setConfirm(prev => ({ ...prev, open: false }));
        }
      },
    });
  };

  const handleBatchDeleteRules = (assetId: number, rulesToDelete: DqcRule[]) => {
    setConfirm({
      open: true,
      title: '批量删除规则',
      message: `确定删除已选的 ${rulesToDelete.length} 条规则？`,
      onConfirm: async () => {
        try {
          for (const r of rulesToDelete) await deleteRule(assetId, r.id);
          setConfirm(prev => ({ ...prev, open: false }));
          if (expandedAssetId === assetId) {
            const res = await listRules(assetId);
            setAssetRules(res.items);
          }
          fetchAssets();
        } catch (e) {
          setError(getErrorMessage(e));
          setConfirm(prev => ({ ...prev, open: false }));
        }
      },
    });
  };

  const handleConfirmSuggested = async (assetId: number, rule: DqcRule) => {
    try {
      await updateRule(assetId, rule.id, { is_active: true });
      if (expandedAssetId === assetId) {
        const res = await listRules(assetId);
        setAssetRules(res.items);
      }
    } catch (e) {
      setError(getErrorMessage(e));
    }
  };

  // 维度-规则联动
  const compatibleRuleTypes = ruleForm.dimension
    ? DIMENSION_RULE_COMPATIBILITY[ruleForm.dimension as Dimension] ?? []
    : (Object.keys(RULE_TYPE_LABELS) as RuleType[]);

  const currentRuleFields = ruleForm.rule_type ? RULE_CONFIG_FIELDS[ruleForm.rule_type as RuleType] ?? [] : [];

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-eye-line text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">数据质量监控</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">注册监控表并配置质量规则</p>
          </div>
          {isDataAdmin && (
            <div className="flex items-center gap-2">
              <button onClick={() => setShowBatchImport(true)} className="flex items-center gap-1.5 px-3.5 py-1.5 border border-slate-200 text-slate-700 text-[12px] font-medium rounded-lg hover:bg-slate-50 transition-colors">
                <i className="ri-download-cloud-line" />批量导入
              </button>
              <button onClick={openAddAsset} className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700 transition-colors">
                <i className="ri-add-line" />添加监控
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-6xl mx-auto">
          <DqcTabs />
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto">
        {error && (
          <div className="mb-4 px-4 py-3 bg-red-50 text-red-700 border border-red-200 rounded-lg text-sm flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError('')}><i className="ri-close-line" /></button>
          </div>
        )}

        {/* Filters */}
        <div className="flex items-center gap-3 mb-5 flex-wrap">
          <MultiSelectFilter
            options={datasources}
            selected={filterDsIds}
            onChange={next => { setFilterDsIds(new Set([...next].map(Number))); setPage(1); }}
            label="全部数据源"
            getKey={o => String(o.id)}
            getLabel={o => o.name}
            toValue={k => Number(k)}
          />
          <MultiSelectFilter
            options={schemaOptions.map(s => ({ id: s, name: s }))}
            selected={filterSchemas}
            onChange={next => { setFilterSchemas(next as Set<string>); setPage(1); }}
            label="全部 Database"
            getKey={o => o.id}
            getLabel={o => o.name}
            toValue={k => k}
          />
          <select value={filterSignal} onChange={e => { setFilterSignal(e.target.value); setPage(1); }} className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white">
            <option value="">全部信号</option>
            <option value="GREEN">GREEN</option>
            <option value="P1">P1</option>
            <option value="P0">P0</option>
          </select>
          <select value={filterStatus} onChange={e => { setFilterStatus(e.target.value); setPage(1); }} className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white">
            <option value="">全部状态</option>
            <option value="enabled">已启用</option>
            <option value="disabled">已停用</option>
          </select>
          <div className="relative">
            <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
            <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} placeholder="搜索表名..." className="pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-[13px] w-56 bg-white" />
          </div>
          {isDataAdmin && selectedIds.size > 0 && (
            <button onClick={handleBatchDelete} className="flex items-center gap-1.5 px-3 py-1.5 bg-red-50 border border-red-200 text-red-600 text-[12px] font-medium rounded-lg hover:bg-red-100 transition-colors">
              <i className="ri-delete-bin-line" />停用已选 {selectedIds.size} 条
            </button>
          )}
        </div>

        {/* Asset Table */}
        {loading ? (
          <div className="text-center py-20 text-slate-400 text-sm">加载中...</div>
        ) : !assets.length ? (
          <div className="text-center py-20">
            <i className="ri-database-2-line text-3xl text-slate-300 block mb-2" />
            <p className="text-[13px] text-slate-400">暂无监控资产</p>
            {isDataAdmin && <button onClick={openAddAsset} className="mt-3 text-[12px] text-blue-600 hover:text-blue-500">添加监控</button>}
          </div>
        ) : (
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50">
                  {isDataAdmin && (
                    <th className="w-8 pl-3">
                      <input
                        type="checkbox"
                        className="rounded"
                        checked={assets.length > 0 && assets.every(a => selectedIds.has(a.id))}
                        ref={el => { if (el) el.indeterminate = assets.some(a => selectedIds.has(a.id)) && !assets.every(a => selectedIds.has(a.id)); }}
                        onChange={e => setSelectedIds(e.target.checked ? new Set(assets.map(a => a.id)) : new Set())}
                      />
                    </th>
                  )}
                  <th className="w-8" />
                  {['资产名称', '数据源', '信号', '置信分', '规则', '操作'].map(h => (
                    <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {assets.map(asset => {
                  const isExpanded = expandedAssetId === asset.id;
                  const sigCfg = asset.current_signal ? SIGNAL_CONFIG[asset.current_signal] : null;
                  return (
                    <AssetRow
                      key={asset.id}
                      asset={asset}
                      isExpanded={isExpanded}
                      sigCfg={sigCfg}
                      onToggle={() => toggleExpand(asset.id)}
                      onDetail={() => navigate(`/governance/dqc/assets/${asset.id}`)}
                      onDelete={() => handleDeleteAsset(asset)}
                      isDataAdmin={isDataAdmin}
                      isSelected={selectedIds.has(asset.id)}
                      onToggleSelect={() => setSelectedIds(prev => {
                        const next = new Set(prev);
                        if (next.has(asset.id)) { next.delete(asset.id); } else { next.add(asset.id); }
                        return next;
                      })}
                      rulesLoading={rulesLoading}
                      rules={isExpanded ? assetRules : []}
                      onCreateRule={() => openCreateRule(asset.id)}
                      onEditRule={(r) => openEditRule(asset.id, r)}
                      onDeleteRule={(r) => handleDeleteRule(asset.id, r)}
                      onBatchDeleteRules={(rs) => handleBatchDeleteRules(asset.id, rs)}
                      onConfirmSuggested={(r) => handleConfirmSuggested(asset.id, r)}
                    />
                  );
                })}
              </tbody>
            </table>

            {/* Pagination */}
            {pages > 1 && (
              <div className="px-5 py-3 border-t border-slate-100 flex items-center justify-between">
                <span className="text-[13px] text-slate-500">共 {total} 条</span>
                <div className="flex items-center gap-1">
                  <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-2 py-1 text-[12px] border border-slate-200 rounded disabled:opacity-30">上一页</button>
                  <span className="px-3 py-1 text-[12px] text-slate-600">{page} / {pages}</span>
                  <button disabled={page >= pages} onClick={() => setPage(p => p + 1)} className="px-2 py-1 text-[12px] border border-slate-200 rounded disabled:opacity-30">下一页</button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
      </div>

      {/* ── 添加监控 Modal ────────────────────────────────── */}
      {showAddAsset && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setShowAddAsset(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <h2 className="text-[15px] font-semibold text-slate-800">添加监控表</h2>
              <button onClick={() => setShowAddAsset(false)}><i className="ri-close-line text-slate-400 hover:text-slate-600" /></button>
            </div>
            <div className="px-6 py-5 space-y-4">
              {assetFormError && <div className="px-3 py-2 bg-red-50 text-red-600 text-[12px] rounded-lg">{assetFormError}</div>}
              <div>
                <label className="text-[11px] font-medium text-slate-500 mb-1 block">数据源</label>
                <select value={assetForm.datasource_id || ''} onChange={e => setAssetForm(f => ({ ...f, datasource_id: Number(e.target.value) }))} className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px]">
                  <option value="">选择数据源</option>
                  {datasources.map(ds => <option key={ds.id} value={ds.id}>{ds.name}</option>)}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-medium text-slate-500 mb-1 block">Schema</label>
                  <input value={assetForm.schema_name} onChange={e => setAssetForm(f => ({ ...f, schema_name: e.target.value }))} className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px]" placeholder="如 dws" />
                </div>
                <div>
                  <label className="text-[11px] font-medium text-slate-500 mb-1 block">表名</label>
                  <input value={assetForm.table_name} onChange={e => setAssetForm(f => ({ ...f, table_name: e.target.value }))} className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px]" placeholder="如 dws_order_daily" />
                </div>
              </div>
              <div>
                <label className="text-[11px] font-medium text-slate-500 mb-1 block">显示名称（选填）</label>
                <input value={assetForm.display_name ?? ''} onChange={e => setAssetForm(f => ({ ...f, display_name: e.target.value || undefined }))} className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px]" placeholder="如 订单日汇总表" />
              </div>
              <label className="flex items-center gap-2 text-[12px] text-slate-600">
                <input type="checkbox" checked={assetForm.auto_suggest_rules ?? true} onChange={e => setAssetForm(f => ({ ...f, auto_suggest_rules: e.target.checked }))} className="rounded" />
                开启后自动 Profiling 并推荐规则
              </label>
            </div>
            <div className="px-6 py-4 border-t border-slate-100 flex justify-end gap-2">
              <button onClick={() => setShowAddAsset(false)} className="px-4 py-2 text-[12px] text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50">取消</button>
              <button onClick={handleCreateAsset} disabled={assetFormLoading} className="px-4 py-2 text-[12px] text-white bg-blue-600 rounded-lg hover:bg-blue-500 disabled:opacity-50">
                {assetFormLoading ? '提交中...' : '确认添加'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 批量导入 Modal ────────────────────────────────── */}
      {showBatchImport && (
        <BatchImportModal
          onClose={() => setShowBatchImport(false)}
          onImported={() => { setShowBatchImport(false); fetchAssets(); }}
        />
      )}

      {/* ── 规则 Modal ────────────────────────────────────── */}
      {showRuleModal && (
        <div className="fixed inset-0 bg-black/20 backdrop-blur-[2px] flex items-center justify-center z-50" onClick={() => setShowRuleModal(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="px-6 pt-6 pb-2">
              <div className="flex items-center justify-between">
                <h2 className="text-[16px] font-semibold text-slate-900">{editingRule ? '编辑规则' : '新建质量规则'}</h2>
                <button onClick={() => setShowRuleModal(false)} className="w-7 h-7 flex items-center justify-center rounded-full hover:bg-slate-100 transition-colors"><i className="ri-close-line text-slate-400" /></button>
              </div>
              {editingRule?.template_id && (
                <p className="text-[11px] text-slate-400 mt-1">修改参数后不再随模板同步更新</p>
              )}
            </div>
            <div className="px-6 py-5 space-y-5">
              {ruleFormError && <div className="px-3 py-2 bg-red-50 text-red-600 text-[12px] rounded-xl">{ruleFormError}</div>}

              <div className="space-y-1.5">
                <label className="text-[13px] font-medium text-slate-700">规则名称</label>
                {editingRule ? (
                  <div className="px-3 py-2.5 text-[13px] text-slate-500 bg-slate-50/80 rounded-xl">{ruleForm.name}</div>
                ) : (
                  <input value={ruleForm.name} onChange={e => setRuleForm(f => ({ ...f, name: e.target.value }))} className="w-full px-3 py-2.5 border border-slate-200 rounded-xl text-[13px] placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-300 transition-all" placeholder="订单日增量监控" />
                )}
              </div>
              {!editingRule && (
                <>
                  <div className="space-y-1.5">
                    <label className="text-[13px] font-medium text-slate-700">质量维度</label>
                    <select value={ruleForm.dimension} onChange={e => setRuleForm(f => ({ ...f, dimension: e.target.value, rule_type: '', rule_config: {} }))} className="w-full px-3 py-2.5 border border-slate-200 rounded-xl text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-300 transition-all">
                      <option value="">选择维度</option>
                      {ALL_DIMENSIONS.map(d => <option key={d} value={d}>{DIMENSION_LABELS[d]}</option>)}
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[13px] font-medium text-slate-700">规则类型</label>
                    <select value={ruleForm.rule_type} onChange={e => setRuleForm(f => ({ ...f, rule_type: e.target.value, rule_config: {} }))} className="w-full px-3 py-2.5 border border-slate-200 rounded-xl text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-300 transition-all" disabled={!ruleForm.dimension}>
                      <option value="">选择类型</option>
                      {compatibleRuleTypes.map(rt => <option key={rt} value={rt}>{RULE_TYPE_LABELS[rt]}</option>)}
                    </select>
                  </div>
                </>
              )}
              {/* Dynamic config fields */}
              {currentRuleFields.length > 0 && (() => {
                const mainFields = currentRuleFields.filter(f => !f.advanced);
                const advancedFields = currentRuleFields.filter(f => f.advanced);
                const isPercentField = (key: string) => ruleForm.rule_type === 'volume_anomaly' && key === 'threshold_pct';
                const formatDefault = (key: string, val: unknown) => {
                  if (isPercentField(key) && typeof val === 'number') return String(Math.round(val * 100));
                  return String(val);
                };
                const renderField = (field: RuleFieldDef) => {
                  const rawDefault = editingRule?.template_default_config?.[field.key];
                  const templateDefault = rawDefault !== undefined ? formatDefault(field.key, rawDefault) : undefined;
                  const currentVal = ruleForm.rule_config[field.key];
                  const isOverridden = templateDefault !== undefined && currentVal !== undefined && currentVal !== '' && String(currentVal) !== templateDefault;
                  return (
                    <div key={field.key} className="space-y-1.5">
                      <div className="flex items-baseline justify-between">
                        <label className="text-[13px] font-medium text-slate-700">{field.label}</label>
                        {templateDefault !== undefined && isOverridden && (
                          <span className="text-[11px] text-amber-500">已自定义</span>
                        )}
                      </div>
                      {field.type === 'select' ? (
                        <div className="flex gap-1">
                          {field.options?.map(o => (
                            <button
                              key={o.value}
                              type="button"
                              onClick={() => setRuleForm(f => ({ ...f, rule_config: { ...f.rule_config, [field.key]: o.value } }))}
                              className={`flex-1 px-3 py-2 text-[12px] rounded-lg border transition-all ${
                                String(currentVal) === o.value
                                  ? 'border-blue-500 bg-blue-50 text-blue-700 font-medium'
                                  : 'border-slate-200 text-slate-500 hover:border-slate-300'
                              }`}
                            >
                              {o.label}
                            </button>
                          ))}
                        </div>
                      ) : (
                        <input
                          type={field.type}
                          value={String(currentVal ?? '')}
                          onChange={e => {
                            const val = field.type === 'number' ? (e.target.value ? Number(e.target.value) : '') : e.target.value;
                            setRuleForm(f => ({ ...f, rule_config: { ...f.rule_config, [field.key]: val } }));
                          }}
                          min={field.min}
                          max={field.max}
                          step={field.step}
                          placeholder={templateDefault ?? field.placeholder}
                          className="w-full px-3 py-2.5 border border-slate-200 rounded-xl text-[13px] text-slate-800 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-300 transition-all"
                        />
                      )}
                      {field.help && <p className="text-[11px] text-slate-400 leading-relaxed">{field.help}</p>}
                      {templateDefault !== undefined && !isOverridden && (
                        <p className="text-[11px] text-slate-300">默认 {templateDefault}{isPercentField(field.key) ? '%' : ''}</p>
                      )}
                    </div>
                  );
                };
                return (
                  <div className="space-y-5 pt-1">
                    {mainFields.map(renderField)}
                    {advancedFields.length > 0 && (
                      <details className="group">
                        <summary className="text-[12px] text-slate-400 cursor-pointer hover:text-slate-500 select-none list-none transition-colors">
                          更多选项
                        </summary>
                        <div className="mt-4 space-y-5">
                          {advancedFields.map(renderField)}
                        </div>
                      </details>
                    )}
                    {ruleForm.rule_type === 'volume_anomaly' && (
                      <div className="rounded-xl bg-slate-50/80 px-4 py-3">
                        <p className="text-[12px] text-slate-500 leading-relaxed">每次执行会自动记录当天数据量，作为未来对比的基线。首次执行只采集、不报警。</p>
                      </div>
                    )}
                  </div>
                );
              })()}
              <label className="flex items-center gap-2 text-[13px] text-slate-600 pt-1">
                <input type="checkbox" checked={ruleForm.is_active} onChange={e => setRuleForm(f => ({ ...f, is_active: e.target.checked }))} className="rounded" />
                启用
              </label>
            </div>
            <div className="px-6 py-4 flex justify-end gap-2">
              <button onClick={() => setShowRuleModal(false)} className="px-5 py-2.5 text-[13px] text-slate-500 rounded-xl hover:bg-slate-50 transition-colors">取消</button>
              <button onClick={handleSaveRule} disabled={ruleFormLoading} className="px-5 py-2.5 text-[13px] text-white bg-blue-600 rounded-xl hover:bg-blue-500 disabled:opacity-50 transition-colors font-medium">
                {ruleFormLoading ? '保存中...' : editingRule ? '保存' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmModal
        open={confirm.open}
        title={confirm.title}
        message={confirm.message}
        variant="danger"
        confirmLabel="确认"
        onConfirm={confirm.onConfirm}
        onCancel={() => setConfirm(prev => ({ ...prev, open: false }))}
      />
    </div>
  );
}

// ── 资产行组件 ────────────────────────────────────────────────

function AssetRow({ asset, isExpanded, sigCfg, onToggle, onDetail, onDelete, isDataAdmin, isSelected, onToggleSelect, rulesLoading, rules, onCreateRule, onEditRule, onDeleteRule, onBatchDeleteRules, onConfirmSuggested }: {
  asset: DqcAsset;
  isExpanded: boolean;
  sigCfg: typeof SIGNAL_CONFIG.GREEN | null;
  onToggle: () => void;
  onDetail: () => void;
  onDelete: () => void;
  isDataAdmin: boolean;
  isSelected: boolean;
  onToggleSelect: () => void;
  rulesLoading: boolean;
  rules: DqcRule[];
  onCreateRule: () => void;
  onEditRule: (r: DqcRule) => void;
  onDeleteRule: (r: DqcRule) => void;
  onBatchDeleteRules: (rs: DqcRule[]) => void;
  onConfirmSuggested: (r: DqcRule) => void;
}) {
  const colSpan = isDataAdmin ? 8 : 7;
  const [selectedRuleIds, setSelectedRuleIds] = useState<Set<number>>(new Set());

  // 规则列表变化时清空选择
  useEffect(() => { setSelectedRuleIds(new Set()); }, [rules]);
  return (
    <>
      <tr className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer" onClick={onToggle}>
        {isDataAdmin && (
          <td className="pl-3 py-3" onClick={e => e.stopPropagation()}>
            <input type="checkbox" className="rounded" checked={isSelected} onChange={onToggleSelect} />
          </td>
        )}
        <td className="pl-3 py-3">
          <i className={`${isExpanded ? 'ri-arrow-down-s-line' : 'ri-arrow-right-s-line'} text-slate-400`} />
        </td>
        <td className="px-4 py-3">
          <div className="text-[12px] font-medium text-slate-700">{asset.display_name || `${asset.schema_name}.${asset.table_name}`}</div>
          {asset.display_name && <div className="text-[11px] text-slate-400">{asset.schema_name}.{asset.table_name}</div>}
        </td>
        <td className="px-4 py-3 text-[12px] text-slate-500">{asset.datasource_name ?? `#${asset.datasource_id}`}</td>
        <td className="px-4 py-3">
          {sigCfg ? (
            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${sigCfg.bg} ${sigCfg.text} ${sigCfg.border}`}>
              {asset.current_signal}
            </span>
          ) : (
            <span className="text-[10px] text-slate-400">--</span>
          )}
        </td>
        <td className="px-4 py-3 text-[12px] font-medium text-slate-700">
          {asset.current_confidence_score != null ? Math.round(asset.current_confidence_score) : '--'}
        </td>
        <td className="px-4 py-3 text-[12px] text-slate-600">{asset.active_rules_count} / {asset.rules_count}</td>
        <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
          <div className="flex items-center gap-2">
            <button onClick={onDetail} title="详情" className="text-slate-400 hover:text-blue-600"><i className="ri-settings-3-line" /></button>
            {isDataAdmin && <button onClick={onDelete} title="停用" className="text-slate-400 hover:text-red-500"><i className="ri-close-circle-line" /></button>}
          </div>
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={colSpan} className="bg-slate-50 px-4 py-3">
            <div className="ml-4 border border-slate-200 rounded-lg bg-white">
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                <span className="text-[12px] font-semibold text-slate-600">规则列表</span>
                <div className="flex items-center gap-3">
                  {isDataAdmin && selectedRuleIds.size > 0 && (
                    <button
                      onClick={() => onBatchDeleteRules(rules.filter(r => selectedRuleIds.has(r.id)))}
                      className="text-[11px] text-red-500 hover:text-red-600 flex items-center gap-1"
                    >
                      <i className="ri-delete-bin-line" />删除已选 {selectedRuleIds.size} 条
                    </button>
                  )}
                  {isDataAdmin && (
                    <button onClick={onCreateRule} className="text-[11px] text-blue-600 hover:text-blue-500 flex items-center gap-1">
                      <i className="ri-add-line" />新建规则
                    </button>
                  )}
                </div>
              </div>
              {rulesLoading ? (
                <div className="text-center py-6 text-[12px] text-slate-400">加载规则...</div>
              ) : !rules.length ? (
                <div className="text-center py-6 text-[12px] text-slate-400">暂无规则</div>
              ) : (
                <table className="w-full">
                  <thead>
                    <tr className="bg-slate-50">
                      {isDataAdmin && (
                        <th className="w-8 pl-4">
                          <input
                            type="checkbox"
                            className="rounded"
                            checked={rules.length > 0 && rules.every(r => selectedRuleIds.has(r.id))}
                            ref={el => { if (el) el.indeterminate = rules.some(r => selectedRuleIds.has(r.id)) && !rules.every(r => selectedRuleIds.has(r.id)); }}
                            onChange={e => setSelectedRuleIds(e.target.checked ? new Set(rules.map(r => r.id)) : new Set())}
                          />
                        </th>
                      )}
                      {['规则名称', '维度', '类型', '状态', '操作'].map(h => (
                        <th key={h} className="text-left text-[10px] font-semibold text-slate-500 uppercase px-4 py-2">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rules.map(rule => {
                      const isSuggested = rule.is_system_suggested && !rule.is_active;
                      return (
                        <tr key={rule.id} className="border-t border-slate-100 hover:bg-slate-50">
                          {isDataAdmin && (
                            <td className="pl-4 py-2.5">
                              <input
                                type="checkbox"
                                className="rounded"
                                checked={selectedRuleIds.has(rule.id)}
                                onChange={() => setSelectedRuleIds(prev => {
                                  const next = new Set(prev);
                                  if (next.has(rule.id)) { next.delete(rule.id); } else { next.add(rule.id); }
                                  return next;
                                })}
                              />
                            </td>
                          )}
                          <td className="px-4 py-2.5 text-[12px] text-slate-700">
                            {isSuggested && <i className="ri-lightbulb-line text-amber-500 mr-1" />}
                            {rule.name}
                          </td>
                          <td className="px-4 py-2.5 text-[12px] text-slate-600">{DIMENSION_LABELS[rule.dimension] ?? rule.dimension}</td>
                          <td className="px-4 py-2.5 text-[12px] text-slate-600">{RULE_TYPE_LABELS[rule.rule_type] ?? rule.rule_type}</td>
                          <td className="px-4 py-2.5">
                            {rule.is_active
                              ? <span className="text-[10px] font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full">启用</span>
                              : <span className="text-[10px] font-semibold text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">{isSuggested ? '待确认' : '停用'}</span>
                            }
                          </td>
                          <td className="px-4 py-2.5">
                            {isDataAdmin && (
                              <div className="flex items-center gap-2">
                                {isSuggested ? (
                                  <>
                                    <button onClick={() => onConfirmSuggested(rule)} className="text-[11px] text-emerald-600 hover:text-emerald-500">确认</button>
                                    <button onClick={() => onDeleteRule(rule)} className="text-[11px] text-slate-400 hover:text-red-500">忽略</button>
                                  </>
                                ) : (
                                  <>
                                    <button onClick={() => onEditRule(rule)} className="text-[11px] text-blue-600 hover:text-blue-500">编辑</button>
                                    <button onClick={() => onDeleteRule(rule)} className="text-[11px] text-slate-400 hover:text-red-500">删除</button>
                                  </>
                                )}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── 多选筛选器 ────────────────────────────────────────────────

function MultiSelectFilter<T extends { id: string | number; name: string }>({
  options, selected, onChange, label, getKey, getLabel, toValue,
}: {
  options: T[];
  selected: Set<string | number>;
  onChange: (next: Set<string | number>) => void;
  label: string;
  getKey: (o: T) => string | number;
  getLabel: (o: T) => string;
  toValue: (k: string) => string | number;
}) {
  const [open, setOpen] = useState(false);
  const count = selected.size;
  const btnLabel = count === 0 ? label
    : count === 1 ? getLabel(options.find(o => String(getKey(o)) === String([...selected][0]))!) || label
    : `${count} 项已选`;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className={`flex items-center gap-1 text-xs px-3 py-1.5 border rounded-lg bg-white transition-colors ${count > 0 ? 'border-blue-300 text-blue-700' : 'border-slate-200 text-slate-600'}`}
      >
        {btnLabel}
        <i className={`ri-arrow-${open ? 'up' : 'down'}-s-line text-slate-400`} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute top-full mt-1 left-0 z-20 bg-white border border-slate-200 rounded-lg shadow-lg py-1 min-w-[180px] max-h-64 overflow-y-auto">
            {options.length === 0 && (
              <div className="px-3 py-2 text-[12px] text-slate-400">暂无选项</div>
            )}
            {options.map(o => {
              const key = String(getKey(o));
              const checked = selected.has(toValue(key));
              return (
                <label key={key} className="flex items-center gap-2 px-3 py-1.5 hover:bg-slate-50 cursor-pointer">
                  <input
                    type="checkbox"
                    className="rounded shrink-0"
                    checked={checked}
                    onChange={() => {
                      const next = new Set(selected);
                      if (checked) { next.delete(toValue(key)); } else { next.add(toValue(key)); }
                      onChange(next);
                    }}
                  />
                  <span className="text-[12px] text-slate-700 truncate">{getLabel(o)}</span>
                </label>
              );
            })}
            {count > 0 && (
              <div className="border-t border-slate-100 mt-1 pt-1">
                <button onClick={() => { onChange(new Set()); setOpen(false); }} className="w-full text-left px-3 py-1.5 text-[11px] text-slate-400 hover:text-slate-600">
                  清空筛选
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ── 批量导入 Modal ────────────────────────────────────────────

type TableItem = { schema_name: string; table_name: string };
type ImportStep = 'pick-source' | 'select-tables';

function BatchImportModal({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [step, setStep] = useState<ImportStep>('pick-source');
  const [datasources, setDatasources] = useState<DataSource[]>([]);
  const [datasourceId, setDatasourceId] = useState<number>(0);
  const [autoSuggest, setAutoSuggest] = useState(false);
  const [loadingTables, setLoadingTables] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [allTables, setAllTables] = useState<TableItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState('');

  useEffect(() => {
    listDataSources().then(r => setDatasources(r.datasources)).catch(() => {});
  }, []);

  const key = (t: TableItem) => `${t.schema_name}.${t.table_name}`;

  const filtered = useMemo(() => {
    if (!search.trim()) return allTables;
    const q = search.toLowerCase();
    return allTables.filter(t => t.table_name.toLowerCase().includes(q) || t.schema_name.toLowerCase().includes(q));
  }, [allTables, search]);

  const groups = useMemo(() => {
    const map = new Map<string, TableItem[]>();
    for (const t of filtered) {
      const arr = map.get(t.schema_name) ?? [];
      arr.push(t);
      map.set(t.schema_name, arr);
    }
    return new Map([...map.entries()].sort((a, b) => a[0].localeCompare(b[0])));
  }, [filtered]);

  const handleLoadTables = async () => {
    if (!datasourceId) { setLoadError('请选择数据源'); return; }
    setLoadingTables(true);
    setLoadError('');
    try {
      const res = await listDatasourceTables(datasourceId);
      setAllTables(res.items);
      setSelected(new Set(res.items.map(key)));
      setStep('select-tables');
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : '加载失败，请重试');
    } finally {
      setLoadingTables(false);
    }
  };

  const toggleItem = (t: TableItem) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(key(t))) next.delete(key(t)); else next.add(key(t));
      return next;
    });
  };

  const toggleSchema = (schema: string) => {
    const items = groups.get(schema) ?? [];
    const allSelected = items.every(t => selected.has(key(t)));
    setSelected(prev => {
      const next = new Set(prev);
      items.forEach(t => allSelected ? next.delete(key(t)) : next.add(key(t)));
      return next;
    });
  };

  const toggleAll = () => {
    const allSelected = filtered.every(t => selected.has(key(t)));
    setSelected(prev => {
      const next = new Set(prev);
      filtered.forEach(t => allSelected ? next.delete(key(t)) : next.add(key(t)));
      return next;
    });
  };

  const handleImport = async () => {
    if (selected.size === 0) return;
    setSaving(true);
    setSaveResult('');
    try {
      const tables = allTables.filter(t => selected.has(key(t)));
      const res = await batchImportAssets({ datasource_id: datasourceId, tables, auto_suggest_rules: autoSuggest });
      setSaveResult(`成功注册 ${res.created} 张，跳过 ${res.skipped} 张已存在`);
      setTimeout(() => onImported(), 1800);
    } catch (e) {
      setSaveResult(e instanceof Error ? e.message : '导入失败，请重试');
      setSaving(false);
    }
  };

  // 三态 checkbox ref helper
  const SchemaCheckbox = ({ schema }: { schema: string }) => {
    const items = groups.get(schema) ?? [];
    const selectedCount = items.filter(t => selected.has(key(t))).length;
    const allChk = selectedCount === items.length;
    const indeterminate = selectedCount > 0 && selectedCount < items.length;
    const ref = useRef<HTMLInputElement>(null);
    useEffect(() => { if (ref.current) ref.current.indeterminate = indeterminate; }, [indeterminate]);
    return (
      <input
        ref={ref}
        type="checkbox"
        checked={allChk}
        onChange={() => toggleSchema(schema)}
        className="rounded"
        onClick={e => e.stopPropagation()}
      />
    );
  };

  const allFilteredSelected = filtered.length > 0 && filtered.every(t => selected.has(key(t)));

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl mx-4 flex flex-col max-h-[88vh]" onClick={e => e.stopPropagation()}>
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 shrink-0">
          <div>
            <h2 className="text-[15px] font-semibold text-slate-800">从数据源批量导入</h2>
            {step === 'select-tables' && (
              <p className="text-[11px] text-slate-400 mt-0.5">已选 {selected.size} 张 / 共 {allTables.length} 张</p>
            )}
          </div>
          <button onClick={onClose}><i className="ri-close-line text-slate-400 hover:text-slate-600 text-lg" /></button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {/* Step 1: 选数据源 */}
          {step === 'pick-source' && (
            <div className="px-6 py-6 space-y-5">
              {loadError && (
                <div className="px-3 py-2 bg-red-50 text-red-600 text-[12px] rounded-lg">{loadError}</div>
              )}
              <div>
                <label className="text-[11px] font-medium text-slate-500 mb-1.5 block">数据源</label>
                <select
                  value={datasourceId || ''}
                  onChange={e => setDatasourceId(Number(e.target.value))}
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px]"
                >
                  <option value="">选择数据源</option>
                  {datasources.map(ds => <option key={ds.id} value={ds.id}>{ds.name}</option>)}
                </select>
              </div>
              <label className="flex items-start gap-2.5 text-[12px] text-slate-600 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoSuggest}
                  onChange={e => setAutoSuggest(e.target.checked)}
                  className="rounded mt-0.5"
                />
                <span>
                  导入后自动 Profiling 并推荐规则
                  <span className="block text-[11px] text-slate-400 mt-0.5">2000+ 张表建议关闭，可导入后逐表开启</span>
                </span>
              </label>
            </div>
          )}

          {/* Step 2: 选表 */}
          {step === 'select-tables' && (
            <div className="flex flex-col h-full">
              {/* 搜索 + 全选 */}
              <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-3 shrink-0">
                <div className="relative flex-1">
                  <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
                  <input
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="搜索 schema 或表名..."
                    className="w-full pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-[12px]"
                  />
                </div>
                <button
                  onClick={toggleAll}
                  className="text-[11px] text-slate-500 hover:text-slate-700 whitespace-nowrap"
                >
                  {allFilteredSelected ? '清空' : '全选'}
                </button>
              </div>

              {/* 树形列表 */}
              <div className="overflow-y-auto flex-1 py-1">
                {groups.size === 0 ? (
                  <div className="text-center py-12 text-[12px] text-slate-400">无匹配表</div>
                ) : (
                  [...groups.entries()].map(([schema, tables]) => {
                    const isCollapsed = collapsed.has(schema);
                    const selCount = tables.filter(t => selected.has(key(t))).length;
                    return (
                      <div key={schema}>
                        {/* Schema 节点 */}
                        <div
                          className="flex items-center gap-1.5 px-3 py-1.5 hover:bg-slate-50 cursor-pointer select-none"
                          onClick={() => setCollapsed(prev => {
                            const next = new Set(prev);
                            if (isCollapsed) { next.delete(schema); } else { next.add(schema); }
                            return next;
                          })}
                        >
                          <i className={`ri-arrow-${isCollapsed ? 'right' : 'down'}-s-line text-slate-400 text-[13px] w-4 shrink-0`} />
                          <i className="ri-database-2-line text-blue-400 text-[13px] shrink-0" />
                          <span className="text-[12px] font-medium text-slate-800 flex-1 truncate">{schema}</span>
                          <span className="text-[10px] text-slate-400 mr-2 shrink-0">{selCount}/{tables.length}</span>
                          <span onClick={e => e.stopPropagation()}>
                            <SchemaCheckbox schema={schema} />
                          </span>
                        </div>
                        {/* 表节点（缩进 + 左边框连线） */}
                        {!isCollapsed && (
                          <div className="ml-[22px] border-l border-slate-200">
                            {tables.map((t) => (
                              <div
                                key={t.table_name}
                                onClick={() => toggleItem(t)}
                                className="flex items-center gap-1.5 pl-3 pr-3 py-1 hover:bg-blue-50 cursor-pointer relative"
                              >
                                {/* 横向连接线 */}
                                <span className="absolute left-0 top-1/2 w-3 h-px bg-slate-200 -translate-y-px shrink-0" />
                                <i className="ri-table-line text-slate-300 text-[12px] shrink-0" />
                                <span className="text-[12px] text-slate-600 flex-1 truncate">{t.table_name}</span>
                                <input
                                  type="checkbox"
                                  checked={selected.has(key(t))}
                                  onChange={() => toggleItem(t)}
                                  onClick={e => e.stopPropagation()}
                                  className="rounded shrink-0"
                                />
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}
        </div>

        {/* 底部操作栏 */}
        <div className="px-6 py-4 border-t border-slate-100 shrink-0">
          {saveResult && (
            <p className={`text-[12px] mb-3 ${saveResult.includes('失败') ? 'text-red-600' : 'text-emerald-600'}`}>
              {saveResult}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button
              onClick={step === 'select-tables' ? () => setStep('pick-source') : onClose}
              className="px-4 py-2 text-[12px] text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50"
            >
              {step === 'select-tables' ? '上一步' : '取消'}
            </button>
            {step === 'pick-source' ? (
              <button
                onClick={handleLoadTables}
                disabled={loadingTables || !datasourceId}
                className="px-4 py-2 text-[12px] text-white bg-blue-600 rounded-lg hover:bg-blue-500 disabled:opacity-50 flex items-center gap-1.5"
              >
                {loadingTables ? <><i className="ri-loader-4-line animate-spin" />加载中…</> : '加载表列表'}
              </button>
            ) : (
              <button
                onClick={handleImport}
                disabled={saving || selected.size === 0}
                className="px-4 py-2 text-[12px] text-white bg-slate-800 rounded-lg hover:bg-slate-700 disabled:opacity-50 flex items-center gap-1.5"
              >
                {saving ? <><i className="ri-loader-4-line animate-spin" />导入中…</> : `导入已选 ${selected.size} 张`}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
