import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { triggerScan, getHealthSummary, getScan, getScanIssues, listScans, downloadScanReport } from '@/api/health-scan';
import type { HealthScan, HealthIssue } from '@/api/health-scan';
import { listDataSources } from '@/api/datasources';

const severityConfig = {
  high: { label: '高风险', bg: 'bg-red-50', text: 'text-red-600', border: 'border-red-200', dot: 'bg-red-500' },
  medium: { label: '中风险', bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-200', dot: 'bg-amber-500' },
  low: { label: '低风险', bg: 'bg-blue-50', text: 'text-blue-600', border: 'border-blue-200', dot: 'bg-blue-500' },
};

const issueTypeLabels: Record<string, string> = {
  // MySQL / 通用规则
  naming: '命名规范',
  comment: '缺少注释',
  primary_key: '缺失主键',
  update_field: '缺失更新字段',
  data_type: '数据类型问题',
  table_naming: '表命名规范',
  column_naming: '字段命名规范',
  table_comment: '表缺少注释',
  column_comment: '字段缺少注释',
  missing_pk: '缺失主键',
  missing_update_time: '缺失更新字段',
  // StarRocks 规则分类 (rule.category → 友好名称)
  sr_layer_naming: '分层命名规范',
  sr_type_alignment: '类型对齐',
  sr_public_fields: '公共字段',
  sr_field_naming: '字段命名规范',
  sr_comment: '注释规范',
  sr_database_whitelist: '数据库白名单',
  sr_table_naming: '表命名规范',
  sr_view_naming: '视图命名规范',
};

// rule_id → 友好名称（用于 rule_name 为 rule_id 格式的情况）
const ruleIdLabels: Record<string, string> = {
  RULE_SR_001: 'ODS 双下划线命名',
  RULE_SR_002: 'DWD 业务域+粒度后缀',
  RULE_SR_003: 'DIM 无业务域前缀',
  RULE_SR_004: 'DWS 粒度后缀',
  RULE_SR_005: 'ADS 场景前缀',
  RULE_SR_006: '金额字段必须 DECIMAL',
  RULE_SR_007: '日期字段禁止 VARCHAR',
  RULE_SR_008: '公共字段 etl_time',
  RULE_SR_009: '公共字段 dt',
  RULE_SR_010: 'ODS 全套公共字段',
  RULE_SR_011: 'ODS_DB CDC 字段',
  RULE_SR_012: '字段 snake_case',
  RULE_SR_013: '字段注释覆盖率',
  RULE_SR_014: '表注释存在',
  RULE_SR_015: '禁止额外数据库',
  RULE_SR_016: 'Feature 表命名',
  RULE_SR_017: 'AI 表前缀',
  RULE_SR_018: 'Backup 命名含日期',
  RULE_SR_019: '数量字段类型',
  RULE_SR_020: '比率字段类型',
  RULE_SR_021: '无 ods_hive 库',
  RULE_SR_022: '表名无中文',
  RULE_SR_023: '表名无版本号',
  RULE_SR_024: 'DM 部门前缀',
  RULE_SR_025: '视图命名 _vw 后缀',
};

function ScoreBar({ score }: { score: number | null }) {
  if (score === null || score === undefined) {
    return <span className="text-sm text-slate-400">无数据</span>;
  }
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

interface DataHealthPageProps {
  headerControlsRef?: React.RefObject<HTMLDivElement | null>;
}

// 本组件由 dw-audit/page.tsx 作为 tab 子页面渲染，外层已提供 header + min-h-screen 容器
export default function DataHealthPage({ headerControlsRef }: DataHealthPageProps) {
  const [summaryScans, setSummaryScans] = useState<HealthScan[]>([]);
  const [activeScan, setActiveScan] = useState<HealthScan | null>(null);
  const [issues, setIssues] = useState<HealthIssue[]>([]);
  const [issueTotal, setIssueTotal] = useState(0);
  const [filterSeverity, setFilterSeverity] = useState('');
  const [filterObjectType, setFilterObjectType] = useState('');
  const [filterObjectName, setFilterObjectName] = useState('');
  const [issuePage, setIssuePage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState('');

  // Datasource picker
  const [datasources, setDatasources] = useState<any[]>([]);
  const [showDsPicker, setShowDsPicker] = useState(false);
  const [selectedDsId, setSelectedDsId] = useState<number | null>(null);
  const [tab, setTab] = useState<'overview' | 'history'>('overview');
  const [history, setHistory] = useState<HealthScan[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [filterDb, setFilterDb] = useState('all');

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load summary on mount
  useEffect(() => {
    loadSummary();
    loadDatasources();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  async function loadSummary() {
    setLoading(true);
    try {
      const data = await getHealthSummary();
      setSummaryScans(data.scans);
      if (data.scans.length > 0) {
        const latest = data.scans.reduce((a, b) => (a.id > b.id ? a : b));
        setActiveScan(latest);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadDatasources() {
    try {
      const res = await listDataSources();
      setDatasources(Array.isArray(res) ? res : res.datasources || []);
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
      // ignore issues loading errors to keep page usable
    }
  }, [filterSeverity, issuePage]);

  const filteredIssues = issues.filter((i) => {
    if (filterObjectType && i.object_type !== filterObjectType) return false;
    if (filterObjectName && !i.object_name.toLowerCase().includes(filterObjectName.toLowerCase())) return false;
    return true;
  });

  const loadHistory = useCallback(async () => {
    try {
      const data = await listScans({ page: historyPage, page_size: 20 });
      setHistory(data.scans);
      setHistoryTotal(data.total);
    } catch (_err) {
      // ignore history loading errors to keep page usable
    }
  }, [historyPage]);

  // Load issues when activeScan or filters change
  useEffect(() => {
    if (activeScan && activeScan.status === 'success') {
      loadIssues(activeScan.id);
    }
  }, [activeScan, loadIssues]);

  useEffect(() => {
    if (tab === 'history') loadHistory();
  }, [tab, loadHistory]);

  const uniqueDbs = [...new Set(summaryScans.map(s => s.database_name).filter(Boolean))];

  useEffect(() => {
    if (summaryScans.length === 0) return;
    if (filterDb === 'all') {
      const latest = summaryScans.reduce((a, b) => (a.id > b.id ? a : b));
      setActiveScan(latest);
    } else {
      const match = summaryScans.filter(s => s.database_name === filterDb);
      if (match.length > 0) {
        setActiveScan(match.reduce((a, b) => (a.id > b.id ? a : b)));
      }
    }
    setIssuePage(1);
    setFilterSeverity('');
    setFilterObjectType('');
    setFilterObjectName('');
  }, [filterDb, summaryScans]);

  async function handleExportReport() {
    if (!activeScan) return;
    setExporting(true);
    try {
      await downloadScanReport(activeScan.id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setExporting(false);
    }
  }

  async function handleTriggerScan() {
    if (!selectedDsId) return;
    setShowDsPicker(false);
    setScanning(true);
    setError('');
    try {
      const { scan_id } = await triggerScan(selectedDsId);
      // Poll for completion
      pollRef.current = setInterval(async () => {
        try {
          const scan = await getScan(scan_id);
          if (scan.status !== 'running' && scan.status !== 'pending') {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setScanning(false);
            setActiveScan(scan);
            loadSummary();
          }
        } catch (_err) {
          // ignore transient polling errors
        }
      }, 3000);
    } catch (e: any) {
      setScanning(false);
      setError(e.message);
    }
  }

  // Aggregate stats from active scan
  const score = activeScan?.health_score ?? null;
  const noData = score === null || activeScan?.total_tables === 0;
  const totalTables = activeScan?.total_tables ?? 0;
  const totalIssues = activeScan?.total_issues ?? 0;
  const highCount = activeScan?.high_count ?? 0;
  const mediumCount = activeScan?.medium_count ?? 0;
  const lowCount = activeScan?.low_count ?? 0;
  const lastScan = activeScan?.finished_at || activeScan?.started_at || '-';

  const headerControls = (
    <>
      <select
        value={filterDb}
        onChange={e => setFilterDb(e.target.value)}
        className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
      >
        <option value="all">全部</option>
        {uniqueDbs.map(db => (
          <option key={db} value={db}>{db}</option>
        ))}
      </select>
      <div className="relative">
        <button
          onClick={() => setShowDsPicker(!showDsPicker)}
          disabled={scanning}
          className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700 transition-colors cursor-pointer disabled:opacity-50"
        >
          {scanning ? (
            <><i className="ri-loader-4-line animate-spin" /> 扫描中...</>
          ) : (
            <><i className="ri-play-line" /> 发起扫描</>
          )}
        </button>
        {showDsPicker && (
          <div className="absolute right-0 top-full mt-2 w-72 bg-white border border-slate-200 rounded-xl shadow-lg z-10 p-4">
            <p className="text-xs text-slate-500 mb-2">选择数据源</p>
            {datasources.length === 0 ? (
              <p className="text-xs text-slate-400">暂无数据源，请先在管理后台添加</p>
            ) : (
              <div className="space-y-1 max-h-48 overflow-auto">
                {datasources.map((ds: any) => (
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
            )}
            <div className="flex justify-end gap-2 mt-3 pt-3 border-t border-slate-100">
              <button onClick={() => setShowDsPicker(false)} className="px-3 py-1 text-xs text-slate-500 hover:bg-slate-100 rounded-lg">取消</button>
              <button
                onClick={handleTriggerScan}
                disabled={!selectedDsId}
                className="px-3 py-1 text-xs bg-slate-900 text-white rounded-lg hover:bg-slate-700 disabled:opacity-50"
              >确认扫描</button>
            </div>
          </div>
        )}
      </div>
    </>
  );

  return (
    <div className="px-8 py-7">
      <div className="max-w-6xl mx-auto">
      {headerControlsRef?.current && createPortal(headerControls, headerControlsRef.current)}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-600 text-xs rounded-lg px-4 py-2 mb-4">{error}</div>
      )}

      {loading ? (
        <div className="text-center py-20 text-slate-400 text-sm">加载中...</div>
      ) : !activeScan ? (
        <div className="text-center py-20 text-slate-400 text-sm">暂无扫描记录，点击"发起扫描"开始</div>
      ) : (
          <>
            {/* Stats row */}
            <div className="grid grid-cols-4 gap-4 mb-6">
              {/* 体检评分 */}
              <div className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] text-slate-500">体检评分</span>
                  <div className="w-6 h-6 flex items-center justify-center"><i className="ri-award-line text-slate-400" /></div>
                </div>
                <div className="mb-2"><ScoreBar score={score} /></div>
                <div className="text-[11px] text-slate-400 mt-0.5">{noData ? '未检测到业务表' : `问题数 ${totalIssues} 个`}</div>
              </div>
              {/* 监控表数量 */}
              <div className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] text-slate-500">监控表数量</span>
                  <div className="w-6 h-6 flex items-center justify-center"><i className="ri-table-line text-slate-400" /></div>
                </div>
                <div className="text-2xl font-bold text-slate-800">{totalTables}</div>
                <div className="text-[11px] text-slate-400 mt-0.5">{`数据源: ${activeScan.datasource_name}`}</div>
              </div>
              {/* 风险分布 — 柱状图 */}
              <div className="bg-white border border-slate-200 rounded-xl p-4 flex flex-col">
                <div className="flex items-center justify-between mb-auto">
                  <span className="text-[11px] text-slate-500">风险分布</span>
                  <div className="w-6 h-6 flex items-center justify-center"><i className="ri-pie-chart-line text-slate-400" /></div>
                </div>
                {(() => {
                  const counts = [highCount, mediumCount, lowCount];
                  const maxCount = Math.max(...counts, 1);
                  return (
                    <>
                      <div className="flex items-end gap-1.5 h-10 mb-1">
                        {[{ bg: 'bg-red-500' }, { bg: 'bg-amber-500' }, { bg: 'bg-blue-500' }].map((cfg, i) => {
                          const ratio = counts[i] / maxCount;
                          return (
                            <div key={i} className="flex-1 flex flex-col items-center gap-0.5 h-full justify-end">
                              <div className={`w-full rounded-sm ${cfg.bg}`} style={{ height: `${Math.max(6, ratio * 100)}%` }} />
                              <span className="text-[9px] text-slate-400 shrink-0">{counts[i]}</span>
                            </div>
                          );
                        })}
                      </div>
                      <div className="flex">
                        {['高', '中', '低'].map(l => (
                          <span key={l} className="text-[9px] text-slate-400 flex-1 text-center">{l}</span>
                        ))}
                      </div>
                    </>
                  );
                })()}
              </div>
              {/* 最近扫描 */}
              <div className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] text-slate-500">最近扫描</span>
                  <div className="w-6 h-6 flex items-center justify-center"><i className="ri-time-line text-slate-400" /></div>
                </div>
                <div className="text-2xl font-bold text-slate-800">{lastScan.split(' ')[1] || '-'}</div>
                <div className="text-[11px] text-slate-400 mt-0.5">{lastScan.split(' ')[0] || '-'}</div>
              </div>
            </div>

            {/* Tab container */}
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
                <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-0.5 w-fit">
                  {[
                    { key: 'overview' as const, label: '扫描结果' },
                    { key: 'history' as const, label: '历史记录' },
                  ].map((t) => (
                    <button
                      key={t.key}
                      onClick={() => setTab(t.key)}
                      className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                        tab === t.key ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                      }`}
                    >{t.label}</button>
                  ))}
                </div>
                {tab === 'overview' && (
                <div className="flex items-center gap-2 flex-wrap">
                  <select
                    value={filterSeverity}
                    onChange={(e) => { setFilterSeverity(e.target.value); setIssuePage(1); }}
                    className="text-xs px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
                  >
                    <option value="">全部风险</option>
                    <option value="high">高风险</option>
                    <option value="medium">中风险</option>
                    <option value="low">低风险</option>
                  </select>
                  <select
                    value={filterObjectType}
                    onChange={(e) => setFilterObjectType(e.target.value)}
                    className="text-xs px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
                  >
                    <option value="">全部类型</option>
                    <option value="table">表</option>
                    <option value="field">字段</option>
                  </select>
                  <input
                    value={filterObjectName}
                    onChange={(e) => setFilterObjectName(e.target.value)}
                    placeholder="搜索对象名称"
                    className="text-xs px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white w-32"
                  />
                  <button
                    onClick={handleExportReport}
                    disabled={exporting || activeScan?.status !== 'success'}
                    className="flex items-center gap-1 px-3 py-1.5 text-xs text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50"
                  >
                    <i className={exporting ? "ri-loader-4-line animate-spin" : "ri-download-line"} />
                    {exporting ? '导出中...' : '下载报告'}
                  </button>
                </div>
                )}
              </div>

              {tab === 'overview' ? (
              <>
              {filteredIssues.length === 0 ? (
                <div className="text-center py-10 text-slate-400 text-xs">
                  {activeScan.status === 'success' ? '未发现问题' : '扫描未完成'}
                </div>
              ) : (
                <table className="w-full table-fixed">
                  <thead>
                    <tr className="bg-slate-50">
                      <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 w-20">风险</th>
                      <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 w-16">对象类型</th>
                      <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">对象名称</th>
                      <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">主机地址</th>
                      <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 w-20">名称</th>
                      <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 w-[120px]">数据库</th>
                      <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 w-32">问题类型</th>
                      <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 w-14">评分</th>
                      <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 w-40">检查时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredIssues.map((issue) => {
                      const sc = severityConfig[issue.severity] || severityConfig.low;
                      return (
                        <tr key={issue.id} className="border-t border-slate-100 hover:bg-slate-50">
                          <td className="px-4 py-3 whitespace-nowrap">
                            <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${sc.bg} ${sc.text} ${sc.border}`}>
                              <span className={`w-1.5 h-1.5 rounded-full ${sc.dot}`} />
                              {sc.label}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-[12px] text-slate-500 whitespace-nowrap">
                            {issue.object_type === 'table' ? <i className="ri-table-line mr-1" /> : <i className="ri-function-line mr-1" />}
                            {issue.object_type === 'table' ? '表' : '字段'}
                          </td>
                          <td className="px-4 py-3 text-[12px] font-medium text-slate-700 font-mono break-all">{issue.object_name}</td>
                          <td className="px-4 py-3 text-[12px] text-slate-500 font-mono break-all">{datasources.find((d: any) => d.id === activeScan.datasource_id)?.host || '-'}</td>
                          <td className="px-4 py-3 text-[12px] text-slate-600">{activeScan.datasource_name}</td>
                          <td className="px-4 py-3 text-[12px] text-slate-500 break-all">{issue.database_name || '-'}</td>
                          <td className="px-4 py-3 text-[12px] text-slate-600 truncate">{issueTypeLabels[issue.issue_type] || ruleIdLabels[issue.issue_type] || issue.issue_type}</td>
                          <td className="px-4 py-3 text-[12px] text-slate-600">{activeScan.health_score != null ? `${activeScan.health_score}分` : '-'}</td>
                          <td className="px-4 py-3 text-[11px] text-slate-400 leading-tight">
                            {activeScan.finished_at ? (<><div>{activeScan.finished_at.slice(0, 10)}</div><div>{activeScan.finished_at.slice(11, 19)}</div></>) : '-'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}

              {/* Pagination */}
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
              </>
              ) : (
              <>
              {history.length === 0 ? (
                <div className="text-center py-10 text-slate-400 text-xs">暂无扫描记录</div>
              ) : (
                <table className="w-full">
                  <thead>
                    <tr className="bg-slate-50">
                      {['ID', '数据源', '数据库类型', '状态', '表数', '问题数', '评分', '扫描时间', '操作'].map((h) => (
                        <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((s) => (
                      <tr key={s.id} className="border-t border-slate-100 hover:bg-slate-50">
                        <td className="px-4 py-3 text-xs text-slate-500">#{s.id}</td>
                        <td className="px-4 py-3 text-xs font-medium text-slate-700">{s.datasource_name}</td>
                        <td className="px-4 py-3 text-xs text-slate-500">{s.db_type}</td>
                        <td className="px-4 py-3">
                          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                            s.status === 'success' ? 'bg-emerald-50 text-emerald-600' :
                            s.status === 'failed' ? 'bg-red-50 text-red-600' :
                            'bg-amber-50 text-amber-600'
                          }`}>{s.status === 'success' ? '完成' : s.status === 'failed' ? '失败' : '进行中'}</span>
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-600">{s.total_tables}</td>
                        <td className="px-4 py-3 text-xs text-slate-600">{s.total_issues}</td>
                        <td className="px-4 py-3 text-xs font-bold" style={{ color: s.health_score == null ? '#94a3b8' : (s.health_score ?? 0) >= 90 ? '#16a34a' : (s.health_score ?? 0) >= 75 ? '#d97706' : '#dc2626' }}>
                          {s.health_score ?? '无数据'}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">{s.finished_at || s.started_at || '-'}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => { setActiveScan(s); setTab('overview'); setIssuePage(1); setFilterSeverity(''); setFilterObjectType(''); setFilterObjectName(''); }}
                              className="text-[11px] text-blue-600 hover:underline"
                            >查看</button>
                            {s.status === 'success' && (
                              <button
                                onClick={async () => {
                                  try {
                                    await downloadScanReport(s.id);
                                  } catch (_err) {
                                    // ignore export failure in history row action
                                  }
                                }}
                                className="text-[11px] text-slate-500 hover:underline"
                              >导出</button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {historyTotal > 20 && (
                <div className="px-5 py-3 border-t border-slate-100 flex items-center justify-between">
                  <span className="text-[11px] text-slate-400">共 {historyTotal} 条</span>
                  <div className="flex items-center gap-2">
                    <button onClick={() => setHistoryPage(Math.max(1, historyPage - 1))} disabled={historyPage <= 1} className="px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 rounded disabled:opacity-50">上一页</button>
                    <span className="text-xs text-slate-500">{historyPage}</span>
                    <button onClick={() => setHistoryPage(historyPage + 1)} disabled={historyPage * 20 >= historyTotal} className="px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 rounded disabled:opacity-50">下一页</button>
                  </div>
                </div>
              )}
              </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
