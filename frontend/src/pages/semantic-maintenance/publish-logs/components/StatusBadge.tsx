export type PublishStatus = 'pending' | 'success' | 'failed' | 'rolled_back' | 'not_supported';

interface StatusBadgeProps {
  status: PublishStatus;
  size?: 'sm' | 'md';
}

const STATUS_CONFIG: Record<PublishStatus, { text: string; className: string; dot: string }> = {
  pending: {
    text: '进行中',
    className: 'bg-amber-50 text-amber-700 border-amber-200',
    dot: 'bg-amber-400',
  },
  success: {
    text: '成功',
    className: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    dot: 'bg-emerald-400',
  },
  failed: {
    text: '失败',
    className: 'bg-red-50 text-red-700 border-red-200',
    dot: 'bg-red-400',
  },
  rolled_back: {
    text: '已回滚',
    className: 'bg-slate-100 text-slate-600 border-slate-200',
    dot: 'bg-slate-400',
  },
  not_supported: {
    text: '不支持',
    className: 'bg-violet-50 text-violet-700 border-violet-200',
    dot: 'bg-violet-400',
  },
};

export function StatusBadge({ status, size = 'sm' }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.pending;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${config.className} ${
        size === 'md' ? 'px-3 py-1 text-sm' : ''
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot} ${size === 'md' ? 'w-2 h-2' : ''}`} />
      {config.text}
    </span>
  );
}

export function getStatusBadge(status: PublishStatus) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  return {
    text: config.text,
    className: `inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${config.className}`,
  };
}
