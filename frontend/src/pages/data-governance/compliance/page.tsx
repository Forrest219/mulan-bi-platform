import { useState, useEffect, useCallback } from 'react';
import {
  listComplianceRules,
  toggleComplianceRule,
  CATEGORY_LABELS,
  CATEGORY_ICONS,
} from '@/api/compliance';
import type { ComplianceRule } from '@/api/compliance';
import {
  triggerScan,
  getHealthSummary,
  getScan,
  getScanIssues,
} from '@/api/health-scan';
import type { HealthScan, HealthIssue } from '@/api/health-scan';
import { listDataSources } from '@/api/datasources';
import { useRef } from 'react';

const severityConfig: Record<string, { label: string; bg: string; text: string; border: string; dot: string }> = {
  high: { label: '高风险', bg: 'bg-red-50', text: 'text-red-600', border: 'border-red-200', dot: 'bg-red-500' },
  medium: { label: '中风险', bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-200', dot: 'bg-amber-500' },
  low: { label: '低风险', bg: 'bg-blue-50', text: 'text-blue-600', border: 'border-blue-200', dot: 'bg-blue-500' },
};

const levelConfig: Record<string, { label: string; bg: string; text: string }> = {
  HIGH: { label: '高', bg: 'bg-red-50', text: 'text-red-600' },
  MEDIUM: { label: '中', bg: 'bg-amber-50', text: 'text-amber-600' },
  LOW: { label: '低', bg: 'bg-blue-50', text: 'text-blue-600' },
};

type SubTab = 'rules' | 'results';

function ScoreBar({ score }: { score: number }) {
  const color = score >= 90 ? 'bg-emerald-500' : score >= 75 ? 'bg-amber-400' : 'bg-red-500';
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-sm font-bold text-slate-700 w-8">{score}</span>
    </div>
  );
}

