// 防止回归：应用外壳快捷键不得调用 addConversation（写库）。
// 当前统一布局为 AppShellLayout；历史 HomeLayout 已由 AppShellLayout 替代。

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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
  default: ({ onOpenHelpAgent }: { onOpenHelpAgent?: () => void }) => (
    <header data-testid="app-header">
      {onOpenHelpAgent && (
        <button type="button" aria-label="打开 Help Agent" onClick={onOpenHelpAgent}>
          Help
        </button>
      )}
    </header>
  ),
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

  it('只通过顶栏传递 Help Agent 入口，不渲染旧悬浮按钮', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <AppShellLayout />
      </MemoryRouter>
    );

    expect(screen.getAllByRole('button', { name: '打开 Help Agent' })).toHaveLength(1);
  });
});
