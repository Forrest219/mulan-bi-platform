import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  DataExplorerApiError,
  type DataExplorerColumn,
  type DataExplorerConnection,
  type DataExplorerConnectionOverview,
  type DataExplorerPermissions,
  type DataExplorerPreview,
  type DataExplorerSchema,
  type DataExplorerTable,
  type DataExplorerTableOverview,
  encodeExplorerTableRef,
  getDataExplorerConnectionOverview,
  getDataExplorerPermissions,
  getDataExplorerPreview,
  getDataExplorerTableOverview,
  listDataExplorerColumns,
  listDataExplorerConnections,
  listDataExplorerSchemas,
  listDataExplorerTables,
} from '../../../api/dataExplorer';
import ExplorerTree from './components/ExplorerTree';
import TableDetail from './components/TableDetail';
import type {
  ExplorerConnection,
  ExplorerError,
  ExplorerTabKey,
  PermissionSummary,
  PreviewCell,
  PreviewData,
} from './components/types';

interface ExplorerSelection {
  connectionId: number | null;
  schema: string | null;
  table: string | null;
}

function parseConnectionId(raw: string | null): number | null {
  if (!raw) return null;
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message;
  return fallback;
}

function toExplorerError(error: unknown, fallback: string): ExplorerError {
  if (error instanceof DataExplorerApiError) {
    return {
      error_code: error.errorCode,
      message: error.message || fallback,
      detail: error.detail && typeof error.detail === 'object' ? error.detail as Record<string, unknown> : null,
    };
  }
  return { message: getErrorMessage(error, fallback) };
}

function isDisconnectedError(error: unknown): boolean {
  return error instanceof DataExplorerApiError && error.errorCode === 'DEX_010';
}

function schemaKey(connectionId: number, schemaName: string): string {
  return `${connectionId}:${schemaName}`;
}

function toPreviewData(preview: DataExplorerPreview | null): PreviewData | null {
  if (!preview) return null;
  return {
    columns: preview.columns,
    rows: preview.rows as PreviewCell[][],
    limit: preview.limit,
    truncated: preview.truncated,
  };
}

function toPermissionSummary(permissions: DataExplorerPermissions | null): PermissionSummary | null {
  if (!permissions) return null;
  return {
    can_browse: permissions.effective_actions.view_metadata,
    can_preview: permissions.effective_actions.preview_rows,
    scope: '连接级',
    source: permissions.mode,
    message: 'P0 权限来自数据库连接访问权，Explorer 不展示或修改目标库授权。',
    notes: permissions.explanation,
    grants: [
      { label: '可浏览元数据', value: permissions.effective_actions.view_metadata },
      { label: '可预览数据', value: permissions.effective_actions.preview_rows },
      { label: '可导出', value: permissions.effective_actions.export },
      { label: '可授权', value: permissions.effective_actions.grant },
      { label: 'Owner', value: permissions.connection.owner_name ?? String(permissions.connection.owner_id) },
    ],
  };
}

