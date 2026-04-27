import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import MetricsPage from '../../src/pages/data-governance/metrics/page';
import * as metricsApi from '../../src/api/metrics';
import * as datasourcesApi from '../../src/api/datasources';

vi.mock('../../src/api/metrics');
vi.mock('../../src/api/datasources');
vi.mock('../../src/context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 1, role: 'analyst' },
    isDataAdmin: false,
    isAdmin: false,
    isAnalyst: true,
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
    vi.mocked(metricsApi.listMetrics).mockResolvedValue(mockMetricsResponse);
    vi.mocked(datasourcesApi.listDataSources).mockResolvedValue({
      datasources: [],
    });
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
});
