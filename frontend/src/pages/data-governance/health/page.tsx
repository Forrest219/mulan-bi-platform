import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const mockHealthData = {
  score: 78,
  totalTables: 156,
  totalDatabases: 4,
  passCount: 122,
  failCount: 34,
  lastScan: '2026-04-01 09:15',
  issueStats: {
    naming: 8,
    comment: 15,
    primaryKey: 5,
    updateField: 12,
    dataType: 2,
  },
};

const mockIssues = [
  {
    severity: 'high',
    objectType: 'table',
    objectName: 'orders',
    issueType: 'primary_key',
    description: '表 orders 缺少主键',
    suggestion: '建议添加自增主键 id',
    database: 'ecommerce_db',
  },
  {
    severity: 'high',
    objectType: 'field',
    objectName: 'user_id',
    issueType: 'comment',
    description: '字段 user_id 缺少 COMMENT',
    suggestion: '添加 COMMENT "用户ID"',
    database: 'ecommerce_db',
  },
  {
    severity: 'medium',
    objectType: 'table',
    objectName: 'dim_product',
    issueType: 'naming',
    description: '表名 dim_product 符合命名规范',
    suggestion: '-',
    database: 'dw_db',
  },
  {
    severity: 'low',
    objectType: 'field',
    objectName: 'updated_at',
    issueType: 'update_field',
    description: '表 products 缺少 update_time 字段',
    suggestion: '建议添加 update_time 字段跟踪数据变更',
    database: 'ecommerce_db',
  },
];

const severityConfig = {
  high: { label: '高风险', bg: 'bg-red-50', text: 'text-red-600', border: 'border-red-200', dot: 'bg-red-500' },
  medium: { label: '中风险', bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-200', dot: 'bg-amber-500' },
  low: { label: '低风险', bg: 'bg-blue-50', text: 'text-blue-600', border: 'border-blue-200', dot: 'bg-blue-500' },
};

const issueTypeLabels: Record<string, string> = {
  naming: '命名规范',
  comment: '缺少注释',
  primary_key: '缺失主键',
  update_field: '缺失更新字段',
  data_type: '数据类型问题',
};

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

export default function DataHealthPage() {
  const navigate = useNavigate();
  const [filterSeverity, setFilterSeverity] = useState<string>('');
  const [filterDb, setFilterDb] = useState<string>('');

  const filteredIssues = mockIssues.filter((issue) => {
    if (filterSeverity && issue.severity !== filterSeverity) return false;
    if (filterDb && issue.database !== filterDb) return false;
    return true;
  });

  const databases = [...new Set(mockIssues.map((i) => i.database))];

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Page header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="w-5 h-5 flex items-center justify-center">
                <i className="ri-heart-pulse-line text-slate-500 text-base" />
              </span>
              <h1 className="text-lg font-semibold text-slate-800">数据仓库体检</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">Schema 级健康检查 · 问题识别与建议</p>
          </div>
          <button className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700 transition-colors cursor-pointer">
            <i className="ri-play-line" />
            发起扫描
          </button>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-8 py-7">
        {/* Stats row */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            {
              label: '体检评分',
              value: mockHealthData.score,
              sub: `问题数 ${mockHealthData.failCount} 个`,
              icon: 'ri-award-line',
              special: true,
            },
            {
              label: '监控表数量',
              value: mockHealthData.totalTables,
              sub: `跨 ${mockHealthData.totalDatabases} 个数据库`,
              icon: 'ri-table-line',
            },
            {
              label: '合规率',
              value: `${Math.round((mockHealthData.passCount / mockHealthData.totalTables) * 100)}%`,
              sub: `${mockHealthData.passCount} 通过 / ${mockHealthData.failCount} 未通过`,
              icon: 'ri-checkbox-circle-line',
            },
            {
              label: '最近扫描',
              value: mockHealthData.lastScan.split(' ')[1],
              sub: mockHealthData.lastScan.split(' ')[0],
              icon: 'ri-time-line',
            },
          ].map((s) => (
            <div key={s.label} className="bg-white border border-slate-200 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] text-slate-500">{s.label}</span>
                <div className="w-6 h-6 flex items-center justify-center">
                  <i className={`${s.icon} text-slate-400`} />
                </div>
              </div>
              {s.special ? (
                <div className="mb-2">
                  <ScoreBar score={s.value as number} />
                </div>
              ) : (
                <div className="text-2xl font-bold text-slate-800">{s.value}</div>
              )}
              <div className="text-[11px] text-slate-400 mt-0.5">{s.sub}</div>
            </div>
          ))}
        </div>

        {/* Issue breakdown */}
        <div className="bg-white border border-slate-200 rounded-xl p-5 mb-5">
          <h3 className="text-[13px] font-semibold text-slate-700 mb-4">问题类型分布</h3>
          <div className="grid grid-cols-5 gap-3">
            {Object.entries(mockHealthData.issueStats).map(([type, count]) => (
              <div key={type} className="text-center p-3 bg-slate-50 rounded-lg">
                <div className="text-2xl font-bold text-slate-700">{count}</div>
                <div className="text-[11px] text-slate-500 mt-1">{issueTypeLabels[type]}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Issue list */}
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
            <h3 className="text-[13px] font-semibold text-slate-700">问题列表</h3>
            <div className="flex items-center gap-3">
              <select
                value={filterSeverity}
                onChange={(e) => setFilterSeverity(e.target.value)}
                className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
              >
                <option value="">全部风险</option>
                <option value="high">高风险</option>
                <option value="medium">中风险</option>
                <option value="low">低风险</option>
              </select>
              <select
                value={filterDb}
                onChange={(e) => setFilterDb(e.target.value)}
                className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
              >
                <option value="">全部数据库</option>
                {databases.map((db) => (
                  <option key={db} value={db}>{db}</option>
                ))}
              </select>
            </div>
          </div>

          <table className="w-full">
            <thead>
              <tr className="bg-slate-50">
                {['风险', '对象类型', '对象名称', '数据库', '问题类型', '描述', '建议'].map((h) => (
                  <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredIssues.map((issue, i) => {
                const sc = severityConfig[issue.severity as keyof typeof severityConfig];
                return (
                  <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <span className={`flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${sc.bg} ${sc.text} ${sc.border}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${sc.dot}`} />
                        {sc.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[12px] text-slate-500">
                      {issue.objectType === 'table' ? (
                        <i className="ri-table-line mr-1" />
                      ) : (
                        <i className="ri-function-line mr-1" />
                      )}
                      {issue.objectType === 'table' ? '表' : '字段'}
                    </td>
                    <td className="px-4 py-3 text-[12px] font-medium text-slate-700 font-mono">{issue.objectName}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-500 font-mono">{issue.database}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-600">{issueTypeLabels[issue.issueType]}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-600 max-w-xs truncate">{issue.description}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-500 max-w-xs truncate">{issue.suggestion}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
