/**
 * @vitest-environment jsdom
 *
 * 单元测试：T-09 ConnectedAppPanel / ConnectedAppSection 组件
 *
 * 覆盖场景：
 *   1. 未配置时展示「未配置」状态徽标
 *   2. 已配置时展示 client_id，secret 显示 "***"
 *   3. 点击保存调用 PUT API
 *   4. 点击停用弹出二次确认，确认后调用 DELETE
 *   5. API 失败时展示 toast 错误提示
 *
 * 策略：
 *   - 全局 mock fetch，按场景控制返回值
 *   - mock AuthContext，默认以 admin 身份渲染
 *   - 通过展开折叠面板触发 GET 加载
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';

// ─── Global fetch mock ────────────────────────────────────────────────────────

const mockFetch = vi.fn();
global.fetch = mockFetch;

// ─── Mock AuthContext ─────────────────────────────────────────────────────────

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    isAdmin: true,
    user: { id: 1, username: 'admin', role: 'admin' },
  }),
}));

// ─── Mock ConfirmModal（简化为原生 dialog，专注核心行为） ──────────────────

vi.mock('@/components/ConfirmModal', () => ({
  ConfirmModal: ({ open, onConfirm, onCancel, title }: {
    open: boolean;
    onConfirm: () => void;
    onCancel: () => void;
    title: string;
  }) => {
    if (!open) return null;
    return (
      <div data-testid="confirm-modal">
        <span>{title}</span>
        <button data-testid="confirm-ok" onClick={onConfirm}>确认</button>
        <button data-testid="confirm-cancel" onClick={onCancel}>取消</button>
      </div>
    );
  },
}));

// ─── 导入被测组件（在 mock 声明之后）────────────────────────────────────────

// 动态导入避免 hoisting 陷阱；使用默认导出的整页组件
import McpConfigsPage from '@/pages/admin/mcp-configs/page';

// ─── 常量 ─────────────────────────────────────────────────────────────────────

const QUERY_ADMIN_BASE = '/api/admin/query';
const MCP_API_BASE = '/api/mcp-configs';
const TABLEAU_API = '/api/tableau/connections?include_inactive=false';

const FAKE_CONNECTION = {
  id: 1,
  name: 'Tableau Dev',
  server_url: 'http://tableau.example.com',
  site: 'default',
  is_active: true,
};

const STATUS_UNCONFIGURED = {
  configured: false,
  connection_id: null,
  client_id: null,
  secret_masked: null,
  is_active: null,
  created_at: null,
};

const STATUS_CONFIGURED = {
  configured: true,
  connection_id: 1,
  client_id: 'my-app-client-id',
  secret_masked: '***',
  is_active: true,
  created_at: '2026-04-21T10:00:00',
};

// ─── 辅助函数 ─────────────────────────────────────────────────────────────────

function makeFetchResponse(body: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

/**
 * 配置 fetch mock 并渲染 McpConfigsPage，
 * 返回 userEvent 实例供后续交互使用。
 *
 * fetch 调用顺序（页面加载时）：
 *   1. GET /api/mcp-configs/               → McpServerItem[]（空列表）
 *   2. GET /api/tableau/connections...     → { connections: [FAKE_CONNECTION] }
 */
function renderPage(overrides: Partial<{
  mcpServers: unknown[];
  connections: unknown[];
  connectedAppStatus: unknown;
}> = {}) {
  const {
    mcpServers = [],
    connections = [FAKE_CONNECTION],
    connectedAppStatus = STATUS_UNCONFIGURED,
  } = overrides;

  mockFetch.mockImplementation((url: string) => {
    if (url.includes(MCP_API_BASE)) return makeFetchResponse(mcpServers);
    if (url.includes('tableau/connections')) return makeFetchResponse({ connections });
    if (url.includes(`${QUERY_ADMIN_BASE}/connected-app`)) {
      return makeFetchResponse(connectedAppStatus);
    }
    return makeFetchResponse({});
  });

  const user = userEvent.setup();
  render(<McpConfigsPage />);
  return { user };
}

// ─── 测试套件 ─────────────────────────────────────────────────────────────────

describe('ConnectedAppSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('加载 Tableau 连接列表并渲染折叠面板', async () => {
    renderPage();

    // 连接名称出现在折叠面板标题
    await waitFor(() => {
      expect(screen.getByText('Tableau Dev')).toBeInTheDocument();
    });
  });

  it('无激活 Tableau 连接时显示空态提示', async () => {
    renderPage({ connections: [] });

    await waitFor(() => {
      expect(screen.getByText(/暂无激活的 Tableau 连接/)).toBeInTheDocument();
    });
  });
});

