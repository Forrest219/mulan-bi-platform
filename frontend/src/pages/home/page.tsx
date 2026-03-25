import { useNavigate } from 'react-router-dom';

interface ModuleCard {
  icon: string;
  title: string;
  subtitle: string;
  description: string;
  path?: string;
  active: boolean;
  highlight?: boolean;
  stats?: { label: string; value: string }[];
}

const modules: ModuleCard[] = [
  {
    icon: 'ri-database-2-line',
    title: 'Data Source Manager',
    subtitle: '数据源管理',
    description: '配置数据库连接，统一管理 MySQL、SQL Server 等多类型数据源，支持连接健康检测与元数据同步。',
    path: '/database-monitor',
    active: true,
    stats: [
      { label: 'Connected', value: '3' },
      { label: 'Tables', value: '205' },
    ],
  },
  {
    icon: 'ri-shield-check-line',
    title: 'Schema Governance',
    subtitle: '结构规范治理',
    description: '扫描数据库表结构，批量检查是否符合建模规范，识别存量问题，输出全库治理报告。',
    active: false,
    stats: [
      { label: 'Rules', value: '12' },
      { label: 'Scanned', value: '—' },
    ],
  },
  {
    icon: 'ri-code-box-line',
    title: 'DDL Validator',
    subtitle: 'DDL 检查',
    description: '粘贴 CREATE TABLE SQL，立即校验是否符合团队建模规范，输出分级问题清单与评分报告。',
    path: '/ddl-validator',
    active: true,
    highlight: true,
    stats: [
      { label: 'Rules Active', value: '12' },
      { label: 'Last Check', value: '9 min ago' },
    ],
  },
  {
    icon: 'ri-bar-chart-grouped-line',
    title: 'Data Quality Monitor',
    subtitle: '数据质量监控',
    description: '持续监控数据表的空值率、重复率、异常值等质量指标，实时预警数据质量下降趋势。',
    active: false,
    stats: [
      { label: 'Monitors', value: '—' },
      { label: 'Alerts', value: '—' },
    ],
  },
];

