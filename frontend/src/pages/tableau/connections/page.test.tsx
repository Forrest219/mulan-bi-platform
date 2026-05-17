import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import TableauConnectionsPage from './page';

describe('TableauConnectionsPage Agent binding', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('submits agent_enabled with token_value and never renders MCP endpoint input', async () => {
    const requests: Array<{ url: string; init?: { method?: string; body?: unknown } }> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: { method?: string; body?: unknown }) => {
      requests.push({ url, init });
      if (url.includes('/api/tableau/connections') && (!init || init.method === undefined)) {
        return Response.json({ connections: [], total: 0 });
      }
      if (url.includes('/api/tasks/sync-schedules')) {
        return Response.json({ items: [] });
      }
      if (url.includes('/api/tableau/connections') && init?.method === 'POST') {
        return Response.json({ connection: { id: 1 }, message: 'ok' }, { status: 201 });
      }
      return Response.json({});
    }));

    render(
      <MemoryRouter>
        <TableauConnectionsPage />
      </MemoryRouter>
    );

    await screen.findByText('暂无连接，请点击右上角创建');
    await userEvent.click(screen.getByRole('button', { name: /新建连接/ }));

    expect(screen.getByText('启用 Agent 访问')).toBeInTheDocument();
    expect(screen.queryByText(/MCP HTTP Endpoint/i)).not.toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText('如: 生产-KSYUN-MCP'), 'BI Tableau');
    await userEvent.type(screen.getByPlaceholderText('https://bi.ksyun.com'), 'https://tableau.example.com');
    await userEvent.type(screen.getByPlaceholderText('mcp'), 'sales');
    await userEvent.type(screen.getByPlaceholderText('for_bi_team'), 'mulan_pat');
    await userEvent.type(screen.getByPlaceholderText('7fryZb09QYuahmH648nEqA==:...'), 'secret');
    await userEvent.click(screen.getByText('启用 Agent 访问'));
    await userEvent.click(screen.getByRole('button', { name: '创建' }));

    await waitFor(() => {
      const post = requests.find(item => item.init?.method === 'POST');
      expect(post).toBeTruthy();
      const body = JSON.parse(String(post?.init?.body));
      expect(body.agent_enabled).toBe(true);
      expect(body.token_value).toBe('secret');
      expect(body.token_secret).toBeUndefined();
    });
  });

  it('shows Agent binding status on connection cards', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({
      connections: [{
        id: 1,
        name: 'BI Tableau',
        server_url: 'https://tableau.example.com',
        site: 'sales',
        api_version: '3.21',
        connection_type: 'mcp',
        token_name: 'pat',
        owner_id: 1,
        is_active: true,
        auto_sync_enabled: false,
        sync_interval_hours: 24,
        schedule_id: null,
        last_test_at: null,
        last_test_success: true,
        last_test_message: null,
        last_sync_at: null,
        last_sync_duration_sec: null,
        sync_status: 'idle',
        next_sync_at: null,
        created_at: '2026-05-17 00:00:00',
        updated_at: '2026-05-17 00:00:00',
        mcp_binding: {
          mcp_server_id: 9,
          server_url: 'http://gateway.local/mcp',
          binding_status: 'bound',
          health_status: 'healthy',
          last_error: null,
        },
      }],
      total: 1,
    })));

    render(
      <MemoryRouter>
        <TableauConnectionsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('Agent 已启用')).toBeInTheDocument();
    expect(screen.getByText('Agent 状态:')).toBeInTheDocument();
    expect(screen.getByText('可用')).toBeInTheDocument();
  });

  it('explains unbound Agent status without asking users to bind manually', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({
      connections: [{
        id: 1,
        name: 'BI Tableau',
        server_url: 'https://tableau.example.com',
        site: 'sales',
        api_version: '3.21',
        connection_type: 'mcp',
        token_name: 'pat',
        owner_id: 1,
        is_active: true,
        auto_sync_enabled: false,
        sync_interval_hours: 24,
        schedule_id: null,
        last_test_at: null,
        last_test_success: true,
        last_test_message: null,
        last_sync_at: null,
        last_sync_duration_sec: null,
        sync_status: 'idle',
        next_sync_at: null,
        created_at: '2026-05-17 00:00:00',
        updated_at: '2026-05-17 00:00:00',
        agent_enabled: true,
        mcp_binding: {
          mcp_server_id: null,
          server_url: null,
          binding_status: 'unbound',
          health_status: 'unknown',
          last_error: 'TABLEAU_MCP_GATEWAY_URL is not configured',
        },
      }],
      total: 1,
    })));

    render(
      <MemoryRouter>
        <TableauConnectionsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('Agent 待配置')).toBeInTheDocument();
    expect(screen.queryByText('Agent 未绑定')).not.toBeInTheDocument();
    expect(screen.getByText('Agent 状态:')).toBeInTheDocument();
    expect(screen.getByText('管理员需配置 TABLEAU_MCP_GATEWAY_URL')).toBeInTheDocument();
  });

  it('treats unhealthy Agent binding as a saved connection, not a save failure', async () => {
    const requests: Array<{ url: string; init?: { method?: string; body?: unknown } }> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: { method?: string; body?: unknown }) => {
      requests.push({ url, init });
      if (url.includes('/api/tableau/connections') && (!init || init.method === undefined)) {
        return Response.json({ connections: [], total: 0 });
      }
      if (url.includes('/api/tasks/sync-schedules')) {
        return Response.json({ items: [] });
      }
      if (url.includes('/api/tableau/connections') && init?.method === 'POST') {
        return Response.json({
          connection: {
            id: 1,
            mcp_binding: {
              mcp_server_id: 9,
              server_url: 'http://gateway.local/mcp',
              binding_status: 'unhealthy',
              health_status: 'unhealthy',
              last_error: 'TABLEAU_MCP_GATEWAY_URL health check failed: HTTP 503',
            },
          },
          message: 'ok',
        }, { status: 201 });
      }
      return Response.json({});
    }));

    render(
      <MemoryRouter>
        <TableauConnectionsPage />
      </MemoryRouter>
    );

    await screen.findByText('暂无连接，请点击右上角创建');
    await userEvent.click(screen.getByRole('button', { name: /新建连接/ }));
    await userEvent.type(screen.getByPlaceholderText('如: 生产-KSYUN-MCP'), 'BI Tableau');
    await userEvent.type(screen.getByPlaceholderText('https://bi.ksyun.com'), 'https://tableau.example.com');
    await userEvent.type(screen.getByPlaceholderText('mcp'), 'sales');
    await userEvent.type(screen.getByPlaceholderText('for_bi_team'), 'mulan_pat');
    await userEvent.type(screen.getByPlaceholderText('7fryZb09QYuahmH648nEqA==:...'), 'secret');
    await userEvent.click(screen.getByText('启用 Agent 访问'));
    await userEvent.click(screen.getByRole('button', { name: '创建' }));

    expect(await screen.findByText('操作成功')).toBeInTheDocument();
    expect(screen.getByText(/Agent 绑定异常/)).toBeInTheDocument();
    expect(screen.queryByText('操作失败')).not.toBeInTheDocument();
    await waitFor(() => expect(requests.some(item => item.init?.method === 'POST')).toBe(true));
  });
});
