import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import MetricsPage from './page';
import MetricDetailPage from './detail';
import * as metricsApi from '../../../api/metrics';
import * as tableauApi from '../../../api/tableau';

const hoisted = vi.hoisted(() => ({
  authState: {
    user: { id: 1, role: 'analyst' },
    isDataAdmin: false,
    isAdmin: false,
    isAnalyst: true,
  },
}));

vi.mock('../../../api/metrics');
vi.mock('../../../api/tableau');
vi.mock('../../../context/AuthContext', () => ({
  useAuth: () => ({
    ...hoisted.authState,
    hasPermission: () => false,
    loading: false,
    logout: vi.fn(),
  }),
}));
vi.mock('../../agents/help-agent/helpAgentContext', () => ({
  useHelpAgentSelection: vi.fn(),
}));

const emptyMetricsResponse = {
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  pages: 1,
};

const metricWithBindings: metricsApi.MetricItem = {
  id: 'metric-1',
  name: 'gmv',
  name_zh: '商品交易总额',
  metric_type: 'atomic',
  business_domain: 'commerce',
  is_active: false,
  lineage_status: 'unknown',
  sensitivity_level: 'internal',
  datasource_id: null,
  formula: 'SUM([销售额])',
  aggregation_type: 'SUM',
  result_type: 'float',
  unit: '元',
  precision: 2,
  bindings: [
    {
      tableau_connection_id: 11,
      tableau_asset_id: 101,
      tableau_datasource_luid: 'primary-ds-luid',
      field_mappings: { value: '销售额' },
      is_primary: true,
      is_active: true,
    },
    {
      tableau_connection_id: 12,
      tableau_asset_id: 102,
      tableau_datasource_luid: 'secondary-ds-luid',
      field_mappings: { value: '净销售额' },
      is_primary: false,
      is_active: true,
    },
  ],
  primary_binding: {
    tableau_connection_id: 11,
    tableau_asset_id: 101,
    tableau_datasource_luid: 'primary-ds-luid',
    field_mappings: { value: '销售额' },
    is_primary: true,
    is_active: true,
  },
  created_at: '2026-04-21T10:00:00Z',
  updated_at: '2026-04-21T10:00:00Z',
};

function mockTableauResources() {
  vi.mocked(tableauApi.listConnections).mockResolvedValue({
    total: 1,
    connections: [{
      id: 11,
      name: 'Tableau Prod',
      server_url: 'https://tableau.example.com',
      site: '',
      api_version: '3.21',
      connection_type: 'tsc',
      token_name: 'pat',
      owner_id: 1,
      is_active: true,
      auto_sync_enabled: false,
      sync_interval_hours: 24,
      schedule_id: null,
      last_test_at: null,
      last_test_success: null,
      last_test_message: null,
      last_sync_at: null,
      last_sync_duration_sec: null,
      sync_status: 'idle',
      next_sync_at: null,
      created_at: '2026-04-21T10:00:00Z',
      updated_at: '2026-04-21T10:00:00Z',
    }],
  });
  vi.mocked(tableauApi.listAssets).mockResolvedValue({
    assets: [{
      id: 101,
      connection_id: 11,
      asset_type: 'datasource',
      tableau_id: 'ds-luid-101',
      name: 'Sales Datasource',
      project_name: null,
      description: null,
      owner_name: null,
      thumbnail_url: null,
      content_url: null,
      is_deleted: false,
      synced_at: '2026-04-21T10:00:00Z',
      parent_workbook_id: null,
      parent_workbook_name: null,
      tags: null,
      sheet_type: null,
      created_on_server: null,
      updated_on_server: null,
      view_count: null,
      ai_summary: null,
      ai_summary_generated_at: null,
      ai_explain: null,
      ai_explain_at: null,
      health_score: null,
      field_count: 1,
      is_certified: null,
    }],
    total: 1,
    page: 1,
    page_size: 100,
    pages: 1,
  });
  vi.mocked(tableauApi.getDatasourceMetadata).mockResolvedValue({
    datasource_luid: 'ds-luid-101',
    fields: [{ caption: '销售额', name: 'sales_amount' }],
  });
}

