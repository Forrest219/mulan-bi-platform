/**
 * @vitest-environment jsdom
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import QueryResultTable from '../../src/components/chat/QueryResultTable';
import { tableDataFromStructuredPayload, type TableData } from '../../src/hooks/useStreamingChat';

describe('QueryResultTable', () => {
  it('uses table_display labels, alignment, and percent string formatting', () => {
    const data: TableData = {
      fields: ['客户名称', 'SUM(销售额)', '销售额占比'],
      rows: [['李丽丽', 181562.11, '1.08%']],
      col_types: ['string', 'numeric', 'string'],
      table_display: {
        columns: [
          { key: '客户名称', label: '客户名称', align: 'left', format: 'plain' },
          { key: 'SUM(销售额)', label: '销售额', align: 'right', format: 'number' },
          { key: '销售额占比', label: '销售额占比', align: 'right', format: 'percent' },
        ],
      },
    };

    render(<QueryResultTable data={data} />);

    expect(screen.getByRole('columnheader', { name: '销售额' })).toHaveClass('text-right');
    expect(screen.queryByText('SUM(销售额)')).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '销售额占比' })).toHaveClass('text-right');
    expect(screen.getByText('1.08%').closest('td')).toHaveClass('text-right');
  });

  it('formats numeric percentages from table_display as percent values', () => {
    const data: TableData = {
      fields: ['客户名称', '销售额占比'],
      rows: [['李丽丽', 0.0108]],
      col_types: ['string', 'numeric'],
      table_display: {
        columns: [
          { key: '客户名称', label: '客户名称', align: 'left', format: 'plain' },
          { key: '销售额占比', label: '销售额占比', align: 'right', format: 'percent' },
        ],
      },
    };

    render(<QueryResultTable data={data} />);

    expect(screen.getByText('1.08%')).toBeInTheDocument();
    expect(screen.getByText('1.08%').closest('td')).toHaveClass('text-right');
  });

  it('keeps the legacy fields and col_types fallback without table_display', () => {
    const data: TableData = {
      fields: ['客户名称', '销售额'],
      rows: [['李丽丽', 1234.5]],
      col_types: ['string', 'numeric'],
    };

    render(<QueryResultTable data={data} />);

    expect(screen.getByRole('columnheader', { name: '客户名称' })).toHaveClass('text-left');
    expect(screen.getByRole('columnheader', { name: '销售额' })).toHaveClass('text-right');
    expect(screen.getByText('1,234.50').closest('td')).toHaveClass('text-right');
  });

  it('renders fields and rows from structured done response payload', () => {
    const data = tableDataFromStructuredPayload(
      {
        fields: ['region', 'sales'],
        rows: [['east', 100]],
        col_types: ['string', 'numeric'],
        table_display: {
          columns: [
            { key: 'region', label: 'Region', align: 'left', format: 'plain' },
            { key: 'sales', label: 'Sales', align: 'right', format: 'number' },
          ],
        },
      },
      'table',
    );

    expect(data).toEqual({
      fields: ['region', 'sales'],
      rows: [['east', 100]],
      col_types: ['string', 'numeric'],
      table_display: {
        columns: [
          { key: 'region', label: 'Region', align: 'left', format: 'plain' },
          { key: 'sales', label: 'Sales', align: 'right', format: 'number' },
        ],
      },
    });

    render(<QueryResultTable data={data!} />);

    expect(screen.getByRole('columnheader', { name: 'Region' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Sales' })).toHaveClass('text-right');
    expect(screen.getByText('east')).toBeInTheDocument();
    expect(screen.getByText('100.00').closest('td')).toHaveClass('text-right');
  });
});
