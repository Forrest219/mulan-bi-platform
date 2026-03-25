import { Severity } from '../../../mocks/ddlMockData';

interface SeverityBadgeProps {
  level: Severity;
  size?: 'sm' | 'md';
}

export default function SeverityBadge({ level, size = 'md' }: SeverityBadgeProps) {
  const config = {
    HIGH: { bg: 'bg-red-50', text: 'text-red-600', border: 'border-red-200', dot: 'bg-red-500' },
    MEDIUM: { bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-200', dot: 'bg-amber-500' },
    LOW: { bg: 'bg-emerald-50', text: 'text-emerald-600', border: 'border-emerald-200', dot: 'bg-emerald-500' },
  };
  const c = config[level];
  const px = size === 'sm' ? 'px-1.5 py-0.5' : 'px-2.5 py-0.5';
  const textSize = size === 'sm' ? 'text-[10px]' : 'text-[11px]';
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border font-semibold ${c.bg} ${c.text} ${c.border} ${px} ${textSize} whitespace-nowrap`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot} shrink-0`} />
      {level}
    </span>
  );
}
