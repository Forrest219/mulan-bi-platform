import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import MessageBubble from './MessageBubble';

describe('MessageBubble markdown asset lists', () => {
  it('renders a single-item markdown list as an asset card', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content={'#### default（1）\n- [订单+ (示例 - 超市)](https://online.tableau.com/#/site/zy_bi/datasources/8902076)'}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('订单+ (示例 - 超市)')).toBeInTheDocument();
    expect(screen.getByText('查看')).toBeInTheDocument();
  });
});

describe('MessageBubble structured agent responses', () => {
  it('renders datasource inventory candidates as a structured list', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="当前连接的数据源清单，共 2 个：管理费用、销售明细。"
          responseType="asset_candidates"
          responseData={{
            source: 'catalog_cache',
            reason: 'list_datasources',
            total_count: 2,
            shown_count: 2,
            candidates: [
              { datasource_luid: 'ds-1', name: '管理费用', project_name: '财务', field_count: 12, synced_at: '2026-05-20T06:00:00Z' },
              { datasource_luid: 'ds-2', name: '销售明细', project_name: '销售', field_count: 20 },
            ],
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('数据源清单')).toBeInTheDocument();
    expect(screen.getByText('共 2 个')).toBeInTheDocument();
    expect(screen.getByText('Catalog cache 缓存')).toBeInTheDocument();
    expect(screen.getByText('管理费用')).toBeInTheDocument();
    expect(screen.getByText('销售明细')).toBeInTheDocument();
    expect(screen.queryByText(/管理费用、销售明细/)).not.toBeInTheDocument();
  });

  it('renders ambiguous asset candidates as clarification choices', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="找到多个可能的数据源：管理费用月表、管理费用明细。请指定其中一个后继续。"
          responseType="asset_candidates"
          responseData={{
            source: 'catalog_cache',
            reason: 'ambiguous',
            candidates: [
              { datasource_luid: 'ds-1', name: '管理费用月表', project_name: '财务' },
              { datasource_luid: 'ds-2', name: '管理费用明细', project_name: '财务' },
            ],
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('请指定一个数据源')).toBeInTheDocument();
    expect(screen.getByText('管理费用月表')).toBeInTheDocument();
    expect(screen.getByText('管理费用明细')).toBeInTheDocument();
    expect(screen.queryByText('数据源清单')).not.toBeInTheDocument();
  });

  it('renders clarification response candidates without markdown fallback text', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="请在候选数据源中选择一个：销售明细、销售汇总。"
          responseType="clarification"
          responseData={{
            message: '找到多个可能的数据源，请指定其中一个后继续。',
            candidates: [
              { datasource_luid: 'ds-sales-detail', name: '销售明细', project_name: '销售', field_count: 18 },
              { datasource_luid: 'ds-sales-summary', name: '销售汇总', project_name: '销售', field_count: 9 },
            ],
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('请指定一个数据源')).toBeInTheDocument();
    expect(screen.getByText('销售明细')).toBeInTheDocument();
    expect(screen.getByText('销售汇总')).toBeInTheDocument();
    expect(screen.queryByText(/请在候选数据源中选择一个/)).not.toBeInTheDocument();
  });

  it('renders cached asset metadata with a visible cache notice', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="Tableau MCP metadata 暂不可用，以下是基于本地 catalog cache 的缓存元数据。"
          responseType="asset_metadata"
          responseData={{
            source: 'catalog_cache',
            datasource_name: '管理费用',
            project_name: '财务',
            field_count: 2,
            metadata_freshness: '2026-05-20T06:00:00Z',
            fields: [
              { name: 'amount', caption: '金额', data_type: 'number' },
              { name: 'department', caption: '部门', data_type: 'string' },
            ],
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('管理费用')).toBeInTheDocument();
    expect(screen.getByText('财务 · 2 个字段')).toBeInTheDocument();
    expect(screen.getByText(/本地 catalog cache 缓存/)).toBeInTheDocument();
    expect(screen.getByText('金额')).toBeInTheDocument();
    expect(screen.getByText('部门')).toBeInTheDocument();
  });

  it('renders asset metadata field groups before fallback fields and shows analysis suggestions', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="已通过 Tableau MCP 读取数据源元数据。"
          responseType="asset_metadata"
          responseData={{
            source: 'mcp',
            datasource_name: '销售明细',
            project_name: '销售',
            field_count: 3,
            metadata_quality: {
              status: 'partial',
              message: '已解析 2 个字段，与元数据声明的 3 个字段不一致。',
            },
            field_groups: [
              {
                label: '指标字段',
                fields: [
                  { name: 'gmv', caption: 'GMV', dataType: 'REAL', description: '成交金额' },
                  { name: 'order_date', caption: '下单日期', dataType: 'DATE' },
                ],
              },
            ],
            fields: [
              { name: 'legacy_field', caption: '旧字段', data_type: 'string' },
            ],
            analysis_suggestions: [
              {
                title: '成交趋势',
                fields: ['GMV', '下单日期'],
                question: '最近 30 天 GMV 趋势如何？',
              },
            ],
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('指标字段')).toBeInTheDocument();
    expect(screen.getAllByText('GMV').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('下单日期').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('旧字段')).not.toBeInTheDocument();
    expect(screen.getByText(/元数据质量：部分字段信息不完整/)).toBeInTheDocument();
    expect(screen.getByText('分析建议')).toBeInTheDocument();
    expect(screen.getByText('成交趋势')).toBeInTheDocument();
    expect(screen.getByText('最近 30 天 GMV 趋势如何？')).toBeInTheDocument();
  });

  it('renders an empty metadata quality hint when no fields are available', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="未获取到字段。"
          responseType="asset_metadata"
          responseData={{
            source: 'mcp',
            datasource_name: '空数据源',
            project_name: '默认',
            field_count: 0,
            metadata_quality: 'empty',
            field_groups: [],
            fields: [],
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('空数据源')).toBeInTheDocument();
    expect(screen.getByText(/元数据质量：当前未获取到可展示字段/)).toBeInTheDocument();
    expect(screen.getByText('当前没有可展示的字段。')).toBeInTheDocument();
  });

  it('renders query_result response data as a table when no table_data event was emitted', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="查询已完成，返回 1 行结果。"
          responseType="query_result"
          responseData={{
            fields: ['指标', '数值'],
            rows: [['收入', 123]],
            table_display: {
              columns: [
                { key: '指标', label: '指标' },
                { key: '数值', label: '数值', value_type: 'number', align: 'right' },
              ],
            },
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('查询已完成，返回 1 行结果。')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /指标/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /数值/ })).toBeInTheDocument();
    expect(screen.getByText('收入')).toBeInTheDocument();
    expect(screen.getByText('123.00')).toBeInTheDocument();
  });

  it('uses query_result table_display columns as the field display contract', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="查询已完成。"
          responseType="query_result"
          responseData={{
            fields: ['department', 'total_amount'],
            rows: [['财务部', 4500]],
            table_display: {
              columns: [
                { key: 'department', label: '部门' },
                { key: 'total_amount', label: '总金额', value_type: 'number', align: 'right' },
              ],
            },
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole('columnheader', { name: /部门/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /总金额/ })).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /department/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /total_amount/ })).not.toBeInTheDocument();
    expect(screen.getByText('财务部')).toBeInTheDocument();
    expect(screen.getByText('4,500.00')).toBeInTheDocument();
  });

  it('renders derived query_result columns from a previous result transform', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="查询已完成，返回派生列结果。"
          responseType="query_result"
          responseData={{
            source: 'previous_result_transform',
            transformations: [
              { type: 'period_comparison', base_metric: 'amount' },
            ],
            fields: ['period', 'metric', '环比金额', '环比金额变化率'],
            rows: [['2026-04', '收入', 128000, 0.1234]],
            col_types: ['string', 'string', 'numeric', 'numeric'],
            table_display: {
              columns: [
                { key: 'period', label: 'period' },
                { key: 'metric', label: 'metric' },
                { key: '环比金额', label: '环比金额', value_type: 'number', align: 'right' },
                { key: '环比金额变化率', label: '环比金额变化率', value_type: 'percent', align: 'right' },
              ],
            },
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole('columnheader', { name: /period/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /metric/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /^环比金额$/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /^环比金额变化率$/ })).toBeInTheDocument();
    expect(screen.getByText('2026-04')).toBeInTheDocument();
    expect(screen.getByText('收入')).toBeInTheDocument();
    expect(screen.getByText('128,000.00')).toBeInTheDocument();
    expect(screen.getByText('12.34%')).toBeInTheDocument();
    expect(screen.queryByText('previous_result_transform')).not.toBeInTheDocument();
    expect(screen.queryByText('period_comparison')).not.toBeInTheDocument();
    expect(screen.queryByText(/工具暂不可用|未找到匹配资产|出现错误/)).not.toBeInTheDocument();
  });

  it('renders tool_unavailable as a structured failure instead of a successful result', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="查询完成，返回 0 行。"
          responseType="tool_unavailable"
          responseData={{
            message: 'Tableau MCP 工具暂不可用',
            user_hint: '请稍后重试或联系管理员检查 MCP Gateway。',
            tool_name: 'query-datasource',
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('Tableau MCP 工具暂不可用')).toBeInTheDocument();
    expect(screen.getByText('请稍后重试或联系管理员检查 MCP Gateway。')).toBeInTheDocument();
    expect(screen.queryByText(/查询完成/)).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
