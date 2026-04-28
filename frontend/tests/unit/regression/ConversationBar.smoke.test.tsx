// 防止回归：点击"新对话"按钮不得立即调用 addConversation（写库），只应 navigate('/')
// 防止回归：侧边栏不得展示空/无消息的"新对话"占位会话
// Bug 复现：ConversationBar 的 handleNew 曾直接调用 addConversation()，导致大量空对话堆积

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';

// ── 最小 mock：只 mock 必要的 hook ─────────────────────────────────────────────

const mockNavigate = vi.fn();
let mockConversations: Array<{
  id: string;
  title: string;
  updated_at: string;
  messages: Array<{ id: string; role: 'user' | 'assistant'; content: string; created_at: string }>;
  message_count?: number;
}> = [];

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockAddConversation = vi.fn();

vi.mock('../../../src/store/conversationStore', () => ({
  useConversations: () => ({
    conversations: mockConversations,
    isLoading: false,
    addConversation: mockAddConversation,
    appendMessage: vi.fn(),
    deleteConversation: vi.fn(),
    updateConversationTitle: vi.fn(),
  }),
}));

vi.mock('../../../src/context/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 1,
      username: 'test',
      display_name: '测试用户',
      role: 'user',
      permissions: [],
      is_active: true,
      email: null,
      created_at: '',
      last_login: null,
    },
    loading: false,
    logout: vi.fn(),
  }),
}));

vi.mock('../../../src/config', () => ({
  LOGO_URL: '/logo.png',
  API_BASE: '',
}));

vi.mock('../../../src/context/PlatformSettingsContext', () => ({
  usePlatformSettings: () => ({
    settings: {
      platform_name: '木兰 BI 平台',
    },
  }),
}));

// ── import 组件（必须在 vi.mock 之后）─────────────────────────────────────────

import { ConversationBar } from '../../../src/pages/home/components/ConversationBar';

// ── Tests ─────────────────────────────────────────────────────────────────────

// 防止回归：侧边栏头部禁止出现 Logo 图标和折叠按钮（已被修复 3+ 次，永久锁定）
describe('ConversationBar 回归：头部不含 Logo 和折叠按钮', () => {
  it('头部不渲染任何 <img> 元素（无 Logo）', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <ConversationBar collapsed={false} onToggleCollapse={vi.fn()} />
      </MemoryRouter>
    );
    expect(document.querySelector('img')).toBeNull();
  });

  it('头部不渲染折叠按钮（aria-label="折叠侧边栏"）', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <ConversationBar collapsed={false} onToggleCollapse={vi.fn()} />
      </MemoryRouter>
    );
    expect(screen.queryByRole('button', { name: '折叠侧边栏' })).toBeNull();
  });
});

describe('ConversationBar 回归：新对话按钮不写库', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConversations = [];
  });

  it('点击"新对话"按钮不调用 addConversation', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/']}>
        <ConversationBar collapsed={false} onToggleCollapse={vi.fn()} />
      </MemoryRouter>
    );

    const newBtn = screen.getByRole('button', { name: '新对话' });
    await user.click(newBtn);

    expect(mockAddConversation).not.toHaveBeenCalled();
  });

  it('点击"新对话"按钮触发 navigate("/")', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/']}>
        <ConversationBar collapsed={false} onToggleCollapse={vi.fn()} />
      </MemoryRouter>
    );

    const newBtn = screen.getByRole('button', { name: '新对话' });
    await user.click(newBtn);

    expect(mockNavigate).toHaveBeenCalledWith('/');
  });
});

describe('ConversationBar 回归：不展示空/无消息的新对话', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConversations = [];
  });

  it('过滤 message_count=0 的后端空会话', () => {
    mockConversations = [
      {
        id: 'empty-server-conv',
        title: '新对话',
        updated_at: '2026-04-28T10:00:00.000Z',
        messages: [],
        message_count: 0,
      },
      {
        id: 'real-server-conv',
        title: '销售额分析',
        updated_at: '2026-04-28T11:00:00.000Z',
        messages: [],
        message_count: 2,
      },
    ];

    render(
      <MemoryRouter initialEntries={['/']}>
        <ConversationBar collapsed={false} onToggleCollapse={vi.fn()} />
      </MemoryRouter>
    );

    expect(screen.queryByText('新对话')).toBeNull();
    expect(screen.getByText('销售额分析')).toBeInTheDocument();
  });

  it('过滤旧 localStorage 中无 message_count 的空占位会话', () => {
    mockConversations = [
      {
        id: 'empty-local-conv',
        title: '新对话',
        updated_at: '2026-04-28T10:00:00.000Z',
        messages: [],
      },
      {
        id: 'real-local-conv',
        title: '你有几个数据源',
        updated_at: '2026-04-28T11:00:00.000Z',
        messages: [
          {
            id: 'm1',
            role: 'user',
            content: '你有几个数据源',
            created_at: '2026-04-28T11:00:00.000Z',
          },
        ],
      },
    ];

    render(
      <MemoryRouter initialEntries={['/']}>
        <ConversationBar collapsed={false} onToggleCollapse={vi.fn()} />
      </MemoryRouter>
    );

    expect(screen.queryByText('新对话')).toBeNull();
    expect(screen.getByText('你有几个数据源')).toBeInTheDocument();
  });
});
