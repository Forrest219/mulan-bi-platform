// 防止回归：应用外壳快捷键不得调用 addConversation（写库）。
// 当前统一布局为 AppShellLayout；历史 HomeLayout 已由 AppShellLayout 替代。

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';

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

vi.mock('../../../src/components/layout/AppHeader', () => ({
  default: () => <div data-testid="app-header" />,
}));

vi.mock('../../../src/components/layout/AppSidebar', () => ({
  default: () => <aside data-testid="app-sidebar" />,
}));

vi.mock('../../../src/components/layout/PageSkeleton', () => ({
  default: () => <div data-testid="page-skeleton" />,
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    Outlet: () => <div data-testid="outlet" />,
  };
});

import AppShellLayout from '../../../src/components/layout/AppShellLayout';

describe('AppShellLayout 回归：布局快捷键不写库', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    Object.defineProperty(window, 'innerWidth', { value: 1280, writable: true, configurable: true });
  });

  it('⌘+\\ 不调用 addConversation', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <AppShellLayout />
      </MemoryRouter>
    );

    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: '\\', metaKey: true, bubbles: true })
    );

    expect(mockAddConversation).not.toHaveBeenCalled();
  });

  it('Ctrl+\\ 不调用 addConversation', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <AppShellLayout />
      </MemoryRouter>
    );

    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: '\\', ctrlKey: true, bubbles: true })
    );

    expect(mockAddConversation).not.toHaveBeenCalled();
  });
});