describe('ConnectedAppPanel — 未配置状态', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('展开后显示「未配置」徽标', async () => {
    const { user } = renderPage({ connectedAppStatus: STATUS_UNCONFIGURED });

    // 等待连接面板出现
    await waitFor(() => screen.getByText('Tableau Dev'));

    // 点击折叠按钮展开面板，触发 GET
    const panelButton = screen.getByRole('button', { name: /Tableau Dev/ });
    await user.click(panelButton);

    await waitFor(() => {
      expect(screen.getByText('未配置')).toBeInTheDocument();
    });
  });

  it('未配置时表单区标题为「配置密钥」', async () => {
    const { user } = renderPage({ connectedAppStatus: STATUS_UNCONFIGURED });

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    await waitFor(() => {
      expect(screen.getByText('配置密钥')).toBeInTheDocument();
    });
  });
});

describe('ConnectedAppPanel — 已配置状态', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('展开后显示「已配置」徽标', async () => {
    const { user } = renderPage({ connectedAppStatus: STATUS_CONFIGURED });

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    await waitFor(() => {
      expect(screen.getByText('已配置')).toBeInTheDocument();
    });
  });

  it('显示 client_id，secret 显示 "***" 不回显明文', async () => {
    const { user } = renderPage({ connectedAppStatus: STATUS_CONFIGURED });

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    await waitFor(() => {
      expect(screen.getByText('my-app-client-id')).toBeInTheDocument();
      expect(screen.getByText('***')).toBeInTheDocument();
    });
  });

  it('已配置时表单区标题为「更新密钥」', async () => {
    const { user } = renderPage({ connectedAppStatus: STATUS_CONFIGURED });

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    await waitFor(() => {
      expect(screen.getByText('更新密钥')).toBeInTheDocument();
    });
  });
});

describe('ConnectedAppPanel — 保存操作', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('填写表单点击保存 → 调用 PUT API', async () => {
    const putResponse = {
      ok: true,
      connection_id: 1,
      client_id: 'new-client-id',
      is_active: true,
      created_at: '2026-04-21T10:00:00',
    };

    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url.includes(MCP_API_BASE)) return makeFetchResponse([]);
      if (url.includes('tableau/connections')) return makeFetchResponse({ connections: [FAKE_CONNECTION] });
      if (url.includes(`${QUERY_ADMIN_BASE}/connected-app`)) {
        if (options?.method === 'PUT') return makeFetchResponse(putResponse);
        return makeFetchResponse(STATUS_UNCONFIGURED);
      }
      return makeFetchResponse({});
    });

    const user = userEvent.setup();
    render(<McpConfigsPage />);

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    // 等待表单展开
    await waitFor(() => screen.getByPlaceholderText(/Connected App Client ID/));

    // 填写 Client ID
    const clientIdInput = screen.getByPlaceholderText(/Connected App Client ID/);
    await user.type(clientIdInput, 'new-client-id');

    // 填写 Secret Value
    const secretInput = screen.getByPlaceholderText(/Connected App Secret Value/);
    await user.type(secretInput, 'new-secret-value');

    // 点击保存
    const saveBtn = screen.getByRole('button', { name: /保存密钥/ });
    await user.click(saveBtn);

    await waitFor(() => {
      const putCall = mockFetch.mock.calls.find(
        ([url, opts]) =>
          url.includes(`${QUERY_ADMIN_BASE}/connected-app`) && opts?.method === 'PUT',
      );
      expect(putCall).toBeDefined();
      const body = JSON.parse(putCall![1]!.body as string);
      expect(body.connection_id).toBe(1);
      expect(body.client_id).toBe('new-client-id');
      expect(body.secret_value).toBe('new-secret-value');
    });
  });

  it('Client ID 为空时不发起请求，显示表单错误', async () => {
    const { user } = renderPage({ connectedAppStatus: STATUS_UNCONFIGURED });

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    await waitFor(() => screen.getByPlaceholderText(/Connected App Secret Value/));

    // 只填 secret，不填 client_id
    const secretInput = screen.getByPlaceholderText(/Connected App Secret Value/);
    await user.type(secretInput, 'some-secret');

    const saveBtn = screen.getByRole('button', { name: /保存密钥/ });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText('Client ID 不能为空')).toBeInTheDocument();
    });

    // 确认没有 PUT 调用
    const putCalls = mockFetch.mock.calls.filter(
      ([url, opts]) =>
        url.includes(`${QUERY_ADMIN_BASE}/connected-app`) && opts?.method === 'PUT',
    );
    expect(putCalls).toHaveLength(0);
  });

  it('Secret Value 为空时不发起请求，显示表单错误', async () => {
    const { user } = renderPage({ connectedAppStatus: STATUS_UNCONFIGURED });

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    await waitFor(() => screen.getByPlaceholderText(/Connected App Client ID/));

    // 只填 client_id，不填 secret
    const clientIdInput = screen.getByPlaceholderText(/Connected App Client ID/);
    await user.type(clientIdInput, 'some-client');

    const saveBtn = screen.getByRole('button', { name: /保存密钥/ });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText('Secret Value 不能为空')).toBeInTheDocument();
    });
  });
});