export default function HomePage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Page header */}
      <div className="bg-white border-b border-slate-200 px-8 py-6">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-end justify-between">
            <div>
              <h2 className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-1">
                Platform Overview
              </h2>
              <h1 className="text-xl font-semibold text-slate-800">数据建模与治理平台</h1>
              <p className="text-sm text-slate-500 mt-1">
                面向 BI 团队 · 数据质量 · DDL 规范 · 结构治理
              </p>
            </div>
            <div className="flex items-center gap-6 text-center">
              <div>
                <div className="text-2xl font-bold text-slate-800">4</div>
                <div className="text-[11px] text-slate-400 mt-0.5">模块</div>
              </div>
              <div className="w-px h-8 bg-slate-200" />
              <div>
                <div className="text-2xl font-bold text-emerald-600">1</div>
                <div className="text-[11px] text-slate-400 mt-0.5">已启用</div>
              </div>
              <div className="w-px h-8 bg-slate-200" />
              <div>
                <div className="text-2xl font-bold text-amber-500">3</div>
                <div className="text-[11px] text-slate-400 mt-0.5">规划中</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Module cards */}
      <div className="max-w-6xl mx-auto px-8 py-8">
        {/* Current focus banner */}
        <div className="flex items-center gap-2 mb-6">
          <div className="w-1.5 h-4 rounded-full bg-orange-500" />
          <span className="text-[13px] font-medium text-slate-600">
            当前迭代重点：<strong className="text-slate-800">DDL Validator</strong> — 快速接入，即可使用
          </span>
        </div>

        <div className="grid grid-cols-2 gap-5">
          {modules.map((mod) => (
            <div
              key={mod.title}
              onClick={() => mod.path && navigate(mod.path)}
              className={`relative bg-white rounded-xl border transition-all group ${
                mod.highlight
                  ? 'border-orange-300 ring-2 ring-orange-100 cursor-pointer hover:shadow-md hover:-translate-y-0.5'
                  : mod.active && mod.path
                  ? 'border-slate-200 cursor-pointer hover:border-slate-300 hover:shadow-sm hover:-translate-y-0.5'
                  : 'border-slate-200 opacity-70'
              }`}
            >
              {/* Highlight badge */}
              {mod.highlight && (
                <div className="absolute -top-2.5 right-4">
                  <span className="text-[10px] font-bold px-2.5 py-1 rounded-full bg-orange-500 text-white uppercase tracking-wide">
                    Current Focus
                  </span>
                </div>
              )}

              {/* Coming Soon badge */}
              {!mod.active && (
                <div className="absolute top-4 right-4">
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-400 border border-slate-200">
                    Coming Soon
                  </span>
                </div>
              )}

              <div className="p-6">
                <div className="flex items-start gap-4">
                  <div
                    className={`w-10 h-10 flex items-center justify-center rounded-lg shrink-0 ${
                      mod.highlight
                        ? 'bg-orange-50 text-orange-500'
                        : mod.active
                        ? 'bg-slate-100 text-slate-600'
                        : 'bg-slate-50 text-slate-400'
                    }`}
                  >
                    <i className={`${mod.icon} text-lg`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2 mb-0.5">
                      <h3
                        className={`text-[15px] font-semibold ${
                          mod.active ? 'text-slate-800' : 'text-slate-500'
                        }`}
                      >
                        {mod.title}
                      </h3>
                      <span className="text-[11px] text-slate-400">{mod.subtitle}</span>
                    </div>
                    <p className={`text-[13px] leading-relaxed mt-1 ${mod.active ? 'text-slate-500' : 'text-slate-400'}`}>
                      {mod.description}
                    </p>
                  </div>
                </div>

                {/* Stats row */}
                {mod.stats && (
                  <div className="mt-5 pt-4 border-t border-slate-100 flex items-center justify-between">
                    <div className="flex items-center gap-5">
                      {mod.stats.map((s) => (
                        <div key={s.label}>
                          <div
                            className={`text-base font-bold ${
                              mod.active ? 'text-slate-800' : 'text-slate-400'
                            }`}
                          >
                            {s.value}
                          </div>
                          <div className="text-[11px] text-slate-400 mt-0.5">{s.label}</div>
                        </div>
                      ))}
                    </div>
                    {mod.path && mod.active && (
                      <div
                        className={`flex items-center gap-1 text-[12px] font-medium ${
                          mod.highlight
                            ? 'text-orange-500 group-hover:gap-2'
                            : 'text-slate-500 group-hover:gap-2'
                        } transition-all`}
                      >
                        进入模块
                        <i className="ri-arrow-right-line text-sm" />
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Bottom info section */}
        <div className="mt-8 grid grid-cols-3 gap-4">
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-6 h-6 flex items-center justify-center">
                <i className="ri-git-branch-line text-slate-500" />
              </div>
              <span className="text-[13px] font-semibold text-slate-700">平台版本</span>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-[12px]">
                <span className="text-slate-400">Core Engine</span>
                <span className="text-slate-700 font-medium">v0.3.1</span>
              </div>
              <div className="flex justify-between text-[12px]">
                <span className="text-slate-400">Rule Pack</span>
                <span className="text-slate-700 font-medium">2026-03</span>
              </div>
              <div className="flex justify-between text-[12px]">
                <span className="text-slate-400">Last Updated</span>
                <span className="text-slate-700 font-medium">2026-03-25</span>
              </div>
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-6 h-6 flex items-center justify-center">
                <i className="ri-team-line text-slate-500" />
              </div>
              <span className="text-[13px] font-semibold text-slate-700">团队使用情况</span>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-[12px]">
                <span className="text-slate-400">本周 DDL 检查次数</span>
                <span className="text-slate-700 font-medium">84</span>
              </div>
              <div className="flex justify-between text-[12px]">
                <span className="text-slate-400">发现问题总数</span>
                <span className="text-slate-700 font-medium">312</span>
              </div>
              <div className="flex justify-between text-[12px]">
                <span className="text-slate-400">活跃用户</span>
                <span className="text-slate-700 font-medium">7</span>
              </div>
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-6 h-6 flex items-center justify-center">
                <i className="ri-roadmap-line text-slate-500" />
              </div>
              <span className="text-[13px] font-semibold text-slate-700">迭代计划</span>
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[12px]">
                <div className="w-1.5 h-1.5 rounded-full bg-orange-400 shrink-0" />
                <span className="text-slate-600">Q2 · Schema Governance 上线</span>
              </div>
              <div className="flex items-center gap-2 text-[12px]">
                <div className="w-1.5 h-1.5 rounded-full bg-slate-300 shrink-0" />
                <span className="text-slate-400">Q3 · Data Quality Monitor</span>
              </div>
              <div className="flex items-center gap-2 text-[12px]">
                <div className="w-1.5 h-1.5 rounded-full bg-slate-300 shrink-0" />
                <span className="text-slate-400">Q4 · 全库扫描 + 报告导出</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
