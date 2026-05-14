import type {
  ExplorerConnection,
  ExplorerError,
  ExplorerTabKey,
  ExplorerTable,
  PermissionSummary,
  PreviewData,
  TableColumn,
  TableOverview,
} from './types';
import OverviewTab from './OverviewTab';
import PermissionsTab from './PermissionsTab';
import PreviewTab from './PreviewTab';
import SchemaTab from './SchemaTab';

interface TableDetailProps {
  connection?: ExplorerConnection | null;
  table?: ExplorerTable | null;
  activeTab?: ExplorerTabKey;
  onTabChange?: (tab: ExplorerTabKey) => void;
  connectionError?: string | ExplorerError | null;
  overview?: TableOverview | null;
  columns?: TableColumn[];
  preview?: PreviewData | null;
  permissions?: PermissionSummary | null;
  loading?: Partial<Record<ExplorerTabKey, boolean>>;
  errors?: Partial<Record<ExplorerTabKey, string | ExplorerError | null>>;
  onRetry?: Partial<Record<ExplorerTabKey, () => void>>;
}

const TABS: Array<{ key: ExplorerTabKey; label: string; icon: string }> = [
  { key: 'overview', label: 'Overview', icon: 'ri-dashboard-line' },
  { key: 'schema', label: 'Schema', icon: 'ri-list-check-2' },
  { key: 'preview', label: 'Preview', icon: 'ri-table-view' },
  { key: 'permissions', label: 'Permissions', icon: 'ri-shield-keyhole-line' },
];

function messageOf(error: TableDetailProps['connectionError']) {
  if (!error) return '';
  return typeof error === 'string' ? error : error.message;
}

function errorCodeOf(error: TableDetailProps['connectionError']) {
  if (!error || typeof error === 'string') return '';
  return error.error_code ?? '';
}

function ConnectionErrorPanel({ error }: { error: string | ExplorerError }) {
  const message = messageOf(error);
  const code = errorCodeOf(error);
  const isDex010 = code === 'DEX_010';

  return (
    <div className="border border-red-100 bg-red-50 rounded-xl p-5 text-red-700">
      <div className="flex items-start gap-3">
        <i className={`${isDex010 ? 'ri-plug-2-line' : 'ri-error-warning-line'} text-xl mt-0.5`} />
        <div>
          <div className="text-sm font-semibold">{isDex010 ? '目标数据库连接失败' : 'Data Explorer 加载失败'}</div>
          <p className="mt-1 text-[13px] text-red-600">{message || '请稍后重试或检查连接配置。'}</p>
          {code && <div className="mt-3 inline-flex px-2 py-0.5 rounded bg-white border border-red-100 text-[11px] font-mono">{code}</div>}
        </div>
      </div>
    </div>
  );
}

export default function TableDetail({
  connection = null,
  table = null,
  activeTab = 'overview',
  onTabChange,
  connectionError = null,
  overview = null,
  columns = [],
  preview = null,
  permissions = null,
  loading = {},
  errors = {},
  onRetry = {},
}: TableDetailProps) {
  const selectedTab = TABS.some(tab => tab.key === activeTab) ? activeTab : 'overview';

  if (connectionError) {
    return (
      <section className="flex-1 min-w-0 bg-white border border-slate-200 rounded-xl p-5">
        <ConnectionErrorPanel error={connectionError} />
      </section>
    );
  }

  if (!connection) {
    return (
      <section className="flex-1 min-w-0 bg-white border border-slate-200 rounded-xl flex items-center justify-center min-h-[640px]">
        <div className="text-center">
          <i className="ri-database-2-line text-3xl text-slate-300" />
          <div className="mt-3 text-sm font-medium text-slate-600">请选择数据库连接</div>
          <div className="mt-1 text-[12px] text-slate-400">从左侧连接树开始浏览 schema 和 table</div>
        </div>
      </section>
    );
  }

  if (!table) {
    return (
      <section className="flex-1 min-w-0 bg-white border border-slate-200 rounded-xl flex items-center justify-center min-h-[640px]">
        <div className="text-center">
          <i className="ri-folder-open-line text-3xl text-slate-300" />
          <div className="mt-3 text-sm font-medium text-slate-600">请选择 schema 下的表</div>
          <div className="mt-1 text-[12px] text-slate-400">{connection.name} · {connection.db_type}</div>
        </div>
      </section>
    );
  }

  return (
    <section className="flex-1 min-w-0 bg-white border border-slate-200 rounded-xl overflow-hidden min-h-[640px]">
      <div className="px-5 py-4 border-b border-slate-100">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[12px] text-slate-400">
              <span className="truncate">{connection.name}</span>
              <i className="ri-arrow-right-s-line" />
              <span className="font-mono truncate">{table.schema}</span>
            </div>
            <div className="mt-1 flex items-center gap-2 min-w-0">
              <i className={`${table.type === 'view' ? 'ri-eye-line' : 'ri-table-line'} text-slate-400`} />
              <h2 className="text-lg font-semibold text-slate-800 truncate">{table.name}</h2>
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">{table.type}</span>
            </div>
            {table.comment && <p className="mt-1 text-[12px] text-slate-400 truncate">{table.comment}</p>}
          </div>
        </div>
      </div>

      <div className="px-5 border-b border-slate-100">
        <div className="flex gap-1 py-2">
          {TABS.map(tab => (
            <button
              key={tab.key}
              type="button"
              onClick={() => onTabChange?.(tab.key)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${
                selectedTab === tab.key
                  ? 'bg-slate-800 text-white'
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
              }`}
            >
              <i className={tab.icon} />
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="p-5 bg-slate-50/60 min-h-[520px]">
        {selectedTab === 'overview' && (
          <OverviewTab
            table={table}
            overview={overview}
            loading={loading.overview}
            error={errors.overview}
            onRetry={onRetry.overview}
          />
        )}
        {selectedTab === 'schema' && (
          <SchemaTab
            columns={columns}
            loading={loading.schema}
            error={errors.schema}
            onRetry={onRetry.schema}
          />
        )}
        {selectedTab === 'preview' && (
          <PreviewTab
            data={preview}
            loading={loading.preview}
            error={errors.preview}
            onRetry={onRetry.preview}
          />
        )}
        {selectedTab === 'permissions' && (
          <PermissionsTab
            permissions={permissions}
            loading={loading.permissions}
            error={errors.permissions}
            onRetry={onRetry.permissions}
          />
        )}
      </div>
    </section>
  );
}
