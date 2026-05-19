import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import MetricsPage from '../../src/pages/data-governance/metrics/page';
import * as metricsApi from '../../src/api/metrics';
import * as tableauApi from '../../src/api/tableau';

vi.mock('../../src/api/metrics');
vi.mock('../../src/api/tableau');

const hoisted = vi.hoisted(() => ({
  authState: {
    user: { id: 1, role: 'analyst' },
    isDataAdmin: false,
    isAdmin: false,
    isAnalyst: true,
  },
}));

vi.mock('../../src/context/AuthContext', () => ({
  useAuth: () => ({
    ...hoisted.authState,
    hasPermission: () => false,
    loading: false,
    logout: vi.fn(),
  }),
}));

const mockMetricsResponse: metricsApi.MetricsListResponse = {
  items: [
    {
      id: '1',
      name: 'gmv',
      name_zh: '商品交易总额',
      metric_type: 'atomic',
      business_domain: 'commerce',
      is_active: false,
      lineage_status: 'unknown',
      sensitivity_level: 'internal',
      datasource_id: 1,
      table_name: 'orders',
      column_name: 'order_amount',
      formula: 'SUM(order_amount)',
      aggregation_type: 'SUM',
      result_type: 'float',
      unit: '元',
      precision: 2,
      bindings: [
        {
          tableau_connection_id: 2,
          tableau_datasource_luid: 'primary-ds-luid',
          field_mappings: { value: '销售额' },
          is_primary: true,
          is_active: true,
        },
        {
          tableau_connection_id: 3,
          tableau_datasource_luid: 'secondary-ds-luid',
          field_mappings: { value: '净销售额' },
          is_primary: false,
          is_active: true,
        },
      ],
      primary_binding: {
        tableau_connection_id: 2,
        tableau_datasource_luid: 'primary-ds-luid',
        field_mappings: { value: '销售额' },
        is_primary: true,
        is_active: true,
      },
      created_at: '2026-04-21T10:00:00Z',
      updated_at: '2026-04-21T10:00:00Z',
    },
    {
      id: '2',
      name: 'order_count',
      name_zh: '订单数',
      metric_type: 'atomic',
      business_domain: 'commerce',
      is_active: true,
      lineage_status: 'resolved',
      sensitivity_level: 'public',
      datasource_id: 2,
      table_name: 'orders',
      column_name: 'id',
      formula: 'COUNT(id)',
      aggregation_type: 'COUNT',
      result_type: 'integer',
      unit: '笔',
      precision: 0,
      created_at: '2026-04-20T10:00:00Z',
      updated_at: '2026-04-20T10:00:00Z',
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
  pages: 1,
};

describe('MetricsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.authState.user = { id: 1, role: 'analyst' };
    hoisted.authState.isDataAdmin = false;
    hoisted.authState.isAdmin = false;
    hoisted.authState.isAnalyst = true;
    vi.mocked(metricsApi.listMetrics).mockResolvedValue(mockMetricsResponse);
    vi.mocked(metricsApi.createMetric).mockResolvedValue(mockMetricsResponse.items[0]);
    vi.mocked(tableauApi.listConnections).mockResolvedValue({ connections: [], total: 0 });
    vi.mocked(tableauApi.listAssets).mockResolvedValue({
      assets: [],
      total: 0,
      page: 1,
      page_size: 100,
      pages: 1,
    });
    vi.mocked(tableauApi.getDatasourceMetadata).mockResolvedValue({ fields: [] });
  });

  // ── Test 1: 列表渲染 ──
  it('列表渲染: 表格中出现 "gmv" 和 "order_count" 两个指标名', async () => {
    render(<MemoryRouter><MetricsPage /></MemoryRouter>);
    await expect(screen.findByText('gmv')).resolves.toBeInTheDocument();
    expect(screen.getByText('order_count')).toBeInTheDocument();
  });

  // ── Test 2: 搜索过滤 ──
  it('搜索过滤: 在搜索框输入 "gmv"，fetch 被调用时 URL 包含 search=gmv', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><MetricsPage /></MemoryRouter>);
    await screen.findByText('gmv');

    const searchInput = screen.getByPlaceholderText('搜索指标名或中文名');
    await user.clear(searchInput);
    await user.type(searchInput, 'gmv');

    expect(metricsApi.listMetrics).toHaveBeenLastCalledWith(
      expect.objectContaining({ search: 'gmv' }),
    );
  });

  // ── Test 3: 新建按钮权限 ──
  it('新建按钮权限: analyst 角色新建指标按钮不存在', async () => {
    render(<MemoryRouter><MetricsPage /></MemoryRouter>);
    await screen.findByText('gmv');

    // 新建按钮应该不存在（isDataAdmin=false 时隐藏）
    expect(screen.queryByRole('button', { name: /新建指标/ })).not.toBeInTheDocument();
  });

  it('列表展示 active binding 数和 primary Tableau datasource', async () => {
    render(<MemoryRouter><MetricsPage /></MemoryRouter>);

    await expect(screen.findByText('Tableau primary-')).resolves.toBeInTheDocument();
    expect(screen.getByText('2 个 binding')).toBeInTheDocument();
  });

  it('新建原子指标提交 bindings[]，兼容字段来自 primary binding', async () => {
    hoisted.authState.user = { id: 1, role: 'data_admin' };
    hoisted.authState.isDataAdmin = true;
    hoisted.authState.isAdmin = false;
    hoisted.authState.isAnalyst = false;
    vi.mocked(metricsApi.listMetrics).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      pages: 1,
    });
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
      name: 'gmv_new',
      name_zh: '商品交易总额',
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
});