export default function DataExplorerPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const connectionId = parseConnectionId(searchParams.get('connection_id'));
  const schema = searchParams.get('schema');
  const table = searchParams.get('table');

  const selection: ExplorerSelection = useMemo(() => ({
    connectionId,
    schema,
    table,
  }), [connectionId, schema, table]);

  const [connections, setConnections] = useState<DataExplorerConnection[]>([]);
  const [schemas, setSchemas] = useState<DataExplorerSchema[]>([]);
  const [tables, setTables] = useState<DataExplorerTable[]>([]);
  const [connectionOverview, setConnectionOverview] = useState<DataExplorerConnectionOverview | null>(null);
  const [tableOverview, setTableOverview] = useState<DataExplorerTableOverview | null>(null);
  const [columns, setColumns] = useState<DataExplorerColumn[]>([]);
  const [preview, setPreview] = useState<DataExplorerPreview | null>(null);
  const [permissions, setPermissions] = useState<DataExplorerPermissions | null>(null);
  const [activeTab, setActiveTab] = useState<ExplorerTabKey>('overview');
  const [disconnectedConnectionIds, setDisconnectedConnectionIds] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState({ connections: true, schemas: false, tables: false, detail: false });
  const [treeError, setTreeError] = useState<ExplorerError | null>(null);
  const [detailError, setDetailError] = useState<ExplorerError | null>(null);

  const selectedTableRef = useMemo(() => {
    if (!connectionId || !schema || !table) return null;
    return tables.find((item) => item.schema === schema && item.name === table)?.table_ref
      ?? encodeExplorerTableRef(schema, table);
  }, [connectionId, schema, table, tables]);

  const selectedConnection = useMemo(
    () => connections.find((connection) => connection.id === connectionId) ?? null,
    [connections, connectionId],
  );

  const selectedTable = useMemo(
    () => tables.find((item) => item.table_ref === selectedTableRef)
      ?? (schema && table && selectedTableRef
        ? { schema, name: table, type: 'table' as const, table_ref: selectedTableRef, comment: null, row_count: null, column_count: null }
        : null),
    [schema, selectedTableRef, table, tables],
  );

  const decoratedConnections: ExplorerConnection[] = useMemo(() => (
    connections.map((connection) => ({
      ...connection,
      error: disconnectedConnectionIds.has(connection.id)
        ? { error_code: 'DEX_010', message: '目标数据库连接失败' }
        : null,
    }))
  ), [connections, disconnectedConnectionIds]);

  const schemasByConnection = useMemo(() => (
    connectionId ? { [connectionId]: schemas } : {}
  ), [connectionId, schemas]);

  const tablesBySchema = useMemo(() => (
    connectionId && schema ? { [schemaKey(connectionId, schema)]: tables } : {}
  ), [connectionId, schema, tables]);

  const loadConnections = useCallback(async () => {
    setLoading((prev) => ({ ...prev, connections: true }));
    setTreeError(null);
    try {
      const res = await listDataExplorerConnections();
      setConnections(res.items);
    } catch (error) {
      setTreeError(toExplorerError(error, '加载连接失败'));
    } finally {
      setLoading((prev) => ({ ...prev, connections: false }));
    }
  }, []);

  useEffect(() => {
    loadConnections();
  }, [loadConnections]);

  useEffect(() => {
    setSchemas([]);
    setTables([]);
    setConnectionOverview(null);
    setTableOverview(null);
    setColumns([]);
    setPreview(null);
    setPermissions(null);
    setDetailError(null);

    if (!connectionId) return;

    let cancelled = false;
    setLoading((prev) => ({ ...prev, schemas: true }));
    setTreeError(null);

    Promise.all([
      getDataExplorerConnectionOverview(connectionId),
      listDataExplorerSchemas(connectionId),
    ])
      .then(([overviewRes, schemasRes]) => {
        if (cancelled) return;
        setConnectionOverview(overviewRes);
        setSchemas(schemasRes.items);
        setDisconnectedConnectionIds((prev) => {
          const next = new Set(prev);
          next.delete(connectionId);
          return next;
        });
      })
      .catch((error) => {
        if (cancelled) return;
        if (isDisconnectedError(error)) {
          setDisconnectedConnectionIds((prev) => new Set(prev).add(connectionId));
        }
        setTreeError(toExplorerError(error, '加载 schema 失败'));
      })
      .finally(() => {
        if (!cancelled) setLoading((prev) => ({ ...prev, schemas: false }));
      });

    return () => { cancelled = true; };
  }, [connectionId]);

  useEffect(() => {
    setTables([]);
    setTableOverview(null);
    setColumns([]);
    setPreview(null);
    setPermissions(null);
    setDetailError(null);

    if (!connectionId || !schema) return;

    let cancelled = false;
    setLoading((prev) => ({ ...prev, tables: true }));

    listDataExplorerTables(connectionId, { schema, type: 'all', limit: 200, offset: 0 })
      .then((res) => {
        if (!cancelled) setTables(res.items);
      })
      .catch((error) => {
        if (cancelled) return;
        if (isDisconnectedError(error)) {
          setDisconnectedConnectionIds((prev) => new Set(prev).add(connectionId));
        }
        setTreeError(toExplorerError(error, '加载 table 失败'));
      })
      .finally(() => {
        if (!cancelled) setLoading((prev) => ({ ...prev, tables: false }));
      });

    return () => { cancelled = true; };
  }, [connectionId, schema]);

  const loadTableDetail = useCallback(async () => {
    if (!connectionId || !selectedTableRef) return;

    setLoading((prev) => ({ ...prev, detail: true }));
    setDetailError(null);
    try {
      const [overviewRes, columnsRes, previewRes, permissionsRes] = await Promise.all([
        getDataExplorerTableOverview(connectionId, selectedTableRef),
        listDataExplorerColumns(connectionId, selectedTableRef),
        getDataExplorerPreview(connectionId, selectedTableRef, { limit: 100 }),
        getDataExplorerPermissions(connectionId, selectedTableRef),
      ]);
      setTableOverview(overviewRes);
      setColumns(columnsRes.items);
      setPreview(previewRes);
      setPermissions(permissionsRes);
      setDisconnectedConnectionIds((prev) => {
        const next = new Set(prev);
        next.delete(connectionId);
        return next;
      });
    } catch (error) {
      if (isDisconnectedError(error)) {
        setDisconnectedConnectionIds((prev) => new Set(prev).add(connectionId));
      }
      setDetailError(toExplorerError(error, '加载表详情失败'));
    } finally {
      setLoading((prev) => ({ ...prev, detail: false }));
    }
  }, [connectionId, selectedTableRef]);

  useEffect(() => {
    setTableOverview(null);
    setColumns([]);
    setPreview(null);
    setPermissions(null);
    setDetailError(null);
    loadTableDetail();
  }, [loadTableDetail]);

  const updateSelection = useCallback((next: Partial<ExplorerSelection>) => {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      if (next.connectionId !== undefined) {
        if (next.connectionId) params.set('connection_id', String(next.connectionId));
        else params.delete('connection_id');
      }
      if (next.schema !== undefined) {
        if (next.schema) params.set('schema', next.schema);
        else params.delete('schema');
      }
      if (next.table !== undefined) {
        if (next.table) params.set('table', next.table);
        else params.delete('table');
      }
      return params;
    });
  }, [setSearchParams]);

  const handleSelectConnection = useCallback((nextConnection: ExplorerConnection) => {
    if (nextConnection.explorer_supported === false) return;
    updateSelection({ connectionId: nextConnection.id, schema: null, table: null });
  }, [updateSelection]);

  const handleSelectSchema = useCallback((nextConnection: ExplorerConnection, nextSchema: DataExplorerSchema) => {
    updateSelection({ connectionId: nextConnection.id, schema: nextSchema.name, table: null });
  }, [updateSelection]);

  const handleSelectTable = useCallback((nextConnection: ExplorerConnection, nextTable: DataExplorerTable) => {
    updateSelection({ connectionId: nextConnection.id, schema: nextTable.schema, table: nextTable.name });
  }, [updateSelection]);

  return (
    <div className="h-screen min-h-[640px] bg-slate-50 flex flex-col">
      <div className="h-14 bg-white border-b border-slate-200 px-6 flex items-center justify-between shrink-0">
        <div>
          <div className="flex items-center gap-2">
            <i className="ri-node-tree text-slate-500" />
            <h1 className="text-base font-semibold text-slate-900">Data Explorer</h1>
          </div>
          <div className="text-xs text-slate-400">从数据库连接浏览 schema、table、字段、预览和只读权限摘要</div>
        </div>
        {connectionOverview && (
          <div className="hidden md:flex items-center gap-3 text-xs text-slate-500">
            <span>{connectionOverview.connection.db_type}</span>
            <span>{connectionOverview.summary.schema_count ?? '-'} schemas</span>
            <span>{connectionOverview.summary.table_count ?? '-'} tables</span>
          </div>
        )}
      </div>

      <div className="flex-1 min-h-0 flex gap-4 p-4">
        <ExplorerTree
          connections={decoratedConnections}
          schemasByConnection={schemasByConnection}
          tablesBySchema={tablesBySchema}
          selection={{
            connectionId: selection.connectionId,
            schema: selection.schema,
            tableRef: selectedTableRef,
          }}
          loading={loading.connections}
          error={treeError}
          loadingConnectionIds={loading.schemas && connectionId ? [connectionId] : []}
          loadingSchemaKeys={loading.tables && connectionId && schema ? [schemaKey(connectionId, schema)] : []}
          onSelectConnection={handleSelectConnection}
          onSelectSchema={handleSelectSchema}
          onSelectTable={handleSelectTable}
          onRefresh={loadConnections}
        />

        <TableDetail
          connection={selectedConnection}
          table={selectedTable}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          connectionError={selectedConnection && disconnectedConnectionIds.has(selectedConnection.id) ? decoratedConnections.find(item => item.id === selectedConnection.id)?.error : null}
          overview={tableOverview}
          columns={columns}
          preview={toPreviewData(preview)}
          permissions={toPermissionSummary(permissions)}
          loading={{
            overview: loading.detail,
            schema: loading.detail,
            preview: loading.detail,
            permissions: loading.detail,
          }}
          errors={{
            overview: detailError,
            schema: detailError,
            preview: detailError,
            permissions: detailError,
          }}
          onRetry={{
            overview: loadTableDetail,
            schema: loadTableDetail,
            preview: loadTableDetail,
            permissions: loadTableDetail,
          }}
        />
      </div>
    </div>
  );
}
