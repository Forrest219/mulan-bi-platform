import { useEffect, useMemo, useState } from 'react';
import ConnectionNode from './ConnectionNode';
import type { ExplorerConnection, ExplorerError, ExplorerSchema, ExplorerSelection, ExplorerTable } from './types';

interface ExplorerTreeProps {
  connections: ExplorerConnection[];
  schemasByConnection?: Record<number, ExplorerSchema[]>;
  tablesBySchema?: Record<string, ExplorerTable[]>;
  selection?: ExplorerSelection;
  loading?: boolean;
  error?: string | ExplorerError | null;
  loadingConnectionIds?: number[];
  loadingSchemaKeys?: string[];
  onSelectConnection?: (connection: ExplorerConnection) => void;
  onSelectSchema?: (connection: ExplorerConnection, schema: ExplorerSchema) => void;
  onSelectTable?: (connection: ExplorerConnection, table: ExplorerTable) => void;
  onRefresh?: () => void;
}

const schemaKey = (connectionId: number, schemaName: string) => `${connectionId}:${schemaName}`;

function getErrorMessage(error: ExplorerTreeProps['error']) {
  if (!error) return '';
  return typeof error === 'string' ? error : error.message;
}

export default function ExplorerTree({
  connections,
  schemasByConnection = {},
  tablesBySchema = {},
  selection,
  loading = false,
  error = null,
  loadingConnectionIds = [],
  loadingSchemaKeys = [],
  onSelectConnection,
  onSelectSchema,
  onSelectTable,
  onRefresh,
}: ExplorerTreeProps) {
  const [expandedConnections, setExpandedConnections] = useState<Set<number>>(new Set());
  const [expandedSchemas, setExpandedSchemas] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (selection?.connectionId) {
      setExpandedConnections(prev => new Set(prev).add(selection.connectionId));
    }
    if (selection?.connectionId && selection.schema) {
      setExpandedSchemas(prev => new Set(prev).add(schemaKey(selection.connectionId, selection.schema)));
    }
  }, [selection?.connectionId, selection?.schema]);

  const filteredConnections = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return connections;
    return connections.filter(connection => {
      const schemaHit = (schemasByConnection[connection.id] ?? []).some(schema => schema.name.toLowerCase().includes(q));
      return (
        connection.name.toLowerCase().includes(q) ||
        connection.db_type.toLowerCase().includes(q) ||
        (connection.database_name ?? '').toLowerCase().includes(q) ||
        schemaHit
      );
    });
  }, [connections, query, schemasByConnection]);

  const handleToggleConnection = (connection: ExplorerConnection) => {
    setExpandedConnections(prev => {
      const next = new Set(prev);
      if (next.has(connection.id)) next.delete(connection.id);
      else next.add(connection.id);
      return next;
    });
  };

  const handleToggleSchema = (connection: ExplorerConnection, schema: ExplorerSchema) => {
    const key = schemaKey(connection.id, schema.name);
    setExpandedSchemas(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    onSelectSchema?.(connection, schema);
  };

  const errorMessage = getErrorMessage(error);

  return (
    <aside className="w-[320px] min-w-[280px] max-w-[340px] shrink-0 bg-white border border-slate-200 rounded-xl overflow-hidden flex flex-col min-h-[640px]">
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-[13px] font-semibold text-slate-800">连接与对象</h2>
            <p className="text-[11px] text-slate-400 mt-0.5">{connections.length} 个数据库连接</p>
          </div>
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="w-8 h-8 inline-flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 disabled:opacity-50"
            title="刷新连接"
          >
            <i className={`${loading ? 'ri-loader-4-line animate-spin' : 'ri-refresh-line'} text-sm`} />
          </button>
        </div>
        <div className="relative mt-3">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
          <input
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder="搜索连接或 schema"
            className="w-full pl-8 pr-3 py-2 text-[12px] border border-slate-200 rounded-lg focus:outline-none focus:border-slate-400"
          />
        </div>
      </div>

      {errorMessage && (
        <div className="mx-3 mt-3 px-3 py-2 rounded-lg border border-red-100 bg-red-50 text-[12px] text-red-700">
          {errorMessage}
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
        {loading && connections.length === 0 && (
          <div className="py-12 text-center text-[13px] text-slate-400">
            <i className="ri-loader-4-line animate-spin mr-1" />
            加载连接中...
          </div>
        )}

        {!loading && filteredConnections.length === 0 && (
          <div className="py-12 text-center text-[13px] text-slate-400">暂无可浏览连接</div>
        )}

        {filteredConnections.map(connection => {
          const expanded = expandedConnections.has(connection.id);
          const schemas = schemasByConnection[connection.id] ?? [];
          const selectedConnection = selection?.connectionId === connection.id && !selection?.tableRef;

          return (
            <div key={connection.id} className="space-y-1">
              <ConnectionNode
                connection={connection}
                expanded={expanded}
                selected={selectedConnection}
                loading={loadingConnectionIds.includes(connection.id)}
                schemaCount={schemas.length || undefined}
                onSelect={onSelectConnection}
                onToggle={handleToggleConnection}
              />

              {expanded && connection.explorer_supported !== false && (
                <div className="ml-4 pl-3 border-l border-slate-100 space-y-1">
                  {loadingConnectionIds.includes(connection.id) && schemas.length === 0 && (
                    <div className="px-2 py-2 text-[12px] text-slate-400">
                      <i className="ri-loader-4-line animate-spin mr-1" />
                      读取 schema...
                    </div>
                  )}

                  {!loadingConnectionIds.includes(connection.id) && schemas.length === 0 && (
                    <div className="px-2 py-2 text-[12px] text-slate-400">暂无 schema</div>
                  )}

                  {schemas.map(schema => {
                    const key = schemaKey(connection.id, schema.name);
                    const schemaExpanded = expandedSchemas.has(key);
                    const schemaTables = tablesBySchema[key] ?? [];
                    const selectedSchema = selection?.connectionId === connection.id && selection.schema === schema.name && !selection.tableRef;
                    const explicitObjectCount =
                      typeof schema.table_count === 'number' || typeof schema.view_count === 'number'
                        ? (schema.table_count ?? 0) + (schema.view_count ?? 0)
                        : null;
                    const displayObjectCount = explicitObjectCount ?? (schemaTables.length > 0 ? schemaTables.length : null);

                    return (
                      <div key={key}>
                        <button
                          type="button"
                          onClick={() => handleToggleSchema(connection, schema)}
                          className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left transition-colors ${
                            selectedSchema ? 'bg-slate-100 text-slate-800' : 'text-slate-600 hover:bg-slate-50'
                          }`}
                        >
                          <i className={`${schemaExpanded ? 'ri-arrow-down-s-line' : 'ri-arrow-right-s-line'} text-xs text-slate-400`} />
                          <i className="ri-folder-3-line text-sm text-slate-400" />
                          <span className="text-[12px] font-medium truncate flex-1">{schema.name}</span>
                          {displayObjectCount !== null && (
                            <span className="text-[11px] text-slate-400 shrink-0">
                              {displayObjectCount}
                            </span>
                          )}
                        </button>

                        {schemaExpanded && (
                          <div className="ml-5 mt-1 space-y-0.5">
                            {loadingSchemaKeys.includes(key) && schemaTables.length === 0 && (
                              <div className="px-2 py-1.5 text-[12px] text-slate-400">
                                <i className="ri-loader-4-line animate-spin mr-1" />
                                读取表...
                              </div>
                            )}

                            {!loadingSchemaKeys.includes(key) && schemaTables.length === 0 && (
                              <div className="px-2 py-1.5 text-[12px] text-slate-400">暂无表或视图</div>
                            )}

                            {schemaTables.map(table => {
                              const selectedTable = selection?.tableRef === table.table_ref;
                              return (
                                <button
                                  key={table.table_ref}
                                  type="button"
                                  onClick={() => onSelectTable?.(connection, table)}
                                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left transition-colors ${
                                    selectedTable ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-50'
                                  }`}
                                >
                                  <i className={`${table.type === 'view' ? 'ri-eye-line' : 'ri-table-line'} text-sm ${selectedTable ? 'text-white' : 'text-slate-400'}`} />
                                  <span className="text-[12px] truncate flex-1">{table.name}</span>
                                  {typeof table.column_count === 'number' && (
                                    <span className={`text-[11px] shrink-0 ${selectedTable ? 'text-slate-300' : 'text-slate-400'}`}>
                                      {table.column_count}
                                    </span>
                                  )}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