describe('ConnectedAppPanel — 停用操作', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('点击停用弹出二次确认区域', async () => {
    const { user } = renderPage({ connectedAppStatus: STATUS_CONFIGURED });

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    await waitFor(() => screen.getByRole('button', { name: /停用配置/ }));

    const deactivateBtn = screen.getByRole('button', { name: /停用配置/ });
    await user.click(deactivateBtn);

    await waitFor(() => {
      // 确认二次确认区域的 span 提示文字出现
      expect(screen.getByText(/确认停用？停用后问数将无法使用 JWT 鉴权/)).toBeInTheDocument();
    });
  });

  it('取消二次确认后不调用 DELETE', async () => {
    const { user } = renderPage({ connectedAppStatus: STATUS_CONFIGURED });

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    await waitFor(() => screen.getByRole('button', { name: /停用配置/ }));
    await user.click(screen.getByRole('button', { name: /停用配置/ }));

    // 等待二次确认区域出现后点取消
    await waitFor(() => screen.getByRole('button', { name: '取消' }));
    await user.click(screen.getByRole('button', { name: '取消' }));

    await waitFor(() => {
      expect(screen.queryByText(/确认停用/)).not.toBeInTheDocument();
    });

    const deleteCalls = mockFetch.mock.calls.filter(
      ([url, opts]) =>
        url.includes(`${QUERY_ADMIN_BASE}/connected-app`) && opts?.method === 'DELETE',
    );
    expect(deleteCalls).toHaveLength(0);
  });

  it('确认停用后调用 DELETE API', async () => {
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url.includes(MCP_API_BASE)) return makeFetchResponse([]);
      if (url.includes('tableau/connections')) return makeFetchResponse({ connections: [FAKE_CONNECTION] });
      if (url.includes(`${QUERY_ADMIN_BASE}/connected-app`)) {
        if (options?.method === 'DELETE') return makeFetchResponse({ ok: true, deactivated: 1 });
        return makeFetchResponse(STATUS_CONFIGURED);
      }
      return makeFetchResponse({});
    });

    const user = userEvent.setup();
    render(<McpConfigsPage />);

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    await waitFor(() => screen.getByRole('button', { name: /停用配置/ }));
    await user.click(screen.getByRole('button', { name: /停用配置/ }));

    await waitFor(() => screen.getByRole('button', { name: '确认停用' }));
    await user.click(screen.getByRole('button', { name: '确认停用' }));

    await waitFor(() => {
      const deleteCalls = mockFetch.mock.calls.filter(
        ([url, opts]) =>
          url.includes(`${QUERY_ADMIN_BASE}/connected-app`) && opts?.method === 'DELETE',
      );
      expect(deleteCalls).toHaveLength(1);
      const [deleteUrl] = deleteCalls[0];
      expect(deleteUrl).toContain('connection_id=1');
    });
  });
});

describe('ConnectedAppPanel — API 失败处理', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('PUT API 失败时显示 toast 错误提示', async () => {
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url.includes(MCP_API_BASE)) return makeFetchResponse([]);
      if (url.includes('tableau/connections')) return makeFetchResponse({ connections: [FAKE_CONNECTION] });
      if (url.includes(`${QUERY_ADMIN_BASE}/connected-app`)) {
        if (options?.method === 'PUT') {
          return makeFetchResponse({ detail: '密钥保存失败，请稍后重试' }, false, 500);
        }
        return makeFetchResponse(STATUS_UNCONFIGURED);
      }
      return makeFetchResponse({});
    });

    const user = userEvent.setup();
    render(<McpConfigsPage />);

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    await waitFor(() => screen.getByPlaceholderText(/Connected App Client ID/));

    await user.type(screen.getByPlaceholderText(/Connected App Client ID/), 'some-client');
    await user.type(screen.getByPlaceholderText(/Connected App Secret Value/), 'some-secret');
    await user.click(screen.getByRole('button', { name: /保存密钥/ }));

    await waitFor(() => {
      expect(screen.getByText('密钥保存失败，请稍后重试')).toBeInTheDocument();
    });
  });

  it('DELETE API 失败时显示 toast 错误提示', async () => {
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url.includes(MCP_API_BASE)) return makeFetchResponse([]);
      if (url.includes('tableau/connections')) return makeFetchResponse({ connections: [FAKE_CONNECTION] });
      if (url.includes(`${QUERY_ADMIN_BASE}/connected-app`)) {
        if (options?.method === 'DELETE') {
          return makeFetchResponse({ detail: '停用操作失败，请稍后重试' }, false, 500);
        }
        return makeFetchResponse(STATUS_CONFIGURED);
      }
      return makeFetchResponse({});
    });

    const user = userEvent.setup();
    render(<McpConfigsPage />);

    await waitFor(() => screen.getByText('Tableau Dev'));
    await user.click(screen.getByRole('button', { name: /Tableau Dev/ }));

    await waitFor(() => screen.getByRole('button', { name: /停用配置/ }));
    await user.click(screen.getByRole('button', { name: /停用配置/ }));

    await waitFor(() => screen.getByRole('button', { name: '确认停用' }));
    await user.click(screen.getByRole('button', { name: '确认停用' }));

    await waitFor(() => {
      expect(screen.getByText('停用操作失败，请稍后重试')).toBeInTheDocument();
    });
  });
});