export default function CompliancePage() {
  const [rules, setRules] = useState<ComplianceRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(true);
  const [error, setError] = useState('');
  const [subTab, setSubTab] = useState<SubTab>('rules');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterLevel, setFilterLevel] = useState('');
  const [toggling, setToggling] = useState<string | null>(null);

  // Scan state
  const [datasources, setDatasources] = useState<{ id: number; name: string; db_type: string; database_name: string }[]>([]);
  const [srDatasources, setSrDatasources] = useState<{ id: number; name: string; db_type: string; database_name: string }[]>([]);
  const [selectedDsId, setSelectedDsId] = useState<number | null>(null);
  const [showDsPicker, setShowDsPicker] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [activeScan, setActiveScan] = useState<HealthScan | null>(null);
  const [issues, setIssues] = useState<HealthIssue[]>([]);
  const [issueTotal, setIssueTotal] = useState(0);
  const [filterSeverity, setFilterSeverity] = useState('');
  const [issuePage, setIssuePage] = useState(1);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load rules
  useEffect(() => {
    loadRules();
    loadDatasources();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
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

  async function loadDatasources() {
    try {
      const res = await listDataSources();
      const all = Array.isArray(res) ? res : res.datasources || [];
      setDatasources(all);
      const sr = all.filter((ds: { db_type: string }) =>
        ds.db_type.toLowerCase() === 'starrocks'
      );
      setSrDatasources(sr);

      // Load latest StarRocks scans
      const summary = await getHealthSummary();
      const srScan = summary.scans.find(
        (s) => s.db_type.toLowerCase() === 'starrocks' && s.status === 'success'
      );
      if (srScan) {
        setActiveScan(srScan);
      }
    } catch (_err) {
      // ignore datasource load errors
    }
  }

  const loadIssues = useCallback(async (scanId: number) => {
    try {
      const data = await getScanIssues(scanId, {
        severity: filterSeverity || undefined,
        page: issuePage,
        page_size: 50,
      });
      setIssues(data.issues);
      setIssueTotal(data.total);
    } catch (_err) {
      // ignore
    }
  }, [filterSeverity, issuePage]);

  useEffect(() => {
    if (activeScan && activeScan.status === 'success' && subTab === 'results') {
      loadIssues(activeScan.id);
    }
  }, [activeScan, loadIssues, subTab]);

  async function handleToggle(ruleId: string) {
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
  }

  async function handleTriggerScan() {
    if (!selectedDsId) return;
    setShowDsPicker(false);
    setScanning(true);
    setError('');
    try {
      const { scan_id } = await triggerScan(selectedDsId);
      pollRef.current = setInterval(async () => {
        try {
          const scan = await getScan(scan_id);
          if (scan.status !== 'running' && scan.status !== 'pending') {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setScanning(false);
            setActiveScan(scan);
            setSubTab('results');
          }
        } catch (_err) {
          // ignore transient polling errors
        }
      }, 3000);
    } catch (e: unknown) {
      setScanning(false);
      const msg = e instanceof Error ? e.message : '扫描失败';
      setError(msg);
    }
  }

  // Group rules by category
  const categories = Array.from(new Set(rules.map((r) => r.category)));
  const filteredRules = rules.filter((r) => {
    if (filterCategory && r.category !== filterCategory) return false;
    if (filterLevel && r.level !== filterLevel) return false;
    return true;
  });

  const groupedRules: Record<string, ComplianceRule[]> = {};
  for (const r of filteredRules) {
    if (!groupedRules[r.category]) groupedRules[r.category] = [];
    groupedRules[r.category].push(r);
  }

  // Stats
  const enabledCount = rules.filter((r) => r.status === 'enabled').length;
  const highCount = rules.filter((r) => r.level === 'HIGH').length;
  const mediumCount = rules.filter((r) => r.level === 'MEDIUM').length;

  // SR-specific issue type labels
  const issueTypeLabels: Record<string, string> = {
    sr_layer_naming: '分层命名',
    sr_type_alignment: '字段类型对齐',
    sr_public_fields: '公共字段',
    sr_field_naming: '字段命名',
    sr_comment: '注释规范',
    sr_database_whitelist: '数据库白名单',
    sr_table_naming: '表名规范',
    sr_view_naming: '视图命名',
    ...CATEGORY_LABELS,
  };

  return (
    <div className="max-w-6xl mx-auto px-8 py-7">
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
          <div className="text-[11px] text-slate-400 mt-0.5">HIGH 级别规则</div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-slate-500">中优先级</span>
            <i className="ri-alert-line text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-amber-600">{mediumCount}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">MEDIUM 级别规则</div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-slate-500">巡检评分</span>
            <i className="ri-award-line text-slate-400" />
          </div>
          {activeScan ? (
            <>
              <div className="mb-2"><ScoreBar score={activeScan.health_score ?? 0} /></div>
              <div className="text-[11px] text-slate-400 mt-0.5">
                {activeScan.datasource_name} · {activeScan.total_issues} 个问题
              </div>
            </>
          ) : (
            <>
              <div className="text-2xl font-bold text-slate-300">-</div>
              <div className="text-[11px] text-slate-400 mt-0.5">暂无巡检记录</div>
            </>
          )}
        </div>
      </div>

      {/* Sub-tab switcher + scan button */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-1 bg-white border border-slate-200 rounded-lg p-1 w-fit">
          {[
            { key: 'rules' as SubTab, label: '合规规则', icon: 'ri-file-list-3-line' },
            { key: 'results' as SubTab, label: '巡检结果', icon: 'ri-bar-chart-box-line' },
          ].map((t) => (
            <button
              key={t.key}
              onClick={() => setSubTab(t.key)}
              className={`flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                subTab === t.key
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              <i className={t.icon} />
              {t.label}
            </button>
          ))}
        </div>

        <div className="relative">
          <button
            onClick={() => setShowDsPicker(!showDsPicker)}
            disabled={scanning}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700 transition-colors cursor-pointer disabled:opacity-50"
          >
            {scanning ? (
              <><i className="ri-loader-4-line animate-spin" /> 巡检中...</>
            ) : (
              <><i className="ri-play-line" /> 发起巡检</>
            )}
          </button>
          {showDsPicker && (
            <div className="absolute right-0 top-full mt-2 w-72 bg-white border border-slate-200 rounded-xl shadow-lg z-10 p-4">
              <p className="text-xs text-slate-500 mb-2">选择 StarRocks 数据源</p>
              {srDatasources.length === 0 ? (
                <div>
                  <p className="text-xs text-slate-400 mb-2">暂无 StarRocks 数据源</p>
                  {datasources.length > 0 && (
                    <>
                      <p className="text-xs text-slate-500 mb-2">其他数据源</p>
                      <div className="space-y-1 max-h-48 overflow-auto">
                        {datasources.map((ds) => (
                          <button
                            key={ds.id}
                            onClick={() => setSelectedDsId(ds.id)}
                            className={`w-full text-left px-3 py-2 rounded-lg text-xs hover:bg-slate-50 ${
                              selectedDsId === ds.id ? 'bg-blue-50 text-blue-600' : 'text-slate-700'
                            }`}
                          >
                            <div className="font-medium">{ds.name}</div>
                            <div className="text-slate-400">{ds.db_type} · {ds.database_name}</div>
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <div className="space-y-1 max-h-48 overflow-auto">
                  {srDatasources.map((ds) => (
                    <button
                      key={ds.id}
                      onClick={() => setSelectedDsId(ds.id)}
                      className={`w-full text-left px-3 py-2 rounded-lg text-xs hover:bg-slate-50 ${
                        selectedDsId === ds.id ? 'bg-blue-50 text-blue-600' : 'text-slate-700'
                      }`}
                    >
                      <div className="font-medium">{ds.name}</div>
                      <div className="text-slate-400">StarRocks · {ds.database_name}</div>
                    </button>
                  ))}
                </div>
              )}
              <div className="flex justify-end gap-2 mt-3 pt-3 border-t border-slate-100">
                <button onClick={() => setShowDsPicker(false)} className="px-3 py-1 text-xs text-slate-500 hover:bg-slate-100 rounded-lg">
                  取消
                </button>
                <button
                  onClick={handleTriggerScan}
                  disabled={!selectedDsId}
                  className="px-3 py-1 text-xs bg-slate-900 text-white rounded-lg hover:bg-slate-700 disabled:opacity-50"
                >
                  确认巡检
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {subTab === 'rules' ? (
        <>
          {/* Filter bar */}
          <div className="flex items-center gap-3 mb-4">
            <select
              value={filterCategory}
              onChange={(e) => setFilterCategory(e.target.value)}
              className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
            >
              <option value="">全部分类</option>
              {categories.map((cat) => (
                <option key={cat} value={cat}>{CATEGORY_LABELS[cat] || cat}</option>
              ))}
            </select>
            <select
              value={filterLevel}
              onChange={(e) => setFilterLevel(e.target.value)}
              className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
            >
              <option value="">全部级别</option>
              <option value="HIGH">HIGH</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="LOW">LOW</option>
            </select>
            <span className="text-[11px] text-slate-400 ml-auto">
              共 {filteredRules.length} 条规则
            </span>
          </div>

          {rulesLoading ? (
            <div className="text-center py-20 text-slate-400 text-sm">加载中...</div>
          ) : (
            <div className="space-y-4">
              {Object.entries(groupedRules).map(([category, catRules]) => (
                <div key={category} className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                  <div className="px-5 py-3 border-b border-slate-100 flex items-center gap-2">
                    <i className={`${CATEGORY_ICONS[category] || 'ri-file-list-line'} text-slate-500`} />
                    <h3 className="text-[13px] font-semibold text-slate-700">
                      {CATEGORY_LABELS[category] || category}
                    </h3>
                    <span className="text-[11px] text-slate-400 ml-1">({catRules.length})</span>
                  </div>
                  <table className="w-full">
                    <thead>
                      <tr className="bg-slate-50">
                        {['规则 ID', '名称', '级别', '描述', '修复建议', '状态'].map((h) => (
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
                      {catRules.map((rule) => {
                        const lc = levelConfig[rule.level] || levelConfig.MEDIUM;
                        return (
                          <tr key={rule.id} className="border-t border-slate-100 hover:bg-slate-50">
                            <td className="px-4 py-3 text-[12px] font-mono text-slate-500">{rule.id}</td>
                            <td className="px-4 py-3 text-[12px] font-medium text-slate-700">{rule.name}</td>
                            <td className="px-4 py-3">
                              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${lc.bg} ${lc.text}`}>
                                {lc.label}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-[12px] text-slate-600 max-w-xs">{rule.description}</td>
                            <td className="px-4 py-3 text-[12px] text-slate-500 max-w-xs">{rule.suggestion}</td>
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
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ))}

              {Object.keys(groupedRules).length === 0 && (
                <div className="text-center py-10 text-slate-400 text-xs">
                  暂无匹配规则
                </div>
              )}
            </div>
          )}
        </>
      ) : (
        /* Results tab */
        <>
          {!activeScan ? (
            <div className="text-center py-20">
              <i className="ri-checkbox-circle-line text-4xl text-slate-300 mb-3 block" />
              <p className="text-slate-400 text-sm mb-1">暂无巡检记录</p>
              <p className="text-slate-300 text-xs">选择 StarRocks 数据源后点击"发起巡检"开始</p>
            </div>
          ) : activeScan.status === 'failed' ? (
            <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
              <i className="ri-error-warning-line text-3xl text-red-400 mb-2 block" />
              <p className="text-red-600 text-sm font-medium mb-1">巡检失败</p>
              <p className="text-red-400 text-xs">{activeScan.error_message || '未知错误'}</p>
            </div>
          ) : (
            <>
              {/* Scan summary */}
              <div className="bg-white border border-slate-200 rounded-xl p-5 mb-5">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-[13px] font-semibold text-slate-700">巡检概要</h3>
                  <span className="text-[11px] text-slate-400">
                    {activeScan.finished_at || activeScan.started_at || '-'}
                  </span>
                </div>
                <div className="grid grid-cols-4 gap-4">
                  <div>
                    <div className="text-[11px] text-slate-500 mb-1">数据源</div>
                    <div className="text-sm font-medium text-slate-700">{activeScan.datasource_name}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-slate-500 mb-1">检查表数</div>
                    <div className="text-sm font-medium text-slate-700">{activeScan.total_tables}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-slate-500 mb-1">问题总数</div>
                    <div className="text-sm font-medium text-slate-700">{activeScan.total_issues}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-slate-500 mb-1">风险分布</div>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-red-600 font-bold">{activeScan.high_count}</span>
                      <span className="text-slate-300">/</span>
                      <span className="text-amber-600 font-bold">{activeScan.medium_count}</span>
                      <span className="text-slate-300">/</span>
                      <span className="text-blue-600 font-bold">{activeScan.low_count}</span>
                      <span className="text-[10px] text-slate-400">高/中/低</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Issue list */}
              <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
                  <h3 className="text-[13px] font-semibold text-slate-700">
                    违规项 <span className="text-slate-400 font-normal ml-1">({issueTotal})</span>
                  </h3>
                  <select
                    value={filterSeverity}
                    onChange={(e) => { setFilterSeverity(e.target.value); setIssuePage(1); }}
                    className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
                  >
                    <option value="">全部风险</option>
                    <option value="high">高风险</option>
                    <option value="medium">中风险</option>
                    <option value="low">低风险</option>
                  </select>
                </div>

                {issues.length === 0 ? (
                  <div className="text-center py-10 text-slate-400 text-xs">
                    {activeScan.status === 'success' ? '未发现违规项' : '巡检未完成'}
                  </div>
                ) : (
                  <table className="w-full">
                    <thead>
                      <tr className="bg-slate-50">
                        {['风险', '对象类型', '对象名称', '违规类型', '描述', '修复建议'].map((h) => (
                          <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 whitespace-nowrap">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {issues.map((issue) => {
                        const sc = severityConfig[issue.severity] || severityConfig.low;
                        return (
                          <tr key={issue.id} className="border-t border-slate-100 hover:bg-slate-50">
                            <td className="px-4 py-3">
                              <span className={`flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${sc.bg} ${sc.text} ${sc.border}`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${sc.dot}`} />
                                {sc.label}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-[12px] text-slate-500">
                              {issue.object_type === 'table' ? (
                                <><i className="ri-table-line mr-1" />表</>
                              ) : (
                                <><i className="ri-function-line mr-1" />字段</>
                              )}
                            </td>
                            <td className="px-4 py-3 text-[12px] font-medium text-slate-700 font-mono">{issue.object_name}</td>
                            <td className="px-4 py-3 text-[12px] text-slate-600">
                              {issueTypeLabels[issue.issue_type] || issue.issue_type}
                            </td>
                            <td className="px-4 py-3 text-[12px] text-slate-600 max-w-xs truncate">{issue.description}</td>
                            <td className="px-4 py-3 text-[12px] text-slate-500 max-w-xs truncate">{issue.suggestion}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}

                {issueTotal > 50 && (
                  <div className="px-5 py-3 border-t border-slate-100 flex items-center justify-between">
                    <span className="text-[11px] text-slate-400">共 {issueTotal} 条</span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setIssuePage(Math.max(1, issuePage - 1))}
                        disabled={issuePage <= 1}
                        className="px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 rounded disabled:opacity-50"
                      >上一页</button>
                      <span className="text-xs text-slate-500">{issuePage}</span>
                      <button
                        onClick={() => setIssuePage(issuePage + 1)}
                        disabled={issuePage * 50 >= issueTotal}
                        className="px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 rounded disabled:opacity-50"
                      >下一页</button>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
