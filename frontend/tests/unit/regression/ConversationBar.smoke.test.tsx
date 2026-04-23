// 防止回归：点击"新对话"按钮不得立即调用 addConversation（写库），只应 navigate('/')
// Bug 复现：ConversationBar 的 handleNew 曾直接调用 addConversation()，导致大量空对话堆积

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';

// ── 最小 mock：只 mock 必要的 hook ─────────────────────────────────────────────

const mockNavigate = vi.fn();

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
    conversations: [],
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
