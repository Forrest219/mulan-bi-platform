import { useState } from 'react';

const mockQualityRules = [
  {
    id: 1,
    name: '订单ID空值率检查',
    datasource: 'ecommerce_db',
    table: 'orders',
    field: 'order_id',
    ruleType: 'null_rate',
    threshold: 1.0,
    actualValue: 0.12,
    status: 'pass',
    lastRun: '2026-04-01 02:00',
  },
  {
    id: 2,
    name: '手机号重复率检查',
    datasource: 'crm_db',
    table: 'customers',
    field: 'phone',
    ruleType: 'duplicate_rate',
    threshold: 5.0,
    actualValue: 8.5,
    status: 'fail',
    lastRun: '2026-04-01 02:00',
  },
  {
    id: 3,
    name: '订单状态枚举校验',
    datasource: 'ecommerce_db',
    table: 'orders',
    field: 'status',
    ruleType: 'enum',
    threshold: 0,
    actualValue: 0,
    status: 'pass',
    lastRun: '2026-04-01 02:00',
  },
  {
    id: 4,
    name: '销售额非负校验',
    datasource: 'dw_db',
    table: 'fact_sales',
    field: 'sales_amount',
    ruleType: 'custom',
    threshold: 0,
    actualValue: 0,
    status: 'pass',
    lastRun: '2026-04-01 02:00',
  },
];

const mockSummary = {
  avgScore: 87,
  totalRules: 45,
  passCount: 38,
  failCount: 7,
  topFailingRules: [
    { name: '手机号重复率检查', failCount: 3, latestValue: '8.5%' },
    { name: '库存数量空值率', failCount: 2, latestValue: '12.3%' },
  ],
};

const statusConfig = {
  pass: { label: '通过', bg: 'bg-emerald-50', text: 'text-emerald-600', border: 'border-emerald-200' },
  fail: { label: '未通过', bg: 'bg-red-50', text: 'text-red-600', border: 'border-red-200' },
  warn: { label: '告警', bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-200' },
};

const ruleTypeLabels: Record<string, string> = {
  null_rate: '空值率',
  duplicate_rate: '重复率',
  enum: '枚举校验',
  custom: '自定义规则',
};

export default function DataQualityPage() {
  const [selectedRuleType, setSelectedRuleType] = useState<string>('');
  const [selectedStatus, setSelectedStatus] = useState<string>('');

  const filteredRules = mockQualityRules.filter((rule) => {
    if (selectedRuleType && rule.ruleType !== selectedRuleType) return false;
    if (selectedStatus && rule.status !== selectedStatus) return false;
    return true;
  });

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Page header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="w-5 h-5 flex items-center justify-center">
                <i className="ri-shield-check-line text-slate-500 text-base" />
              </span>
              <h1 className="text-lg font-semibold text-slate-800">数据质量监控</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">数据级质量检查 · 规则配置与执行结果</p>
          </div>
          <button className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700 transition-colors cursor-pointer">
            <i className="ri-add-line" />
            新建规则
          </button>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-8 py-7">
        {/* Stats row */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            {
              label: '平均质量评分',
              value: mockSummary.avgScore,
              sub: '基于所有规则',
              icon: 'ri-award-line',
            },
            {
              label: '规则总数',
              value: mockSummary.totalRules,
              sub: `通过 ${mockSummary.passCount} · 未通过 ${mockSummary.failCount}`,
              icon: 'ri-file-list-3-line',
            },
            {
              label: '通过率',
              value: `${Math.round((mockSummary.passCount / mockSummary.totalRules) * 100)}%`,
              sub: '规则通过比例',
              icon: 'ri-checkbox-circle-line',
            },
            {
              label: '未通过规则',
              value: mockSummary.failCount,
              sub: '需关注',
              icon: 'ri-error-warning-line',
            },
          ].map((s) => (
            <div key={s.label} className="bg-white border border-slate-200 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] text-slate-500">{s.label}</span>
                <div className="w-6 h-6 flex items-center justify-center">
                  <i className={`${s.icon} text-slate-400`} />
                </div>
              </div>
              <div className="text-2xl font-bold text-slate-800">{s.value}</div>
              <div className="text-[11px] text-slate-400 mt-0.5">{s.sub}</div>
            </div>
          ))}
        </div>

        {/* Top failing rules */}
        {mockSummary.topFailingRules.length > 0 && (
          <div className="bg-white border border-red-200 rounded-xl p-5 mb-5">
            <h3 className="text-[13px] font-semibold text-red-600 mb-3 flex items-center gap-2">
              <i className="ri-error-warning-line" />
              持续未通过规则
            </h3>
            <div className="grid grid-cols-2 gap-3">
              {mockSummary.topFailingRules.map((rule, i) => (
                <div key={i} className="flex items-center justify-between p-3 bg-red-50 rounded-lg">
                  <div>
                    <div className="text-[12px] font-medium text-slate-700">{rule.name}</div>
                    <div className="text-[11px] text-slate-500">未通过 {rule.failCount} 次 · 最新值 {rule.latestValue}</div>
                  </div>
                  <i className="ri-arrow-right-line text-slate-400" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Rules table */}
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
            <h3 className="text-[13px] font-semibold text-slate-700">规则列表</h3>
            <div className="flex items-center gap-3">
              <select
                value={selectedRuleType}
                onChange={(e) => setSelectedRuleType(e.target.value)}
                className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
              >
                <option value="">全部类型</option>
                <option value="null_rate">空值率</option>
                <option value="duplicate_rate">重复率</option>
                <option value="enum">枚举校验</option>
                <option value="custom">自定义规则</option>
              </select>
              <select
                value={selectedStatus}
                onChange={(e) => setSelectedStatus(e.target.value)}
                className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
              >
                <option value="">全部状态</option>
                <option value="pass">通过</option>
                <option value="fail">未通过</option>
              </select>
            </div>
          </div>

          <table className="w-full">
            <thead>
              <tr className="bg-slate-50">
                {['规则名称', '数据库', '表', '字段', '规则类型', '阈值', '实际值', '状态', '最近运行'].map((h) => (
                  <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredRules.map((rule) => {
                const sc = statusConfig[rule.status as keyof typeof statusConfig];
                const overThreshold = rule.ruleType === 'duplicate_rate' && rule.actualValue > rule.threshold;
                return (
                  <tr key={rule.id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-3 text-[12px] font-medium text-slate-700">{rule.name}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-500 font-mono">{rule.datasource}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-600 font-mono">{rule.table}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-600 font-mono">{rule.field}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-600">{ruleTypeLabels[rule.ruleType]}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-500">
                      {rule.ruleType === 'enum' ? '-' : `${rule.threshold}${rule.ruleType === 'null_rate' || rule.ruleType === 'duplicate_rate' ? '%' : ''}`}
                    </td>
                    <td className="px-4 py-3 text-[12px]">
                      <span className={overThreshold ? 'text-red-500 font-medium' : 'text-slate-600'}>
                        {rule.ruleType === 'enum' ? '-' : `${rule.actualValue}${rule.ruleType === 'null_rate' || rule.ruleType === 'duplicate_rate' ? '%' : ''}`}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${sc.bg} ${sc.text} ${sc.border}`}>
                        {sc.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[12px] text-slate-500">{rule.lastRun}</td>
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
