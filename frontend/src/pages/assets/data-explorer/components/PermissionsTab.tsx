import type { ExplorerError, PermissionSummary } from './types';

interface PermissionsTabProps {
  permissions?: PermissionSummary | null;
  loading?: boolean;
  error?: string | ExplorerError | null;
  onRetry?: () => void;
}

function messageOf(error: PermissionsTabProps['error']) {
  if (!error) return '';
  return typeof error === 'string' ? error : error.message;
}

function yesNo(value?: boolean) {
  if (value === undefined) return '—';
  return value ? '是' : '否';
}

export default function PermissionsTab({ permissions = null, loading = false, error = null, onRetry }: PermissionsTabProps) {
  const errorMessage = messageOf(error);

  if (loading) {
    return <div className="py-16 text-center text-[13px] text-slate-400"><i className="ri-loader-4-line animate-spin mr-1" />加载权限摘要...</div>;
  }

  if (errorMessage) {
    return (
      <div className="border border-red-100 bg-red-50 rounded-xl p-4 text-sm text-red-700">
        <div className="font-medium flex items-center gap-2"><i className="ri-error-warning-line" />权限摘要加载失败</div>
        <p className="mt-1 text-[13px]">{errorMessage}</p>
        {onRetry && <button onClick={onRetry} className="mt-3 px-3 py-1.5 bg-white border border-red-200 rounded-lg text-[12px] hover:bg-red-50">重试</button>}
      </div>
    );
  }

  if (!permissions) {
    return <div className="py-16 text-center text-[13px] text-slate-400">暂无权限摘要</div>;
  }

  const grants = permissions.grants ?? [
    { label: '可浏览元数据', value: yesNo(permissions.can_browse) },
    { label: '可预览数据', value: yesNo(permissions.can_preview) },
    { label: '权限范围', value: permissions.scope ?? '连接级' },
    { label: '权限来源', value: permissions.source ?? '数据库连接访问权' },
  ];

  return (
    <div className="space-y-4">
      <div className="border border-blue-100 bg-blue-50 rounded-xl p-4 text-[13px] text-blue-700 flex gap-3">
        <i className="ri-shield-check-line text-base mt-0.5" />
        <div>
          <div className="font-medium">只读权限摘要</div>
          <p className="mt-1 text-blue-600">{permissions.message ?? 'P0 权限来自数据库连接访问权，Explorer 不展示或修改目标库授权。'}</p>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100">
          <h3 className="text-[13px] font-semibold text-slate-800">当前访问能力</h3>
        </div>
        <dl className="divide-y divide-slate-100 text-[13px]">
          {grants.map(grant => (
            <div key={grant.label} className="grid grid-cols-[160px_1fr] px-4 py-3">
              <dt className="text-slate-400">{grant.label}</dt>
              <dd className="text-slate-700">{String(grant.value ?? '—')}</dd>
            </div>
          ))}
        </dl>
      </div>

      {permissions.notes && permissions.notes.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <h3 className="text-[13px] font-semibold text-slate-800 mb-2">备注</h3>
          <ul className="space-y-1 text-[13px] text-slate-500">
            {permissions.notes.map(note => <li key={note} className="flex gap-2"><span className="text-slate-300">•</span><span>{note}</span></li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
