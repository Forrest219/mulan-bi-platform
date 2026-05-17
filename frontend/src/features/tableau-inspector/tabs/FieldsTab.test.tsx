import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { FieldsTab } from './FieldsTab';

describe('FieldsTab queryability status', () => {
  it('shows queryability summary, badges, and MCP error text', () => {
    render(
      <FieldsTab
        fieldsLoading={false}
        fieldMetadata={{
          catalog_field_count: 32,
          queryable_field_count: 11,
          catalog_only_count: 21,
          mcp_status: 'error',
          mcp_last_error: 'metadata unavailable',
          mcp_checked_at: '2026-05-17T07:06:00Z',
        }}
        fieldSemantics={[
          {
            field: '订单日期',
            data_type: 'DATE',
            role: 'dimension',
            queryability_status: 'catalog_only',
          },
          {
            field: '销售额',
            data_type: 'REAL',
            role: 'measure',
            queryability_status: 'queryable',
          },
          {
            field: '客户 Id',
            data_type: 'STRING',
            role: 'dimension',
            queryability_status: 'error',
            mcp_last_error: 'metadata unavailable',
          },
        ]}
      />
    );

    expect(screen.getByText('资产字段 32')).toBeInTheDocument();
    expect(screen.getByText('Agent 可查询 11')).toBeInTheDocument();
    expect(screen.getByText('仅资产目录 21')).toBeInTheDocument();
    expect(screen.getByText('metadata unavailable')).toBeInTheDocument();
    expect(screen.getAllByText('仅资产目录').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Agent 可查询').length).toBeGreaterThan(0);
    expect(screen.getAllByText('MCP 异常').length).toBeGreaterThan(0);
  });

  it('renders partial MCP status separately from cache status', () => {
    render(
      <FieldsTab
        fieldsLoading={false}
        fieldMetadata={{
          catalog_field_count: 32,
          queryable_field_count: 11,
          catalog_only_count: 21,
          cache_status: 'cached',
          mcp_status: 'partial',
          mcp_checked_at: '2026-05-17T07:06:00Z',
        }}
        fieldSemantics={[
          {
            field: '订单日期',
            data_type: 'DATE',
            role: 'dimension',
            queryability_status: 'catalog_only',
          },
          {
            field: '销售额',
            data_type: 'REAL',
            role: 'measure',
            queryability_status: 'queryable',
          },
        ]}
      />
    );

    expect(screen.getByText('缓存状态 缓存命中')).toBeInTheDocument();
    expect(screen.getByText('MCP 状态 部分可查询')).toBeInTheDocument();
    expect(screen.queryByText('MCP 状态 缓存命中')).not.toBeInTheDocument();
  });
});
