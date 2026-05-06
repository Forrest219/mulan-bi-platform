/**
 * QueryResultChart — Recharts-based chart renderer for chart_data SSE events.
 *
 * Supports:
 *   - bar:  BarChart, one Bar per series key
 *   - line: LineChart, one Line per series key
 *   - pie:  PieChart, one Cell per x_field value
 *
 * When series_field is provided the raw rows are pivoted so that each unique
 * series_field value becomes an independent series.
 */
import { useMemo } from 'react';
import {
  BarChart, Bar,
  LineChart, Line,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import type { ChartData } from '../../hooks/useStreamingChat';

const PALETTE = [
  '#6366f1', '#22d3ee', '#f59e0b', '#10b981',
  '#ef4444', '#8b5cf6', '#f97316', '#ec4899',
];

function fmtNum(v: number): string {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function tooltipFmt(v: unknown): string {
  return typeof v === 'number' ? fmtNum(v) : String(v ?? '');
}

interface Props {
  data: ChartData;
}

export default function QueryResultChart({ data }: Props) {
  const { chart_type, x_field, y_fields, series_field } = data;

  // Build the chart-friendly array and determine which keys to plot.
  const { chartRows, seriesKeys } = useMemo(() => {
    if (!series_field) {
      return { chartRows: data.data, seriesKeys: y_fields };
    }

    // Pivot: one row per x_field value; each unique series_field value becomes a column.
    const xOrder: string[] = [];
    const seenX = new Set<string>();
    const seriesSet = new Set<string>();
    const pivot: Record<string, Record<string, unknown>> = {};

    for (const row of data.data) {
      const xVal = String(row[x_field!] ?? '');
      const sVal = String(row[series_field] ?? '');
      seriesSet.add(sVal);
      if (!seenX.has(xVal)) {
        seenX.add(xVal);
        xOrder.push(xVal);
        pivot[xVal] = { [x_field!]: xVal };
      }
      const yRaw = y_fields[0] != null ? row[y_fields[0]] : null;
      pivot[xVal][sVal] = typeof yRaw === 'number' ? yRaw : null;
    }

    return {
      chartRows: xOrder.map((x) => pivot[x]),
      seriesKeys: Array.from(seriesSet),
    };
  }, [data, x_field, y_fields, series_field]);

  if (!chartRows.length || !x_field) {
    return <p className="text-sm text-slate-400 mt-3 italic">暂无图表数据</p>;
  }

  const margin = { top: 8, right: 20, left: 0, bottom: 4 };

  // ── Pie ─────────────────────────────────────────────────────────────────────
  if (chart_type === 'pie') {
    const pieRows = chartRows.map((d) => ({
      name: String(d[x_field] ?? ''),
      value: typeof d[y_fields[0]] === 'number' ? (d[y_fields[0]] as number) : 0,
    }));
    return (
      <div className="mt-4 w-full h-64">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={pieRows}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={90}
              label={({ name, percent }: { name: string; percent: number }) =>
                `${name} ${(percent * 100).toFixed(1)}%`
              }
            >
              {pieRows.map((_, idx) => (
                <Cell key={idx} fill={PALETTE[idx % PALETTE.length]} />
              ))}
            </Pie>
            <Tooltip formatter={tooltipFmt} />
          </PieChart>
        </ResponsiveContainer>
      </div>
    );
  }

  const xAxisProps = {
    dataKey: x_field,
    tick: { fontSize: 11 },
    ...(seriesKeys.length > 4 ? { angle: -35, textAnchor: 'end' as const, height: 48 } : {}),
  };

  // ── Line ─────────────────────────────────────────────────────────────────────
  if (chart_type === 'line') {
    return (
      <div className="mt-4 w-full h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartRows} margin={{ top: 8, right: 24, left: 8, bottom: seriesKeys.length > 4 ? 32 : 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis {...xAxisProps} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={fmtNum} width={64} />
            <Tooltip formatter={tooltipFmt} />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
            {seriesKeys.map((key, idx) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={PALETTE[idx % PALETTE.length]}
                strokeWidth={2}
                dot={{ r: 3 }}
                activeDot={{ r: 5 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }

  // ── Bar (default) ────────────────────────────────────────────────────────────
  return (
    <div className="mt-4 w-full h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartRows} margin={{ top: 8, right: 24, left: 8, bottom: seriesKeys.length > 4 ? 32 : 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis {...xAxisProps} />
          <YAxis tick={{ fontSize: 11 }} tickFormatter={fmtNum} width={64} />
          <Tooltip formatter={tooltipFmt} />
          <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
          {seriesKeys.map((key, idx) => (
            <Bar key={key} dataKey={key} fill={PALETTE[idx % PALETTE.length]} radius={[3, 3, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
