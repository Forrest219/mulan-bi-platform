// 防止回归：⌘N 快捷键不得调用 addConversation（写库），只应 navigate('/')
// Bug 复现：HomeLayout 的 keydown handler 曾调用 addConversation()，导致大量空对话堆积

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';

// ── 最小 mock ──────────────────────────────────────────────────────────────────

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    // HomeLayout 内嵌 ConversationBar，Outlet 需要保持
    Outlet: () => <div data-testid="outlet" />,
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

import HomeLayout from '../../../src/components/layout/HomeLayout';

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('HomeLayout 回归：⌘N 快捷键不写库', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('⌘N (metaKey + n) 不调用 addConversation', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <HomeLayout />
      </MemoryRouter>
    );

    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'n', metaKey: true, bubbles: true })
    );

    expect(mockAddConversation).not.toHaveBeenCalled();
  });

  it('⌘N (metaKey + n) 触发 navigate("/")', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <HomeLayout />
      </MemoryRouter>
    );

    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'n', metaKey: true, bubbles: true })
    );

    expect(mockNavigate).toHaveBeenCalledWith('/');
  });

  it('Ctrl+N (ctrlKey + n) 同样不调用 addConversation', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <HomeLayout />
      </MemoryRouter>
    );

    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'n', ctrlKey: true, bubbles: true })
    );

    expect(mockAddConversation).not.toHaveBeenCalled();
  });

  it('Ctrl+N (ctrlKey + n) 触发 navigate("/")', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <HomeLayout />
      </MemoryRouter>
    );

    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'n', ctrlKey: true, bubbles: true })
    );

    expect(mockNavigate).toHaveBeenCalledWith('/');
  });
});
