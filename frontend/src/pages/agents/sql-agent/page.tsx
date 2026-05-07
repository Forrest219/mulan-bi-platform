import { useCallback, useEffect, useState } from 'react';
import { listDataSources } from '../../../api/datasources';
import type { DataSource } from '../../../api/datasources';

interface SchemaColumn {
  name: string;
  type: string;
  nullable?: string | null;
}

interface SchemaTable {
  schema: string;
  name: string;
  row_count_estimate: number;
  columns: SchemaColumn[];
}

interface QueryResult {
  log_id: number;
  row_count: number;
  duration_ms: number;
  columns: string[];
  data: unknown[];
  truncated: boolean;
  truncated_reason: string | null;
  warning: string | null;
}

export default function SqlAgentPage() {
  const [datasources, setDatasources] = useState<DataSource[]>([]);
  const [selectedDs, setSelectedDs] = useState<number | ''>('');
  const [sql, setSql] = useState('');
  const [result, setResult] = useState<QueryResult | null>(null);
  const [schema, setSchema] = useState<SchemaTable[] | null>(null);
  const [schemaOpen, setSchemaOpen] = useState(false);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    listDataSources().then(r => setDatasources(r.datasources)).catch(() => {});
  }, []);

  const loadSchema = useCallback(async (dsId: number) => {
    setSchemaLoading(true);
    setSchema(null);
    try {
      const res = await fetch(`/api/sql-agent/datasource/${dsId}/preview`, {
        credentials: 'include',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSchema(data.tables ?? []);
    } catch {
      setSchema([]);
    } finally {
      setSchemaLoading(false);
    }
  }, []);

  const handleDsChange = (id: number | '') => {
    setSelectedDs(id);
    setResult(null);
    setSchema(null);
    setSchemaOpen(false);
    if (id) loadSchema(id as number);
  };

  const handleExecute = async () => {
    if (!selectedDs || !sql.trim()) return;
    setExecuting(true);
    setError('');
    setResult(null);
    try {
      const res = await fetch('/api/sql-agent/query', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ datasource_id: selectedDs, sql: sql.trim() }),
      });
      const body = await res.json();
      if (!res.ok) {
        setError(body.message ?? `执行失败 (HTTP ${res.status})`);
        return;
      }
      setResult(body);
    } catch {
      setError('网络请求失败，请检查连接');
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-file-code-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">SQL Agent</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">安全 SQL 执行 · 自动 LIMIT 注入 · 危险语句拦截</p>
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto space-y-4">
        {/* Datasource selector */}
        <div className="bg-white rounded-xl border border-slate-200 px-5 py-4">
          <label className="block text-[12px] font-medium text-slate-500 mb-2">目标数据源</label>
          <div className="flex items-center gap-3">
            <select
              value={selectedDs}
              onChange={e => handleDsChange(e.target.value ? Number(e.target.value) : '')}
              className="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">— 选择数据源 —</option>
              {datasources.map(ds => (
                <option key={ds.id} value={ds.id}>
                  {ds.name}（{ds.db_type} · {ds.host}:{ds.port}/{ds.database_name}）
                </option>
              ))}
            </select>
            {selectedDs && (
              <button
                onClick={() => setSchemaOpen(v => !v)}
                className="flex items-center gap-1.5 text-sm text-slate-600 border border-slate-200 rounded-lg px-3 py-2 hover:bg-slate-50 whitespace-nowrap"
              >
                <i className={`ri-table-line ${schemaLoading ? 'animate-pulse' : ''}`} />
                {schemaOpen ? '收起表结构' : '查看表结构'}
              </button>
            )}
          </div>

          {/* Schema panel */}
          {schemaOpen && selectedDs && (
            <div className="mt-4 border border-slate-100 rounded-lg overflow-hidden">
              {schemaLoading ? (
                <div className="px-4 py-6 text-center text-sm text-slate-400">加载表结构…</div>
              ) : !schema || schema.length === 0 ? (
                <div className="px-4 py-6 text-center text-sm text-slate-400">暂无表信息</div>
              ) : (
                <div className="max-h-56 overflow-y-auto divide-y divide-slate-50">
                  {schema.map(t => (
                    <div key={`${t.schema}.${t.name}`} className="px-4 py-2.5">
                      <div className="flex items-center gap-2 mb-1">
                        <i className="ri-table-line text-slate-400 text-[12px]" />
                        <span className="text-[13px] font-medium text-slate-700">{t.schema}.{t.name}</span>
                        <span className="text-[11px] text-slate-400">≈{t.row_count_estimate.toLocaleString()} 行</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5 ml-4">
                        {t.columns.map(c => (
                          <span key={c.name} className="text-[11px] bg-slate-50 border border-slate-200 rounded px-1.5 py-0.5 text-slate-600">
                            {c.name} <span className="text-slate-400">{c.type}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* SQL editor */}
        <div className="bg-white rounded-xl border border-slate-200 px-5 py-4">
          <label className="block text-[12px] font-medium text-slate-500 mb-2">SQL 语句</label>
          <textarea
            value={sql}
            onChange={e => setSql(e.target.value)}
            placeholder="SELECT * FROM your_table LIMIT 20"
            rows={7}
            className="w-full font-mono text-sm border border-slate-200 rounded-lg px-3 py-2.5 bg-slate-50 text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
          />
          <div className="mt-3 flex items-center justify-between">
            <p className="text-[12px] text-slate-400">
              危险语句（DROP / TRUNCATE / DELETE）将被拦截；查询结果自动限制最大行数
            </p>
            <button
              onClick={handleExecute}
              disabled={!selectedDs || !sql.trim() || executing}
              className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors whitespace-nowrap"
            >
              {executing ? (
                <>
                  <i className="ri-loader-4-line animate-spin" />
                  执行中…
                </>
              ) : (
                <>
                  <i className="ri-play-line" />
                  执行
                </>
              )}
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-5 py-3 text-sm text-red-700 flex items-start gap-2">
            <i className="ri-error-warning-line mt-0.5 flex-shrink-0" />
            {error}
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="bg-white rounded-xl border border-slate-200">
            <div className="px-5 py-3 border-b border-slate-100 flex items-center gap-4">
              <span className="text-sm font-medium text-slate-700">查询结果</span>
              <span className="text-[12px] text-slate-400">
                {result.row_count} 行 · 耗时 {result.duration_ms} ms · log_id #{result.log_id}
              </span>
              {result.truncated && (
                <span className="text-[12px] text-amber-600 bg-amber-50 px-2 py-0.5 rounded">
                  已截断{result.truncated_reason ? `：${result.truncated_reason}` : ''}
                </span>
              )}
              {result.warning && (
                <span className="text-[12px] text-amber-600">{result.warning}</span>
              )}
            </div>
            {result.columns.length === 0 ? (
              <div className="px-5 py-6 text-center text-sm text-slate-400">无返回数据</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      {result.columns.map(col => (
                        <th key={col} className="text-left px-4 py-2.5 text-[11px] font-medium text-slate-500 uppercase tracking-wider whitespace-nowrap border-b border-slate-100">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(result.data as Record<string, unknown>[]).map((row, i) => (
                      <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                        {result.columns.map(col => (
                          <td key={col} className="px-4 py-2 text-slate-700 whitespace-nowrap max-w-xs">
                            <span className="block truncate">
                              {row[col] == null ? <span className="text-slate-300">NULL</span> : String(row[col])}
                            </span>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        </div>
      </div>
    </div>
  );
}
