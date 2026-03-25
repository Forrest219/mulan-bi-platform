import { useState } from 'react';
import { mockValidationResult, sampleSql, ValidationResult } from '../../mocks/ddlMockData';
import SeverityBadge from './components/SeverityBadge';

const DB_TYPES = ['MySQL', 'SQL Server'];

export default function DDLValidatorPage() {
  const [dbType, setDbType] = useState('MySQL');
  const [sql, setSql] = useState('');
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [severityFilter, setSeverityFilter] = useState<string>('ALL');

  const handleCheck = () => {
    if (!sql.trim()) return;
    setLoading(true);
    setResult(null);
    setTimeout(() => {
      setResult(mockValidationResult);
      setLoading(false);
    }, 1200);
  };

  const handleLoadSample = () => {
    setSql(sampleSql);
  };

  const filteredIssues = result
    ? severityFilter === 'ALL'
      ? result.issues
      : result.issues.filter((i) => i.severity === severityFilter)
    : [];

  const scoreColor =
    result
      ? result.score >= 80
        ? 'text-emerald-600'
        : result.score >= 60
        ? 'text-amber-500'
        : 'text-red-500'
      : 'text-slate-300';

  const scoreRingColor =
    result
      ? result.score >= 80
        ? 'stroke-emerald-500'
        : result.score >= 60
        ? 'stroke-amber-500'
        : 'stroke-red-500'
      : 'stroke-slate-200';

  const circumference = 2 * Math.PI * 34;
  const dashOffset = result
    ? circumference * (1 - result.score / 100)
    : circumference;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Page header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="w-5 h-5 flex items-center justify-center">
                <i className="ri-code-box-line text-orange-500 text-base" />
              </span>
              <h1 className="text-lg font-semibold text-slate-800">DDL Validator</h1>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-orange-100 text-orange-600 uppercase tracking-wide ml-1">
                Active
              </span>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">
              粘贴 CREATE TABLE SQL，即时校验是否符合团队建模规范
            </p>
          </div>
          <div className="flex items-center gap-2 text-[12px] text-slate-500">
            <i className="ri-book-2-line" />
            <span>12 条规则已启用</span>
            <span className="text-slate-300 mx-1">|</span>
            <i className="ri-history-line" />
            <span>本周执行 84 次</span>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-8 py-7">
        <div className="grid grid-cols-5 gap-6">
          {/* Left: Input area (2/5) */}
          <div className="col-span-2 space-y-4">
            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[13px] font-semibold text-slate-700">输入 DDL SQL</h3>
                <button
                  onClick={handleLoadSample}
                  className="text-[11px] text-slate-400 hover:text-slate-600 underline underline-offset-2 cursor-pointer whitespace-nowrap"
                >
                  加载示例 SQL
                </button>
              </div>

              {/* DB Type */}
              <div className="mb-3">
                <label className="text-[11px] font-medium text-slate-500 uppercase tracking-wide block mb-1.5">
                  Database Type
                </label>
                <div className="flex gap-2">
                  {DB_TYPES.map((t) => (
                    <button
                      key={t}
                      onClick={() => setDbType(t)}
                      className={`flex-1 py-1.5 rounded-md text-[12px] font-medium border transition-colors cursor-pointer whitespace-nowrap ${
                        dbType === t
                          ? 'bg-slate-900 text-white border-slate-900'
                          : 'bg-white text-slate-600 border-slate-200 hover:border-slate-300'
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              {/* SQL Textarea */}
              <div className="mb-4">
                <label className="text-[11px] font-medium text-slate-500 uppercase tracking-wide block mb-1.5">
                  CREATE TABLE Statement
                </label>
                <textarea
                  value={sql}
                  onChange={(e) => setSql(e.target.value)}
                  placeholder={`-- 粘贴你的 CREATE TABLE 语句\nCREATE TABLE your_table (\n  ...\n);`}
                  className="w-full h-72 text-[12px] font-mono text-slate-800 bg-slate-50 border border-slate-200 rounded-lg p-3 resize-none focus:outline-none focus:border-slate-400 focus:bg-white transition-colors placeholder-slate-400 leading-relaxed"
                />
                <div className="flex justify-between mt-1">
                  <span className="text-[10px] text-slate-400">支持多个 CREATE TABLE 语句</span>
                  <span className="text-[10px] text-slate-400">{sql.length} chars</span>
                </div>
              </div>

              {/* Submit */}
              <button
                onClick={handleCheck}
                disabled={!sql.trim() || loading}
                className={`w-full py-2.5 rounded-lg text-[13px] font-semibold transition-all whitespace-nowrap cursor-pointer flex items-center justify-center gap-2 ${
                  !sql.trim() || loading
                    ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                    : 'bg-slate-900 text-white hover:bg-slate-700 active:scale-[0.99]'
                }`}
              >
                {loading ? (
                  <>
                    <i className="ri-loader-4-line animate-spin" />
                    Checking...
                  </>
                ) : (
                  <>
                    <i className="ri-play-circle-line" />
                    Start Check
                  </>
                )}
              </button>
            </div>

            {/* Tips */}
            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <h3 className="text-[12px] font-semibold text-slate-600 mb-3 flex items-center gap-1.5">
                <i className="ri-lightbulb-line text-amber-400" />
                规则说明
              </h3>
              <div className="space-y-2">
                {[
                  { level: 'HIGH', desc: '阻断性问题，不允许执行', color: 'text-red-500' },
                  { level: 'MEDIUM', desc: '规范性问题，建议修复后执行', color: 'text-amber-500' },
                  { level: 'LOW', desc: '优化建议，不强制要求', color: 'text-emerald-500' },
                ].map((r) => (
                  <div key={r.level} className="flex items-start gap-2.5">
                    <span className={`text-[10px] font-bold mt-0.5 w-12 ${r.color}`}>{r.level}</span>
                    <span className="text-[11px] text-slate-500">{r.desc}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right: Results area (3/5) */}
          <div className="col-span-3 space-y-5">
            {!result && !loading && (
              <div className="bg-white border border-dashed border-slate-200 rounded-xl flex flex-col items-center justify-center py-20 text-center">
                <div className="w-12 h-12 flex items-center justify-center bg-slate-100 rounded-full mb-3">
                  <i className="ri-file-search-line text-slate-400 text-xl" />
                </div>
                <p className="text-[13px] font-medium text-slate-500">在左侧输入 SQL 并点击 Start Check</p>
                <p className="text-[12px] text-slate-400 mt-1">结果将在这里显示</p>
              </div>
            )}

            {loading && (
              <div className="bg-white border border-slate-200 rounded-xl flex flex-col items-center justify-center py-20">
                <div className="w-12 h-12 flex items-center justify-center mb-4">
                  <i className="ri-loader-4-line text-2xl text-slate-400 animate-spin" />
                </div>
                <p className="text-[13px] text-slate-500">正在执行规则检查...</p>
                <div className="flex items-center gap-1 mt-3">
                  {['DDL-001', 'DDL-010', 'DDL-020'].map((r, i) => (
                    <span
                      key={r}
                      className="text-[10px] bg-slate-100 text-slate-400 px-1.5 py-0.5 rounded"
                      style={{ animationDelay: `${i * 0.2}s` }}
                    >
                      {r}
                    </span>
                  ))}
                  <span className="text-[10px] text-slate-300">...</span>
                </div>
              </div>
            )}

            {result && (
              <>
                {/* A. Summary */}
                <div className="bg-white border border-slate-200 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-[13px] font-semibold text-slate-700 flex items-center gap-1.5">
                      <i className="ri-pie-chart-2-line text-slate-400" />
                      Summary
                    </h3>
                    <span className="text-[11px] text-slate-400">
                      {result.high + result.medium + result.low} 条问题
                    </span>
                  </div>
                  <div className="flex items-center gap-6">
                    {/* Score ring */}
                    <div className="relative w-20 h-20 shrink-0">
                      <svg viewBox="0 0 80 80" className="w-20 h-20 -rotate-90">
                        <circle cx="40" cy="40" r="34" fill="none" stroke="#f1f5f9" strokeWidth="6" />
                        <circle
                          cx="40"
                          cy="40"
                          r="34"
                          fill="none"
                          strokeWidth="6"
                          strokeLinecap="round"
                          strokeDasharray={circumference}
                          strokeDashoffset={dashOffset}
                          className={`${scoreRingColor} transition-all duration-700`}
                        />
                      </svg>
                      <div className="absolute inset-0 flex flex-col items-center justify-center">
                        <span className={`text-xl font-bold ${scoreColor}`}>{result.score}</span>
                        <span className="text-[9px] text-slate-400 -mt-0.5">Score</span>
                      </div>
                    </div>

                    {/* Severity counts */}
                    <div className="flex-1 grid grid-cols-3 gap-3">
                      {[
                        { label: 'HIGH', count: result.high, bg: 'bg-red-50', border: 'border-red-100', text: 'text-red-600', numText: 'text-red-600' },
                        { label: 'MEDIUM', count: result.medium, bg: 'bg-amber-50', border: 'border-amber-100', text: 'text-amber-600', numText: 'text-amber-600' },
                        { label: 'LOW', count: result.low, bg: 'bg-emerald-50', border: 'border-emerald-100', text: 'text-emerald-600', numText: 'text-emerald-600' },
                      ].map((s) => (
                        <div key={s.label} className={`${s.bg} ${s.border} border rounded-lg p-3 text-center`}>
                          <div className={`text-2xl font-bold ${s.numText}`}>{s.count}</div>
                          <div className={`text-[10px] font-semibold mt-0.5 ${s.text}`}>{s.label}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* C. Execution Status */}
                <div
                  className={`rounded-xl border px-5 py-4 flex items-center gap-4 ${
                    result.allowed
                      ? 'bg-emerald-50 border-emerald-200'
                      : 'bg-red-50 border-red-200'
                  }`}
                >
                  <div
                    className={`w-9 h-9 flex items-center justify-center rounded-full ${
                      result.allowed ? 'bg-emerald-100' : 'bg-red-100'
                    }`}
                  >
                    <i
                      className={`text-lg ${
                        result.allowed ? 'ri-checkbox-circle-line text-emerald-600' : 'ri-close-circle-line text-red-500'
                      }`}
                    />
                  </div>
                  <div>
                    <div
                      className={`text-[14px] font-bold ${
                        result.allowed ? 'text-emerald-700' : 'text-red-600'
                      }`}
                    >
                      Execution Status: {result.allowed ? 'ALLOWED' : 'NOT ALLOWED'}
                    </div>
                    <div className={`text-[12px] mt-0.5 ${result.allowed ? 'text-emerald-600' : 'text-red-500'}`}>
                      {result.allowed
                        ? '该 DDL 可以在生产环境执行'
                        : `存在 ${result.high} 条 HIGH 级别问题，DDL 不允许执行，请先修复高危问题`}
                    </div>
                  </div>
                </div>

                {/* B. Issues table */}
                <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                  <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
                    <h3 className="text-[13px] font-semibold text-slate-700 flex items-center gap-1.5">
                      <i className="ri-error-warning-line text-slate-400" />
                      Issues
                    </h3>
                    {/* Severity filter */}
                    <div className="flex items-center gap-1">
                      {['ALL', 'HIGH', 'MEDIUM', 'LOW'].map((f) => (
                        <button
                          key={f}
                          onClick={() => setSeverityFilter(f)}
                          className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors cursor-pointer whitespace-nowrap ${
                            severityFilter === f
                              ? 'bg-slate-900 text-white'
                              : 'text-slate-500 hover:bg-slate-100'
                          }`}
                        >
                          {f === 'ALL' ? `All (${result.issues.length})` : f}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="bg-slate-50">
                          <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 whitespace-nowrap">
                            Rule ID
                          </th>
                          <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 whitespace-nowrap">
                            Severity
                          </th>
                          <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 whitespace-nowrap">
                            Target
                          </th>
                          <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">
                            Message
                          </th>
                          <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">
                            Suggestion
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredIssues.map((issue, idx) => (
                          <tr
                            key={issue.ruleId + idx}
                            className="border-t border-slate-100 hover:bg-slate-50 transition-colors"
                          >
                            <td className="px-4 py-3 whitespace-nowrap">
                              <span className="font-mono text-[11px] text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">
                                {issue.ruleId}
                              </span>
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap">
                              <SeverityBadge level={issue.severity} />
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap">
                              <span className="font-mono text-[11px] text-slate-600">{issue.target}</span>
                            </td>
                            <td className="px-4 py-3">
                              <span className="text-[12px] text-slate-700">{issue.message}</span>
                            </td>
                            <td className="px-4 py-3">
                              <span className="text-[11px] text-slate-400 font-mono leading-relaxed block max-w-xs">
                                {issue.suggestion}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {filteredIssues.length === 0 && (
                      <div className="py-8 text-center text-[13px] text-slate-400">
                        该级别无问题
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