describe('MetricsPage multi Tableau bindings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.authState.user = { id: 1, role: 'analyst' };
    hoisted.authState.isDataAdmin = false;
    hoisted.authState.isAdmin = false;
    hoisted.authState.isAnalyst = true;
    vi.mocked(metricsApi.listMetrics).mockResolvedValue({
      ...emptyMetricsResponse,
      items: [metricWithBindings],
      total: 1,
    });
    vi.mocked(metricsApi.createMetric).mockResolvedValue(metricWithBindings);
    mockTableauResources();
  });

  it('列表展示 primary datasource 和 active binding 数', async () => {
    render(<MemoryRouter><MetricsPage /></MemoryRouter>);

    await expect(screen.findByText('Tableau primary-')).resolves.toBeInTheDocument();
    expect(screen.getByText('2 个 binding')).toBeInTheDocument();
  });

  it('新建原子指标提交 bindings[]，兼容字段仍来自 primary binding', async () => {
    hoisted.authState.user = { id: 1, role: 'data_admin' };
    hoisted.authState.isDataAdmin = true;
    hoisted.authState.isAnalyst = false;
    vi.mocked(metricsApi.listMetrics).mockResolvedValue(emptyMetricsResponse);
    const user = userEvent.setup();

    render(<MemoryRouter><MetricsPage /></MemoryRouter>);
    await user.click(await screen.findByRole('button', { name: /新建指标/ }));
    await user.type(screen.getByPlaceholderText('如 商品交易总额'), '商品交易总额');
    await user.type(screen.getByPlaceholderText('可选，如 gmv'), 'gmv_new');
    await user.selectOptions(screen.getByDisplayValue('请选择 Tableau 连接'), '11');
    await waitFor(() => expect(tableauApi.listAssets).toHaveBeenCalledWith(expect.objectContaining({ connection_id: 11 })));
    await user.selectOptions(await screen.findByDisplayValue('请选择数据源资产'), '101');
    await waitFor(() => expect(tableauApi.getDatasourceMetadata).toHaveBeenCalledWith(101));
    await user.selectOptions(await screen.findByDisplayValue('请选择字段'), '销售额');
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => expect(metricsApi.createMetric).toHaveBeenCalled());
    expect(metricsApi.createMetric).toHaveBeenCalledWith(expect.objectContaining({
      tableau_connection_id: 11,
      tableau_asset_id: 101,
      tableau_datasource_luid: 'ds-luid-101',
      field_mappings: { value: '销售额' },
      bindings: [
        expect.objectContaining({
          tableau_connection_id: 11,
          tableau_asset_id: 101,
          tableau_datasource_luid: 'ds-luid-101',
          field_mappings: { value: '销售额' },
          is_primary: true,
          is_active: true,
        }),
      ],
    }));
  });

  it('新建表单可以添加第二个 binding 并选择 primary', async () => {
    hoisted.authState.user = { id: 1, role: 'data_admin' };
    hoisted.authState.isDataAdmin = true;
    hoisted.authState.isAnalyst = false;
    vi.mocked(metricsApi.listMetrics).mockResolvedValue(emptyMetricsResponse);
    const user = userEvent.setup();

    render(<MemoryRouter><MetricsPage /></MemoryRouter>);
    await user.click(await screen.findByRole('button', { name: /新建指标/ }));
    await user.click(screen.getByRole('button', { name: '添加 binding' }));
    expect(screen.getByText('Binding 2')).toBeInTheDocument();

    const primaryOptions = screen.getAllByLabelText('Primary') as HTMLInputElement[];
    await user.click(primaryOptions[1]);
    expect(primaryOptions[1]).toBeChecked();
    expect(primaryOptions[0]).not.toBeChecked();
    expect(screen.getAllByLabelText('Active')).toHaveLength(2);
  });

  it('详情页展示所有 active Tableau binding', async () => {
    vi.mocked(metricsApi.getMetricDetail).mockResolvedValue({
      ...metricWithBindings,
      tenant_id: 'tenant-1',
      business_domain: 'commerce',
      description: null,
      formula: 'SUM([销售额])',
      formula_template: null,
      aggregation_type: 'SUM',
      result_type: 'float',
      unit: '元',
      datasource_id: null,
      table_name: null,
      column_name: null,
      filters: null,
      dependencies: [],
      queryable: true,
      created_by: 1,
      reviewed_by: null,
      reviewed_at: null,
      published_at: null,
    });

    render(
      <MemoryRouter initialEntries={['/governance/metrics/metric-1']}>
        <Routes>
          <Route path="/governance/metrics/:id" element={<MetricDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getAllByText('primary-ds-luid').length).toBeGreaterThan(0));
    expect(screen.getByText('secondary-ds-luid')).toBeInTheDocument();
    expect(screen.getByText('Active Binding 数')).toBeInTheDocument();
  });
});
