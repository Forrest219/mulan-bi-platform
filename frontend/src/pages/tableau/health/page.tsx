import { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { listConnections, getConnectionHealthOverview } from '@/api/tableau';
import type { HealthOverview, TableauConnection } from '@/api/tableau';
import { ASSET_TYPE_LABELS } from '@/config';

const LEVEL_CONFIG: Record<string, { label: string; color: string; bg: string; chipBg: string; chipText: string }> = {
  excellent: { label: '优秀', color: 'text-emerald-600', bg: 'bg-emerald-500', chipBg: 'bg-emerald-50', chipText: 'text-emerald-600' },
  good:      { label: '良好', color: 'text-blue-600',    bg: 'bg-blue-500',    chipBg: 'bg-blue-50',    chipText: 'text-blue-600' },
  warning:   { label: '需改进', color: 'text-amber-600',  bg: 'bg-amber-500',  chipBg: 'bg-amber-50',  chipText: 'text-amber-600' },
  poor:      { label: '较差', color: 'text-red-600',      bg: 'bg-red-500',    chipBg: 'bg-red-50',    chipText: 'text-red-600' },
};

const LEVEL_KEYS = ['excellent', 'good', 'warning', 'poor'] as const;

const CHECK_LABELS: Record<string, string> = {
  has_description: '缺少描述',
  has_owner: '缺少所有者',
  has_datasource_link: '未关联数据源',
  fields_have_captions: '字段缺少中文名',
  is_certified: '未认证',
  naming_convention: '命名不规范',
  not_stale: '长期未更新',
};

const ALL_CONNECTIONS = 'all';

function formatDateTime(iso: string): { date: string; time: string } | null {
  if (!iso) return null;
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return {
    date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`,
  };
}

function mergeOverviews(overviews: HealthOverview[]): HealthOverview | null {
  if (overviews.length === 0) return null;
  if (overviews.length === 1) return overviews[0];

  const totalAssets = overviews.reduce((s, o) => s + o.total_assets, 0);
  const weightedScore = totalAssets > 0
    ? Math.round(overviews.reduce((s, o) => s + o.avg_score * o.total_assets, 0) / totalAssets)
    : 0;

  const dist = { excellent: 0, good: 0, warning: 0, poor: 0 };
  for (const o of overviews) {
    dist.excellent += o.level_distribution.excellent;
    dist.good += o.level_distribution.good;
    dist.warning += o.level_distribution.warning;
    dist.poor += o.level_distribution.poor;
  }

  const issueMap = new Map<string, number>();
  for (const o of overviews) {
    for (const issue of o.top_issues) {
      issueMap.set(issue.check, (issueMap.get(issue.check) || 0) + issue.count);
    }
  }
  const topIssues = [...issueMap.entries()]
    .map(([check, count]) => ({ check, count }))
    .sort((a, b) => b.count - a.count);

  const assets = overviews.flatMap(o =>
    o.assets.map(a => ({ ...a, connection_name: o.connection_name }))
  ).sort((a, b) => a.score - b.score);

  const level = weightedScore >= 80 ? 'excellent' : weightedScore >= 60 ? 'good' : weightedScore >= 40 ? 'warning' : 'poor';

  return {
    connection_id: 0,
    connection_name: '全部站点',
    total_assets: totalAssets,
    avg_score: weightedScore,
    avg_level: level,
    level_distribution: dist,
    top_issues: topIssues,
    assets,
  };
}

function toggleSet<T>(set: T[], item: T): T[] {
  return set.includes(item) ? set.filter(x => x !== item) : [...set, item];
}

export default function TableauHealthPage() {
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [selectedConn, setSelectedConn] = useState<string>(ALL_CONNECTIONS);
  const [overview, setOverview] = useState<HealthOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [error, setError] = useState('');
  const [levelFilters, setLevelFilters] = useState<string[]>([]);
  const [issueFilters, setIssueFilters] = useState<string[]>([]);
  const [typeFilters, setTypeFilters] = useState<string[]>([]);

  useEffect(() => {
    listConnections()
      .then(d => setConnections(d.connections))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const loadOverview = useCallback(async (connFilter: string, conns: TableauConnection[]) => {
    if (conns.length === 0) return;
    setOverviewLoading(true);
    setError('');
    try {
      if (connFilter === ALL_CONNECTIONS) {
        const results = await Promise.all(conns.map(c => getConnectionHealthOverview(c.id)));
        setOverview(mergeOverviews(results));
      } else {
        const data = await getConnectionHealthOverview(Number(connFilter));
        setOverview(data);
      }
    } catch {
      setOverview(null);
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  useEffect(() => {
    if (connections.length > 0) loadOverview(selectedConn, connections);
  }, [selectedConn, connections, loadOverview]);

  useEffect(() => {
    setLevelFilters([]);
    setIssueFilters([]);
    setTypeFilters([]);
  }, [overview]);

  const allIssueKeys = useMemo(() => {
    if (!overview) return [];
    const keys = new Set<string>();
    for (const a of overview.assets) {
      for (const fc of a.failed_checks ?? []) keys.add(fc);
    }
    return [...keys].sort((a, b) => {
      const ai = overview.top_issues.findIndex(i => i.check === a);
      const bi = overview.top_issues.findIndex(i => i.check === b);
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
    });
  }, [overview]);

  const allAssetTypes = useMemo(() => {
    if (!overview) return [];
    const types = new Set(overview.assets.map(a => a.asset_type));
    return [...types].sort();
  }, [overview]);

  const filtered = useMemo(() => {
    if (!overview) return [];
    let list = overview.assets;
    if (levelFilters.length > 0) {
      list = list.filter(a => levelFilters.includes(a.level));
    }
    if (issueFilters.length > 0) {
      list = list.filter(a => issueFilters.some(f => a.failed_checks?.includes(f)));
    }
    if (typeFilters.length > 0) {
      list = list.filter(a => typeFilters.includes(a.asset_type));
    }
    return list;
  }, [overview, levelFilters, issueFilters, typeFilters]);

  const isAllSites = selectedConn === ALL_CONNECTIONS;
  const hasFilters = levelFilters.length > 0 || issueFilters.length > 0 || typeFilters.length > 0;

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-heart-pulse-line text-slate-500" />
              <h1 className="text-lg font-semibold text-slate-800">Tableau 巡检</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">元数据完整性检查 · 资产质量评分</p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={selectedConn}
              onChange={e => setSelectedConn(e.target.value)}
              className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
            >
              <option value={ALL_CONNECTIONS}>全部站点</option>
              {connections.map(c => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <button
              onClick={() => loadOverview(selectedConn, connections)}
              disabled={overviewLoading || connections.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-slate-200 rounded-lg text-slate-600 bg-white hover:bg-slate-50 disabled:opacity-50 transition-colors"
            >
              <i className={`ri-refresh-line ${overviewLoading ? 'animate-spin' : ''}`} />
              刷新巡检
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-8 py-7">
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-600 text-xs rounded-lg px-4 py-2 mb-4">
            {error}
            <button onClick={() => setError('')} className="ml-2 text-red-400 hover:text-red-600">
              <i className="ri-close-line" />
            </button>
          </div>
        )}

        {overviewLoading ? (
          <div className="text-center py-20 text-slate-400 text-sm">
            <i className="ri-loader-2-line animate-spin text-xl block mb-2" />
            正在评估资产健康度...
          </div>
        ) : !overview || overview.total_assets === 0 ? (
          <div className="text-center py-20">
            <i className="ri-database-2-line text-3xl text-slate-300 block mb-3" />
            <p className="text-sm text-slate-500 mb-1">暂无资产数据</p>
            <p className="text-xs text-slate-400">请先在「资产 → Tableau 连接管理」中同步资产元数据</p>
          </div>
        ) : (
          <>
            {/* Stats row */}
            <div className="grid grid-cols-4 gap-4 mb-6">
              {/* KPI: 平均健康分 */}
              <div className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="text-[11px] text-slate-500 mb-1">平均健康分</div>
                <div className={`text-3xl font-bold ${
                  overview.avg_score >= 80 ? 'text-emerald-600' :
                  overview.avg_score >= 60 ? 'text-amber-600' : 'text-red-600'
                }`}>{overview.avg_score}</div>
                <div className="text-[11px] text-slate-400 mt-1">{overview.connection_name}</div>
              </div>

              {/* KPI: 资产总数 */}
              <div className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="text-[11px] text-slate-500 mb-1">资产总数</div>
                <div className="text-3xl font-bold text-slate-800">{overview.total_assets}</div>
              </div>

              {/* 等级分布 */}
              <div className="bg-white border border-slate-200 rounded-xl p-4 flex flex-col">
                <div className="text-[11px] text-slate-500 mb-auto">等级分布</div>
                {(() => {
                  const counts = LEVEL_KEYS.map(
                    level => overview.level_distribution[level as keyof typeof overview.level_distribution]
                  );
                  const maxCount = Math.max(...counts, 1);
                  return (
                    <>
                      <div className="flex items-end gap-1.5 h-10 mb-1">
                        {LEVEL_KEYS.map((level, i) => {
                          const cfg = LEVEL_CONFIG[level];
                          const ratio = counts[i] / maxCount;
                          return (
                            <div key={level} className="flex-1 flex flex-col items-center gap-0.5 h-full justify-end">
                              <div className={`w-full rounded-sm ${cfg.bg}`} style={{ height: `${Math.max(6, ratio * 100)}%` }} />
                              <span className="text-[9px] text-slate-400 shrink-0">{counts[i]}</span>
                            </div>
                          );
                        })}
                      </div>
                      <div className="flex">
                        {['优', '良', '中', '差'].map(l => (
                          <span key={l} className="text-[9px] text-slate-400 flex-1 text-center">{l}</span>
                        ))}
                      </div>
                    </>
                  );
                })()}
              </div>

              {/* 主要问题 — 横向条形图 */}
              <div className="bg-white border border-slate-200 rounded-xl p-4 flex flex-col">
                <div className="text-[11px] text-slate-500 mb-auto">主要问题</div>
                {overview.top_issues.length === 0 ? (
                  <div className="text-xs text-slate-400 my-auto text-center">无</div>
                ) : (() => {
                  const items = overview.top_issues.slice(0, 4);
                  const maxCount = Math.max(...items.map(i => i.count), 1);
                  return (
                    <div className="space-y-1.5 mt-1">
                      {items.map(issue => (
                        <div key={issue.check} className="flex items-center gap-2">
                          <span className="text-[10px] text-slate-500 w-16 shrink-0 truncate text-right" title={CHECK_LABELS[issue.check] || issue.check}>
                            {CHECK_LABELS[issue.check] || issue.check}
                          </span>
                          <div className="flex-1 h-3 bg-slate-100 rounded-sm overflow-hidden">
                            <div
                              className="h-full bg-red-400 rounded-sm"
                              style={{ width: `${(issue.count / maxCount) * 100}%` }}
                            />
                          </div>
                          <span className="text-[10px] font-medium text-red-500 w-5 text-right">{issue.count}</span>
                        </div>
                      ))}
                    </div>
                  );
                })()}
              </div>
            </div>

            {/* 资产巡检明细 */}
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-slate-100">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-[13px] font-semibold text-slate-700">
                    资产巡检明细 <span className="text-slate-400 font-normal ml-1">({filtered.length}{hasFilters ? ` / ${overview.assets.length}` : ''})</span>
                  </h3>
                  {hasFilters && (
                    <button
                      onClick={() => { setLevelFilters([]); setIssueFilters([]); setTypeFilters([]); }}
                      className="text-[11px] text-slate-400 hover:text-slate-600 transition-colors"
                    >
                      清除筛选
                    </button>
                  )}
                </div>
                <div className="space-y-2.5">
                  {/* 类型筛选 */}
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-slate-600 w-8 shrink-0">类型</span>
                    <div className="flex items-center gap-1.5 flex-wrap">
                    {allAssetTypes.map(type => {
                      const active = typeFilters.includes(type);
                      return (
                        <button
                          key={type}
                          onClick={() => setTypeFilters(toggleSet(typeFilters, type))}
                          className={`text-[11px] px-2.5 py-1 rounded-full border transition-colors ${
                            active
                              ? 'bg-slate-700 text-white border-slate-700'
                              : 'border-slate-200 text-slate-500 hover:border-slate-300'
                          }`}
                        >
                          {ASSET_TYPE_LABELS[type] || type}
                        </button>
                      );
                    })}
                    </div>
                  </div>
                  <div className="border-t border-slate-100" />
                  {/* 等级筛选 */}
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-slate-600 w-8 shrink-0">等级</span>
                    <div className="flex items-center gap-1.5 flex-wrap">
                    {LEVEL_KEYS.map(level => {
                      const cfg = LEVEL_CONFIG[level];
                      const active = levelFilters.includes(level);
                      return (
                        <button
                          key={level}
                          onClick={() => setLevelFilters(toggleSet(levelFilters, level))}
                          className={`text-[11px] font-medium px-2.5 py-1 rounded-full border transition-colors ${
                            active
                              ? `${cfg.chipBg} ${cfg.chipText} border-current`
                              : 'border-slate-200 text-slate-500 hover:border-slate-300'
                          }`}
                        >
                          {cfg.label}
                        </button>
                      );
                    })}
                    </div>
                  </div>
                  <div className="border-t border-slate-100" />
                  {/* 问题筛选 */}
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-slate-600 w-8 shrink-0">问题</span>
                    <div className="flex items-center gap-1.5 flex-wrap">
                    {allIssueKeys.map(key => {
                      const active = issueFilters.includes(key);
                      return (
                        <button
                          key={key}
                          onClick={() => setIssueFilters(toggleSet(issueFilters, key))}
                          className={`text-[11px] px-2.5 py-1 rounded-full border transition-colors ${
                            active
                              ? 'bg-red-50 text-red-500 border-red-300'
                              : 'border-slate-200 text-slate-500 hover:border-slate-300'
                          }`}
                        >
                          {CHECK_LABELS[key] || key}
                        </button>
                      );
                    })}
                    </div>
                  </div>
                </div>
              </div>
              <table className="w-full">
                <thead>
                  <tr className="bg-slate-50">
                    <th className="text-left text-[11px] font-semibold text-slate-500 tracking-wide px-4 py-2.5 w-[18%]">资产名称</th>
                    {isAllSites && <th className="text-left text-[11px] font-semibold text-slate-500 tracking-wide px-4 py-2.5 w-[10%] whitespace-nowrap">站点</th>}
                    <th className="text-left text-[11px] font-semibold text-slate-500 tracking-wide px-4 py-2.5 w-[8%] whitespace-nowrap">类型</th>
                    <th className="text-left text-[11px] font-semibold text-slate-500 tracking-wide px-4 py-2.5 w-[6%] whitespace-nowrap">评分</th>
                    <th className="text-left text-[11px] font-semibold text-slate-500 tracking-wide px-4 py-2.5 w-[7%] whitespace-nowrap">等级</th>
                    <th className="text-left text-[11px] font-semibold text-slate-500 tracking-wide px-4 py-2.5 w-[22%]">主要问题</th>
                    <th className="text-left text-[11px] font-semibold text-slate-500 tracking-wide px-4 py-2.5 w-[12%] whitespace-nowrap">检查时间</th>
                    <th className="text-left text-[11px] font-semibold text-slate-500 tracking-wide px-4 py-2.5 w-[8%] whitespace-nowrap">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(a => {
                    const cfg = LEVEL_CONFIG[a.level] || LEVEL_CONFIG.poor;
                    return (
                      <tr key={a.asset_id} className="border-t border-slate-100 hover:bg-slate-50">
                        <td className="px-4 py-3 text-xs font-medium text-slate-700">{a.name}</td>
                        {isAllSites && (
                          <td className="px-4 py-3 whitespace-nowrap">
                            <span className="text-[10px] text-slate-500">{a.connection_name || '-'}</span>
                          </td>
                        )}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className="text-[10px] px-1.5 py-0.5 bg-slate-100 text-slate-600 rounded">
                            {ASSET_TYPE_LABELS[a.asset_type] || a.asset_type}
                          </span>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className={`text-sm font-bold ${cfg.color}`}>{a.score}</span>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${cfg.chipBg} ${cfg.chipText}`}>{cfg.label}</span>
                        </td>
                        <td className="px-4 py-3">
                          {a.failed_checks?.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {a.failed_checks.map(fc => (
                                <span key={fc} className="text-[9px] px-1.5 py-0.5 bg-red-50 text-red-500 rounded">
                                  {CHECK_LABELS[fc] || fc}
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span className="text-[10px] text-emerald-500">全部通过</span>
                          )}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          {(() => {
                            const dt = formatDateTime(a.checked_at);
                            if (!dt) return <span className="text-[10px] text-slate-400">-</span>;
                            return (
                              <div className="leading-tight">
                                <div className="text-[11px] text-slate-600">{dt.date}</div>
                                <div className="text-[11px] text-slate-600">{dt.time}</div>
                              </div>
                            );
                          })()}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <Link to={`/assets/tableau/${a.asset_id}`} className="text-[11px] text-blue-600 hover:underline">
                            查看详情
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
