import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import McpConfigsPage from './page';

vi.mock('../../../context/AuthContext', () => ({
  useAuth: () => ({
    isAdmin: true,
  }),
}));

describe('McpConfigsPage Tableau binding source', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('shows Tableau MCP source connection', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/api/mcp-configs/')) {
        return Response.json([{
          id: 9,
          name: 'BI Tableau Agent',
          type: 'tableau',
          server_url: 'http://gateway.local/mcp',
          description: null,
          is_active: true,
          credentials: {},
          tableau_connection_id: 1,
          tableau_connection_name: 'BI Tableau',
          binding_source: 'auto_tableau_connection',
          binding_status: 'bound',
          last_binding_error: null,
          created_at: '2026-05-17 00:00:00',
          updated_at: '2026-05-17 00:00:00',
        }]);
      }
      if (url.includes('/api/tableau/connections')) {
        return Response.json({
          connections: [{ id: 1, name: 'BI Tableau', server_url: 'https://tableau.example.com', site: 'sales', is_active: true }],
          total: 1,
        });
      }
      if (url.includes('/api/admin/query/connected-app')) {
        return Response.json({ configured: false, connection_id: 1, client_id: null, secret_masked: null, is_active: null, created_at: null });
      }
      return Response.json({});
    }));

    render(<McpConfigsPage headerless />);

    expect(await screen.findByText('BI Tableau Agent')).toBeInTheDocument();
    expect(screen.getByText(/来源 Tableau 连接：BI Tableau/)).toBeInTheDocument();
  });

  it('hides the Tableau MCP HTTP endpoint input in default mode', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/api/mcp-configs/')) {
        return Response.json([]);
      }
      if (url.includes('/api/tableau/connections')) {
        return Response.json({
          connections: [{ id: 1, name: 'BI Tableau', server_url: 'https://tableau.example.com', site: 'sales', is_active: true }],
          total: 1,
        });
      }
      if (url.includes('/api/admin/query/connected-app')) {
        return Response.json({ configured: false, connection_id: 1, client_id: null, secret_masked: null, is_active: null, created_at: null });
      }
      return Response.json({});
    }));

    render(<McpConfigsPage headerless />);

    await screen.findByText('暂无 MCP 配置');
    await userEvent.click(screen.getByRole('button', { name: '添加第一个配置' }));

    expect(await screen.findByText(/来源 Tableau 连接/)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('http://localhost:3927/tableau-mcp')).not.toBeInTheDocument();
    expect(screen.getByText('Tableau URL / Site / PAT 请在数据连接入口维护；此处只绑定 Agent 工具配置。')).toBeInTheDocument();
  });

  it('keeps non-Tableau endpoint editing available', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/api/mcp-configs/')) {
        return Response.json([]);
      }
      if (url.includes('/api/tableau/connections')) {
        return Response.json({ connections: [], total: 0 });
      }
      return Response.json({});
    }));

    render(<McpConfigsPage headerless />);

    await screen.findByText('暂无 MCP 配置');
    await userEvent.click(screen.getByRole('button', { name: '添加第一个配置' }));
    await userEvent.selectOptions(screen.getByDisplayValue('Tableau'), 'starrocks');

    const endpointInput = screen.getByPlaceholderText('http://localhost:3928/starrocks-mcp');
    await userEvent.type(endpointInput, 'http://localhost:3928/starrocks-mcp');

    expect(endpointInput).toHaveValue('http://localhost:3928/starrocks-mcp');
    expect(screen.getByText('StarRocks 连接')).toBeInTheDocument();
  });
});
